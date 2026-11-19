"""Submit CPU-bound tasks through the bounded process backend."""

from bounded_execution import ExecutionEngine


def sum_squares(stop: int) -> int:
    """Return the sum of squares below stop."""
    return sum(value * value for value in range(stop))


def main() -> None:
    with ExecutionEngine(
        process_config={"max_workers": 2, "max_in_flight": 4}
    ) as engine:
        futures = [
            engine.submit(sum_squares, stop, backend="process")
            for stop in (100_000, 200_000, 300_000, 400_000)
        ]
        for future in futures:
            print(future.result())


if __name__ == "__main__":
    main()
