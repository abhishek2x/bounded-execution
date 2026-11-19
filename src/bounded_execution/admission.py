"""Per-backend bounded task admission."""

from collections.abc import Callable
from concurrent.futures import Executor, Future
from threading import Condition
from typing import Any, TypeVar

from bounded_execution.exceptions import EngineClosedError

_Result = TypeVar("_Result")


class AdmissionController:
    """Limit submitted-but-incomplete work for one executor."""

    def __init__(
        self,
        max_in_flight: int,
        condition: Condition,
        is_open: Callable[[], bool],
    ) -> None:
        self._max_in_flight = max_in_flight
        self._condition = condition
        self._is_open = is_open
        self._in_flight = 0

    def submit(
        self,
        executor: Executor,
        fn: Callable[..., _Result],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[_Result]:
        """Wait for a slot, submit work, and release the slot on completion."""

        with self._condition:
            while self._in_flight >= self._max_in_flight and self._is_open():
                self._condition.wait()
            if not self._is_open():
                raise EngineClosedError(
                    "Cannot submit work after engine shutdown begins."
                )

            self._in_flight += 1
            try:
                future = executor.submit(fn, *args, **kwargs)
            except BaseException:
                self._in_flight -= 1
                self._condition.notify_all()
                raise

            future.add_done_callback(self._release)
            return future

    def _release(self, _: Future[Any]) -> None:
        with self._condition:
            self._in_flight -= 1
            self._condition.notify_all()
