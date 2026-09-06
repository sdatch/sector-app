import type { ModelId, OutcomeEnvelope } from "@/lib/types";
import { MODEL_LABEL } from "@/lib/types";
import { money, pct, num } from "@/lib/format";

const ACCENT: Record<ModelId, string> = {
  fama_french: "var(--ff)",
  black_litterman: "var(--bl)",
  monte_carlo: "var(--mc)",
};

function isProvisional(env: OutcomeEnvelope): boolean {
  return (
    env.status === "provisional" ||
    (env.outcome?.diagnostics.warnings.includes("provisional_estimate") ?? false)
  );
}

export default function ModelColumns({
  outcomes,
}: {
  outcomes: OutcomeEnvelope[];
}) {
  return (
    <div className="model-cols">
      {outcomes.map((env) => (
        <div
          key={env.model_id}
          className="model-col"
          style={{ ["--accent" as any]: ACCENT[env.model_id] }}
        >
          <div className="head">
            <span className="name">{MODEL_LABEL[env.model_id]}</span>
            {env.status === "failed" ? (
              <span className="badge failed">failed</span>
            ) : isProvisional(env) ? (
              <span className="badge provisional">provisional</span>
            ) : env.status === "complete" ? (
              <span className="badge complete">complete</span>
            ) : (
              <span className="badge default">running</span>
            )}
          </div>

          {env.status === "running" && !env.outcome && (
            <div style={{ padding: "0.9rem" }}>
              <div className="progress">
                <span style={{ width: `${(env.progress_pct || 0) * 100}%` }} />
              </div>
              <div className="muted small" style={{ marginTop: "0.4rem" }}>
                simulating…
              </div>
            </div>
          )}

          {env.status === "failed" && (
            <div style={{ padding: "0.9rem" }} className="small loss">
              {env.error?.message || "Model unavailable."}
            </div>
          )}

          {env.outcome && (
            <>
              {isProvisional(env) && (env.progress_pct ?? 0) < 1 && (
                <div style={{ padding: "0.6rem 0.9rem 0" }}>
                  <div className="progress">
                    <span
                      style={{ width: `${(env.progress_pct || 0) * 100}%` }}
                    />
                  </div>
                </div>
              )}
              <Metric
                k="Expected return"
                v={pct(env.outcome.metrics.expected_return)}
              />
              <Metric k="Volatility" v={pct(env.outcome.metrics.volatility)} />
              <Metric
                k="Sharpe"
                v={num(env.outcome.metrics.sharpe_ratio)}
              />
              <Metric
                k="P(loss)"
                v={pct(env.outcome.metrics.prob_loss)}
              />
              <Metric
                k="VaR (horizon)"
                v={money(env.outcome.metrics.var_horizon)}
                loss={env.outcome.metrics.var_horizon > 0}
              />
              <Metric
                k="CVaR (horizon)"
                v={money(env.outcome.metrics.cvar_horizon)}
                loss={env.outcome.metrics.cvar_horizon > 0}
              />
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function Metric({ k, v, loss }: { k: string; v: string; loss?: boolean }) {
  return (
    <div className="metric-row">
      <span className="k">{k}</span>
      <span className={loss ? "loss" : undefined}>{v}</span>
    </div>
  );
}
