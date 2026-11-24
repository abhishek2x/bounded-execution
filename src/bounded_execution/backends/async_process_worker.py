"""Worker-side runtime and serialization helpers for async process execution."""

from __future__ import annotations

import asyncio
import inspect
import pickle
from collections.abc import Callable
from typing import Any, Optional

from bounded_execution.exceptions import RemoteExecutionError

_PROTOCOL = pickle.HIGHEST_PROTOCOL


def pickle_value(value: object) -> bytes:
    return pickle.dumps(value, protocol=_PROTOCOL)


def pickle_exception(exception: BaseException) -> bytes:
    try:
        return pickle.dumps(("exception", exception), protocol=_PROTOCOL)
    except Exception:
        try:
            message = str(exception)
        except Exception:
            message = "<exception message could not be rendered>"
        error_type = f"{type(exception).__module__}.{type(exception).__qualname__}"
        return pickle.dumps(("description", error_type, message), protocol=_PROTOCOL)


def decode_exception(payload: bytes) -> BaseException:
    try:
        kind, *data = pickle.loads(payload)
    except Exception as exc:
        return RemoteExecutionError(
            f"Could not decode a task exception from a process worker: {exc}"
        )
    if kind == "exception" and len(data) == 1 and isinstance(data[0], BaseException):
        return data[0]
    if kind == "description" and len(data) == 2:
        return RemoteExecutionError(f"Remote task raised {data[0]}: {data[1]}")
    return RemoteExecutionError("Worker returned an invalid exception payload.")


def run_worker(
    worker_index: int,
    generation: int,
    task_queue: Any,
    control_queue: Any,
    result_queue: Any,
    child_concurrency: int,
    initializer: Optional[Callable[..., Any]],
    initargs: tuple[object, ...],
    loop_initializer: Optional[Callable[..., Any]],
    loop_initargs: tuple[object, ...],
) -> None:
    if initializer is not None:
        initializer_result = initializer(*initargs)
        if inspect.isawaitable(initializer_result):
            raise TypeError("The process initializer must be synchronous.")
    asyncio.run(
        run_worker_loop(
            worker_index,
            generation,
            task_queue,
            control_queue,
            result_queue,
            child_concurrency,
            loop_initializer,
            loop_initargs,
        )
    )


async def run_worker_loop(
    worker_index: int,
    generation: int,
    task_queue: Any,
    control_queue: Any,
    result_queue: Any,
    child_concurrency: int,
    loop_initializer: Optional[Callable[..., Any]],
    loop_initargs: tuple[object, ...],
) -> None:
    if loop_initializer is not None:
        result = loop_initializer(asyncio.get_running_loop(), *loop_initargs)
        if inspect.isawaitable(result):
            await result

    semaphore = asyncio.Semaphore(child_concurrency)
    active: dict[int, asyncio.Task[None]] = {}
    cancelled: set[int] = set()

    async def execute(task_id: int, payload: bytes) -> None:
        outcome = "result"
        result_payload = b""
        try:
            fn, args, kwargs = await asyncio.to_thread(pickle.loads, payload)
            async with semaphore:
                value = fn(*args, **kwargs)
                if not inspect.isawaitable(value):
                    raise TypeError("The async process backend requires an awaitable.")
                value = await value
        except asyncio.CancelledError:
            outcome = "cancelled"
        except BaseException as exc:
            outcome = "error"
            result_payload = await asyncio.to_thread(pickle_exception, exc)
        else:
            try:
                result_payload = await asyncio.to_thread(pickle_value, value)
            except asyncio.CancelledError:
                outcome = "cancelled"
            except Exception as exc:
                outcome = "error"
                transfer_error = RemoteExecutionError(
                    f"Could not transfer task result: {exc}"
                )
                result_payload = await asyncio.to_thread(
                    pickle_exception,
                    transfer_error,
                )
        finally:
            active.pop(task_id, None)

        result_queue.put((worker_index, generation, task_id, outcome, result_payload))

    def task_done(task_id: int, task: asyncio.Task[None]) -> None:
        active.pop(task_id, None)
        if task.cancelled():
            result_queue.put((worker_index, generation, task_id, "cancelled", b""))
            return
        exception = task.exception()
        if exception is not None:
            result_queue.put(
                (
                    worker_index,
                    generation,
                    task_id,
                    "error",
                    pickle_exception(exception),
                )
            )

    async def read_tasks() -> None:
        while True:
            message = await asyncio.to_thread(task_queue.get)
            if message is None:
                return

            task_id, payload = message
            if task_id in cancelled:
                cancelled.discard(task_id)
                result_queue.put((worker_index, generation, task_id, "cancelled", b""))
                continue

            task = asyncio.create_task(execute(task_id, payload))
            active[task_id] = task

            def handle_done(
                completed: asyncio.Task[None],
                current_id: int = task_id,
            ) -> None:
                task_done(current_id, completed)

            task.add_done_callback(handle_done)
            if task_id in cancelled:
                cancelled.discard(task_id)
                task.cancel()

    async def read_controls() -> None:
        while True:
            message = await asyncio.to_thread(control_queue.get)
            if message is None:
                return

            command, task_id = message
            if command == "cancel":
                task = active.get(task_id)
                if task is None:
                    cancelled.add(task_id)
                else:
                    task.cancel()
            elif command == "ack":
                cancelled.discard(task_id)

    readers = (
        asyncio.create_task(read_tasks()),
        asyncio.create_task(read_controls()),
    )
    await asyncio.gather(*readers)
    if active:
        await asyncio.gather(*tuple(active.values()), return_exceptions=True)
