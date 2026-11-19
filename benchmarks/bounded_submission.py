"""Compare unbounded, semaphore-bounded, and library task submission."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
import tracemalloc
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import Any, Optional

from bounded_execution import ExecutionEngine


class _Tracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._in_flight = 0
        self.peak_in_flight = 0
        self.completed = 0
        self.errors: list[BaseException] = []

    def track(
        self,
        future: Future[Any],
        semaphore: Optional[BoundedSemaphore] = None,
    ) -> None:
        with self._lock:
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        future.add_done_callback(lambda done: self._completed(done, semaphore))

    def _completed(
        self,
        future: Future[Any],
        semaphore: Optional[BoundedSemaphore],
    ) -> None:
        error = future.exception()
        with self._lock:
            self._in_flight -= 1
            self.completed += 1
            if error is not None:
                self.errors.append(error)
        if semaphore is not None:
            semaphore.release()


def _run_task(workload: str, work_units: int, task_id: int) -> int:
    if workload == "io":
        time.sleep(work_units / 1000)
        return task_id
    if workload == "cpu":
        return sum(value * value for value in range(work_units))
    return task_id + 1


def _create_executor(backend: str, max_workers: int) -> Executor:
    if backend == "thread":
        return ThreadPoolExecutor(max_workers=max_workers)
    return ProcessPoolExecutor(max_workers=max_workers)


def _run_variant(
    variant: str,
    backend: str,
    workload: str,
    tasks: int,
    work_units: int,
    max_workers: int,
    max_in_flight: int,
) -> dict[str, Any]:
    tracker = _Tracker()
    executor: Optional[Executor] = None
    engine: Optional[ExecutionEngine] = None
    semaphore: Optional[BoundedSemaphore] = None
    submit_latencies: list[float] = []
    manual_admission_wait = 0.0
    tracemalloc.start()
    total_started = time.perf_counter()

    try:
        if variant == "bounded_execution":
            config = {
                "max_workers": max_workers,
                "max_in_flight": max_in_flight,
            }
            if backend == "thread":
                engine = ExecutionEngine(thread_config=config)
            else:
                engine = ExecutionEngine(process_config=config)
        else:
            executor = _create_executor(backend, max_workers)
            if variant == "native_semaphore":
                semaphore = BoundedSemaphore(max_in_flight)

        producer_started = time.perf_counter()
        for task_id in range(tasks):
            submit_started = time.perf_counter()
            if semaphore is not None:
                admission_started = time.perf_counter()
                semaphore.acquire()
                manual_admission_wait += time.perf_counter() - admission_started

            try:
                if engine is not None:
                    future = engine.submit(
                        _run_task, workload, work_units, task_id, backend=backend
                    )
                else:
                    assert executor is not None
                    future = executor.submit(_run_task, workload, work_units, task_id)
            except BaseException:
                if semaphore is not None:
                    semaphore.release()
                raise

            submit_latencies.append(time.perf_counter() - submit_started)
            tracker.track(future, semaphore)

        producer_seconds = time.perf_counter() - producer_started
    finally:
        if engine is not None:
            engine.shutdown(wait=True)
        if executor is not None:
            executor.shutdown(wait=True)
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    total_seconds = time.perf_counter() - total_started
    if tracker.errors:
        raise RuntimeError(
            f"{variant} benchmark task failed: {tracker.errors[0]}"
        ) from tracker.errors[0]
    if tracker.completed != tasks:
        raise RuntimeError(
            f"{variant} completed {tracker.completed} of {tasks} submitted tasks."
        )

    return {
        "total_seconds": total_seconds,
        "producer_submit_seconds": producer_seconds,
        "mean_submit_call_seconds": statistics.mean(submit_latencies),
        "max_submit_call_seconds": max(submit_latencies),
        "manual_admission_wait_seconds": (
            manual_admission_wait if variant == "native_semaphore" else None
        ),
        "peak_in_flight_tasks": tracker.peak_in_flight,
        "parent_peak_tracemalloc_bytes": peak_memory,
        "throughput_tasks_per_second": tasks / total_seconds,
    }


def _summarize(variant: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"variant": variant, "runs": len(runs)}
    for metric in runs[0]:
        values = [run[metric] for run in runs if run[metric] is not None]
        summary[metric] = statistics.median(values) if values else None
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("thread", "process"), default="thread")
    parser.add_argument(
        "--workload",
        choices=("tiny", "io", "cpu"),
        default="tiny",
    )
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-in-flight", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--work-units",
        type=int,
        help="IO: milliseconds to sleep; CPU: loop iterations; tiny: unused.",
    )
    args = parser.parse_args()

    if args.tasks < 1 or args.workers < 1 or args.repeats < 1:
        parser.error("--tasks, --workers, and --repeats must be positive.")
    if args.max_in_flight < args.workers:
        parser.error("--max-in-flight must be at least --workers.")

    default_work_units = {"tiny": 0, "io": 1, "cpu": 10_000}
    work_units = (
        args.work_units
        if args.work_units is not None
        else default_work_units[args.workload]
    )
    if work_units < 0:
        parser.error("--work-units cannot be negative.")

    variants = ("native_unbounded", "native_semaphore", "bounded_execution")
    results: list[dict[str, Any]] = []
    for variant in variants:
        runs = [
            _run_variant(
                variant,
                args.backend,
                args.workload,
                args.tasks,
                work_units,
                args.workers,
                args.max_in_flight,
            )
            for _ in range(args.repeats)
        ]
        results.append(_summarize(variant, runs))

    print(
        json.dumps(
            {
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "processor": platform.processor() or platform.machine(),
                    "cpu_count": os.cpu_count(),
                },
                "configuration": {
                    "backend": args.backend,
                    "workload": args.workload,
                    "tasks": args.tasks,
                    "work_units": work_units,
                    "max_workers": args.workers,
                    "max_in_flight": args.max_in_flight,
                },
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
