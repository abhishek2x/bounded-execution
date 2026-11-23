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

## Error boundaries

The public exception names are `ExecutionEngineError` (base),
`UnsupportedBackendError` (unknown or unconfigured backend),
`EngineClosedError` (submission after shutdown starts, including an
awakened waiting submitter), and `InvalidConfigurationError` (also a
`ValueError`). Exceptions raised by submitted functions are not wrapped;
they remain available from the Future. Native executor errors, including
process serialization failures, are surfaced rather than converted into
successful-looking fallback results.
