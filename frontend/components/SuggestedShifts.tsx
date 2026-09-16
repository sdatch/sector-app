import type {
  ModelId,
  OutcomeEnvelope,
  RiskLevel,
  SectorShift,
} from "@/lib/types";
import { MODEL_LABEL, RISK_LEVEL_HINT, RISK_LEVEL_LABEL } from "@/lib/types";
import { num, pct } from "@/lib/format";

const ACCENT: Record<ModelId, string> = {
  fama_french: "var(--ff)",
  black_litterman: "var(--bl)",
  monte_carlo: "var(--mc)",
};

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
            <Column env={env} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Column({ env }: { env: OutcomeEnvelope }) {
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
  return (
    <>
      {env.outcome.suggested_shifts.map((s) => (
        <ShiftCard key={`${s.from_sector}->${s.to_sector}`} shift={s} />
      ))}
    </>
  );
}

function ShiftCard({ shift }: { shift: SectorShift }) {
  const b = shift.metrics_before;
  const a = shift.metrics_after;
  // Every shift raises Sharpe; add a digit when 2dp rounding would hide that.
  const sharpeDigits =
    num(b.sharpe_ratio) === num(a.sharpe_ratio) ? 3 : 2;
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
        before={num(b.sharpe_ratio, sharpeDigits)}
        after={num(a.sharpe_ratio, sharpeDigits)}
        good={a.sharpe_ratio > b.sharpe_ratio}
      />
      <Delta
        k="Volatility"
        before={pct(b.volatility)}
        after={pct(a.volatility)}
        good={a.volatility < b.volatility}
      />
      <Delta
        k="Expected return"
        before={pct(b.expected_return)}
        after={pct(a.expected_return)}
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

function Delta({
  k,
  before,
  after,
  good,
}: {
  k: string;
  before: string;
  after: string;
  good: boolean;
}) {
  return (
    <div className="metric-row small" style={{ padding: "0.15rem 0", border: 0 }}>
      <span className="k">{k}</span>
      <span>
        <span className="muted">{before}</span> →{" "}
        <span className={before === after ? undefined : good ? "gain" : "loss"}>
          {after}
        </span>
      </span>
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
