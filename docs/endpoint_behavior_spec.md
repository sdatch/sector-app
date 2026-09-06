# Comparison API — Endpoint Behavior Specification

Schema contract: `comparison_contract.py` (v1.0). This document specifies runtime
behavior: latency, delivery, failure, and caching semantics. Target stack is a
fresh FastAPI application.

## 1. Design goals

The API should feel like a web application, not a batch system. A request for a
comparison returns useful numbers within a normal page-load budget, and anything
still computing arrives progressively over the same connection. Long-running work
is an implementation detail the client experiences as refinement, never as
waiting on an empty screen. Partial results and partial failures are first-class
states, not errors.

## 2. Resource model and endpoints

A comparison is a resource, created once and observable thereafter. This keeps
results shareable, cacheable, and resumable after a dropped connection.

```
POST /v1/comparisons                  Create a comparison; returns inline results
GET  /v1/comparisons/{id}             Full current state (poll fallback, shareable)
GET  /v1/comparisons/{id}/events      SSE stream of progressive updates
GET  /v1/snapshots/current            Metadata for the active DataSnapshot
```

`POST /v1/comparisons` accepts a `CompareRequest` and returns `201 Created` with
a `ComparisonResource` body and a `Location` header. The body contains every
outcome that completed within the synchronous budget (Section 3) and status
markers for the rest.

## 3. Latency contract

The server holds the POST response for a **synchronous budget of 500 ms** and
returns whatever is ready at that point.

Expected behavior per model against a warm snapshot: Fama-French and
Black-Litterman are closed-form and complete inline in tens of milliseconds.
Monte Carlo runs in **two stages**: a provisional stage at ~1,000 paths that
usually fits the sync budget, and a refinement stage at the full requested path
count that completes in the background. The client therefore renders a full
three-column comparison on first paint, with the Monte Carlo column labeled
provisional and refined in place moments later.

Hard cap on total background compute per comparison: **30 seconds**. Anything
exceeding the cap transitions to `failed` with code `compute_timeout`.

## 4. Outcome status machine

Each requested model progresses independently:

```
pending → running → provisional → complete
                  ↘ failed        ↘ failed
```

The response envelope wraps each outcome accordingly:

```json
{
  "model_id": "monte_carlo",
  "status": "provisional",
  "progress_pct": 0.12,
  "outcome": { "...": "ModelOutcome (provisional numbers)" },
  "error": null
}
```

`outcome` is present for `provisional` and `complete`; `error` is present only
for `failed` and carries `{code, message, retryable}`. A provisional
`ModelOutcome` is schema-identical to a final one; `Diagnostics.warnings`
includes `"provisional_estimate"` so the UI can badge it.

The comparison resource itself has an aggregate status: `running` while any
outcome is unresolved, then `complete` (all succeeded), `partial` (mixed), or
`failed` (none succeeded).

## 5. Progressive delivery (SSE)

`GET /v1/comparisons/{id}/events` returns `text/event-stream`. Event vocabulary:

```
event: outcome        data: OutcomeEnvelope        (on any status transition)
event: progress       data: {model_id, pct}        (Monte Carlo, throttled to 2/s)
event: comparison     data: {status}               (terminal; stream closes after)
event: heartbeat      data: {}                     (every 15 s)
```

Every event carries an `id:` field. Clients reconnecting with `Last-Event-ID`
receive only events after that id, so a dropped connection never forces
recomputation. If the comparison is already terminal when a client subscribes,
the server replays the terminal `comparison` event immediately and closes.

Polling `GET /v1/comparisons/{id}` is the degraded-client fallback and returns
the identical aggregate state; while `running` it sets `Retry-After: 1`.

## 6. Partial failure semantics

A comparison never fails wholesale because one model failed. HTTP status
reflects only the request/resource layer:

- `201` — comparison created (even if some models will fail)
- `200` — resource retrieved (even if aggregate status is `partial` or `failed`)
- `422` — request invalid against the contract (weights, discriminators, ranges)
- `409` — snapshot referenced by an idempotent retry no longer active
- `429` / `503` — rate limit / load shedding, with `Retry-After`

Model-level failures are **data, not transport errors**. `normalization_notes`
explains user-facing consequences (e.g., "Black-Litterman outcome unavailable:
view references unknown sector 'Cryptomining'"). Failed outcomes with
`retryable: true` may be retried via `POST /v1/comparisons/{id}/retry` without
re-running succeeded models.

## 7. Caching and idempotency

Comparisons are deterministic given a snapshot, so caching is aggressive:

- **Cache key**: `sha256(snapshot_id + canonical_json(CompareRequest))`, where
  canonical JSON sorts keys and normalizes float formatting.
- **Hit behavior**: POST returns `200` (not `201`) with the complete cached
  resource; no background work, no SSE needed. `X-Cache: hit` header for
  observability.
- **TTL**: until the snapshot rotates (daily after market close), then entries
  lapse naturally because the key changes.
- **Idempotency-Key** header (optional, 24 h retention): duplicate POSTs with
  the same key return the original resource regardless of cache state, which
  protects against client retries during creation.

## 8. Cancellation and limits

Client disconnect from the SSE stream does **not** cancel computation (another
tab may be polling; the cache wants the result). Explicit cancellation is
`DELETE /v1/comparisons/{id}` while `running`, which cancels pending tasks and
marks unresolved outcomes `failed` with code `cancelled`. Rate limit:
10 comparison creations per minute per user; cache hits are exempt.

## 9. Implementation notes (fresh start)

- **Single-process first.** FastAPI + `asyncio.TaskGroup`; Monte Carlo numpy
  work runs in a `ProcessPoolExecutor` so the event loop never blocks. SSE fans
  out from an in-process registry of `asyncio.Queue`s keyed by comparison id.
- **Redis enters when replicas do.** With one uvicorn worker, no shared state is
  required. Scaling beyond one replica moves comparison state and the event log
  to Redis (Streams map one-to-one onto the SSE `Last-Event-ID` resume
  semantics), and the cache from an in-process LRU to Redis. The endpoint
  contract above is unchanged by that migration — that is the point of
  specifying behavior, not infrastructure.
- **Snapshot warm-up.** On snapshot rotation, a startup task precomputes factor
  regressions and covariance matrices so the 500 ms budget holds from the first
  request of the day.

## 10. Open items for the PRD

- Snapshot rotation policy: strictly daily, or intraday refresh for the
  risk-free rate?
- Whether provisional Monte Carlo outcomes should be cached or only finals.
- AuthN/AuthZ model and whether comparison resources are user-scoped or
  shareable by link.
