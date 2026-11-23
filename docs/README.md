# Documentation

This directory contains maintained knowledge documents by topic. Update
the relevant document when implementation changes a public contract or
an operational recommendation.

- [Core concepts and backend selection](concepts.md) — workers,
  in-flight work, backpressure, Conditions, and thread/process trade-offs.
- [Public contract](contracts.md) — configuration, submission,
  cancellation, and shutdown semantics agreed for v0.1.
- [Thread example](../examples/thread_example.py),
  [process example](../examples/process_example.py), and
  [async example](../examples/async_example.py) — runnable usage.
- [Benchmarking](benchmarking.md) — compare unbounded, semaphore-bounded,
  and library submission.
- [Benchmark results](benchmark-results.md) — a local measurement snapshot
  and its limitations.
- [Publishing to PyPI](releasing.md) — build, verify, and upload a release.

The [root README](../README.md) is the user-facing project introduction.
