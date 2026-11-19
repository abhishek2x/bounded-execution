from concurrent.futures import Future
from queue import Queue
from threading import Event, Thread
from typing import Optional

from bounded_execution import EngineClosedError, ExecutionEngine


def wait_for_release(started: Event, release: Event) -> int:
    started.set()
    if not release.wait(timeout=5):
        raise TimeoutError("test task was not released")
    return 42


def test_shutdown_wakes_submitter_waiting_for_capacity() -> None:
    engine = ExecutionEngine(thread_config={"max_workers": 1, "max_in_flight": 1})
    task_started = Event()
    release_task = Event()
    submit_started = Event()
    submit_finished = Event()
    errors: Queue[BaseException] = Queue()
    running = engine.submit(
        wait_for_release, task_started, release_task, backend="thread"
    )

    def blocked_submit() -> None:
        submit_started.set()
        try:
            engine.submit(lambda: None, backend="thread")
        except EngineClosedError as error:
            errors.put(error)
        finally:
            submit_finished.set()

    producer = Thread(target=blocked_submit)
    producer.start()
    try:
        assert task_started.wait(timeout=5)
        assert submit_started.wait(timeout=5)
        assert not submit_finished.wait(timeout=0.1)
        engine.shutdown(wait=False)
        assert submit_finished.wait(timeout=5)
    finally:
        release_task.set()

    producer.join(timeout=5)
    assert not producer.is_alive()
    assert isinstance(errors.get_nowait(), EngineClosedError)
    assert running.result(timeout=5) == 42
    engine.shutdown(wait=True)


def test_repeated_shutdown_can_wait_after_non_waiting_shutdown() -> None:
    engine = ExecutionEngine(thread_config={"max_workers": 1, "max_in_flight": 1})
    task_started = Event()
    release_task = Event()
    shutdown_started = Event()
    shutdown_finished = Event()
    running = engine.submit(
        wait_for_release, task_started, release_task, backend="thread"
    )
    assert task_started.wait(timeout=5)

    engine.shutdown(wait=False)

    def wait_for_shutdown() -> None:
        shutdown_started.set()
        engine.shutdown(wait=True)
        shutdown_finished.set()

    shutdown_thread = Thread(target=wait_for_shutdown)
    shutdown_thread.start()
    try:
        assert shutdown_started.wait(timeout=5)
        assert not shutdown_finished.wait(timeout=0.1)
    finally:
        release_task.set()

    assert shutdown_finished.wait(timeout=5)
    shutdown_thread.join(timeout=5)
    assert not shutdown_thread.is_alive()
    assert running.result(timeout=5) == 42


def test_shutdown_cancel_futures_cancels_queued_tasks() -> None:
    engine = ExecutionEngine(thread_config={"max_workers": 1, "max_in_flight": 2})
    task_started = Event()
    release_task = Event()
    running = engine.submit(
        wait_for_release, task_started, release_task, backend="thread"
    )
    queued: Optional[Future[int]] = None

    try:
        assert task_started.wait(timeout=5)
        queued = engine.submit(lambda: 1, backend="thread")
        engine.shutdown(wait=False, cancel_futures=True)
        assert queued.cancelled()
    finally:
        release_task.set()

    assert running.result(timeout=5) == 42
    engine.shutdown(wait=True)
