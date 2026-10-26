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
                        portfolios/     ingestion, resolution, portfolio routes  (M3)
                        db/             SQLAlchemy models, migrations           (M3)
                        narration/      optional LLM wording, OFF by default (post-v1)
                        sector_lookup/  optional suggested sectors in the CSV
                                        preview, OFF by default (post-v1)
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
   "monte" in logic or user-facing copy outside `engines/` — the discriminated
   union in `contracts/` and explanatory *comments* are the exceptions, and a
   comment cannot go stale into a user's face. It consumes a uniform
   `OutcomeTransition` stream. Copy that needs a model's name reads
   `display_name` off the engine through the registry (that is why the
   narration layer can say "Black-Litterman" without breaking this). Where
   copy can avoid naming one, it does: the VaR/CVaR caveat in `comparator.py`
   speaks of "simulated" models, because it branches on `EstimationMethod` and
   would otherwise be wrong the day a second simulated engine is registered.
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
backend :8000, Postgres :5432); 190 backend tests green. Remaining before a real
launch: a mail provider (verification tokens are logged today), user-facing
manual QA, and final disclaimer-copy review (PRD §13).

**Post-v1 additions** (see the sections below): `/learn` educational content
pages; an ingestion overhaul so real broker exports resolve instead of arriving
mostly rejected; fund decomposition, so a portfolio of index funds gets a real
sector mix; a snapshot-artifact fingerprint that stops stale reference data
being served forever; `/easy`, a one-model, three-move front door; an
optional, off-by-default Claude narration layer for the moves it suggests; and
user-confirmed sectors in the CSV preview, with optional Claude suggestions.

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
  cookie/SSE verified. Live browser click-through done (2026-10-11, via the
  Chrome extension) — it is now a standing stage of the verify loop, not a
  one-off, and it is where the display-rounding and copy defects surface that
  the test suite cannot see.
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

## Suggested sector shifts

Every `ModelOutcome` carries `suggested_shifts`: up to 3 tilts like "move 10%
from Financials to Real Estate", limited by `CompareRequest.risk_level`. They are
sector shifts, never tickers (PRD non-goal), and the copy never says buy or sell.

- One generator, `engines/common/shifts.py`. Each engine calls it with its **own**
  sector (mu, cov): FF-implied, BL posterior, historical for MC. The candidates
  are the same for every model; the ranking differs, and that is the lesson.
- No metric math of its own: numbers come from `normalize.portfolio_moments` +
  `metrics_from_moments`. For FF/BL, `metrics_after` equals the engine's metrics
  on the shifted weights (a property test). `metrics_before` uses the same
  estimator, so the UI delta is the shift alone.
- Candidates: every held sector moving 5% or 10% (capped at its weight) into any
  other sector. All must strictly raise Sharpe. Risk level sets the volatility
  cap *and* the ranking key: conservative = vol must fall, ranked by vol cut;
  moderate = vol ≤ current, ranked by Sharpe gain; aggressive = vol ≤ 1.10×,
  ranked by expected-return gain. (Ranking everything by Sharpe made the levels
  indistinguishable, because the best Sharpe moves already lower vol.) At most
  one shift per (from, to) pair.
- Monte Carlo scores shifts in closed form from the moments it simulates
  (re-simulating would break the first-paint budget), labeled
  `parametric_normal` + warning `parametric_estimate`.
- `suggested_shifts` is `None` on comparisons saved before the field existed
  (the UI says "not computed"); `[]` means nothing qualified. Additive to schema
  1.1, no migration. Keep `/learn/why-models-disagree` in sync with the constants.

## Easy mode (`/easy`)

The low-ceremony front door, for the user who wants to know what to *do* rather
than to study three columns: pick a portfolio, pick one model, pick a risk
level, read three sector moves in plain language. It **computes nothing of its
own** — it renders the `suggested_shifts` the comparison already returns, which
is what keeps NFR-2 determinism and `tests/golden/` untouched.

- It POSTs **all three** models with `/compare`'s exact defaults (horizon 120,
  10 000 paths, no views) so the two pages share a cache entry, then renders one
  column. Switching model is a re-render, not a request; switching risk level or
  portfolio re-POSTs, because `risk_level` is both a cache-key field and the
  shift ranking key. The defaults live in `frontend/lib/types.ts` and both pages
  import them — diverging on any of them silently doubles the compute.
