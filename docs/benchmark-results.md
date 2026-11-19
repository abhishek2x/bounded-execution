# Benchmark results

These are local smoke measurements, not general performance claims. Each
reported value is the median of three runs on Python 3.9.6, macOS
26.6.2, arm64, 8 logical CPUs, with 4 workers and `max_in_flight=16`.
Parent peak memory is Python `tracemalloc` data; it excludes child
process memory.

| Workload               | Submission mode    | Tasks | Total seconds | Peak in-flight | Parent peak bytes |
| ---------------------- | ------------------ | ----: | ------------: | -------------: | ----------------: |
| Tiny                   | Native unbounded   | 5,000 |        0.1561 |   846 observed |         2,238,841 |
| Tiny                   | Native + semaphore | 5,000 |        0.1404 |             16 |           202,485 |
| Tiny                   | `ExecutionEngine`  | 5,000 |        0.1668 |             16 |           214,117 |
| I/O, 1 ms              | Native unbounded   |   200 |        0.0673 |            200 |           479,025 |
| I/O, 1 ms              | Native + semaphore |   200 |        0.0654 |             16 |            48,111 |
| I/O, 1 ms              | `ExecutionEngine`  |   200 |        0.0658 |             16 |            49,081 |
| CPU, 10,000 iterations | Native unbounded   |   500 |        1.9391 |            489 |         1,172,224 |
| CPU, 10,000 iterations | Native + semaphore |   500 |        1.9633 |             16 |            62,241 |
| CPU, 10,000 iterations | `ExecutionEngine`  |   500 |        2.0407 |             16 |            63,847 |

The bounded modes observed no more than 16 incomplete tasks. In these
runs, the engine and a manual semaphore had similar I/O total times and
parent allocation peaks. Tiny and CPU-thread tasks exposed additional
orchestration overhead in the engine relative to direct native
submission. Thread CPU results do not demonstrate parallel speedup;
benchmark your own workload before choosing limits.

Reproduce with the commands in [benchmarking.md](benchmarking.md). The
process backend has not been measured in this sandbox because native
process-pool semaphore creation is blocked; run the process workload on
a normal development machine before publishing benchmark conclusions.
