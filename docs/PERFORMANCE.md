# Offline performance measurements

Quality and correct external actions take precedence over processing speed. The worker deliberately completes one opportunity before advancing; these measurements do not change its ordering, provider waits, GPT budgets or review gates.

## Method

`scripts/benchmark_local.py` creates a temporary SQLite workspace with a fictional candidate, ten verified project records and 1, 100 or 1,000 compact fictional opportunities. It preloads the read workload in one transaction, warms each endpoint and measures 20 sequential in-process FastAPI/TestClient requests. Median and nearest-rank p95 use `perf_counter`. A separate single list read uses `tracemalloc` to report peak traced Python allocations; tracing is off during the latency samples.

The benchmark measures `/api/health`, `/api/settings`, `/api/applications`, `/api/worker/status` and deterministic fit evaluation. It asserts response success, list size/order, expected fit and zero application attempts/submission records. The temporary workspace is removed afterwards. It does not load `.env`, inspect live data, call OpenAI, launch a provider browser or submit applications/invitations. Storage insertion cost, TCP, UI rendering, PDF generation, model latency and provider timing are outside its scope.

## Windows baseline, 5 October 2026 (Europe/London)

The [machine-readable report](../benchmarks/local_performance_2026-10-05.json) records Python 3.14.2 on Windows. The report timestamp is UTC, when the local date had already advanced to 5 October.

| Opportunities | List median | List p95 | Response size | Peak traced Python allocations |
| --- | --- | --- | --- | --- |
| 1 | 2.49 ms | 2.87 ms | 498 bytes | 51,060 bytes |
| 100 | 3.62 ms | 4.60 ms | 50,069 bytes | 353,935 bytes |
| 1,000 | 11.95 ms | 15.61 ms | 504,573 bytes | 3,186,478 bytes |

At 1,000 opportunities, settings median/p95 was 3.25/4.79 ms, worker status 2.68/2.88 ms and deterministic fit evaluation 0.70/0.80 ms. Peak traced allocations are neither process RSS nor total browser memory. The sample uses compact jobs without lengthy descriptions, document manifests or a large journal; it does not establish capacity for every real workspace.

The measurements show response size and list allocations growing with queue size. There is no measured reason to weaken verification or parallelise submissions. For a substantially larger archive, server-side list pagination and bounded summaries should be assessed with representative long descriptions before implementing them; currently the dashboard retrieves the complete opportunity list.

## Complete-validation recheck, 6 October 2026

The [new report](../benchmarks/local_performance_2026-10-06.json) repeats the same fictional workload on Windows/Python 3.14.2 with the current question-library implementation. It was collected whilst the complete test suites were running, so timings include possible resource contention and do not provide a controlled comparison with the earlier baseline.

| Opportunities | List median | List p95 | Response size | Peak traced Python allocations |
| --- | --- | --- | --- | --- |
| 1 | 4.17 ms | 5.91 ms | 498 bytes | 51,229 bytes |
| 100 | 4.53 ms | 6.37 ms | 50,069 bytes | 353,967 bytes |
| 1,000 | 14.45 ms | 23.99 ms | 504,573 bytes | 3,186,510 bytes |

All count/order, fit and zero-send assertions passed. The independent performance-contract tests remain part of the complete Python suite. These in-process observations exclude TCP, rendering, PDFs, model calls and actual provider operations; no throughput or live submission latency is inferred.

## Reproduction and CI

```powershell
uv run python scripts/benchmark_local.py
uv run python scripts/benchmark_local.py --sizes 1 100 1000 --repeats 20 --output test-results/local-benchmark.json
uv run python -m pytest tests/test_local_performance.py tests/test_security_hardening.py --no-cov -o 'addopts=--strict-markers'
```

Workloads are bounded to five sizes, each with 1–5,000 opportunities and 5–100 repetitions. CI records the same default benchmark for every Windows/Linux and Python 3.12/3.14 combination and uploads its JSON alongside coverage artifacts. Absolute latency is informational: shared runners, disk contention and tracing affect timing. The tests gate correctness and measurement contracts rather than a fragile universal millisecond threshold.

Hard resource boundaries are enforced independently: API requests stop at 500,000 bytes or a ten-second intake deadline; public board intake stops at 5,000,000 bytes and refuses unsolicited compression. Security regressions verify cancellation, stream closure, exact size boundaries and absence of application side effects. [Testing](TESTING.md) distinguishes these assertions from timing observations and live-provider compatibility.
