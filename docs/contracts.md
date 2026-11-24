# Public contract for v0.1

This document records the public API and lifecycle contract.

The package supports Python 3.9 and newer.

## Engine configuration

Construct `ExecutionEngine` with `thread_config`, `process_config`, or
both. Each configured mapping requires these keys:

| Key | Requirement | Meaning |
| --- | --- | --- |
| `max_workers` | Positive integer | Maximum tasks executing simultaneously |
| `max_in_flight` | Integer greater than or equal to `max_workers` | Maximum accepted tasks that have not completed |

At least one backend must be configured. A backend without a
configuration is unavailable on that engine. There are no implicit
worker-count defaults. Unknown keys and invalid values are configuration errors. Booleans are not accepted as integer limits.

`process_config` additionally accepts these optional native process-pool
settings:

| Key | Requirement | Meaning |
| --- | --- | --- |
| `initializer` | Callable or `None` | Called once when each worker starts, including replacement workers |
| `initargs` | Tuple; defaults to `()` | Arguments passed to `initializer` |
| `max_tasks_per_child` | Positive integer or `None`; defaults to `None` | Recycle a worker after it has processed this many tasks; requires Python 3.11+ |

Worker initialization functions and their arguments must meet the native
process pool's pickling requirements. When worker recycling is enabled,
Python uses spawn semantics, which can increase startup overhead and
requires the usual safe process-startup guard. The option is unavailable
on Python 3.9 and 3.10; setting a non-`None` value there raises
`InvalidConfigurationError`.

Each backend has an independent in-flight limit; v0.1 does not impose a
combined global limit.

## Submission

The v0.1 signature is:

```python
future = engine.submit(fn, *args, backend="thread", **kwargs)
```

The backend argument is required and reserved by the engine; it is not
passed to the submitted function. Backend names are `thread` and
`process`. The engine returns the native
`concurrent.futures.Future`, and task results and exceptions are
observed through its standard methods.

If capacity is exhausted, `submit()` waits indefinitely until capacity is
available. The admission permit is held from submission through queueing
and execution, and released when the Future is completed, failed, or
cancelled. If native submission fails, the reserved permit is released
and the original error propagated. v0.1 has no submission timeout,
non-blocking submission, or `map()` method.

## Cancellation

Cancellation follows the underlying executor's Future semantics.
Cancelling queued work may succeed; cancelling running work generally
cannot stop the function. Capacity remains reserved until the Future
reaches a terminal state. The library does not promise to forcibly stop
threads or processes.

## Shutdown and context management

`shutdown(wait=True, cancel_futures=False)` is the default.

- Shutdown atomically closes admission and wakes producers waiting for
  capacity; those producers and later submitters receive
  `EngineClosedError`.
- With `wait=True`, shutdown waits for accepted work to finish.
- With `wait=False`, shutdown returns without waiting, but accepted work
  is not abandoned and may continue in the background.
- With `cancel_futures=True`, queued work is cancelled where the native
  executor supports it. Running work is not forcibly stopped.
- Repeated shutdown calls are safe. A later waiting shutdown may wait
  for work after a prior non-waiting call.
- Exiting an engine context is equivalent to
  `shutdown(wait=True, cancel_futures=False)`.

The engine is ready for use after construction; entering its context
does not create additional resources.

## Async contract

`AsyncExecutionEngine` is a separate API for callers running an asyncio
event loop. It may be constructed with `async_config`, `thread_config`,
and/or `process_config`; at least one backend must be configured.

- `async_config` contains exactly `max_in_flight`, a positive integer.
- `submit()` is asynchronous. It waits for capacity, then returns an
  `asyncio.Future`/Task.
- `backend="async"` accepts a native coroutine function and executes it
  on the caller's event loop.
- `backend="thread"` or `"process"` accepts a synchronous function and
  offloads it to the corresponding native executor.
- Async submission, cancellation, and shutdown are confined to one event
  loop. Use the engine on the loop that creates or enters it.
- `shutdown(wait=True, cancel_futures=False)` closes admission and waits
  for accepted work; `wait=False` returns without waiting.

`AsyncProcessExecutionEngine` is a separate API for native coroutine
functions that must run in worker processes. Construct it with
`process_config` containing `max_workers`, `child_concurrency`, and
`max_in_flight`; `max_in_flight` must be at least `max_workers`.
`child_concurrency` is the maximum number of active coroutines per child,
and `max_in_flight` is the engine-wide bound on queued and running tasks.

- `submit()` is asynchronous, accepts only coroutine functions, and
  returns an `asyncio.Future`.
- Functions, arguments, and successful results must be picklable.
  Picklable task exceptions retain their original type. Untransferable
  results or exceptions raise `RemoteExecutionError`.
- Optional `initializer` / `initargs` run once per process. Optional
  `loop_initializer` / `loop_initargs` run once after that process's event
  loop starts; the loop is passed as the initializer's first argument.
  Initializers and their arguments must be picklable. The process
  initializer must be synchronous; the loop initializer may be
  synchronous or asynchronous.
- `max_worker_restarts` is a non-negative integer, defaulting to `3`.
  Unexpected worker exits fail tasks assigned to that worker with
  `WorkerProcessError`; those tasks are not replayed. A replacement worker
  is started while the restart limit permits. After the limit is reached,
  the engine rejects further submissions with `WorkerProcessError`.
- Cancelling a returned Future requests cancellation of its remote
  coroutine. Cancellation is cooperative and cannot stop synchronous or
  CPU-bound code blocking the child event loop.
- `shutdown(wait=True, cancel_futures=False)` closes admission and waits
  for accepted work. With `wait=False`, accepted work continues while
  workers shut down in the background. `cancel_futures=True` requests
  cancellation of accepted coroutines.
- Async process workers use Python's `spawn` start method. Use the usual
  `if __name__ == "__main__":` guard in executable scripts.

## Error boundaries

The public exception names are `ExecutionEngineError` (base),
`UnsupportedBackendError` (unknown or unconfigured backend),
`EngineClosedError` (submission after shutdown starts, including an
awakened waiting submitter), and `InvalidConfigurationError` (also a
`ValueError`). `RemoteExecutionError` reports result-transfer failures,
and `WorkerProcessError` reports unexpected async worker exits. Exceptions
raised by regular submitted functions are not wrapped; they remain
available from the Future. Native executor errors, including synchronous
process serialization failures, are surfaced rather than converted into
successful-looking fallback results.
