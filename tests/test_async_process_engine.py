import asyncio
import os
import pickle
import queue
from typing import Any

import pytest

from bounded_execution import (
    AsyncProcessExecutionEngine,
    EngineClosedError,
    RemoteExecutionError,
    WorkerProcessError,
)
from bounded_execution.backends.async_process_worker import run_worker_loop

_ACTIVE_TASKS = 0
_PEAK_ACTIVE_TASKS = 0
_INITIALIZED_VALUE = 0
_LOOP_INITIALIZED_VALUE = 0


async def _async_value(value: int) -> int:
    await asyncio.sleep(0.01)
    return value


async def _async_process_id() -> int:
    return os.getpid()


async def _tracked_async_value(value: int) -> int:
    global _ACTIVE_TASKS, _PEAK_ACTIVE_TASKS
    _ACTIVE_TASKS += 1
    _PEAK_ACTIVE_TASKS = max(_PEAK_ACTIVE_TASKS, _ACTIVE_TASKS)
    try:
        await asyncio.sleep(0.05)
        return _PEAK_ACTIVE_TASKS
    finally:
        _ACTIVE_TASKS -= 1


async def _wait_forever() -> None:
    await asyncio.sleep(30)


async def _raise_value_error() -> None:
    raise ValueError("remote failure")


async def _return_unpicklable_result() -> object:
    return lambda: None


async def _crash_worker() -> None:
    os._exit(17)


def _initialize_process(value: int) -> None:
    global _INITIALIZED_VALUE
    _INITIALIZED_VALUE = value


def _initialize_loop(loop: asyncio.AbstractEventLoop, value: int) -> None:
    global _LOOP_INITIALIZED_VALUE
    _LOOP_INITIALIZED_VALUE = value


async def _initialized_values() -> tuple[int, int]:
    return _INITIALIZED_VALUE, _LOOP_INITIALIZED_VALUE


def test_async_process_engine_runs_native_coroutines_in_workers() -> None:
    async def run() -> None:
        async with AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 2,
                "max_in_flight": 4,
            }
        ) as engine:
            futures: list[asyncio.Future[int]] = [
                await engine.submit(_async_process_id) for _ in range(2)
            ]
            process_ids = await asyncio.gather(*futures)
            assert all(process_id != os.getpid() for process_id in process_ids)

    asyncio.run(run())


def test_child_concurrency_bounds_coroutines_per_process() -> None:
    async def run() -> None:
        global _ACTIVE_TASKS, _PEAK_ACTIVE_TASKS
        _ACTIVE_TASKS = 0
        _PEAK_ACTIVE_TASKS = 0
        async with AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 2,
                "max_in_flight": 4,
            }
        ) as engine:
            futures: list[asyncio.Future[int]] = [
                await engine.submit(_tracked_async_value, value) for value in range(4)
            ]
            peaks = await asyncio.gather(*futures)
            assert max(peaks) == 2

    asyncio.run(run())


def test_process_and_event_loop_initializers_run_once_per_worker() -> None:
    async def run() -> None:
        async with AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 1,
                "max_in_flight": 1,
                "initializer": _initialize_process,
                "initargs": (17,),
                "loop_initializer": _initialize_loop,
                "loop_initargs": (23,),
            }
        ) as engine:
            future: asyncio.Future[tuple[int, int]] = await engine.submit(
                _initialized_values
            )
            assert await asyncio.wait_for(future, timeout=10) == (17, 23)

    asyncio.run(run())


def test_async_process_engine_propagates_task_exceptions() -> None:
    async def run() -> None:
        async with AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 1,
                "max_in_flight": 1,
            }
        ) as engine:
            future: asyncio.Future[None] = await engine.submit(_raise_value_error)
            with pytest.raises(ValueError, match="remote failure"):
                await asyncio.wait_for(future, timeout=10)

    asyncio.run(run())


def test_unpicklable_result_raises_remote_execution_error() -> None:
    async def run() -> None:
        async with AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 1,
                "max_in_flight": 1,
            }
        ) as engine:
            future: asyncio.Future[object] = await engine.submit(
                _return_unpicklable_result
            )
            with pytest.raises(RemoteExecutionError, match="Could not transfer"):
                await asyncio.wait_for(future, timeout=10)

    asyncio.run(run())


def test_cancelling_future_cancels_remote_coroutine_and_releases_capacity() -> None:
    async def run() -> None:
        async with AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 1,
                "max_in_flight": 1,
            }
        ) as engine:
            pending: asyncio.Future[None] = await engine.submit(_wait_forever)
            await asyncio.sleep(0.1)
            assert pending.cancel()
            next_future: asyncio.Future[int] = await asyncio.wait_for(
                engine.submit(_async_value, 42),
                timeout=10,
            )
            assert await asyncio.wait_for(next_future, timeout=10) == 42
            with pytest.raises(asyncio.CancelledError):
                await pending

    asyncio.run(run())


def test_crashed_worker_is_replaced() -> None:
    async def run() -> None:
        async with AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 1,
                "max_in_flight": 1,
                "max_worker_restarts": 1,
            }
        ) as engine:
            failed: asyncio.Future[None] = await engine.submit(_crash_worker)
            with pytest.raises(WorkerProcessError, match="exited unexpectedly"):
                await asyncio.wait_for(failed, timeout=10)

            recovered: asyncio.Future[int] = await engine.submit(_async_value, 42)
            assert await asyncio.wait_for(recovered, timeout=10) == 42

    asyncio.run(run())


def test_submit_after_shutdown_is_rejected() -> None:
    async def run() -> None:
        engine = AsyncProcessExecutionEngine(
            process_config={
                "max_workers": 1,
                "child_concurrency": 1,
                "max_in_flight": 1,
            }
        )
        await engine.shutdown(wait=True)
        with pytest.raises(EngineClosedError):
            await engine.submit(_async_value, 1)

    asyncio.run(run())


def test_worker_loop_enforces_child_concurrency_without_process_startup() -> None:
    async def run() -> None:
        global _ACTIVE_TASKS, _PEAK_ACTIVE_TASKS
        _ACTIVE_TASKS = 0
        _PEAK_ACTIVE_TASKS = 0
        task_queue: queue.Queue[Any] = queue.Queue()
        control_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[Any] = queue.Queue()
        for task_id in range(4):
            payload = pickle.dumps((_tracked_async_value, (task_id,), {}))
            task_queue.put((task_id, payload))
        task_queue.put(None)
        control_queue.put(None)

        await run_worker_loop(
            0,
            0,
            task_queue,
            control_queue,
            result_queue,
            2,
            None,
            (),
        )

        messages = [result_queue.get_nowait() for _ in range(4)]
        values = [pickle.loads(message[4]) for message in messages]
        assert all(message[3] == "result" for message in messages)
        assert max(values) == 2

    asyncio.run(run())


def test_worker_loop_honors_remote_cancellation_without_process_startup() -> None:
    async def run() -> None:
        task_queue: queue.Queue[Any] = queue.Queue()
        control_queue: queue.Queue[Any] = queue.Queue()
        result_queue: queue.Queue[Any] = queue.Queue()
        task_queue.put((1, pickle.dumps((_wait_forever, (), {}))))
        task_queue.put(None)
        control_queue.put(("cancel", 1))
        control_queue.put(None)

        await run_worker_loop(
            0,
            0,
            task_queue,
            control_queue,
            result_queue,
            1,
            None,
            (),
        )

        message = result_queue.get_nowait()
        assert message[3] == "cancelled"

    asyncio.run(run())
