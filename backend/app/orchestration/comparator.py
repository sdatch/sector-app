"""
Comparator — owns a comparison's lifecycle, model-agnostic by construction
(compute layer design). Never names a model; consumes a uniform stream of
OutcomeTransition values and maps each 1:1 onto OutcomeEnvelope + SSE frames.

run() semantics (endpoint spec §3–4, §6):
  - resolve allocation -> EvaluationContext once, shared across engines
  - launch requested engines; one engine's exception -> that model's terminal
    `failed` transition; siblings are NOT cancelled (each task is wrapped)
  - forward every transition to the state store + event bus
  - POST awaits a 500 ms budget or all-terminal, whichever first; the driver
    keeps running in the background either way
  - 30 s hard cap -> unresolved outcomes become `failed` / compute_timeout
  - terminal => aggregate complete|partial|failed, emit terminal `comparison`
    event, write cache (finals only)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.config import Settings
from app.contracts.comparison import (
    ComparisonResource,
    CompareRequest,
    EstimationMethod,
    ModelId,
    OutcomeEnvelope,
    OutcomeError,
    OutcomeStatus,
)
from app.engines.base import EvaluationContext, RiskModelEngine, SnapshotArtifacts
from app.engines.context import AllocationError, build_context
from app.engines.base import OutcomeTransition

from .cache import ComparisonCache, cache_key
from .events import ChannelRegistry
from .state import ComparisonState, StateStore


def _envelope_from_transition(tr: OutcomeTransition) -> OutcomeEnvelope:
    error = None
    if tr.status is OutcomeStatus.FAILED:
        error = OutcomeError(
            code=tr.error_code or "error",
            message=tr.error_message or "",
            retryable=tr.retryable,
        )
    return OutcomeEnvelope(
        model_id=tr.model_id,
        status=tr.status,
        progress_pct=tr.progress_pct,
        outcome=tr.outcome,
        error=error,
    )


def _normalization_notes(models: list[ModelId], envelopes) -> list[str]:
    notes: list[str] = []
    methods = {
        e.outcome.diagnostics.estimation_method
        for e in envelopes.values()
        if e.outcome is not None
    }
    if (
        EstimationMethod.EMPIRICAL_SIMULATED in methods
        and methods & {
            EstimationMethod.PARAMETRIC_NORMAL,
            EstimationMethod.PARAMETRIC_FACTOR,
        }
    ):
        notes.append(
            "VaR/CVaR are parametric for closed-form models and empirical for "
            "Monte Carlo — tail estimates differ by design, not by error."
        )
    for e in envelopes.values():
        if e.error is not None:
            notes.append(e.error.message)
    return notes


class ComparisonManager:
    """Process-wide owner of comparison state, engines, cache, and channels."""

    def __init__(
        self,
        artifacts: SnapshotArtifacts,
        ticker_sector: dict[str, str],
        engines: dict[ModelId, RiskModelEngine],
        settings: Settings,
        on_finalize=None,
    ) -> None:
        self._artifacts = artifacts
        self._ticker_sector = ticker_sector
        self._engines = engines
        self._settings = settings
        # Async callback(state) invoked once a comparison is terminal — used to
        # persist the result to the comparisons table (M5). Owned comparisons
        # only; anonymous/in-memory states are not persisted.
        self._on_finalize = on_finalize
        self._store = StateStore()
        self._channels = ChannelRegistry()
        self._cache = ComparisonCache()
        self._tasks: dict[str, asyncio.Task] = {}

    # -- lookups -------------------------------------------------------------

    def get_resource(self, comparison_id: str) -> ComparisonResource | None:
        state = self._store.get(comparison_id)
        return state.to_resource() if state else None

    def get_state(self, comparison_id: str) -> ComparisonState | None:
        return self._store.get(comparison_id)

    def channel(self, comparison_id: str):
        return self._channels.get(comparison_id)

    def cache_lookup(self, request: CompareRequest) -> ComparisonResource | None:
        key = cache_key(self._artifacts.meta.snapshot_id, request)
        return self._cache.get(key)

    # -- creation ------------------------------------------------------------

    def owns(self, comparison_id: str, user_id: str) -> bool:
        state = self._store.get(comparison_id)
        # Cache-only results (no live state) are deterministic and not tied to a
        # user session; ownership is enforced on stateful resources.
        return state is None or state.user_id is None or state.user_id == user_id

    async def create(
        self,
        request: CompareRequest,
        user_id: str | None = None,
        portfolio_id: str | None = None,
    ) -> tuple[ComparisonResource, bool]:
        """Create + run within the sync budget. Returns (resource, cache_hit).
        Raises AllocationError (=> 422) if the allocation can't be resolved."""
        key = cache_key(self._artifacts.meta.snapshot_id, request)
        cached = self._cache.get(key)
        if cached is not None:
            return cached, True

        comparison_id = uuid4()
        ctx = self._build_context(request, comparison_id, key)  # may raise 422

        state = ComparisonState(
            id=comparison_id,
            request=request,
            snapshot=self._artifacts.meta,
            cache_key=key,
            generated_at=datetime.now(timezone.utc),
            envelopes={
                m: OutcomeEnvelope(model_id=m, status=OutcomeStatus.PENDING)
                for m in request.models
            },
            user_id=user_id,
            portfolio_id=portfolio_id,
        )
        self._store.put(state)
        self._channels.create(str(comparison_id))

        task = asyncio.create_task(self._drive(state, ctx))
        self._tasks[str(comparison_id)] = task

        # Budget: return whatever is ready at 500 ms, or earlier if all terminal.
        budget_s = self._settings.sync_budget_ms / 1000.0
        try:
            await asyncio.wait_for(state.terminal_event.wait(), timeout=budget_s)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        return state.to_resource(), False

    def _build_context(
        self, request: CompareRequest, comparison_id: UUID, key: str
    ) -> EvaluationContext:
        if request.allocation.portfolio_id is not None:
            # portfolio_id resolution needs the DB (M3); explicit modes work now.
            raise AllocationError(
                "portfolio_id allocation requires authentication and portfolio "
                "storage (available in M3); use sector_weights or ticker_weights"
            )
        # Seed the RNG from the cache key so identical requests are bit-identical.
        rng_seed = int(key[:16], 16)
        return build_context(
            request, self._artifacts, rng_seed=rng_seed,
            ticker_sector=self._ticker_sector,
        )

    # -- driving -------------------------------------------------------------

    async def _drive(self, state: ComparisonState, ctx: EvaluationContext) -> None:
        cap_s = self._settings.compute_cap_s
        try:
            await asyncio.wait_for(self._run_engines(state, ctx), timeout=cap_s)
        except (asyncio.TimeoutError, TimeoutError):
            self._fail_unresolved(
                state, "compute_timeout",
                f"Compute exceeded the {cap_s}s cap", retryable=False,
            )
        except asyncio.CancelledError:
            self._fail_unresolved(
                state, "cancelled", "Comparison cancelled", retryable=False
            )
        finally:
            self._finalize(state)

    async def _run_engines(
        self, state: ComparisonState, ctx: EvaluationContext
    ) -> None:
        async with asyncio.TaskGroup() as tg:
            for model_id in state.request.models:
                tg.create_task(self._run_one(state, ctx, model_id))

    async def _run_one(
        self, state: ComparisonState, ctx: EvaluationContext, model_id: ModelId
    ) -> None:
        engine = self._engines[model_id]
        try:
            async for tr in engine.evaluate(ctx):
                self._apply(state, tr)
        except asyncio.CancelledError:
            self._apply(
                state,
                OutcomeTransition(
                    model_id=model_id, status=OutcomeStatus.FAILED,
                    error_code="cancelled", error_message="Comparison cancelled",
                    retryable=False,
                ),
            )
            raise  # propagate so the whole comparison unwinds on cancel
        except Exception as exc:  # noqa: BLE001 — sibling isolation by design
            self._apply(
                state,
                OutcomeTransition(
                    model_id=model_id, status=OutcomeStatus.FAILED,
                    error_code="engine_error", error_message=str(exc),
                    retryable=True,
                ),
            )

    # -- transition application ---------------------------------------------

    def _apply(self, state: ComparisonState, tr: OutcomeTransition) -> None:
        prev = state.envelopes.get(tr.model_id)
        prev_status = prev.status if prev else None
        channel = self._channels.get(str(state.id))

        is_pure_progress = (
            tr.status is OutcomeStatus.RUNNING
            and tr.outcome is None
            and tr.progress_pct is not None
            and prev_status is OutcomeStatus.RUNNING
        )

        if is_pure_progress:
            # Throttle progress to 2/s per model; still record latest pct.
            if prev is not None:
                state.envelopes[tr.model_id] = prev.model_copy(
                    update={"progress_pct": tr.progress_pct}
                )
            if channel is not None and self._progress_ok(state, tr.model_id):
                channel.publish(
                    "progress",
                    {"model_id": tr.model_id.value, "pct": tr.progress_pct},
                )
            return

        envelope = _envelope_from_transition(tr)
        state.envelopes[tr.model_id] = envelope
        if channel is not None:
            channel.publish("outcome", envelope.model_dump(mode="json"))

    def _progress_ok(self, state: ComparisonState, model_id: ModelId) -> bool:
        loop = asyncio.get_running_loop()
        now = loop.time()
        last = state.last_progress_at.get(model_id, 0.0)
        if now - last >= 0.5:
            state.last_progress_at[model_id] = now
            return True
        return False

    def _fail_unresolved(
        self, state: ComparisonState, code: str, message: str, retryable: bool
    ) -> None:
        from .state import _UNRESOLVED

        for model_id, env in list(state.envelopes.items()):
            if env.status in _UNRESOLVED:
                self._apply(
                    state,
                    OutcomeTransition(
                        model_id=model_id, status=OutcomeStatus.FAILED,
                        error_code=code, error_message=message,
                        retryable=retryable,
                    ),
                )

    def _finalize(self, state: ComparisonState) -> None:
        if state.terminal_event.is_set():
            return
        state.normalization_notes = _normalization_notes(
            state.request.models, state.envelopes
        )
        resource = state.to_resource()

        # Cache finals only, and never cache a transient (retryable) failure so
        # an identical request can recompute it.
        has_retryable_failure = any(
            e.error is not None and e.error.retryable
            for e in state.envelopes.values()
        )
        if not has_retryable_failure:
            self._cache.put(state.cache_key, resource)

        channel = self._channels.get(str(state.id))
        if channel is not None:
            channel.publish("comparison", {"status": resource.status.value})
            channel.close()
        state.terminal_event.set()

        # Persist terminal owned comparisons for history (M5).
        if self._on_finalize is not None and state.user_id is not None:
            asyncio.create_task(self._safe_finalize(state))

    async def _safe_finalize(self, state: ComparisonState) -> None:
        try:
            await self._on_finalize(state)
        except Exception:  # noqa: BLE001 — persistence must not crash the loop
            pass

    # -- cancellation --------------------------------------------------------

    async def cancel(self, comparison_id: str) -> bool:
        state = self._store.get(comparison_id)
        if state is None:
            return False
        if state.terminal_event.is_set():
            return False  # already terminal; nothing to cancel
        task = self._tasks.get(comparison_id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return True
