"""Use AsyncExecutionEngine with native coroutines and executor offloading."""

import asyncio
from asyncio import Future

from bounded_execution import AsyncExecutionEngine


async def fetch_item(item_id: int) -> str:
    """Simulate asynchronous I/O without blocking the event loop."""
    await asyncio.sleep(0.1)
    return f"async-item-{item_id}"


def blocking_lookup(item_id: int) -> str:
    """Simulate a blocking function that should run in a thread."""
    return f"thread-item-{item_id}"


def calculate(stop: int) -> int:
    """Perform a small CPU-bound calculation in a process."""
    return sum(value * value for value in range(stop))


async def main() -> None:
    async with AsyncExecutionEngine(
        async_config={"max_in_flight": 3},
        thread_config={"max_workers": 2, "max_in_flight": 2},
        process_config={"max_workers": 2, "max_in_flight": 2},
    ) as engine:
        async_futures: list[Future[str]] = [
            await engine.submit(fetch_item, item_id, backend="async")
            for item_id in range(3)
        ]
        thread_future: Future[str] = await engine.submit(
            blocking_lookup, 1, backend="thread"
        )
        process_future: Future[int] = await engine.submit(
            calculate, 100_000, backend="process"
        )

        for future in async_futures:
            print(await future)
        print(await thread_future)
        print(f"process result: {await process_future}")


if __name__ == "__main__":
    asyncio.run(main())
