import sys

import pytest

from bounded_execution import (
    AsyncProcessExecutionEngine,
    ExecutionEngine,
    InvalidConfigurationError,
)
from bounded_execution.config import (
    validate_async_process_config,
    validate_process_config,
)


def _initializer() -> None:
    pass


@pytest.mark.parametrize(
    "config",
    [
        {"max_workers": 0, "max_in_flight": 1},
        {"max_workers": -1, "max_in_flight": 1},
        {"max_workers": 1, "max_in_flight": 0},
        {"max_workers": 1, "max_in_flight": -1},
        {"max_workers": True, "max_in_flight": 1},
        {"max_workers": 1, "max_in_flight": 2, "extra": 3},
        {"max_workers": 1},
        {"max_workers": 2, "max_in_flight": 1},
    ],
)
def test_invalid_thread_configuration_is_rejected(
    config: dict[str, object],
) -> None:
    with pytest.raises(InvalidConfigurationError):
        ExecutionEngine(thread_config=config)


def test_at_least_one_backend_must_be_configured() -> None:
    with pytest.raises(InvalidConfigurationError):
        ExecutionEngine()


def test_non_mapping_configuration_is_rejected() -> None:
    with pytest.raises(InvalidConfigurationError):
        ExecutionEngine(thread_config=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("initializer", "not callable"),
        ("initargs", ["not", "a", "tuple"]),
        ("max_tasks_per_child", 0),
        ("max_tasks_per_child", -1),
        ("max_tasks_per_child", True),
    ],
)
def test_invalid_process_options_are_rejected(
    option: str,
    value: object,
) -> None:
    config: dict[str, object] = {
        "max_workers": 1,
        "max_in_flight": 1,
        option: value,
    }

    with pytest.raises(InvalidConfigurationError):
        ExecutionEngine(process_config=config)


def test_process_only_options_are_rejected_for_threads() -> None:
    with pytest.raises(InvalidConfigurationError, match="unknown keys: initializer"):
        ExecutionEngine(
            thread_config={
                "max_workers": 1,
                "max_in_flight": 1,
                "initializer": _initializer,
            }
        )


def test_unknown_process_option_is_rejected() -> None:
    with pytest.raises(InvalidConfigurationError, match="unknown keys: extra"):
        ExecutionEngine(
            process_config={
                "max_workers": 1,
                "max_in_flight": 1,
                "extra": True,
            }
        )


def test_process_options_are_returned_with_validated_configuration() -> None:
    config = {
        "max_workers": 2,
        "max_in_flight": 4,
        "initializer": _initializer,
        "initargs": ("worker",),
        "max_tasks_per_child": None,
    }

    validated = validate_process_config(config)

    assert validated is not None
    assert validated.max_workers == 2
    assert validated.max_in_flight == 4
    assert validated.initializer is _initializer
    assert validated.initargs == ("worker",)
    assert validated.max_tasks_per_child is None


@pytest.mark.skipif(sys.version_info >= (3, 11), reason="supported in Python 3.11+")
def test_worker_recycling_is_rejected_before_python_311() -> None:
    with pytest.raises(InvalidConfigurationError, match="requires Python 3.11"):
        ExecutionEngine(
            process_config={
                "max_workers": 1,
                "max_in_flight": 1,
                "max_tasks_per_child": 1,
            }
        )


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"max_workers": 0, "child_concurrency": 1, "max_in_flight": 1},
        {"max_workers": 1, "child_concurrency": True, "max_in_flight": 1},
        {"max_workers": 1, "child_concurrency": 1, "max_in_flight": 0},
        {"max_workers": 2, "child_concurrency": 1, "max_in_flight": 1},
        {
            "max_workers": 1,
            "child_concurrency": 1,
            "max_in_flight": 1,
            "max_worker_restarts": -1,
        },
        {
            "max_workers": 1,
            "child_concurrency": 1,
            "max_in_flight": 1,
            "loop_initargs": [],
        },
        {
            "max_workers": 1,
            "child_concurrency": 1,
            "max_in_flight": 1,
            "unexpected": True,
        },
    ],
)
def test_invalid_async_process_configuration_is_rejected(
    config: dict[str, object],
) -> None:
    with pytest.raises(InvalidConfigurationError):
        AsyncProcessExecutionEngine(process_config=config)


def test_async_process_configuration_is_validated() -> None:
    config = {
        "max_workers": 2,
        "child_concurrency": 3,
        "max_in_flight": 8,
        "initializer": _initializer,
        "initargs": ("process",),
        "loop_initializer": _initializer,
        "loop_initargs": ("event loop",),
        "max_worker_restarts": 1,
    }

    validated = validate_async_process_config(config)

    assert validated.max_workers == 2
    assert validated.child_concurrency == 3
    assert validated.max_in_flight == 8
    assert validated.initializer is _initializer
    assert validated.initargs == ("process",)
    assert validated.loop_initializer is _initializer
    assert validated.loop_initargs == ("event loop",)
    assert validated.max_worker_restarts == 1
