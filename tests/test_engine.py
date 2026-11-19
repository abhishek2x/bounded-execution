from concurrent.futures import Future

import pytest

from bounded_execution import EngineClosedError, ExecutionEngine
from bounded_execution.exceptions import UnsupportedBackendError


def add(left: int, right: int) -> int:
    return left + right


def raise_value_error() -> None:
    raise ValueError("task failed")


def make_engine(backend: str) -> ExecutionEngine:
    config = {"max_workers": 1, "max_in_flight": 1}
    if backend == "thread":
        return ExecutionEngine(thread_config=config)
    return ExecutionEngine(process_config=config)


@pytest.mark.parametrize("backend", ["thread", "process"])
def test_selected_backend_returns_native_future_and_result(
    backend: str,
) -> None:
    with make_engine(backend) as engine:
        future = engine.submit(add, 20, 22, backend=backend)

        assert isinstance(future, Future)
        assert future.result(timeout=10) == 42


@pytest.mark.parametrize("backend", ["thread", "process"])
def test_task_exception_is_exposed_by_future(backend: str) -> None:
    with make_engine(backend) as engine:
        future = engine.submit(raise_value_error, backend=backend)

        with pytest.raises(ValueError, match="task failed"):
            future.result(timeout=10)

        assert engine.submit(add, 20, 22, backend=backend).result(timeout=10) == 42


def test_unconfigured_backend_is_rejected() -> None:
    with ExecutionEngine(
        thread_config={"max_workers": 1, "max_in_flight": 1}
    ) as engine:
        with pytest.raises(UnsupportedBackendError):
            engine.submit(add, 1, 2, backend="process")


def test_unknown_backend_is_rejected() -> None:
    with ExecutionEngine(
        thread_config={"max_workers": 1, "max_in_flight": 1}
    ) as engine:
        with pytest.raises(UnsupportedBackendError):
            engine.submit(add, 1, 2, backend="unknown")


def test_submission_after_shutdown_is_rejected() -> None:
    engine = ExecutionEngine(thread_config={"max_workers": 1, "max_in_flight": 1})
    engine.shutdown()

    with pytest.raises(EngineClosedError):
        engine.submit(add, 1, 2, backend="thread")
