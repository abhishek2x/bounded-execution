import asyncio

from bounded_execution import AsyncProcessExecutionEngine


async def fetch_item(item_id: int) -> str:
    await asyncio.sleep(0.2)
    return f"item-{item_id}"


async def main() -> None:
    async with AsyncProcessExecutionEngine(
        process_config={
            "max_workers": 2,
            "child_concurrency": 4,
            "max_in_flight": 8,
        }
    ) as engine:
        futures: list[asyncio.Future[str]] = [
            await engine.submit(fetch_item, item_id) for item_id in range(8)
        ]
        results = await asyncio.gather(*futures)
        print(results)


if __name__ == "__main__":
    asyncio.run(main())
