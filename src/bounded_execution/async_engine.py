"""Public asynchronous execution engine."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
from typing import Any, Optional, TypeVar, cast

from bounded_execution.config import (
    validate_async_config,
    validate_process_config,
    validate_thread_config,
)
from bounded_execution.exceptions import (
    EngineClosedError,
    InvalidConfigurationError,
    UnsupportedBackendError,
)

_Result = TypeVar("_Result")


class AsyncExecutionEngine:
    """Route work through bounded asynchronous and native executors.

    Native coroutine functions use ``backend="async"``. Synchronous functions
    use ``backend="thread"`` or ``backend="process"``.
    """

    def __init__(
        self,
        *,
        async_config: Optional[Mapping[str, object]] = None,
        thread_config: Optional[Mapping[str, object]] = None,
        process_config: Optional[Mapping[str, object]] = None,
    ) -> None:
        async_limits = validate_async_config(async_config)
        thread_limits = validate_thread_config(thread_config)
        process_limits = validate_process_config(process_config)
        if async_limits is None and thread_limits is None and process_limits is None:
            raise InvalidConfigurationError(
                "Configure async_config, thread_config, or process_config."
            )

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._state = "open"
        self._condition = asyncio.Condition()
        self._in_flight: dict[str, int] = {}
        self._limits: dict[str, int] = {}
        self._tasks: set[asyncio.Future[Any]] = set()

        self._thread_executor: Optional[ThreadPoolExecutor] = None
        self._process_executor: Optional[ProcessPoolExecutor] = None

        if async_limits is not None:
            self._limits["async"] = async_limits.max_in_flight
            self._in_flight["async"] = 0
        if thread_limits is not None:
            self._limits["thread"] = thread_limits.max_in_flight
            self._in_flight["thread"] = 0
            self._thread_executor = ThreadPoolExecutor(
                max_workers=thread_limits.max_workers
            )
        if process_limits is not None:
            executor_options: dict[str, Any] = {
                "initializer": process_limits.initializer,
                "initargs": process_limits.initargs,
            }
            if process_limits.max_tasks_per_child is not None:
                executor_options["max_tasks_per_child"] = (
                    process_limits.max_tasks_per_child
                )
            self._limits["process"] = process_limits.max_in_flight
            self._in_flight["process"] = 0
            self._process_executor = ProcessPoolExecutor(
                max_workers=process_limits.max_workers,
                **executor_options,
            )

    def _bind_loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError(
                "AsyncExecutionEngine cannot be used across different event loops."
            )
        return loop

    async def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        backend: str,
        **kwargs: Any,
    ) -> asyncio.Future[_Result]:
        """Admit and submit work asynchronously.

        Awaiting this method waits for capacity and returns an asyncio Future.
        Use ``backend="async"`` only for coroutine functions. Use ``thread``
        or ``process`` for synchronous functions.
        """
        loop = self._bind_loop()
        if backend not in self._limits:
            if self._state != "open":
                raise EngineClosedError(
                    "Cannot submit work after engine shutdown begins."
                )
            raise UnsupportedBackendError(
                f"Backend {backend!r} is unknown or not configured."
            )

        async with self._condition:
            while (
                self._in_flight[backend] >= self._limits[backend]
                and self._state == "open"
            ):
                await self._condition.wait()
            if self._state != "open":
                raise EngineClosedError(
                    "Cannot submit work after engine shutdown begins."
                )
            self._in_flight[backend] += 1

        try:
            task: asyncio.Future[_Result] = await self._create_task(
                loop, backend, fn, args, kwargs
            )
        except BaseException:
            await self._release(backend)
            raise

        self._tasks.add(task)
        task.add_done_callback(lambda done: self._task_done(backend, done))
        return task

    async def _create_task(
        self,
        loop: asyncio.AbstractEventLoop,
        backend: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> asyncio.Future[_Result]:
        if backend == "async":
            if not inspect.iscoroutinefunction(fn):
                raise TypeError("The 'async' backend requires a coroutine function.")
            result = fn(*args, **kwargs)
            if not inspect.isawaitable(result):
                raise TypeError("The 'async' backend returned a non-awaitable result.")
            return cast(asyncio.Future[_Result], asyncio.ensure_future(result))

        if inspect.iscoroutinefunction(fn):
            raise TypeError(f"The {backend!r} backend requires a synchronous function.")
        executor = (
            self._thread_executor if backend == "thread" else self._process_executor
        )
        if executor is None:
            raise UnsupportedBackendError(
                f"Backend {backend!r} is unknown or not configured."
            )
        wrapped = loop.run_in_executor(executor, partial(fn, *args, **kwargs))
        return cast(asyncio.Future[_Result], asyncio.ensure_future(wrapped))

    def _task_done(
        self,
        backend: str,
        task: asyncio.Future[Any],
    ) -> None:
        self._tasks.discard(task)
        asyncio.create_task(self._release(backend))

    async def _release(self, backend: str) -> None:
        async with self._condition:
            self._in_flight[backend] -= 1
            self._condition.notify_all()

    async def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        """Stop admission and shut down owned native executors."""
        self._bind_loop()
        async with self._condition:
            if self._state == "open":
                self._state = "closing"
            self._condition.notify_all()

        if cancel_futures:
            for task in tuple(self._tasks):
                task.cancel()

        if wait:
            if self._tasks:
                await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

        shutdown_calls: list[Awaitable[None]] = []
        if self._thread_executor is not None:
            shutdown_calls.append(
                asyncio.to_thread(
                    self._thread_executor.shutdown,
                    wait=wait,
                    cancel_futures=cancel_futures,
                )
            )
        if self._process_executor is not None:
            shutdown_calls.append(
                asyncio.to_thread(
                    self._process_executor.shutdown,
                    wait=wait,
                    cancel_futures=cancel_futures,
                )
            )
        if shutdown_calls:
            await asyncio.gather(*shutdown_calls)

        async with self._condition:
            self._state = "closed"
            self._condition.notify_all()

    async def __aenter__(self) -> AsyncExecutionEngine:
        self._bind_loop()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[object],
    ) -> None:
        await self.shutdown(wait=True)
