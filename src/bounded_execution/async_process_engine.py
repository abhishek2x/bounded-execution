"""Public API for bounded process-hosted coroutine execution."""

from __future__ import annotations

import asyncio
import inspect
import pickle
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, TypeVar

from bounded_execution.backends.async_process import (
    AsyncProcessBackend,
    WorkerExit,
    WorkerRef,
    WorkerResult,
)
from bounded_execution.backends.async_process_worker import (
    decode_exception,
    pickle_value,
)
from bounded_execution.config import validate_async_process_config
from bounded_execution.exceptions import (
    EngineClosedError,
    InvalidConfigurationError,
    RemoteExecutionError,
    WorkerProcessError,
)

_Result = TypeVar("_Result")


class _EngineState(Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass
class _TaskRecord:
    task_id: int
    worker: WorkerRef
    future: asyncio.Future[Any]
    completing: bool = False
    cancel_requested: bool = False


class AsyncProcessExecutionEngine:
    """Run native coroutine functions in bounded process-hosted event loops.

    Each process owns one event loop and can run up to ``child_concurrency``
    coroutines concurrently. Submitted functions, arguments, and results
    must be picklable.
    """

    def __init__(self, *, process_config: Mapping[str, object]) -> None:
        if not isinstance(process_config, Mapping):
            raise InvalidConfigurationError("async_process_config must be a mapping.")
        config = validate_async_process_config(process_config)
        self._backend = AsyncProcessBackend(config)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._state = _EngineState.OPEN
        self._fatal_error: Optional[WorkerProcessError] = None
        self._condition = asyncio.Condition()
        self._lifecycle_lock = asyncio.Lock()
        self._tasks: dict[int, _TaskRecord] = {}
        self._next_task_id = 0
        self._in_flight = 0
        self._submitting = 0

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError(
                "AsyncProcessExecutionEngine cannot be used across event loops."
            )
        return loop

    async def _ensure_started(self, loop: asyncio.AbstractEventLoop) -> None:
        async with self._lifecycle_lock:
            self._raise_if_unavailable()
            await self._backend.start(
                loop,
                self._handle_worker_message,
                self._worker_exited,
            )

    def _handle_worker_message(self, message: WorkerResult) -> None:
        record = self._tasks.get(message.task_id)
        if record is None or record.worker != message.worker or record.completing:
            return
        record.completing = True
        self._backend.send_control(message.worker, "ack", message.task_id)
        asyncio.create_task(self._finish_task(record, message))

    async def _finish_task(
        self,
        record: _TaskRecord,
        message: WorkerResult,
    ) -> None:
        value: Any = None
        error: Optional[BaseException] = None
        try:
            if message.outcome == "result":
                value = await asyncio.to_thread(pickle.loads, message.payload)
            elif message.outcome == "error":
                error = await asyncio.to_thread(decode_exception, message.payload)
            elif message.outcome != "cancelled":
                error = RemoteExecutionError(
                    f"Worker returned unknown task outcome {message.outcome!r}."
                )
        except Exception as exc:
            error = RemoteExecutionError(
                f"Could not decode the result from a process worker: {exc}"
            )

        async with self._condition:
            if self._tasks.get(record.task_id) is not record:
                return
            del self._tasks[record.task_id]
            self._in_flight -= 1
            self._backend.release(record.worker)
            self._condition.notify_all()

        if record.future.done():
            return
        if message.outcome == "cancelled":
            record.future.cancel()
        elif error is not None:
            record.future.set_exception(error)
        else:
            record.future.set_result(value)

    def _worker_exited(self, event: WorkerExit) -> None:
        asyncio.create_task(self._handle_worker_exit(event))

    async def _handle_worker_exit(self, event: WorkerExit) -> None:
        result = await self._backend.handle_exit(event)
        if result.expected:
            return

        error = result.error or WorkerProcessError(
            f"Async process worker {event.worker.index} exited unexpectedly."
        )
        async with self._condition:
            for task_id, record in tuple(self._tasks.items()):
                if record.worker != event.worker or record.completing:
                    continue
                del self._tasks[task_id]
                self._in_flight -= 1
                if not record.future.done():
                    record.future.set_exception(WorkerProcessError(str(error)))

            if result.fatal_error is not None:
                self._fatal_error = result.fatal_error
                self._state = _EngineState.FAILED
            self._condition.notify_all()

    def _future_done(self, task_id: int, future: asyncio.Future[Any]) -> None:
        if not future.cancelled():
            return
        record = self._tasks.get(task_id)
        if record is None or record.completing or record.cancel_requested:
            return
        record.cancel_requested = True
        self._backend.send_control(record.worker, "cancel", task_id)

    def _raise_if_unavailable(self) -> None:
        if self._fatal_error is not None:
            raise self._fatal_error
        if self._state is not _EngineState.OPEN:
            raise EngineClosedError("Cannot submit work after engine shutdown begins.")

    async def submit(
        self,
        fn: Callable[..., Awaitable[_Result]],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> asyncio.Future[_Result]:
        """Wait for admission and submit one native coroutine function."""
        loop = self._bind_loop()
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(
                "AsyncProcessExecutionEngine requires a coroutine function."
            )
        await self._ensure_started(loop)

        async with self._condition:
            while (
                self._in_flight >= self._backend.max_in_flight
                and self._state is _EngineState.OPEN
                and self._fatal_error is None
            ):
                await self._condition.wait()
            self._raise_if_unavailable()
            self._in_flight += 1
            self._submitting += 1
            task_id = self._next_task_id
            self._next_task_id += 1

        try:
            payload = await asyncio.to_thread(pickle_value, (fn, args, kwargs))
            async with self._condition:
                worker = self._backend.select_worker()
                while worker is None and self._state is _EngineState.OPEN:
                    if self._fatal_error is not None:
                        break
                    await self._condition.wait()
                    worker = self._backend.select_worker()
                if worker is None:
                    self._raise_if_unavailable()
                    raise WorkerProcessError("No async process workers are available.")

                future: asyncio.Future[_Result] = loop.create_future()
                record = _TaskRecord(task_id, worker, future)
                self._tasks[task_id] = record
                try:
                    self._backend.submit(worker, task_id, payload)
                except WorkerProcessError:
                    del self._tasks[task_id]
                    raise
                self._submitting -= 1
                self._condition.notify_all()
        except BaseException:
            await self._release_submission()
            raise

        future.add_done_callback(lambda done: self._future_done(task_id, done))
        return future

    async def _release_submission(self) -> None:
        async with self._condition:
            self._submitting -= 1
            self._in_flight -= 1
            self._condition.notify_all()

    async def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        """Stop admission and shut down process workers."""
        self._bind_loop()
        async with self._lifecycle_lock:
            async with self._condition:
                if self._state is _EngineState.OPEN:
                    self._state = _EngineState.CLOSING
                self._condition.notify_all()
            await self._backend.begin_shutdown()

        if cancel_futures:
            for record in tuple(self._tasks.values()):
                if not record.future.done() and not record.completing:
                    record.cancel_requested = True
                    self._backend.send_control(
                        record.worker,
                        "cancel",
                        record.task_id,
                    )
                    record.future.cancel()

        async with self._condition:
            while self._submitting or (wait and self._in_flight):
                await self._condition.wait()

        await self._backend.shutdown(wait=wait)
        self._state = _EngineState.CLOSED

    async def __aenter__(self) -> AsyncProcessExecutionEngine:
        self._bind_loop()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[object],
    ) -> None:
        await self.shutdown(wait=True)
