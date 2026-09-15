# CLAUDE.md — Sector Insight

Educational tool that puts three risk models — **Fama-French 5-factor**,
**Black-Litterman**, and **Monte Carlo GBM** — side by side against the *same*
portfolio, *same* data, and *same* assumptions, so model disagreement teaches.
The unit of advice is the **sector**, not the trade. It never executes trades,
never recommends individual securities.

This is a **fresh-start successor** to a batch trading app. No code inherited.
The founding constraints: **web-like always** (useful screen within a page-load
budget; heavy compute *refines* the screen) and **sector-level advice**.

## Normative specs (read these before changing behavior)

The `docs/` folder is the contract. Do not restate or contradict it:

- `docs/PRD.md` — product requirements, milestones M1–M5, scope cut-lines.
- `docs/comparison_contract.py` — wire schema (v1.0 source; ported to v1.1 at
  `backend/app/contracts/comparison.py`).
- `docs/endpoint_behavior_spec.md` — latency, SSE, failure, caching semantics.
- `docs/compute_layer_design.py` — engine protocol + orchestration design.
- `docs/user_model_spec.md` — auth, persistence, CSV ingestion; v1.1 contract
  amendment (Allocation.portfolio_id).

## Architecture

```
Next.js frontend  ->  FastAPI app
                        api/            routers, SSE framing, poll fallback  (M2)
                        orchestration/  Comparator, state store, event bus, cache (M2)
                        contracts/      comparison.py — the wire schema
                        engines/        base protocol + 3 engines + common/normalize
                        snapshots/      builder, artifacts, providers/ (synthetic|real)
                        db/             SQLAlchemy models, migrations           (M3)
Postgres  = user state only (users, portfolios, positions, comparisons, progress)
Snapshots = memory-mapped npz artifacts keyed by snapshot_id (NEVER in SQL)
```

## Invariants (these are load-bearing — do not violate)

1. **The contract is the wire schema.** Everything crossing the API boundary is
   a Pydantic model from `contracts/comparison.py`. Schema version is `1.1`.
2. **`engines/common/normalize.py` is the ONLY producer of comparable numbers.**
   Engines produce raw `(mu, sigma)` moments or a terminal-value array and hand
   them to the normalizer. They never implement sqrt-t scaling, VaR signs, or
   Euler attribution themselves. This is *why* three models are comparable.
3. **The orchestration/API layer never names a model.** No "fama"/"litterman"/
   "monte" outside `engines/`. It consumes a uniform `OutcomeTransition` stream.
   Adding model #4 = implement the protocol + register + add a detail variant to
   the contract union. Nothing else changes.
4. **Determinism (NFR-2).** Identical request + snapshot => bit-identical result.
   RNG is seeded from the cache key. Required for caching, history, and trust.
   Guarded by `tests/golden/` (golden reproduction + repeated-run determinism).
5. **Market data never enters SQL.** SQL holds user state; snapshot artifacts
   are memory-mapped files referenced by opaque `snapshot_id` string.
6. **Raw uploaded CSVs are never persisted.** Only `ticker` + `quantity` survive
   ingestion; weights are derived at evaluation time from snapshot prices.
   Ingestion locates the header anywhere in a leading preamble and keeps each
   row's true file line number. A holding silently dropped is a bug — the
   preview surfaces every excluded row and why.
8. **A fund is decomposed, never assigned one sector.** See "Fund
   decomposition" below. Forcing an index fund into a single sector would
   corrupt attribution; dropping it would make the app useless for the
   portfolios most people hold.
7. **Partial failure is data, not a transport error.** One model failing yields
   that column a `failed` outcome; the comparison still returns 201/200.

## Convention: the GBM the whole app agrees on

Portfolio value follows GBM with annual arithmetic drift `mu` and vol `sigma`:
`V = V0·exp((mu − ½σ²)T + σ√T·Z)`. Parametric engines (FF, BL) feed
`metrics_from_moments`; Monte Carlo simulates this exact GBM and feeds
`metrics_from_paths`. That shared convention is why empirical metrics converge
to parametric ones as `n_simulations → ∞` (a property test).

## Status: all milestones (M1–M5) complete

