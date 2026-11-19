# Benchmarking

Run the comparison from the repository root with the development
environment active:

```sh
python benchmarks/bounded_submission.py \
  --backend thread \
  --workload tiny \
  --tasks 1000 \
  --workers 4 \
  --max-in-flight 16 \
  --repeats 5
```

Choose `--workload io` to simulate blocking I/O or `--workload cpu` for
pure-Python CPU work. `--work-units` sets sleep milliseconds for I/O and
loop iterations for CPU. For CPU-bound work, compare the thread and
process backends separately; process startup is included in total time.

The script compares:

1. Native executor submission without an admission limit.
2. Native executor submission guarded by a `BoundedSemaphore`.
3. `ExecutionEngine` with the same worker and in-flight limits.

It reports median total runtime, producer submission time, per-call
submission latency, peak observed in-flight tasks, parent-process
`tracemalloc` peak, and throughput. Manual semaphore wait time is
reported separately. For `ExecutionEngine`, each synchronous
`submit()` latency includes both admission waiting and submission
overhead; the library does not expose a separate wait-time metric.

The memory number covers Python allocations in the benchmark process,
not total operating-system memory or child-process memory. The observed
in-flight peak is tracked through Future callbacks, so tiny workloads can
complete between native submission and tracker registration. Repeat
measurements, retain the emitted Python/platform/workload/configuration
metadata, and avoid drawing conclusions from one machine or workload.
