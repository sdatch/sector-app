"use client";

import type { ModelId, OutcomeEnvelope, RiskLevel, SectorShift } from "@/lib/types";
import { ACCENT, ALL_MODELS, MODEL_LABEL, RISK_LEVEL_HINT } from "@/lib/types";
import { num, pct } from "@/lib/format";
import { describeMove, moveDigits, moveHeadline, type MoveDigits } from "@/lib/moves";
import Delta from "./Delta";

export const moveKey = (s: SectorShift) => `${s.from_sector}->${s.to_sector}`;

/** Easy mode: one model's three moves, in plain language. The same
 *  `suggested_shifts` the three-column view renders — this view just picks one
 *  column and explains it, so switching model is a re-render, not a request. */
export default function EasyMoves({
  outcomes,
  model,
  onModelChange,
  riskLevel,
  narration,
  stale = false,
}: {
  outcomes: OutcomeEnvelope[];
  model: ModelId;
  onModelChange: (m: ModelId) => void;
  riskLevel: RiskLevel;
  /** moveKey -> prose, when the optional narration layer is enabled. */
  narration?: Record<string, string> | null;
  /** Showing the previous run's moves while a new one is in flight. */
  stale?: boolean;
}) {
  const env = outcomes.find((o) => o.model_id === model);
  const narrated = Boolean(narration && Object.keys(narration).length > 0);

  return (
    <div className="card" style={{ ["--accent" as any]: ACCENT[model] }}>
      <h2>Three moves to consider</h2>
      <p className="muted small">
        {RISK_LEVEL_HINT[riskLevel]} Each model ranks the same candidate shifts
        using its own assumptions, so switching model below changes the order —
        and sometimes the list. These are sector tilts for you to think about,
        not a recommendation to buy or sell anything.
      </p>

      <div className="easy-tabs" style={{ marginTop: "0.9rem" }} role="tablist">
        {ALL_MODELS.map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={m === model}
            className="easy-tab"
            style={{ ["--accent" as any]: ACCENT[m] }}
            onClick={() => onModelChange(m)}
          >
            {MODEL_LABEL[m]}
          </button>
        ))}
      </div>

      {narrated && (
        // Disclosure, not a credit line. An operator flag is not consent: if
        // the wording came from Claude, the reader is told so, and told what
        // was sent to get it (PRD NFR-3).
        <p className="muted small" style={{ marginTop: "0.6rem" }}>
          <strong>Wording by Claude.</strong> The moves, the ranking and every
          figure here are computed by the model named above — Claude only writes
          the explanations, from those figures. Producing them sends your sector
          weights and the figures to Anthropic. It never sends your holdings:
          no tickers, no quantities, no account value.
        </p>
      )}

      <div style={{ marginTop: "0.6rem", opacity: stale ? 0.5 : 1 }}>
        {env ? (
          <Moves
            env={env}
            model={model}
            riskLevel={riskLevel}
            narration={narration}
          />
        ) : (
          <Note>This model was not part of the run.</Note>
        )}
      </div>
    </div>
  );
}

function Moves({
  env,
  model,
  riskLevel,
  narration,
}: {
  env: OutcomeEnvelope;
  model: ModelId;
  riskLevel: RiskLevel;
  narration?: Record<string, string> | null;
}) {
  if (env.status === "failed") {
    return (
      <Note>
        {MODEL_LABEL[model]} failed to run
        {env.error?.message ? `: ${env.error.message}` : "."} The other models
        above may still have moves for you.
      </Note>
    );
  }
  if (!env.outcome) return <Note>Working out this model&apos;s moves…</Note>;
  // Comparisons saved before shifts existed carry no list at all.
  if (env.outcome.suggested_shifts == null) {
    return <Note>Moves weren&apos;t computed for this saved comparison.</Note>;
  }
  if (env.outcome.suggested_shifts.length === 0) {
    return (
      <Note>
        At this risk level, {MODEL_LABEL[model]} finds no shift that improves
        your portfolio&apos;s return per unit of risk — which is itself an
        answer. Try a different risk level, or another model, to see whether
        they agree.
      </Note>
    );
  }
  // One precision for the whole list: the moves are ranked against each other,
  // so they have to be readable against each other.
  const digits = moveDigits(env.outcome.suggested_shifts, riskLevel);
  return (
    <>
      {env.outcome.suggested_shifts.map((s, i) => (
        <Move
          key={moveKey(s)}
          shift={s}
          model={model}
          riskLevel={riskLevel}
          rank={i}
          digits={digits}
          text={narration?.[moveKey(s)]}
        />
      ))}
    </>
  );
}

function Move({
  shift,
  model,
  riskLevel,
  rank,
  digits,
  text,
}: {
  shift: SectorShift;
  model: ModelId;
  riskLevel: RiskLevel;
  rank: number;
  digits: MoveDigits;
  text?: string;
}) {
  const b = shift.metrics_before;
  const a = shift.metrics_after;

  return (
    <div className="easy-move">
      <div className="easy-move-head">{moveHeadline(shift)}</div>
      <p className="easy-move-text">
        {text ?? describeMove(shift, model, riskLevel, rank, digits)}
      </p>
      <Delta
        k="Return per unit of risk"
        before={num(b.sharpe_ratio, digits.sharpe)}
        after={num(a.sharpe_ratio, digits.sharpe)}
        good={a.sharpe_ratio > b.sharpe_ratio}
      />
      <Delta
        k="Volatility"
        before={pct(b.volatility, digits.vol)}
        after={pct(a.volatility, digits.vol)}
        good={a.volatility < b.volatility}
      />
      <Delta
        k="Expected return"
        before={pct(b.expected_return, digits.ret)}
        after={pct(a.expected_return, digits.ret)}
        good={a.expected_return > b.expected_return}
      />
      {shift.warnings.includes("parametric_estimate") && (
        <div style={{ marginTop: "0.4rem" }}>
          <span
            className="badge provisional"
            title="Estimated in closed form from the inputs Monte Carlo simulates from, not simulated separately"
          >
            estimate
          </span>
        </div>
      )}
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="small muted" style={{ padding: "0.9rem 0" }}>
      {children}
    </div>
  );
}
