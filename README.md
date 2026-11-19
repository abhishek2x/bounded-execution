# bounded-execution

**Bounded admission control for Python thread and process executors.**

`bounded-execution` is a synchronous library that limits how many tasks
can be submitted without completing. Python's native executors limit
concurrent workers, but ordinary `submit()` calls can continue to queue
work. This library adds per-backend in-flight limits and producer
backpressure while leaving execution and `Future` behavior to
`concurrent.futures`.

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

## Choosing a backend

- Use **threads** for blocking I/O and work that spends substantial time
  waiting.
- Use **processes** for CPU-heavy pure-Python work when parallel
  execution justifies process startup and serialization overhead.

Process tasks and their arguments generally need to be picklable. Define
process worker functions at module scope and protect process startup code
with `if __name__ == "__main__":` where required by the platform.

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

See the runnable [thread example](examples/thread_example.py) and
[process example](examples/process_example.py) for standalone examples.

## Project layout

```text
.
├── examples/                  # Runnable thread and process examples
├── benchmarks/                # Submission comparison benchmark
├── src/bounded_execution/     # Installable Python package
├── tests/                     # Configuration, backend, and API tests
├── CHANGELOG.md               # Release history
├── MANIFEST.in                # Source distribution contents
└── pyproject.toml             # Packaging and tool configuration
```

Run `python benchmarks/bounded_submission.py --help` for benchmark
options.

## Scope

The initial release is an in-process execution library, not a distributed
queue or workflow system. Async scheduling, automatic backend selection,
retries, pipelines, rate limiting, and priority scheduling are outside
the v0.1 scope.

## Future scope

Potential additions after the synchronous API is established include:

- A separate async API with event-loop-safe admission and lifecycle
  handling.
- An interpreter-pool backend when supported by the Python runtime
  (Python 3.14+).
- Opt-in retries with bounded scheduling, backoff, and clear guidance on
  idempotency.
- Multi-stage task pipelines and an optional global capacity budget
  across backends.

These are possible directions, not features of the current release.
