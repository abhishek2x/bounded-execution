"""Submit blocking I/O tasks through the bounded thread backend."""

import time

from bounded_execution import ExecutionEngine


def fetch_item(item_id: int) -> str:
    """Simulate a blocking I/O operation."""
    time.sleep(0.1)
    return f"item-{item_id}"


def main() -> None:
    thread_config = {"max_workers": 2, "max_in_flight": 3}

    with ExecutionEngine(thread_config=thread_config) as engine:
        print("Submitting 5 blocking tasks with at most 3 in flight...")
        futures = [
            engine.submit(fetch_item, item_id, backend="thread") for item_id in range(5)
        ]

        for item_id, future in enumerate(futures):
            result = future.result(timeout=10)
            print(f"item {item_id}: {result}")


if __name__ == "__main__":
    main()
