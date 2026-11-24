"""Parent-side process pool for coroutine workers."""

from __future__ import annotations

import asyncio
import multiprocessing
import queue
import threading
from dataclasses import dataclass
from multiprocessing.process import BaseProcess
from typing import Any, Callable, Optional

from bounded_execution.config import _AsyncProcessConfig
from bounded_execution.exceptions import WorkerProcessError

from .async_process_worker import run_worker

_MONITOR_STOP = ("__stop_monitor__",)


@dataclass(frozen=True)
class WorkerRef:
    index: int
    generation: int


@dataclass(frozen=True)
class WorkerResult:
    worker: WorkerRef
    task_id: int
    outcome: str
    payload: bytes


@dataclass(frozen=True)
class WorkerExit:
    worker: WorkerRef
    exitcode: Optional[int]


@dataclass(frozen=True)
class WorkerExitResult:
    expected: bool
    error: Optional[WorkerProcessError] = None
    fatal_error: Optional[WorkerProcessError] = None


@dataclass
class _WorkerSlot:
    index: int
    process: Optional[BaseProcess] = None
    task_queue: Any = None
    control_queue: Any = None
    generation: int = 0
    restarts: int = 0
    load: int = 0
    shutdown_sent: bool = False


class AsyncProcessBackend:
    """Own process workers and their IPC, restart, and shutdown lifecycle."""

    def __init__(self, config: _AsyncProcessConfig) -> None:
        self._config = config
        self._context = multiprocessing.get_context("spawn")
        self._state = "open"
        self._slots = [_WorkerSlot(index) for index in range(config.max_workers)]
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_result: Optional[Callable[[WorkerResult], None]] = None
        self._on_exit: Optional[Callable[[WorkerExit], None]] = None
        self._start_lock = asyncio.Lock()
        self._workers_lock = threading.Lock()
        self._result_queue: Any = None
        self._monitor_stop = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._started = False
        self._shutdown_sent = False
        self._cleanup_lock = threading.Lock()
        self._cleaned = False

    @property
    def max_in_flight(self) -> int:
        return self._config.max_in_flight

    async def start(
        self,
        loop: asyncio.AbstractEventLoop,
        on_result: Callable[[WorkerResult], None],
        on_exit: Callable[[WorkerExit], None],
    ) -> None:
        async with self._start_lock:
            if self._started:
                return
            if self._state != "open":
                raise WorkerProcessError("Cannot start a closed process backend.")
            self._loop = loop
            self._on_result = on_result
            self._on_exit = on_exit
            await asyncio.to_thread(self._start_workers, loop)
            self._started = True

    def _start_workers(self, loop: asyncio.AbstractEventLoop) -> None:
        self._result_queue = self._context.Queue()
        started: list[_WorkerSlot] = []
        try:
            for slot in self._slots:
                self._start_worker(slot)
                started.append(slot)
        except Exception as exc:
            for slot in started:
                self._stop_worker(slot)
            self._close_queue(self._result_queue)
            self._result_queue = None
            raise WorkerProcessError(f"Could not start process workers: {exc}") from exc

        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_workers,
            args=(loop,),
            name="bounded-execution-async-process-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _start_worker(self, slot: _WorkerSlot) -> None:
        task_queue = self._context.Queue(maxsize=self._config.max_in_flight + 1)
        control_queue = self._context.Queue(
            maxsize=(2 * self._config.max_in_flight) + 1
        )
        process = self._context.Process(
            target=run_worker,
            args=(
                slot.index,
                slot.generation,
                task_queue,
                control_queue,
                self._result_queue,
                self._config.child_concurrency,
                self._config.initializer,
                self._config.initargs,
                self._config.loop_initializer,
                self._config.loop_initargs,
            ),
            name=f"bounded-execution-async-worker-{slot.index}",
        )
        with self._workers_lock:
            slot.task_queue = task_queue
            slot.control_queue = control_queue
            slot.process = None
            slot.shutdown_sent = False
        try:
            process.start()
        except Exception:
            self._close_queue(task_queue)
            self._close_queue(control_queue)
            with self._workers_lock:
                slot.process = None
                slot.task_queue = None
                slot.control_queue = None
            raise
        with self._workers_lock:
            slot.process = process

    @staticmethod
    def _close_queue(work_queue: Any) -> None:
        if work_queue is None:
            return
        try:
            work_queue.cancel_join_thread()
            work_queue.close()
        except ValueError:
            pass

    def _stop_worker(self, slot: _WorkerSlot) -> None:
        process = slot.process
        if process is not None and process.is_alive():
            slot.task_queue.put_nowait(None)
            slot.control_queue.put_nowait(None)
            process.join()
        self._close_queue(slot.task_queue)
        self._close_queue(slot.control_queue)

    def select_worker(self) -> Optional[WorkerRef]:
        if self._state not in ("open", "closing"):
            return None
        alive = [slot for slot in self._slots if self._is_alive(slot)]
        if not alive:
            return None
        slot = min(alive, key=lambda candidate: candidate.load)
        return WorkerRef(slot.index, slot.generation)

    def submit(self, worker: WorkerRef, task_id: int, payload: bytes) -> None:
        slot = self._current_slot(worker)
        if slot is None or not self._is_alive(slot):
            raise WorkerProcessError(
                f"Async process worker {worker.index} is not available."
            )
        try:
            slot.task_queue.put_nowait((task_id, payload))
        except (queue.Full, OSError, ValueError) as exc:
            raise WorkerProcessError(
                f"Could not queue task for worker {worker.index}: {exc}"
            ) from exc
        slot.load += 1

    def send_control(
        self,
        worker: WorkerRef,
        command: str,
        task_id: int,
    ) -> None:
        slot = self._current_slot(worker)
        if slot is None or slot.control_queue is None:
            return
        try:
            slot.control_queue.put_nowait((command, task_id))
        except (queue.Full, OSError, ValueError) as exc:
            loop = self._loop
            if loop is not None:
                loop.call_exception_handler(
                    {
                        "message": "Could not send process-worker control message.",
                        "exception": exc,
                    }
                )

    def release(self, worker: WorkerRef) -> None:
        slot = self._current_slot(worker)
        if slot is not None and slot.load > 0:
            slot.load -= 1

    def _current_slot(self, worker: WorkerRef) -> Optional[_WorkerSlot]:
        if not 0 <= worker.index < len(self._slots):
            return None
        slot = self._slots[worker.index]
        if slot.generation != worker.generation:
            return None
        return slot

    @staticmethod
    def _is_alive(slot: _WorkerSlot) -> bool:
        return slot.process is not None and slot.process.is_alive()

    def _monitor_workers(self, loop: asyncio.AbstractEventLoop) -> None:
        reported: set[WorkerRef] = set()
        while not self._monitor_stop.is_set():
            stop_after_check = False
            try:
                message = self._result_queue.get(timeout=0.05)
            except queue.Empty:
                message = None
            except (EOFError, OSError, ValueError):
                return

            if message == _MONITOR_STOP:
                stop_after_check = True
            elif message is not None:
                result = WorkerResult(
                    worker=WorkerRef(message[0], message[1]),
                    task_id=message[2],
                    outcome=message[3],
                    payload=message[4],
                )
                if not self._dispatch(loop, self._on_result, result):
                    return

            with self._workers_lock:
                snapshots = [
                    (WorkerRef(slot.index, slot.generation), slot.process)
                    for slot in self._slots
                ]
            for worker, process in snapshots:
                if (
                    process is not None
                    and worker not in reported
                    and not process.is_alive()
                ):
                    reported.add(worker)
                    exit_event = WorkerExit(worker, process.exitcode)
                    if not self._dispatch(loop, self._on_exit, exit_event):
                        return
            if stop_after_check:
                return

    @staticmethod
    def _dispatch(
        loop: asyncio.AbstractEventLoop,
        callback: Optional[Callable[[Any], None]],
        event: Any,
    ) -> bool:
        if callback is None:
            return False
        try:
            loop.call_soon_threadsafe(callback, event)
        except RuntimeError:
            return False
        return True

    async def handle_exit(self, event: WorkerExit) -> WorkerExitResult:
        async with self._start_lock:
            slot = self._current_slot(event.worker)
            if slot is None:
                return WorkerExitResult(expected=True)
            process = slot.process
            if process is not None:
                process.join(timeout=0)
            if slot.shutdown_sent and event.exitcode == 0:
                self._close_queue(slot.task_queue)
                self._close_queue(slot.control_queue)
                return WorkerExitResult(expected=True)

            slot.load = 0
            self._close_queue(slot.task_queue)
            self._close_queue(slot.control_queue)
            message = (
                f"Async process worker {event.worker.index} exited unexpectedly "
                f"with code {event.exitcode}."
            )
            if self._state != "open":
                return WorkerExitResult(
                    expected=False,
                    error=WorkerProcessError(message),
                )
            if slot.restarts >= self._config.max_worker_restarts:
                error = WorkerProcessError(
                    f"{message} Restart limit "
                    f"({self._config.max_worker_restarts}) was reached."
                )
                self._state = "failed"
                return WorkerExitResult(
                    expected=False,
                    error=WorkerProcessError(message),
                    fatal_error=error,
                )

            slot.generation += 1
            slot.restarts += 1
            try:
                await asyncio.to_thread(self._start_worker, slot)
            except Exception as exc:
                error = WorkerProcessError(
                    f"Could not replace async process worker {slot.index}: {exc}"
                )
                self._state = "failed"
                return WorkerExitResult(
                    expected=False,
                    error=WorkerProcessError(message),
                    fatal_error=error,
                )
            return WorkerExitResult(
                expected=False,
                error=WorkerProcessError(message),
            )

    async def begin_shutdown(self) -> None:
        async with self._start_lock:
            if self._state == "open":
                self._state = "closing"

    async def shutdown(self, wait: bool) -> None:
        async with self._start_lock:
            if self._state == "open":
                self._state = "closing"
            if not self._started:
                self._state = "closed"
                return
            if not self._shutdown_sent:
                for slot in self._slots:
                    if not self._is_alive(slot):
                        continue
                    try:
                        slot.task_queue.put_nowait(None)
                        slot.control_queue.put_nowait(None)
                        slot.shutdown_sent = True
                    except (queue.Full, OSError, ValueError) as exc:
                        raise WorkerProcessError(
                            f"Could not stop process worker {slot.index}: {exc}"
                        ) from exc
                self._shutdown_sent = True
            self._state = "closed"

        if wait:
            await asyncio.to_thread(self._cleanup_resources)
        else:
            threading.Thread(
                target=self._cleanup_resources,
                name="bounded-execution-async-process-cleanup",
                daemon=True,
            ).start()

    def _cleanup_resources(self) -> None:
        with self._cleanup_lock:
            if self._cleaned:
                return
            with self._workers_lock:
                processes = [
                    slot.process for slot in self._slots if slot.process is not None
                ]
            for process in processes:
                process.join()
            if self._result_queue is not None:
                self._result_queue.put(_MONITOR_STOP)
            monitor = self._monitor_thread
            if monitor is not None and monitor is not threading.current_thread():
                monitor.join()
            self._monitor_stop.set()
            for slot in self._slots:
                self._close_queue(slot.task_queue)
                self._close_queue(slot.control_queue)
            self._close_queue(self._result_queue)
            self._cleaned = True
