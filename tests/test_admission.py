from concurrent.futures import Executor, Future
from queue import Queue
from threading import Barrier, Condition, Event, Thread
from typing import Any
from unittest.mock import Mock

import pytest

from bounded_execution import ExecutionEngine
from bounded_execution.admission import AdmissionController


def add(left: int, right: int) -> int:
    return left + right


def wait_for_release(started: Event, release: Event) -> int:
    started.set()
    if not release.wait(timeout=5):
        raise TimeoutError("test task was not released")
    return 42


def test_submit_waits_until_in_flight_capacity_is_released() -> None:
    task_started = Event()
    release_task = Event()
    submit_started = Event()
    submit_finished = Event()
    submitted_futures: Queue[Future[int]] = Queue()
    with ExecutionEngine(
        thread_config={"max_workers": 1, "max_in_flight": 1}
    ) as engine:
        first = engine.submit(
            wait_for_release, task_started, release_task, backend="thread"
        )

        def submit_another_task() -> None:
            submit_started.set()
            try:
                submitted_futures.put(engine.submit(add, 20, 22, backend="thread"))
            finally:
                submit_finished.set()

        producer = Thread(target=submit_another_task)
        producer.start()
        try:
            assert task_started.wait(timeout=5)
            assert submit_started.wait(timeout=5)
            assert not submit_finished.wait(timeout=0.1)
        finally:
            release_task.set()

        assert submit_finished.wait(timeout=5)
        producer.join(timeout=5)
        assert not producer.is_alive()
        assert first.result(timeout=5) == 42
        assert submitted_futures.get_nowait().result(timeout=5) == 42


def test_concurrent_producers_share_the_backend_capacity_limit() -> None:
    producer_count = 10
    max_in_flight = 3
    task_started = Event()
    release_tasks = Event()
    start_barrier = Barrier(producer_count + 1)
    state_changed = Condition()
    attempts_started = 0
    submitted_futures: list[Future[int]] = []

    with ExecutionEngine(
        thread_config={"max_workers": 1, "max_in_flight": max_in_flight}
    ) as engine:

        def produce() -> None:
            nonlocal attempts_started
            start_barrier.wait(timeout=5)
            with state_changed:
                attempts_started += 1
                state_changed.notify_all()
            future = engine.submit(
                wait_for_release, task_started, release_tasks, backend="thread"
            )
            with state_changed:
                submitted_futures.append(future)
                state_changed.notify_all()

        producers = [Thread(target=produce) for _ in range(producer_count)]
        for producer in producers:
            producer.start()

        try:
            start_barrier.wait(timeout=5)
            with state_changed:
                assert state_changed.wait_for(
                    lambda: attempts_started == producer_count,
                    timeout=5,
                )
                assert state_changed.wait_for(
                    lambda: len(submitted_futures) == max_in_flight,
                    timeout=5,
                )
                assert not state_changed.wait_for(
                    lambda: len(submitted_futures) > max_in_flight,
                    timeout=0.1,
                )
            assert task_started.wait(timeout=5)
        finally:
            release_tasks.set()

        with state_changed:
            assert state_changed.wait_for(
                lambda: len(submitted_futures) == producer_count,
                timeout=5,
            )

        for producer in producers:
            producer.join(timeout=5)
            assert not producer.is_alive()
        assert all(future.result(timeout=5) == 42 for future in submitted_futures)


def test_task_failure_releases_in_flight_capacity() -> None:
    def fail() -> None:
        raise ValueError("task failed")

    with ExecutionEngine(
        thread_config={"max_workers": 1, "max_in_flight": 1}
    ) as engine:
        failed = engine.submit(fail, backend="thread")
        with pytest.raises(ValueError, match="task failed"):
            failed.result(timeout=5)

        assert engine.submit(add, 1, 2, backend="thread").result(timeout=5) == 3


def test_cancelling_queued_task_releases_in_flight_capacity() -> None:
    task_started = Event()
    release_task = Event()
    with ExecutionEngine(
        thread_config={"max_workers": 1, "max_in_flight": 2}
    ) as engine:
        try:
            running = engine.submit(
                wait_for_release, task_started, release_task, backend="thread"
            )
            assert task_started.wait(timeout=5)

            queued = engine.submit(add, 1, 2, backend="thread")
            assert queued.cancel()
            next_task = engine.submit(add, 20, 22, backend="thread")
        finally:
            release_task.set()

        assert running.result(timeout=5) == 42
        assert next_task.result(timeout=5) == 42


def test_native_submission_failure_releases_reserved_capacity() -> None:
    admission = AdmissionController(
        max_in_flight=1,
        condition=Condition(),
        is_open=lambda: True,
    )
    executor: Any = Mock(spec=Executor)
    completed: Future[int] = Future()
    completed.set_result(42)
    executor.submit.side_effect = [RuntimeError("executor rejected task"), completed]

    with pytest.raises(RuntimeError, match="executor rejected task"):
        admission.submit(executor, add, 20, 22)

    assert admission.submit(executor, add, 20, 22).result() == 42
