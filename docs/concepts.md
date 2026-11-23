# Core concepts and backend selection

## Worker count and in-flight work

`max_workers` controls concurrent execution within one backend. It does
not limit how many tasks can be submitted to a native executor.

`max_in_flight` controls accepted tasks that have not reached a terminal
Future state. It includes both work waiting in the executor's queue and
work currently executing. Completed, failed, and cancelled tasks no
longer count.

The v0.1 contract requires `max_in_flight >= max_workers`, so the
admission limit does not prevent all configured workers from being
occupied.

## Backpressure

When a backend has no in-flight capacity, a producer calling synchronous
`submit()` waits for an accepted task to complete, fail, or be cancelled.
This slows admission into the executor and bounds queued-plus-running
work. The wait has no timeout in v0.1.

Backpressure does not reduce task execution time or guarantee a lower
end-to-end latency. It limits the amount of outstanding work and the
resources retained for that work.

## Conditions and thread coordination

A `threading.Condition` coordinates threads around shared state. In this
engine, the shared state is the in-flight task count and whether the
engine is still open. A condition does not pass data between threads or
store notifications for later.

The condition's lock must be held when calling `wait()` or
`notify_all()`:

- `wait()` atomically releases the lock and suspends the calling thread.
  When awakened, it reacquires the lock before returning.
- `notify_all()` wakes threads currently waiting on that condition, but
  does not release the lock. Awakened threads continue only after the
  notifying thread releases it.

A notification means “check the shared state again,” not “you now own
capacity.” Multiple awakened submitters compete for the lock and each
rechecks the `while` predicate; a submitter that still finds the limit
full waits again. The loop is also necessary because a condition can
wake spuriously.

Here, a completed Future decreases `_in_flight` and notifies waiters.
Shutdown changes the engine state and notifies them, so waiting
submitters wake, observe that the engine is closing, and raise
`EngineClosedError`.

## Choosing a backend

### Threads

Use the thread backend for blocking I/O, such as synchronous network,
database, or file operations. Threads share process memory, so mutable
shared state may need synchronization. Under conventional CPython, pure
Python CPU-bound work generally does not gain parallel execution from
threads.

### Processes

Use the process backend for independent CPU-heavy pure-Python work when
parallelism is worth the process and serialization costs. Functions and
arguments generally need to be picklable. Prefer module-level worker
functions, and use the `if __name__ == "__main__":` guard for portable
program startup where required by the platform.

`process_config` can pass an `initializer` and tuple `initargs`; the
initializer runs once for each worker process, including replacements.
On Python 3.11+, `max_tasks_per_child` asks the native executor to replace
a worker after it has processed the configured number of tasks. This
option selects spawn semantics, which adds worker startup overhead and
requires the usual safe process-startup guard. It is not available on
Python 3.9 or 3.10.

Cancelling a Future does not forcibly stop work that is already running.
See [the public contract](contracts.md) for cancellation and shutdown
details.

## Scope boundaries

This project wraps Python's native executors; it does not implement its
own thread pool, process pool, or Future. Distributed dispatch,
automatic workload detection, async execution inside worker processes,
retries, and workflow orchestration are not part of v0.1.

`AsyncExecutionEngine` is a separate API for native coroutines and
synchronous offloading. It must not block the event-loop thread and
uses asynchronous capacity waiting.
