"""ThreadPoolExecutor adapter."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Condition
from typing import Any, TypeVar

from bounded_execution.admission import AdmissionController

_Result = TypeVar("_Result")


class ThreadBackend:
    """Owns a native thread pool and exposes its submission interface."""

    def __init__(
        self,
        max_workers: int,
        max_in_flight: int,
        *,
        condition: Condition,
        is_open: Callable[[], bool],
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._admission = AdmissionController(max_in_flight, condition, is_open)

    def submit(
        self,
        fn: Callable[..., _Result],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[_Result]:
        """Submit work and return the native Future."""
        return self._admission.submit(self._executor, fn, *args, **kwargs)

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        """Shut down the owned native thread pool."""
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
