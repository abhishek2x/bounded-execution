"""Configuration models and validation for execution backends."""

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional

from bounded_execution.exceptions import InvalidConfigurationError

_EXECUTOR_KEYS = frozenset({"max_workers", "max_in_flight"})
_PROCESS_OPTIONS = frozenset({"initializer", "initargs", "max_tasks_per_child"})
_ASYNC_KEYS = frozenset({"max_in_flight"})


@dataclass(frozen=True)
class _AdmissionConfig:
    max_in_flight: int


@dataclass(frozen=True)
class _ExecutorConfig(_AdmissionConfig):
    max_workers: int


@dataclass(frozen=True)
class _ProcessConfig(_ExecutorConfig):
    initializer: Optional[Callable[..., Any]] = None
    initargs: tuple[object, ...] = ()
    max_tasks_per_child: Optional[int] = None


def _validate_mapping(
    backend: str,
    config: Optional[Mapping[str, object]],
    required: frozenset[str],
    optional: frozenset[str],
) -> Optional[Mapping[str, object]]:
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise InvalidConfigurationError(f"{backend}_config must be a mapping.")

    keys = set(config)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        missing = sorted(required - keys)
        unknown = sorted(keys - required - optional, key=str)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown keys: {', '.join(map(str, unknown))}")
        raise InvalidConfigurationError(
            f"Invalid {backend}_config ({'; '.join(details)})."
        )
    return config


def _positive_int(backend: str, name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidConfigurationError(
            f"{backend}_config['{name}'] must be a positive integer."
        )
    return value


def _executor_config(
    backend: str,
    config: Mapping[str, object],
) -> _ExecutorConfig:
    max_workers = _positive_int(backend, "max_workers", config["max_workers"])
    max_in_flight = _positive_int(backend, "max_in_flight", config["max_in_flight"])
    if max_in_flight < max_workers:
        raise InvalidConfigurationError(
            f"{backend}_config['max_in_flight'] must be greater than or equal "
            "to max_workers."
        )
    return _ExecutorConfig(max_in_flight=max_in_flight, max_workers=max_workers)


def validate_async_config(
    config: Optional[Mapping[str, object]],
) -> Optional[_AdmissionConfig]:
    """Validate and construct async admission settings."""
    values = _validate_mapping("async", config, _ASYNC_KEYS, frozenset())
    if values is None:
        return None
    max_in_flight = _positive_int("async", "max_in_flight", values["max_in_flight"])
    return _AdmissionConfig(max_in_flight)


def validate_thread_config(
    config: Optional[Mapping[str, object]],
) -> Optional[_ExecutorConfig]:
    """Validate and construct thread executor settings."""
    values = _validate_mapping("thread", config, _EXECUTOR_KEYS, frozenset())
    if values is None:
        return None
    return _executor_config("thread", values)


def validate_process_config(
    config: Optional[Mapping[str, object]],
) -> Optional[_ProcessConfig]:
    """Validate and construct process executor settings."""
    values = _validate_mapping(
        "process",
        config,
        _EXECUTOR_KEYS,
        _PROCESS_OPTIONS,
    )
    if values is None:
        return None

    executor_config = _executor_config("process", values)

    initializer = values.get("initializer")
    if initializer is not None and not callable(initializer):
        raise InvalidConfigurationError(
            "process_config['initializer'] must be callable or None."
        )
    initargs = values.get("initargs", ())
    if not isinstance(initargs, tuple):
        raise InvalidConfigurationError("process_config['initargs'] must be a tuple.")

    max_tasks_per_child = values.get("max_tasks_per_child")
    if max_tasks_per_child is not None:
        max_tasks_per_child = _positive_int(
            "process", "max_tasks_per_child", max_tasks_per_child
        )
        if sys.version_info < (3, 11):
            raise InvalidConfigurationError(
                "process_config['max_tasks_per_child'] requires Python 3.11 or newer."
            )

    return _ProcessConfig(
        max_in_flight=executor_config.max_in_flight,
        max_workers=executor_config.max_workers,
        initializer=initializer,
        initargs=initargs,
        max_tasks_per_child=max_tasks_per_child,
    )
