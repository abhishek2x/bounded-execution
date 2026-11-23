"""Bounded admission control for Python executor backends."""

from bounded_execution.async_engine import AsyncExecutionEngine
from bounded_execution.engine import ExecutionEngine
from bounded_execution.exceptions import (
    EngineClosedError,
    ExecutionEngineError,
    InvalidConfigurationError,
    UnsupportedBackendError,
)

__version__ = "0.1.0a4"

__all__ = [
    "AsyncExecutionEngine",
    "EngineClosedError",
    "ExecutionEngine",
    "ExecutionEngineError",
    "InvalidConfigurationError",
    "UnsupportedBackendError",
    "__version__",
]
