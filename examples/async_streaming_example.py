"""Consume async results as they finish with a bounded set of futures."""

import asyncio
from asyncio import Future
from itertools import islice

from bounded_execution import AsyncExecutionEngine


async def fetch_item(item_id: int) -> str:
    """Simulate asynchronous I/O with one slow item and one failure."""
    await asyncio.sleep(0.05 if item_id == 0 else 0.01)
    if item_id == 2:
        raise ValueError("simulated fetch failure")
    return f"item-{item_id}"


async def main() -> None:
    max_in_flight = 3
    items = iter(range(8))
    pending: dict[Future[str], int] = {}
    async with AsyncExecutionEngine(
        async_config={"max_in_flight": max_in_flight}
    ) as engine:
        while True:
            # Pull only enough input to fill the available window.
            for item_id in islice(items, max_in_flight - len(pending)):
                future: Future[str] = await engine.submit(
                    fetch_item, item_id, backend="async"
                )
                pending[future] = item_id
                print(f"submitted {item_id}")

            if not pending:
                break

            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for future in done:
                item_id = pending.pop(future)
                try:
                    result = future.result()
                except ValueError as error:
                    print(f"error {item_id}: {error}")
                else:
                    print(f"result {item_id}: {result}")


if __name__ == "__main__":
    asyncio.run(main())
