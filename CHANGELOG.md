# Changelog

## 0.1.0a4 - 2026-11-24

- Add an async-facing execution engine for native coroutines and synchronous offloading.
- Add process worker initialization and optional worker recycling.
- Add a standalone async example covering coroutine, thread, and process backends.

## 0.1.0a2 - 2026-11-19

- Clarify planned extensions and release boundaries in the README.
- Fix `bounded_execution.__version__` to match the package release version.

## 0.1.0a1 - 2026-11-19

- Add synchronous bounded submission for thread and process backends.
- Preserve native `concurrent.futures.Future` behavior.
- Validate backend configuration and define shutdown semantics.
- Add runnable examples, topic documentation, and benchmark tooling.