- `frontend/lib/moves.ts` writes the copy from the numbers on the shift and
  nothing else, so prose and deltas cannot disagree. It leads with whatever the
  risk level actually ranks by, always names the other side of the trade-off,
  and never says buy/sell/hold/trade (PRD §3 non-goal).
- `moveDigits` decides display precision once per list, widening a figure whose
  own before/after collapses ("volatility falls from 16.3% to 16.3%" reads as a
  bug) and widening the *ranking key* when ties make the order look arbitrary.
  `SuggestedShifts` uses the same function — the two views render the same
  shifts and must agree digit for digit.
- `GET /v1/portfolios/{id}/allocation` exposes `unmodeled_share` +
  `approximations`, which the comparison path resolves and discards. Without it
  a 60/40 fund holder would read three moves about 60% of their money with no
  notice. It is a property of (portfolio, snapshot), not of a comparison, which
  is why it is not on `ComparisonResource`.
- An empty list is a real answer and says so: Black-Litterman finds no
  qualifying shift on its own optimal allocation while the other two still offer
  three. That disagreement *is* the lesson, surfaced to a user who never opened
  the comparison view.

## Narration (`backend/app/narration/`, off by default)

Optional Claude-written wording for the three moves. The split is load-bearing:
**the math decides, the model only narrates.** `shifts.py` chooses which moves
appear and computes every number on them, and nothing in this package can
change either — an LLM that picked or scored a move would break NFR-2
determinism (guarded by `tests/golden/`) and NFR-5 traceability.

`NARRATION_ENABLED=false` is the default. With it off the SDK is never
imported, no request leaves the process, and the client renders its own
deterministic copy, so the feature is complete without any of this. The
frontend still issues the narration POST and the server answers `template` —
one source of truth for whether the layer is on, at the cost of one cheap
request per view.

| File | Responsibility |
|---|---|
| `payload.py` | What may leave the process — **the privacy boundary** |
| `prompt.py` | The versioned prompt (`PROMPT_VERSION` is in the cache key) |
| `schema.py` | What the model returns: prose only, never a metric |
| `validate.py` | Checking prose against the figures — **the honesty boundary** |
| `client.py` | The only network call |
| `cache.py` | In-process LRU, keyed on comparison + model + prompt version |
| `service.py` | cache → payload → client → validate → fallback |

- **Privacy is structural, not a promise.** `build_payload` takes a display
  name, a risk level, `SectorAttribution` and `SectorShift` — never a
  `ModelOutcome`, `CompareRequest`, `Portfolio` or `User` — so a ticker or a
  quantity has no field to travel in. Current weights come from
  `sector_attribution`, *not* `request.allocation`, whose `ticker_weights` mode
  carries real tickers. `var_horizon`/`cvar_horizon` are excluded: they are
  currency amounts derived from `initial_value`. Both payload models are
  `extra="forbid"`, and a test freezes their field sets so a new field fails CI.
- **Numbers are pre-formatted and validated numerically.** The model is given
  display strings plus the deltas and told to quote them; the validator parses
  numeric tokens and compares on absolute value, so "16.3%" and "16.30%" are
  one claim while an invented figure fails whatever its formatting. It also
  rejects foreign sectors, ticker-shaped tokens, buy/sell/hold language,
  spelled-out quantities, and any reply whose shape does not match the moves
  exactly. One bad move rejects the whole set — never generated prose beside
  template prose. `order`, bare `short` and `will` are deliberately *not*
  policed (false rejections make the layer look broken); the prompt steers away
  from `will` instead.
- **Degradation is the only failure mode.** Flag off, no key, timeout, API
  error, refusal, `max_tokens`, or any validator rejection all return
  `200 {source: "template", moves: []}` — the same shape — so no client branch
  exists. 404 means not yours or not there, 409 not ready, 429 slow down.
- `display_name` on the engine protocol is the invariant-3 carve-out: good copy
  wants to name the model, and the API layer may not, so the string lives in
  `engines/` and narration reads it from the registry.
- **Disclosure is part of the feature.** An env flag is an operator switch and
  NFR-3 is a promise to users, so narrated moves carry a visible line naming
  Claude and stating what is sent, and PRD §13 copy says the same.
- Not cached in SQL: narration is cosmetic, and a JSONB column would make
  generated prose part of the 90-day record. The cost is that a reopened
  comparison may be narrated again with different wording.

