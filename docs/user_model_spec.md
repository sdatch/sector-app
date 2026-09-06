# User Model, Persistence, and Portfolio Ingestion — Specification

Companion to `endpoint_behavior_spec.md` and `compute_layer_design.py`. This
document specifies the three user-facing capabilities: authenticated access,
SQL-backed user state, and CSV portfolio upload. It also resolves the auth
open item from endpoint spec §10 and amends the wire contract to v1.1.

## 1. Authentication

### 1.1 Model

All `/v1/*` endpoints require an authenticated user. Comparisons, portfolios,
and progress history are user-scoped resources: a user can only read and
mutate their own. There are no anonymous comparisons in v1 (this resolves
endpoint spec §10 — resources are user-scoped, not link-shareable, for now).

Two gates apply at the account boundary (PRD decisions): **email
verification is required before the first comparison** (hard gate — 403
`verification_required` on /v1/comparisons for unverified users), and
**registration requires explicit consent** to the educational-use
disclaimer, recorded as `users.consented_at TIMESTAMPTZ NOT NULL`.

### 1.2 Mechanism: cookie-based sessions, not bearer tokens

Credential auth (email + password) issuing a **JWT carried in an httpOnly,
Secure, SameSite=Lax cookie**, short-lived (15 min) with a refresh token
cookie (7 days, rotated on use).

The cookie transport is not a style preference — it is forced by the SSE
design. The browser `EventSource` API **cannot attach custom headers**, so
`Authorization: Bearer` auth would break `GET /v1/comparisons/{id}/events`
and push the frontend toward token-in-query-string (which leaks into logs)
or a fetch-based SSE polyfill. Cookies flow on EventSource requests
automatically. CSRF exposure introduced by cookie auth is covered by
SameSite=Lax plus an `X-Requested-With` custom-header check on mutating
routes (the standard double-defense for JSON APIs; no form posts exist).

### 1.3 Implementation

`fastapi-users` with the SQLAlchemy adapter and cookie/JWT transport:
registration, email verification, password reset, and the user table come
out of the box, and it leaves room for OAuth social login later without
re-architecting. Password hashing: argon2. This is deliberately boring —
auth is undifferentiated heavy lifting and a fresh start should not include
a hand-rolled session layer.

Rate limiting from endpoint spec §8 becomes per-user rather than per-IP.

## 2. Persistence

### 2.1 Engine and boundary

**PostgreSQL from day one**, accessed via SQLAlchemy 2.0 (async, asyncpg)
with Alembic migrations; a `postgres` service in docker-compose for local
dev. SQLite would satisfy the single-process MVP, but Postgres avoids a
migration on the already-planned path to replicas, and keeps the
operational surface to one relational store, one schema.

Boundary rule: **SQL holds user state; market data does not enter SQL.**
Snapshot artifacts (returns matrices, covariances, factor data) remain
memory-mapped files keyed by `snapshot_id`, per the compute layer design.
SQL rows reference `snapshot_id` as an opaque string.

### 2.2 Schema (v1)

```sql
-- users: owned by fastapi-users (id UUID PK, email, hashed_password,
--        is_active, is_verified, created_at)

CREATE TABLE portfolios (
    id            UUID PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('csv','manual')),
    is_default    BOOLEAN NOT NULL DEFAULT false,  -- UI default selection
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE UNIQUE INDEX one_default_portfolio
    ON portfolios(user_id) WHERE is_default;
-- Multi-portfolio is v1 scope: users hold several named portfolios
-- (IRA, brokerage, hypothetical) and compare them side by side.

CREATE TABLE positions (
    portfolio_id  UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    ticker        TEXT NOT NULL,
    quantity      NUMERIC(18,6) NOT NULL CHECK (quantity > 0),
    sector        TEXT NOT NULL,             -- resolved at ingest
    PRIMARY KEY (portfolio_id, ticker)
);

CREATE TABLE comparisons (
    id            UUID PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id  UUID REFERENCES portfolios(id) ON DELETE SET NULL,
    snapshot_id   TEXT NOT NULL,
    request       JSONB NOT NULL,            -- canonical CompareRequest
    result        JSONB,                     -- terminal ComparisonResource
    status        TEXT NOT NULL,             -- running|complete|partial|failed
    cache_key     TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL     -- created_at + 90 days (PRD D4)
);
CREATE INDEX comparisons_by_user ON comparisons(user_id, created_at DESC);
CREATE INDEX comparisons_by_cache ON comparisons(cache_key);
CREATE INDEX comparisons_by_expiry ON comparisons(expires_at);
-- Retention: a daily purge task (piggybacked on snapshot rotation) hard-
-- deletes rows past expires_at. Cache lookups filter expires_at > now().

CREATE TABLE progress_points (
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    as_of         DATE NOT NULL,
    portfolio_id  UUID NOT NULL,
    total_value   NUMERIC(18,2) NOT NULL,
    metrics       JSONB NOT NULL,            -- CommonMetrics per portfolio
    PRIMARY KEY (user_id, portfolio_id, as_of)
);
-- Progress is tracked for EVERY portfolio (multi-portfolio v1), not only
-- the default; the trajectory chart overlays or filters by portfolio.
```