The full PRD v1 is built and running in `docker compose` (frontend :3000,
backend :8000, Postgres :5432); 55 backend tests green. Remaining before a real
launch: a mail provider (verification tokens are logged today), user-facing
manual QA, and final disclaimer-copy review (PRD §13).

**Post-v1 additions** (see the sections below): `/learn` educational content
pages; an ingestion overhaul so real broker exports resolve instead of arriving
mostly rejected; fund decomposition, so a portfolio of index funds gets a real
sector mix; and a snapshot-artifact fingerprint that stops stale reference data
being served forever.

## Milestone status

- **M1 ✅ DONE** — contract, engine protocol, `normalize`, synthetic snapshot
  builder + artifacts (npz + mmap), three engines, golden + property tests
  (Euler sums to σ_p; parametric↔empirical convergence). Minimal FastAPI app
  with snapshot warm-up + `GET /v1/snapshots/current`.
- **M2 ✅ DONE** — Comparator (TaskGroup, 500 ms gather-with-budget, sibling-
  isolated failures, 30 s cap), in-process state store + event bus, deterministic
  sha256 cache + idempotency, per-key rate limit, comparison endpoints + SSE
  (resume via Last-Event-ID, heartbeats, terminal replay), poll fallback, cancel.
  U3/U9 covered by integration tests. (Retry endpoint deferred per PRD §9.)
- **M3 ✅ DONE** — fastapi-users 15 (argon2 via pwdlib, cookie/JWT, verification
  hard gate → 403, consent capture → consented_at), SQLAlchemy 2.0 async models
  + Alembic initial migration (applied to Postgres), CSV preview→commit ingestion
  (header tolerance, ticker normalization, sector resolution, raw file never
  stored), manual + portfolio_id allocation modes, per-user rate limiting, CSRF
  X-Requested-With check. 31 tests green; full flow verified live on Postgres.
  Note: single session cookie instead of access+refresh rotation (see users.py).
  Comparison DB persistence + history deferred to M5.
- **M4 ✅ DONE** — Next.js 15 (app router, standalone image). Auth (register w/
  consent gate, login, verify), portfolio mgmt + CSV preview→commit UI + manual
  sector weights, comparison view (3 columns, provisional MC badge refined live
  over SSE), outcome-distribution bands, sector attribution chart, BL advice
  delta, multi-portfolio matrix (client-composed parallel POSTs), assumptions/
  caveats panel from API transparency fields, disclaimer footer + per-comparison
  inline. Builds clean; full stack in compose (frontend:3000). CORS + cross-origin
  cookie/SSE verified. Live browser click-through pending (Chrome ext not
  connected this session).
- **M5 ✅ DONE** — comparison DB persistence (finalize → comparisons table),
  history list + reopen from DB after in-memory eviction (U8), per-portfolio
  progress trajectory reconstructed from snapshot history + daily maintenance
  loop that values every portfolio into progress_points and purges expired rows
  (U7, FR-6). Frontend: /history (reopen), /progress (SVG trajectory chart).
  Railway deploy config (backend/railway.json runs migrations; DEPLOY.md).
  34 tests green; progress + history + reopen verified live on Postgres.

## Learn section (`frontend/app/learn/`)

Six static content pages explaining the models and the strategy, derived from
the PRD vision + the engines' actual implementation (constants, conventions and
caveats match the code — keep them in sync when engine math changes):
sector-investing, fama-french, black-litterman, monte-carlo,
reading-the-numbers, why-models-disagree. `lib/learn.ts` is the registry: add a
route plus one row there and the index, nav and prev/next footers pick it up.
Public (no auth) — the education *is* the product. Linked from the nav and from
the home-page model cards.

## Fund decomposition

`snapshots/providers/funds.py` maps a pooled vehicle to the sectors it actually
holds: `FundComposition(name, kind, equity_share, sector_weights,
approximation)`. Two honesty constraints are baked into the shape:

- `equity_share` — the fraction that maps to a GICS equity sector at all. A
  bond fund is `0.0` and is rejected with `no_equity_exposure`; a 60/40 fund is
  `0.6`, and the other 0.4 is reported as an unmodeled sleeve rather than
  quietly inflating the equity weights.
- `approximation` — what is being fudged (international mapped onto US sector
  returns, small-caps modeled with large-cap returns), surfaced to the user.

