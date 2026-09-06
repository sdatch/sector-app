# Product Requirements Document
## Sector Insight — Risk Model Comparison for Everyday Investors
*(working title — rename freely)*

**Version:** 1.1 · **Owner:** Glenn · **Status:** Approved for build

**Changes from 1.0 draft:** D3–D6 resolved (hard-gated email verification;
90-day comparison retention; multi-portfolio comparison promoted to v1;
consent disclaimer required at registration, draft copy in §13). D1/D2
adopted per lean (daily-only snapshot rotation; cache final outcomes only).
Appendix D updated to match.

**Appendices (normative):**
A. `comparison_contract.py` — wire schema v1.1
B. `endpoint_behavior_spec.md` — latency, delivery, failure, caching semantics
C. `compute_layer_design.py` — engine protocol and orchestration
D. `user_model_spec.md` — auth, persistence, CSV ingestion

---

## 1. Vision

Most retail investors are told *what* a risk number is; almost none are shown
that the number depends on the model that produced it. This product puts three
established risk models — a Fama-French factor model, Black-Litterman, and
Monte Carlo simulation — side by side against the same portfolio, the same
data, and the same assumptions, and lets the differences teach. The unit of
advice is the **sector**, not the trade: users learn where their risk
concentrates, what tilting toward or away from a sector does to their
outcomes, and why three respectable models can disagree.

The product is an educational advice tool, not a trading tool. It never
executes, never recommends individual securities, and is explicit everywhere
that model output is a lens, not a promise.

## 2. Background

This is a fresh-start successor to a personal trading-analysis application.
That system proved out the modeling substrate (portfolio risk profiles under a
CRRA framework, FRED integration, bond analytics) but was built around long,
asynchronous, batch-oriented jobs and trade-level outputs. Two lessons carry
forward as founding constraints:

1. **Web-like, always.** A user request produces a useful screen within a
   normal page-load budget; heavy computation refines the screen rather than
   preceding it.
2. **Sector-level advice over trade-level signals.** The prior app answered
   "what should I trade"; this one answers "what am I exposed to, and what
   would change if I shifted it."

No code is inherited. FastAPI remains the API layer by deliberate choice.

## 3. Goals and non-goals

**Goals**

- G1. Let a verified user upload their real portfolios (CSV) and see a
  three-model risk comparison in one interaction.
- G2. Make model disagreement legible: identical inputs, normalized outputs,
  visible assumptions, plain-language caveats.
- G3. Provide sector-level advice framing — attribution of return and risk by
  sector, and a model-suggested allocation delta (Black-Litterman).
- G4. Let users hold several portfolios (IRA, brokerage, hypothetical) and
  compare them side by side under all three models.
- G5. Track each portfolio's financial progress over time with zero user
  effort.
- G6. First useful paint ≤ 500 ms for a warm snapshot; full Monte Carlo
  refinement within seconds, delivered progressively.

**Non-goals (v1 and likely ever)**

- Trade execution or brokerage connectivity.
- Individual-security recommendations or price targets.
- P&L / tax-lot accounting (progress is value + risk trajectory, not returns
  attribution against cost basis).
- Real-time or intraday market data; the product is daily-snapshot based.
- Regulated financial advice. Registration requires explicit consent to the
  educational-use disclaimer (§13).

## 4. Personas

**Priya — the self-directed accumulator.** Mid-career professional with a
brokerage account and an IRA. Can export CSVs from her broker. Wants to know
if she is overexposed to tech, how her two accounts differ in risk, and what
diversifying would actually change. Success for Priya: uploads both CSVs,
reads the side-by-side within a minute, and can explain to a friend why the
Monte Carlo loss number differs from the parametric one.

**Marcus — the finance learner.** Student or career-changer studying
investments. Uses hypothetical portfolios rather than real ones. Success for
Marcus: manipulates sector weights and Black-Litterman views and watches all
three models respond — the tool as a laboratory.

**Glenn — the power user / operator.** Wants deterministic, reproducible
results, an API he can script against, and an architecture a coding agent can
extend spec-first. Success: adding a fourth model touches the engine registry
and the contract union, nothing else.

## 5. User stories (v1)

