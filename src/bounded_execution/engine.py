"""Public synchronous execution engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future
from enum import Enum
from threading import Condition, Lock
from types import TracebackType
from typing import Any, Optional, TypeVar, Union

from bounded_execution.backends.process import ProcessBackend
from bounded_execution.backends.thread import ThreadBackend
from bounded_execution.config import validate_process_config, validate_thread_config
from bounded_execution.exceptions import (
    EngineClosedError,
    InvalidConfigurationError,
    UnsupportedBackendError,
)

_Result = TypeVar("_Result")
_Backend = Union[ThreadBackend, ProcessBackend]


class _EngineState(Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class ExecutionEngine:
    """Route work through bounded native thread and process executors.

    Configure at least one backend. Each backend requires positive
    ``max_workers`` and ``max_in_flight`` values.
    """

    def __init__(
        self,
        *,
        thread_config: Optional[Mapping[str, object]] = None,
        process_config: Optional[Mapping[str, object]] = None,
    ) -> None:
        thread_limits = validate_thread_config(thread_config)
        process_limits = validate_process_config(process_config)
        if thread_limits is None and process_limits is None:
            raise InvalidConfigurationError(
                "Configure at least one of thread_config or process_config."
            )

        self._condition = Condition()
        self._shutdown_lock = Lock()
        self._state = _EngineState.OPEN
        self._backends: dict[str, _Backend] = {}

        if thread_limits is not None:
            self._backends["thread"] = ThreadBackend(
                thread_limits.max_workers,
                thread_limits.max_in_flight,
                condition=self._condition,
                is_open=self._is_open,
            )
        if process_limits is not None:
            self._backends["process"] = ProcessBackend(
                process_limits.max_workers,
                process_limits.max_in_flight,
                condition=self._condition,
                is_open=self._is_open,
                initializer=process_limits.initializer,
                initargs=process_limits.initargs,
                max_tasks_per_child=process_limits.max_tasks_per_child,
            )

    def submit(
        self,
        fn: Callable[..., _Result],
        /,
        *args: Any,
        backend: str,
        **kwargs: Any,
    ) -> Future[_Result]:
        """Submit work and return its native Future.

        This call blocks when the selected backend has reached its
        ``max_in_flight`` limit. The ``backend`` argument is required.
        """
        selected_backend = self._backends.get(backend)
        if selected_backend is None:
            with self._condition:
                if self._state is not _EngineState.OPEN:
                    raise EngineClosedError(
                        "Cannot submit work after engine shutdown begins."
                    )
            raise UnsupportedBackendError(
                f"Backend {backend!r} is unknown or not configured."
            )
        return selected_backend.submit(fn, *args, **kwargs)

    def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        """Stop accepting tasks and shut down configured executors.

        Waiting submitters are woken and rejected. With ``wait=False``,
        already accepted work may continue after this method returns.
        """
        with self._shutdown_lock:
            with self._condition:
                if self._state is _EngineState.OPEN:
                    self._state = _EngineState.CLOSING
                self._condition.notify_all()

            for backend in self._backends.values():
                backend.shutdown(wait=wait, cancel_futures=cancel_futures)

            with self._condition:
                self._state = _EngineState.CLOSED
                self._condition.notify_all()

    def _is_open(self) -> bool:
        return self._state is _EngineState.OPEN

    def __enter__(self) -> ExecutionEngine:
        """Return this engine for use as a context manager."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """Wait for submitted work when leaving the context."""
        self.shutdown()
