from importlib.metadata import version

import bounded_execution


def test_installed_distribution_matches_package_version() -> None:
    assert bounded_execution.__version__ == version("bounded-execution")
