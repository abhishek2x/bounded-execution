"""Submit blocking tasks through the bounded thread backend."""

import time

from bounded_execution import ExecutionEngine


def fetch_item(item_id: int) -> str:
    """Simulate a blocking I/O operation."""
    time.sleep(0.1)
    return f"item-{item_id}"


def main() -> None:
    with ExecutionEngine(
        thread_config={"max_workers": 2, "max_in_flight": 3}
    ) as engine:
        futures = [
            engine.submit(fetch_item, item_id, backend="thread") for item_id in range(5)
        ]
        for future in futures:
            print(future.result())


if __name__ == "__main__":
    main()
