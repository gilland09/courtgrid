# Phase 5 Performance Benchmark Report

## Objective

Compare the Django serial availability evaluator with the parallel candidate
evaluator reached through the FastAPI HTTP service. Correctness is a
precondition for reporting performance: the benchmark compares the returned
slot sets and stops with an error if they differ.

## Methodology

The benchmark script, `benchmarks/run_benchmark.py`, creates an entirely
synthetic workload consisting of:

- 1 synthetic sport;
- 10 explicitly labeled synthetic facilities;
- 10 bookable resources (one per facility);
- Operating-hour and sport-schedule records for the target date;
- One synthetic closure per resource; and
- **70 available candidate slots** after schedule and closure filtering.

It records 10 serial evaluations and 10 calls to the parallel evaluator over
HTTP to the separately running FastAPI service on port 8001. The serial and
parallel result sets are compared before medians and speedup are reported.
The synthetic database records are created inside a transaction that is rolled
back after the run. A post-run check found no benchmark facilities or sports
left in the database.

Elapsed times are measured with `time.perf_counter()` and summarized using the
median of each set of 10 observations. The serial timer covers execution of
the Django serial evaluator. The parallel HTTP timer covers the Django client
call to FastAPI, including request serialization/HTTP transport and the
service's process-pool evaluation. Consequently, this is an observed
application-path comparison, not an isolated CPU-only comparison.

## Results

| Metric | Observed result |
|---|---:|
| Synthetic facilities | 10 |
| Synthetic bookable resources | 10 |
| Available slots | 70 |
| Iterations per evaluator | 10 |
| Serial median | 1.548 s |
| Parallel HTTP median | 0.542 s |
| Measured speedup (`serial / parallel`) | 2.86× |
| Serial/parallel slot sets identical | Yes |
| Benchmark records persisted | No; transaction rolled back |

These are measurements from one run on the project workstation. They are
specific to this workload and environment and should not be interpreted as a
universal speedup guarantee.

## Analysis and academic justification

Candidate-slot checks are independent once Django has assembled a read-only
snapshot of facilities, operating hours, schedules, closures, and confirmed
booking intervals. Evaluating separate facilities therefore has an
embarrassingly parallel structure: each worker can evaluate its assigned
facility using ordinary, picklable dictionaries, without coordinating writes
or sharing a database connection. `ProcessPoolExecutor` can run CPU-bound
Python work in multiple processes and use multiple CPU cores when available.

The observed 2.86× result reflects the complete tested implementation path,
not parallelism alone. The serial reference evaluator performs repeated
Django/ORM availability checks, while the parallel path sends a serialized
snapshot to a separate process and evaluates that snapshot in workers. The
measured difference therefore includes both the evaluator design and the
parallel execution path; it does not isolate a pure CPU scaling factor.

The parallel path also incurs costs: Django must collect and serialize
database data, HTTP adds transport and request/response overhead, and a
process pool must start workers and serialize work between processes. These
fixed costs can outweigh parallel computation for tiny workloads. For larger
candidate sets, the independent work offers more opportunity to amortize
serialization, HTTP, and process-startup overhead, so parallel evaluation may
be beneficial. Workload-size benchmarks are still required before asserting a
threshold or generalizing the result.

## Reproducibility and interpretation

Run the benchmark with the project virtual environment while the PostgreSQL
database and FastAPI service are available:

```powershell
.\.venv\Scripts\python.exe benchmarks\run_benchmark.py
```

The script uses unique synthetic names and rolls all generated records back,
but it depends on an available configured Django database and a reachable
FastAPI service at `FASTAPI_URL` (default `http://127.0.0.1:8001`). The reported
benchmark is local multi-process and HTTP communication on one workstation; it
does not demonstrate deployment across multiple physical machines.
