"""Submit CPU-bound tasks through the bounded process backend."""

import sys

from bounded_execution import ExecutionEngine

_WORKER_SCALE = 1


def initialize_worker(scale: int) -> None:
    """Set process-local state once when a worker starts."""
    global _WORKER_SCALE
    _WORKER_SCALE = scale


def sum_squares(stop: int) -> int:
    """Return the sum of squares below stop."""
    return _WORKER_SCALE * sum(value * value for value in range(stop))


def main() -> None:
    print("Process worker initializer: enabled")
    process_config: dict[str, object] = {
        "max_workers": 2,
        "max_in_flight": 4,
        "initializer": initialize_worker,
        "initargs": (2,),
    }
    if sys.version_info >= (3, 11):
        # Recycling is optional. It is useful for processes that accumulate
        # memory or other resources, but it adds process-startup overhead.
        process_config["max_tasks_per_child"] = 100

    with ExecutionEngine(process_config=process_config) as engine:
        print("Submitting 4 CPU-bound tasks with at most 4 in flight...")
        futures = [
            engine.submit(sum_squares, stop, backend="process")
            for stop in (100_000, 200_000, 300_000, 400_000)
        ]
        for stop, future in zip((100_000, 200_000, 300_000, 400_000), futures):
            print(f"stop={stop}: {future.result(timeout=30)}")


if __name__ == "__main__":
    main()
