"""Validation for per-backend engine configuration."""

from collections.abc import Mapping
from typing import Optional

from bounded_execution.exceptions import InvalidConfigurationError

_REQUIRED_KEYS = frozenset({"max_workers", "max_in_flight"})


def validate_backend_config(
    backend: str,
    config: Optional[Mapping[str, object]],
) -> Optional[tuple[int, int]]:
    """Validate a backend mapping and return its worker limits."""
    if config is None:
        return None

    if not isinstance(config, Mapping):
        raise InvalidConfigurationError(
            f"{backend}_config must be a mapping with keys "
            "'max_workers' and 'max_in_flight'."
        )

    config_keys = set(config)
    if config_keys != _REQUIRED_KEYS:
        missing = sorted(_REQUIRED_KEYS - config_keys)
        unknown = sorted(config_keys - _REQUIRED_KEYS, key=str)
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

    return max_workers, max_in_flight
