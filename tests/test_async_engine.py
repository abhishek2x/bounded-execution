import asyncio

import pytest

from bounded_execution import (
    AsyncExecutionEngine,
    EngineClosedError,
    InvalidConfigurationError,
    UnsupportedBackendError,
)


async def _async_value(value: int) -> int:
    await asyncio.sleep(0.01)
    return value


def _sync_value(value: int) -> int:
    return value


def test_async_backend_runs_native_coroutine() -> None:
    async def run() -> None:
        async with AsyncExecutionEngine(async_config={"max_in_flight": 2}) as engine:
            future: asyncio.Future[int] = await engine.submit(
                _async_value, 42, backend="async"
            )
            assert await asyncio.wait_for(future, timeout=1) == 42

    asyncio.run(run())


def test_thread_backend_offloads_synchronous_function() -> None:
    async def run() -> None:
        async with AsyncExecutionEngine(
            thread_config={"max_workers": 2, "max_in_flight": 2}
        ) as engine:
            future: asyncio.Future[int] = await engine.submit(
                _sync_value, 42, backend="thread"
            )
            assert await asyncio.wait_for(future, timeout=1) == 42

    asyncio.run(run())


def test_process_backend_offloads_synchronous_function() -> None:
    async def run() -> None:
        async with AsyncExecutionEngine(
            process_config={"max_workers": 1, "max_in_flight": 1}
        ) as engine:
            future: asyncio.Future[int] = await engine.submit(
                _sync_value, 42, backend="process"
            )
            assert await asyncio.wait_for(future, timeout=10) == 42

    asyncio.run(run())


def test_async_capacity_backpressure_and_cancellation() -> None:
    async def run() -> None:
        async def wait_forever() -> None:
            await asyncio.sleep(10)

        engine = AsyncExecutionEngine(async_config={"max_in_flight": 1})
        running: asyncio.Future[None] = await engine.submit(
            wait_forever, backend="async"
        )
        submit_task: asyncio.Task[asyncio.Future[None]] = asyncio.create_task(
            engine.submit(wait_forever, backend="async")
        )
        await asyncio.sleep(0.01)
        assert not submit_task.done()

        await engine.shutdown(wait=False, cancel_futures=True)
        submit_task.cancel()
        running.cancel()

        results = await asyncio.gather(submit_task, running, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert isinstance(results[1], asyncio.CancelledError)

    asyncio.run(run())


def test_submit_after_async_shutdown_is_rejected() -> None:
    async def run() -> None:
        engine = AsyncExecutionEngine(async_config={"max_in_flight": 1})
        await engine.shutdown(wait=True)

        with pytest.raises(EngineClosedError):
            await engine.submit(_async_value, 1, backend="async")

    asyncio.run(run())


def test_async_engine_rejects_unknown_backend() -> None:
    async def run() -> None:
        async with AsyncExecutionEngine(async_config={"max_in_flight": 1}) as engine:
            with pytest.raises(UnsupportedBackendError):
                await engine.submit(_async_value, 1, backend="thread")

    asyncio.run(run())


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"max_in_flight": 0},
        {"max_in_flight": True},
        {"max_in_flight": 2, "extra": 1},
    ],
)
def test_async_config_is_validated(config: dict[str, object]) -> None:
    with pytest.raises(InvalidConfigurationError):
        AsyncExecutionEngine(async_config=config)
