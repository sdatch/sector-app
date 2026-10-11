import type { OutcomeEnvelope, RiskLevel, SectorShift } from "@/lib/types";
import {
  ACCENT,
  MODEL_LABEL,
  RISK_LEVEL_HINT,
  RISK_LEVEL_LABEL,
} from "@/lib/types";
import { num, pct } from "@/lib/format";
import { moveDigits, type MoveDigits } from "@/lib/moves";
import Delta from "./Delta";

// Up to three sector shifts per model (engines/common/shifts.py). Each model
// ranks the same candidates with its own moments, so the columns can disagree.
export default function SuggestedShifts({
  outcomes,
  riskLevel,
}: {
  outcomes: OutcomeEnvelope[];
  riskLevel: RiskLevel;
}) {
  if (!outcomes.some((o) => o.outcome)) return null;
  // Saved comparisons from before shifts existed echo the default risk_level
  // on reload, so only name a level if some model actually computed shifts.
  const computed = outcomes.some((o) => o.outcome?.suggested_shifts != null);

  return (
    <div className="card">
      <h2>Sector shifts to explore</h2>
      <p className="muted small">
        {computed &&
          `${RISK_LEVEL_LABEL[riskLevel]} risk level: ${RISK_LEVEL_HINT[riskLevel]} `}
        Every shift shown raises the Sharpe ratio. Each model ranks the same
        candidates using its own assumptions, so the lists can differ. This is a
        lens on the models, not a recommendation to buy or sell anything.
      </p>
      <div className="model-cols" style={{ marginTop: "0.8rem" }}>
        {outcomes.map((env) => (
          <div
            key={env.model_id}
            className="model-col"
            style={{ ["--accent" as any]: ACCENT[env.model_id] }}
          >
            <div className="head">
              <span className="name">{MODEL_LABEL[env.model_id]}</span>
            </div>
            <Column env={env} riskLevel={riskLevel} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Column({ env, riskLevel }: { env: OutcomeEnvelope; riskLevel: RiskLevel }) {
  if (env.status === "failed") {
    return <Note>This model failed to run, so it has no shifts.</Note>;
  }
  if (!env.outcome) return <Note>Waiting for results…</Note>;
  // Comparisons saved before this feature have no shifts field.
  if (env.outcome.suggested_shifts == null) {
    return <Note>Shifts weren&apos;t computed for this saved comparison.</Note>;
  }
  if (env.outcome.suggested_shifts.length === 0) {
    return <Note>No shift raises the Sharpe ratio at this risk level.</Note>;
  }
  // Shared precision across the column, widened only where the default would
  // hide a real change or the ranking key's order (see lib/moves.ts). Easy mode
  // renders the same shifts, so both views have to agree digit for digit.
  const digits = moveDigits(env.outcome.suggested_shifts, riskLevel);
  return (
    <>
      {env.outcome.suggested_shifts.map((s) => (
        <ShiftCard
          key={`${s.from_sector}->${s.to_sector}`}
          shift={s}
          digits={digits}
        />
      ))}
    </>
  );
}

function ShiftCard({
  shift,
  digits,
}: {
  shift: SectorShift;
  digits: MoveDigits;
}) {
  const b = shift.metrics_before;
  const a = shift.metrics_after;
  return (
    <div
      style={{ padding: "0.7rem 0.9rem", borderTop: "1px solid var(--border)" }}
    >
      <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>
        Move {pct(shift.fraction, 0)} of the portfolio from{" "}
        {shift.from_sector} to {shift.to_sector}
      </div>
      <Delta
        k="Sharpe"
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
        <div style={{ marginTop: "0.35rem" }}>
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
    <div className="small muted" style={{ padding: "0.9rem" }}>
      {children}
    </div>
  );
}