Notes:
- `comparisons` doubles as the durable state store from endpoint spec §9:
  terminal resources land here, which makes the deterministic cache a SQL
  lookup by `cache_key` (Redis becomes a read-through layer later, not a
  source of truth). A history UI ("your past comparisons") is a free query.
- `progress_points` is the "financial progress" surface: on each snapshot
  rotation, a scheduled task values every active portfolio at the new
  snapshot prices and appends a point. Users get a trajectory chart without
  any action on their part. Cost basis is deliberately excluded from v1 —
  progress is portfolio value + risk metrics over time, not P&L accounting.
- Positions store `quantity`, not weights. Weights are derived at evaluation
  time from snapshot prices, so a portfolio's sector allocation drifts with
  the market exactly as it does in reality.

## 3. CSV portfolio ingestion

### 3.1 Flow: preview, then commit

Uploading is a two-step, mirroring the "web-like" posture — users see what
the parser understood before anything persists:

```
POST /v1/portfolios/preview     multipart/form-data, field "file"
  → 200 IngestReport            (nothing persisted)
POST /v1/portfolios             {name, accepted_rows from the report}
  → 201 Portfolio               (positions persisted, is_active if first)
```

Constraints: max 1 MB, max 500 rows, MIME text/csv or text/plain, UTF-8 or
Latin-1. The raw file is parsed in memory and **never stored** — only
validated positions reach disk. This keeps broker-export artifacts (account
numbers, names, cash lines) out of the database entirely: only `ticker` and
`quantity` survive ingestion.

### 3.2 Format and header tolerance

Canonical format:

```csv
ticker,quantity
AAPL,25
MSFT,10.5
VTI,112
```

Real inputs are broker exports, so the parser applies a header-mapping table
before validation: `symbol|Symbol|Ticker → ticker`, `shares|Quantity|Qty →
quantity`. Unrecognized columns are ignored, not fatal. Rows with blank
tickers or summary lines ("Total", "Cash") are dropped with a report entry.
An optional `weight` column is accepted as an alternative to `quantity` (all
rows must then use weights, summing to 1.0 ± 1e-4; stored by converting to
notional quantities against a nominal $100k, flagged in the report).

### 3.3 IngestReport

```json
{
  "accepted": [
    {"ticker": "AAPL", "quantity": 25, "sector": "Information Technology",
     "last_price": 231.10, "value": 5777.50, "weight": 0.31}
  ],
  "rejected": [
    {"row": 7, "raw": "BRK.B,10", "reason": "ticker_normalized",
     "resolution": "BRK-B accepted"},
    {"row": 9, "raw": "MYPRIVATEFUND,100", "reason": "unknown_ticker"}
  ],
  "warnings": ["2 rows dropped as summary lines"],
  "totals": {"value": 18630.20, "positions": 12, "coverage_pct": 0.96}
}
```

Sector resolution uses the ticker→sector table maintained by the snapshot
builder (from the price provider's reference data). Tickers outside the
snapshot universe are rejected with `unknown_ticker` — they cannot be risk-
modeled, and admitting them would silently corrupt attribution. The report
makes the exclusion visible instead of hiding it.

### 3.4 Contract amendment (v1.1)

`Allocation` gains a third, preferred mode:

```python
class Allocation(BaseModel):
    portfolio_id: UUID | None = None       # NEW — server resolves to weights
    sector_weights: list[SectorWeight] | None = None
    ticker_weights: dict[str, float] | None = None
    # validator: exactly one of the three
```

When `portfolio_id` is supplied, the orchestrator resolves positions to
sector weights against the current snapshot's prices before building the
`EvaluationContext` — engines are unaffected. The `CompareRequest` echo in
responses contains the resolved weights alongside the id, so cached results
remain interpretable after the portfolio changes. One caution: the cache key
must incorporate the resolved weight vector (not just the portfolio id) so
an edited portfolio never hits a stale entry; snapshot rotation alone does
not cover mid-day portfolio edits.

## 4. Decisions (resolved in PRD v1.1)

- Email verification: **required before first comparison** (hard gate, §1.1).
- Retention: **comparisons expire after 90 days** (schema + purge task, §2.2).
- Multi-portfolio comparison: **v1 scope** — several named portfolios per
  user, side-by-side comparison via parallel comparison resources (§2.2;
  PRD FR-2/FR-3, story U9).
- Consent disclaimer: **required at registration**, recorded in
  `users.consented_at`; draft copy lives in the PRD (§1.1).
