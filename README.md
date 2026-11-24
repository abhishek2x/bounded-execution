# bounded-execution

**Bounded admission control for Python async, thread, and process execution.**

[View the package on PyPI](https://pypi.org/project/bounded-execution/).

`bounded-execution` provides separate synchronous and async APIs that
limit how many tasks can be submitted without completing. Python's
native executors limit concurrent workers, but ordinary `submit()` calls
can continue to queue work. The library adds in-flight limits and
producer backpressure while delegating execution to native executors and
the caller's event loop or process-hosted event loops.

## The two limits

- **`max_workers`** limits how many tasks execute simultaneously.
- **`max_in_flight`** limits accepted tasks that have not completed,
  including queued and running tasks. When capacity is exhausted,
  `submit()` waits until an accepted task completes, fails, or is
  cancelled.

## Usage

Configure one or both backends explicitly and select a backend for every
submission:

```python
from bounded_execution import ExecutionEngine

with ExecutionEngine(
    thread_config={"max_workers": 8, "max_in_flight": 24},
    process_config={"max_workers": 4, "max_in_flight": 12},
) as engine:
    future = engine.submit(calculate, value, backend="process")
    result = future.result()
```

Each configured mapping contains exactly `max_workers` and
`max_in_flight`, both positive integers, with
`max_in_flight >= max_workers`. At least one backend configuration is
required; there are no implicit worker-count defaults. `submit()` returns
a standard `concurrent.futures.Future`. The v0.1 API will not
include `map()`, submission timeouts, or a non-blocking submission
variant.

Each backend has an independent in-flight limit. The limit controls
admission, not task execution speed.

### Async usage

Use `AsyncExecutionEngine` when the caller is running inside an asyncio
event loop:

```python
import asyncio
from bounded_execution import AsyncExecutionEngine

async def fetch_item(item_id: int) -> str:
    await asyncio.sleep(0.1)
    return f"item-{item_id}"

async def main() -> None:
    async with AsyncExecutionEngine(
        async_config={"max_in_flight": 3}
    ) as engine:
        futures = [
            await engine.submit(fetch_item, item_id, backend="async")
            for item_id in range(5)
        ]
        for future in futures:
            print(await future)

asyncio.run(main())
```

`backend="async"` executes native coroutine functions on the event loop.
Use `backend="thread"` or `backend="process"` to offload synchronous
functions without blocking the event loop. Async capacity is configured
with `async_config={"max_in_flight": ...}`.

### Async process usage

`AsyncProcessExecutionEngine` runs native coroutine functions in separate
processes, each with its own event loop. This is useful for I/O-bound
coroutines that need process isolation or independent event loops:

```python
import asyncio
from bounded_execution import AsyncProcessExecutionEngine

async def fetch_item(item_id: int) -> str:
    await asyncio.sleep(0.1)
    return f"item-{item_id}"

async def main() -> None:
    async with AsyncProcessExecutionEngine(
        process_config={
            "max_workers": 2,
            "child_concurrency": 4,
            "max_in_flight": 8,
        }
    ) as engine:
        futures = [
            await engine.submit(fetch_item, item_id)
            for item_id in range(8)
        ]
        print(await asyncio.gather(*futures))

if __name__ == "__main__":
    asyncio.run(main())
```

Coroutine functions, arguments, and results must be picklable. Pure
Python CPU-bound work should use the synchronous process backend instead;
CPU-intensive code inside a coroutine blocks that worker's event loop.
Workers use the `spawn` start method, so keep worker functions at module
scope and guard program startup with `if __name__ == "__main__":`.

## Choosing a backend

- Use **threads** for blocking I/O and work that spends substantial time
  waiting.
- Use **processes** for CPU-heavy pure-Python work when parallel
  execution justifies process startup and serialization overhead.

Process tasks and their arguments generally need to be picklable. Define
process worker functions at module scope and protect process startup code
with `if __name__ == "__main__":` where required by the platform.
`process_config` can also pass an `initializer` and `initargs` to each
worker. On Python 3.11 and newer, `max_tasks_per_child` can recycle
workers after a configured number of tasks; worker replacement adds
startup overhead and follows the native process-pool start-method rules.
See [Core concepts and backend selection](docs/concepts.md) for more
details.

## Development setup

Requires Python 3.9 or newer.

```sh
python3.9 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
ruff check .
ruff format --check src tests examples benchmarks
mypy src tests examples benchmarks
pytest
```

See the runnable [thread example](examples/thread_example.py),
[process example](examples/process_example.py), [async example](examples/async_example.py),
and [async process example](examples/async_process_example.py) for
standalone examples.

## Project layout

```text
.
├── docs/                      # Concepts, contracts, benchmarking, and release guides
├── examples/                  # Runnable async, thread, and process examples
├── benchmarks/                # Submission comparison benchmark
├── src/bounded_execution/     # Installable Python package
├── tests/                     # Configuration, backend, and API tests
├── CHANGELOG.md               # Release history
├── MANIFEST.in                # Source distribution contents
└── pyproject.toml             # Packaging and tool configuration
```

Run `python benchmarks/bounded_submission.py --help` for benchmark
options; see the [benchmarking guide](docs/benchmarking.md) for
measurement details.

## Scope

The library provides local task execution; it is not a distributed
task queue or workflow engine. Automatic backend selection, retries,
rate limiting, and priority scheduling are not included in the current
release.

Distributed under the MIT License; see [LICENSE](LICENSE).

## Roadmap

Proposed enhancements are tracked in the
[GitHub issues](https://github.com/abhishek2x/bounded-execution/issues).
They are not implemented features or release commitments. For topic
guides, see the [documentation index](docs/README.md).
