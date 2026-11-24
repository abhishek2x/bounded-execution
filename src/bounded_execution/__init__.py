"""Bounded admission control for Python execution backends."""

from bounded_execution.async_engine import AsyncExecutionEngine
from bounded_execution.async_process_engine import AsyncProcessExecutionEngine
from bounded_execution.engine import ExecutionEngine
from bounded_execution.exceptions import (
    EngineClosedError,
    ExecutionEngineError,
    InvalidConfigurationError,
    RemoteExecutionError,
    UnsupportedBackendError,
    WorkerProcessError,
)

__version__ = "0.1.0a4"

__all__ = [
    "AsyncExecutionEngine",
    "AsyncProcessExecutionEngine",
    "EngineClosedError",
    "ExecutionEngine",
    "ExecutionEngineError",
    "InvalidConfigurationError",
    "RemoteExecutionError",
    "UnsupportedBackendError",
    "WorkerProcessError",
    "__version__",
]