`FUND_COMPOSITION` and the provider's `_TICKER_SECTOR` must stay **disjoint** —
a test enforces it. Every pooled vehicle belongs in the fund table, *including*
single-sector ETFs whose sector is unambiguous (XLE is `{Energy: 1.0}`): both
tables resolve XLE to Energy, but only the fund table tells the holder they own
a fund. Bullion trusts (GLD, SLV) and commodity funds are `equity_share = 0.0`
alongside bond funds — they hold metal, not equities, so any sector assignment
for them is a fiction that would feed the factor regressions a series with no
factor exposure. Prices are hashed per ticker, so moving a ticker between the
two tables never re-prices it or re-weights a saved portfolio.

Decomposition happens in `portfolios/service.resolve_allocation` at **evaluation
time**, not commit time — refreshed fund holdings then flow through to existing
portfolios exactly the way refreshed prices already do. `Position.sector` stores
the `FUND_SECTOR` sentinel (`"(fund)"`); if a snapshot ever lacks a breakdown
for a stored fund, its value goes to the unmodeled bucket rather than being
attributed to a sector literally named "(fund)". `ResolvedAllocation.weights`
always sums to 1.0 over the modeled equity sleeve, with `unmodeled_share`
carried alongside.

The weight tables are typical published allocations, **not live holdings** — the
same standing as the synthetic prices beside them. A real provider would supply
actual fund holdings into the same shape.

## Snapshot staleness (load-bearing)

`SnapshotBundle` carries the ticker reference tables, and artifacts persist to
a volume. `ensure_bundle` therefore compares a **reference fingerprint**
(`SyntheticProvider.reference_fingerprint()` — hashes the ticker universe,
sectors, factors, seed and `BUILD_VERSION`) against the one stored in the
sidecar meta, and rebuilds on mismatch. Without this, changing the ticker
universe has *no effect* on any environment that already has an artifacts
volume — the symptom is a rebuilt container still rejecting tickers the running
code clearly recognizes. Bump `BUILD_VERSION` when generation math changes.

## Data provider

Default is **synthetic** (`snapshots/providers/synthetic.py`) — deterministic,
zero API keys, generates sector returns *from* a factor model so FF regressions
recover signal. Swap in a real free provider (yfinance/Tiingo/FRED/Ken French)
behind `MarketDataProvider` without touching the builder or engines (NFR-7).

## Running

Backend tests (fast, no containers):
```
cd backend
python -m venv .venv && ./.venv/Scripts/python -m pip install -r requirements.txt
./.venv/Scripts/python -m pip install pytest pytest-asyncio hypothesis
./.venv/Scripts/python -m pytest -q
```
Regenerate golden after an intentional engine change:
```
SECTOR_INSIGHT_WRITE_GOLDEN=1 ./.venv/Scripts/python -m pytest tests/golden -q
```

Full stack (local containers, mirrors Railway):
```
docker compose up --build
# frontend http://localhost:3000   (the app)
# backend  http://localhost:8000   (API; /docs for interactive docs)
# postgres localhost:5432
```
Frontend dev with hot reload (outside compose):
```
cd frontend && npm install && npm run dev   # http://localhost:3000
```
No mail server yet: the email-verification token is printed to the backend logs
(`docker compose logs backend | grep verify`); paste it on the /verify page.

## Deployment target

**Railway.** The same containers run locally (`docker-compose`) and on Railway
(container services + Postgres plugin). Config is entirely env-driven — Railway
injects `DATABASE_URL` and `PORT`; everything else is a service variable. No
serverless reshaping (Railway gives the persistent process SSE + the process
pool + the in-process event bus require, which Vercel does not).

## Conventions

- Python 3.12, Pydantic v2, async SQLAlchemy 2.0, numpy in a ProcessPoolExecutor
  for Monte Carlo (never block the event loop; CPU work is pure functions of
  arrays, never pickles `self`).
- Every displayed metric traces to an `EstimationMethod`; provisional numbers
  carry `"provisional_estimate"` in `Diagnostics.warnings` so the UI badges them.
- The educational disclaimer (PRD §13) renders at registration (consent gate),
  the persistent footer, and every comparison view.
