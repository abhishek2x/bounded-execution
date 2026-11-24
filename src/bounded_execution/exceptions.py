"""Public exceptions raised by the execution engine."""


class ExecutionEngineError(Exception):
    """Base class for execution-engine errors."""


class UnsupportedBackendError(ExecutionEngineError):
    """Raised when a backend is unknown or not configured."""


class EngineClosedError(ExecutionEngineError):
    """Raised when submitting work after engine shutdown begins."""


class InvalidConfigurationError(ExecutionEngineError, ValueError):
    """Raised when engine or backend configuration is invalid."""


class RemoteExecutionError(ExecutionEngineError):
    """Raised when a remote task result or exception cannot be transferred."""


class WorkerProcessError(ExecutionEngineError):
    """Raised when an asynchronous process worker exits unexpectedly."""