| # | Story | Acceptance sketch |
|---|-------|-------------------|
| U1 | As a visitor, I register with email + password, consent to the disclaimer, and verify my address before running anything. | Consent checkbox required; `consented_at` recorded; unverified users receive 403 `verification_required` on comparisons. (App. D §1) |
| U2 | As a user, I upload a broker CSV per portfolio and confirm what was understood before it is saved. | Preview returns IngestReport; nothing persists until commit; raw file never stored. (App. D §3) |
| U3 | As a user, I run a comparison on a portfolio and see all three model columns on first paint. | FF + BL complete inline; MC column renders provisional and refines in place. (App. B §3–5) |
| U4 | As a user, I see where my return and risk come from by sector, consistently across models. | Euler attribution sums to portfolio vol in every column. (App. C) |
| U5 | As a user, I enter a view ("I think Energy returns 8%") and see Black-Litterman's advice delta. | Views echoed in assumptions; optimal_weights vs my weights rendered as a delta. (App. A) |
| U6 | As a user with several portfolios, I select two or more and see each portfolio's three-model results side by side. | Matrix view (portfolios × models) built from parallel comparison resources; no new backend resource. (§6 FR-3) |
| U7 | As a user, I open the app after a month and see value and risk trajectories for every portfolio. | progress_points appended per portfolio on snapshot rotation. (App. D §2) |
| U8 | As a user, I revisit any comparison from the last 90 days. | History query; reproducible via pinned snapshot + seed; older comparisons purged. (App. B §7, App. D §2) |
| U9 | As a user, when one model fails I still get the other two, with a plain-language reason. | Partial status; failure rendered as data in-column. (App. B §6) |

## 6. Functional requirements

**FR-1 Accounts.** Email/password registration with required consent
(`consented_at`), email verification **hard-gated before first comparison**,
password reset, session via httpOnly cookie JWT (App. D §1). Per-user rate
limiting.

**FR-2 Portfolio management.** Multiple named portfolios per user, one
flagged `is_default` for UI preselection. CSV upload via preview→commit per
portfolio; header-tolerant parsing; ticker normalization and sector
resolution; manual sector-weight entry as the no-CSV path (App. D §3;
contract Allocation modes, App. A).

**FR-3 Comparison.** POST creates a user-scoped comparison resource; three
models evaluated against a pinned daily DataSnapshot; normalized
CommonMetrics, terminal-value distribution, and sector attribution per model;
model-specific detail per the discriminated union; SSE progressive delivery
with poll fallback (Apps. A–C). **Multi-portfolio comparison** is composed
client-side: the frontend issues one POST per selected portfolio and renders
a portfolios × models matrix. Deterministic caching (App. B §7) makes
re-selection nearly free; no new backend resource exists in v1.

**FR-4 Advice surfaces.** Sector attribution visualization; Black-Litterman
advice delta; per-model "assumptions & caveats" panel populated from
diagnostics and normalization_notes — the education layer is rendered from
the API's transparency fields, not hand-maintained copy.

**FR-5 Progress.** Daily valuation of **every** portfolio into
progress_points (keyed user, portfolio, date); trajectory chart overlaying or
filtering by portfolio (App. D §2).

**FR-6 History and retention.** List and reopen comparisons from the last
**90 days**; a daily purge task (piggybacked on snapshot rotation) hard-
deletes expired rows; cache lookups exclude expired entries. Deterministic
reproduction guaranteed within the window by snapshot pinning and seeded
simulation.

**FR-7 Consent and disclaimer.** Registration blocks without affirmative
consent; the disclaimer (§13) also renders as a persistent footer and on
every comparison view.

## 7. Non-functional requirements

- **NFR-1 Latency.** ≤ 500 ms synchronous budget for comparison creation
  against a warm snapshot; provisional Monte Carlo inside the budget in the
  common case; 30 s hard compute cap (App. B §3).
- **NFR-2 Determinism.** Identical request + snapshot ⇒ bit-identical result
  (seeded RNG, canonical cache key). Required for caching, history, and
  trust (Apps. B §7, C).
- **NFR-3 Privacy.** Raw uploaded CSVs are never persisted; only ticker and
  quantity survive ingestion; user data isolated per account; comparisons
  self-expire at 90 days; no third-party analytics on portfolio contents
  (App. D §3).
- **NFR-4 Security.** Argon2 hashing; httpOnly/Secure/SameSite cookies; CSRF
  custom-header check on mutations; per-user rate limits (App. D §1).
