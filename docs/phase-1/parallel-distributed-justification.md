# Parallel Processing and Distributed-Service Justification

## Workload being evaluated

An availability search can evaluate many independent candidate combinations. A candidate may represent one physical resource, eligible sport, date, and one-hour interval. The inputs needed to decide whether it is playable include:

- The facility's operating hours.
- Whether the resource/facility supports the requested sport.
- The sport-specific recurring weekly schedule and its effective dates.
- Date/time closures that override an otherwise open schedule.
- A snapshot of existing confirmed reservations on the physical resource.

Once Django has assembled a consistent, plain-data snapshot for a search, each candidate can be tested independently. Evaluating one candidate does not require changing the result of another. This is the basis for treating candidate evaluation as an embarrassingly parallel, stateless, read-only workload.

## Serial reference and process-pool evaluator

The serial evaluator is the simple deterministic reference implementation. The process-pool evaluator should apply the same pure candidate rule to the same snapshot using `concurrent.futures.ProcessPoolExecutor`.

Implementation constraints:

- Pass plain, picklable structures (for example, strings, numbers, booleans, and simple tuples/dictionaries); do not pass ORM instances, database connections, request objects, or open handles to workers.
- Use importable top-level worker functions rather than closures or lambdas.
- Keep process creation behind an import-safe entry point and test under Windows' spawn behavior.
- Keep worker work read-only. Workers must not write booking, pricing, schedule, or closure data.
- Ensure output ordering and tie-breaking are deterministic so a serial result can be compared reliably to a parallel result.
- Preserve the physical-resource identity in each candidate. Two different sports sharing one resource must still contend for the same reservations.
- Keep the candidate evaluator separate from the final booking transaction. Its response is a search result, not a hold or reservation.

Because the dataset is copied or serialized to workers, the evaluated workload should be bounded and measured. If later measurements show that repeatedly sending full snapshots is too costly, optimize only after preserving the same observable rules and documenting the change.

## Why use a separate FastAPI service

FastAPI provides a distinct HTTP boundary for availability evaluation. Django sends a request to `POST /availability/search` and receives candidate results. This allows the project to demonstrate service-to-service HTTP communication while keeping responsibilities clear:

- **Django + PostgreSQL:** authoritative facility/catalog data, authentication, server-side price calculation, booking writes, cancellations, and final transactional conflict checks.
- **FastAPI + Uvicorn:** read-only evaluation of candidate availability data supplied to it by Django. It does not create, confirm, cancel, or price bookings and does not become a second source of booking truth.

The availability service may return a result that is stale by the time a user submits a booking. Django must revalidate the candidate against PostgreSQL inside the final booking transaction. A timeout or service error must be surfaced explicitly; it must not be converted into a success-shaped response that claims a slot is available.

This separation is justified as an academic service boundary, not as a claim that two frameworks are intrinsically required for correctness. A single Django service could evaluate candidates too; FastAPI is used to demonstrate the approved separate HTTP service and compare an independent evaluator.

## What “distributed” means in the demonstration

Running Django and FastAPI as separate processes on the same Windows laptop demonstrates two separately running services and HTTP communication between them. The processes share the laptop's operating system, hardware, and local network stack; this is **local multi-process service separation**, not multi-machine or cloud deployment.

If the HTTP URL is configured through an environment variable and the owner later chooses to run the services on two laptops on a LAN, a successful end-to-end test can demonstrate multi-machine LAN communication. That test would additionally depend on the LAN, host firewall rules, listening address, and local security setup. Do not claim that such a test occurred unless it is actually run. No cloud hosting is part of the MVP.

## Benchmark design and honest interpretation

Measure at least small, medium, and large candidate workloads using identical input snapshots. Record:

- Candidate count and the dimensions used to form the workload.
- A stable workload identifier or seed where generated test data is used.
- Python and dependency-lock versions, operating system, process-worker count, and benchmark command.
- Serial and parallel elapsed times, repetitions, and a clear aggregation method.
- Whether process startup is included; for the user-visible end-to-end result, include startup/IPC costs that the real request path incurs.
- A serial-versus-parallel result-equivalence check.

Small workloads may be slower in the process pool because Windows starts worker processes with spawn semantics, and tasks incur pickling, inter-process communication, scheduling, and result-collection overhead. Report measured results, including slowdowns. Do not promise speedup or select a threshold based on unmeasured assumptions.

## Correctness boundary

Parallelism is an implementation strategy for read-only candidate evaluation. It is not a concurrency-control mechanism for booking writes. Only Django's final PostgreSQL transaction and its selected resource-level conflict guard can authorize a booking. FastAPI results cannot reserve capacity, and workers cannot bypass the transaction.
