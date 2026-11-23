"""ProcessPoolExecutor adapter."""

from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from threading import Condition
from typing import Any, Optional, TypeVar

from bounded_execution.admission import AdmissionController

_Result = TypeVar("_Result")


class ProcessBackend:
    """Owns a native process pool and exposes its submission interface."""

    def __init__(
        self,
        max_workers: int,
        max_in_flight: int,
        *,
        condition: Condition,
        is_open: Callable[[], bool],
        initializer: Optional[Callable[..., Any]] = None,
        initargs: tuple[object, ...] = (),
        # Optional; defaults to no recycling and is only needed in specific
        # cases such as isolating state or resource leaks between worker lifetimes.
        max_tasks_per_child: Optional[int] = None,
    ) -> None:
        executor_options: dict[str, Any] = {
            "initializer": initializer,
            "initargs": initargs,
        }
        if max_tasks_per_child is not None:
            executor_options["max_tasks_per_child"] = max_tasks_per_child
        self._executor = ProcessPoolExecutor(
            max_workers=max_workers,
            **executor_options,
        )
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
        """Shut down the owned native process pool."""
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
