"""Validation for per-backend engine configuration."""

import sys
from collections.abc import Mapping
from typing import Any, Callable, NamedTuple, Optional, cast

from bounded_execution.exceptions import InvalidConfigurationError

_REQUIRED_KEYS = frozenset({"max_workers", "max_in_flight"})
_PROCESS_OPTIONAL_KEYS = frozenset({"initializer", "initargs", "max_tasks_per_child"})


class _ValidatedBackendConfig(NamedTuple):
    max_workers: int
    max_in_flight: int
    initializer: Optional[Callable[..., Any]] = None
    initargs: tuple[object, ...] = ()
    max_tasks_per_child: Optional[int] = None


def validate_backend_config(
    backend: str,
    config: Optional[Mapping[str, object]],
) -> Optional[_ValidatedBackendConfig]:
    """Validate a backend mapping and return its normalized settings."""
    if config is None:
        return None

    optional_keys = _PROCESS_OPTIONAL_KEYS if backend == "process" else frozenset()
    allowed_keys = _REQUIRED_KEYS | optional_keys
    if not isinstance(config, Mapping):
        raise InvalidConfigurationError(
            f"{backend}_config must be a mapping with keys "
            "'max_workers' and 'max_in_flight'."
        )

    config_keys = set(config)
    if not _REQUIRED_KEYS.issubset(config_keys) or not config_keys.issubset(
        allowed_keys
    ):
        missing = sorted(_REQUIRED_KEYS - config_keys)
        unknown = sorted(config_keys - allowed_keys, key=str)
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown keys: {', '.join(map(str, unknown))}")
        raise InvalidConfigurationError(
            f"Invalid {backend}_config ({'; '.join(details)})."
        )

    max_workers = config["max_workers"]
    max_in_flight = config["max_in_flight"]
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or max_workers < 1
    ):
        raise InvalidConfigurationError(
            f"{backend}_config['max_workers'] must be a positive integer."
        )
    if (
        isinstance(max_in_flight, bool)
        or not isinstance(max_in_flight, int)
        or max_in_flight < 1
    ):
        raise InvalidConfigurationError(
            f"{backend}_config['max_in_flight'] must be a positive integer."
        )
    if max_in_flight < max_workers:
        raise InvalidConfigurationError(
            f"{backend}_config['max_in_flight'] must be greater than or equal "
            "to max_workers."
        )

    initializer = config.get("initializer")
    if initializer is not None and not callable(initializer):
        raise InvalidConfigurationError(
            "process_config['initializer'] must be callable or None."
        )

    initargs = config.get("initargs", ())
    if not isinstance(initargs, tuple):
        raise InvalidConfigurationError("process_config['initargs'] must be a tuple.")

    max_tasks_per_child = config.get("max_tasks_per_child")
    if max_tasks_per_child is not None:
        if (
            isinstance(max_tasks_per_child, bool)
            or not isinstance(max_tasks_per_child, int)
            or max_tasks_per_child < 1
        ):
            raise InvalidConfigurationError(
                "process_config['max_tasks_per_child'] must be a positive "
                "integer or None."
            )
        if sys.version_info < (3, 11):
            raise InvalidConfigurationError(
                "process_config['max_tasks_per_child'] requires Python 3.11 or newer."
            )

    return _ValidatedBackendConfig(
        max_workers=max_workers,
        max_in_flight=max_in_flight,
        initializer=cast(Optional[Callable[..., Any]], initializer),
        initargs=initargs,
        max_tasks_per_child=max_tasks_per_child,
    )