- **NFR-5 Transparency.** Every displayed metric is traceable to an
  estimation method; provisional numbers are always badged (Apps. A, B §4).
- **NFR-6 Scalability path.** Single-process first; the endpoint contract is
  invariant under the move to replicas + Redis (App. B §9). Postgres is the
  source of truth from day one (App. D §2).
- **NFR-7 Data cost.** Operates entirely on free/public data: price API free
  tier, Ken French library, FRED. Snapshot builder tolerates provider
  substitution.

## 8. System overview

Next.js frontend → FastAPI application. Within the API: an orchestration
layer (Comparator, state store, event bus, cache) drives three model engines
behind one protocol; a snapshot builder produces immutable daily artifacts
from public data sources; Postgres holds users, portfolios, comparisons, and
progress; SSE streams outcome transitions to the browser. Architecture,
interfaces, and semantics are fully specified in Appendices A–D; this PRD
does not restate them.

## 9. Scope — v1 cut-lines

**In v1:** three models (FF5, BL, Monte Carlo GBM); daily snapshot; CSV
upload + manual sector weights; **multiple portfolios with side-by-side
matrix comparison**; 90-day comparison history; per-portfolio progress
charts; email/password auth with hard-gated verification and consent.

**Explicitly deferred:** OAuth social login; block-bootstrap Monte Carlo as
a user-visible return_model choice; shareable comparison links; comparison
retry endpoint; a dedicated backend "comparison set" resource (v1 composes
client-side); intraday risk-free refresh; mobile-native client; fourth model
slot (candidates: CVaR-optimal allocation, Kelly).

Deferred items were design-anticipated (schema and contract already
accommodate them), so deferral is a scheduling decision, not a redesign risk.

## 10. Resolved decisions

| # | Decision | Resolution |
|---|----------|------------|
| D1 | Snapshot rotation | Daily post-close only (adopted lean) |
| D2 | Cache provisional MC outcomes | No — cache finals only (adopted lean) |
| D3 | Email verification gating | **Hard gate before first comparison** |
| D4 | Comparison retention | **90 days**, daily purge task |
| D5 | Multi-portfolio comparison | **v1 scope**, client-composed matrix |
| D6 | Disclaimer/consent | **Required at registration**; draft copy §13 |

## 11. Success measures

Personal-scale, so measures are qualitative gates plus a few counters:
time-to-first-comparison for a new user under 5 minutes including
verification and CSV upload; first-paint budget met on ≥ 95% of
warm-snapshot requests; cache hit rate observable and non-trivial; at least
one non-author user (a Priya) completes registration through the
multi-portfolio matrix unassisted and can articulate why two models
disagreed — the real success criterion for an education product.

## 12. Milestones

| M | Deliverable | Exit test |
|---|-------------|-----------|
| M1 | Snapshot builder + artifacts; three engines with golden + property tests | Engines reproduce goldens on frozen snapshot; Euler sums verified |
| M2 | Orchestrator + comparison endpoints + SSE | U3/U9 pass via curl/httpx against local snapshot |
| M3 | Auth (verification hard gate, consent capture) + Postgres schema + CSV ingestion | U1/U2 pass; raw-file-never-stored verified; unverified-user 403 verified |
| M4 | Frontend: comparison view, attribution chart, advice delta, multi-portfolio matrix | Priya walkthrough of U2–U6 |
| M5 | Progress task + history + 90-day purge + disclaimer surfaces + polish | U7/U8 pass; purge verified against seeded expired rows |

Each milestone is scoped to be executable spec-first with a coding agent
against Appendices A–D.

## 13. Disclaimer copy (draft — review wording before launch)

> **Educational tool — not financial advice.** Sector Insight is provided
> for education and research. Nothing in this application constitutes
> investment, legal, or tax advice, or a recommendation to buy, sell, or
> hold any security. Model outputs are estimates derived from historical
> data and simplifying assumptions that may not hold in the future; three
> models are shown precisely because reasonable models disagree. Past
> performance does not guarantee future results. You are solely responsible
> for your investment decisions. Consider consulting a licensed financial
> professional before acting on any information shown here.

Registration presents this text with an unchecked consent box; the account
is created only on affirmative consent, recorded with a timestamp. A
condensed one-line version renders in the persistent footer and on every
comparison view.
