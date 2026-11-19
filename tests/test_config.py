import pytest

from bounded_execution import ExecutionEngine, InvalidConfigurationError


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