Tests use a fake on `app.state.narration_client` — no network, no key. A guard
test asserts `anthropic` is not in `sys.modules` after importing `app.main`.
**Untested against live output:** no API key was available when this was built,
so the prompt-plus-validator pairing has only been exercised against
hand-written realistic prose. Watch the `narration rejected:` warning rate the
first time the flag is turned on.

## Sector lookup + user-confirmed sectors (`backend/app/sector_lookup/`)

Every single-company row in the CSV preview has an editable sector, and an
unrecognized ticker can be given one and included. Optionally (off by
default), "Check sectors with Claude" suggests a sector for each symbol, as a
gap-fill for unknown tickers and a second opinion on the reference table. The
rule is load-bearing: **the lookup proposes, the user confirms, the stored row
is truth.**

- **Determinism survives a non-deterministic model** because the model is never
  in the evaluation path. A suggestion is shown beside the picker and applied
  only on "Use". The confirmed sector travels as `sector_overrides` on
  re-preview and as `AcceptedRow.sector` on commit, and is stored in
  `Position.sector`, which is all `resolve_allocation` reads.
  `Position.sector_source` (NULL = reference, `model`, `user`) is provenance
  only. Nothing in `sector_lookup/` is imported by ingestion, orchestration or
  engines.
- **Funds never take an override** (invariant 8): `parse_csv` and
  `create_portfolio` 422 on one, the validator drops a `fund` answer that
  carries a sector, and the UI hides the picker for a symbol Claude calls a
  fund or non-equity holding.
- **Unlisted tickers need a price.** `SnapshotBundle.price_of(ticker)` reads
  `ticker_price`, then falls back to the provider's formula when it has one
  (`unlisted_price_seed`; synthetic only, the same `hashed_price` every listed
  ticker uses). A provider without one returns None, and the row is rejected as
  `no_price` rather than silently valued at zero. Every valuation path
  (ingest, `resolve_allocation`, progress, comparisons) goes through
  `price_of`.
- **Privacy.** Unlike narration, this does send tickers, so the boundary is
  drawn around them. `LookupPayload` is a tuple of pattern-checked symbols and
  nothing else (`extra="forbid"`, field set frozen by a test). Non-symbols from
  the ticker column are never sent. There is no `metadata.user_id`. The
  disclosure sits beside the button, and PRD NFR-3 (amendment) and §13 say the
  same.
- **Client.** `client.beta.messages.create` with `output_config.format` (the
  same transformed schema `parse` would send), `web_search_20260209` capped by
  `SECTOR_LOOKUP_MAX_SEARCHES`, `fallbacks: "default"` (server-side refusal
  fallback), and bounded `pause_turn` resumption. Not `messages.parse`: it
  validates *every* text block, and a search turn can carry text that isn't the
  answer. `extract_answer` reads the text after the last tool block.
- **Degradation is the only failure mode**, as in narration. Flag off, no key,
  timeout, error, refusal or rejection all return `200 {source:
  "unavailable"}`. A partial answer lists the rest in `unchecked`. Entries are
  validated independently: one bad symbol drops alone.
- Per-ticker in-process cache, keyed on model + `PROMPT_VERSION`, shared
  across users (it holds no user data). `unknown` is not cached. The GET route
  is registered **before** `portfolios_router`, whose `/{portfolio_id}` would
  otherwise capture `/sector-lookup`.

**Untested against live output** until the first run with a real key: the
`output_config.format` + web-search pairing has been exercised only against a
mocked transport (`tests/sector_lookup/test_client_wire.py`). Watch
`sector lookup:` (usage) and `sector lookup rejected:` in the logs the first
time it is on. To click through with no key:
`SECTOR_LOOKUP_ENABLED=true SECTOR_LOOKUP_STUB=true docker compose up -d backend`.

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

Narration is off by default. To see the narrated UI — including its disclosure
line — with no API key and no spend:
```
NARRATION_ENABLED=true NARRATION_STUB=true docker compose up -d backend
```
The stub writes the same sentence the real model is asked for, from the payload
alone; it is ignored when `ENVIRONMENT=production`. For the real thing, swap
`NARRATION_STUB` for `ANTHROPIC_API_KEY=...`. Both pass through
`docker-compose.yml` from the shell. The `anthropic` package is in
`requirements.txt` but imported lazily, so the app and its tests run whether or
not it is installed — a test asserts exactly that.

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
