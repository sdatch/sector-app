import type { ModelId, OutcomeEnvelope } from "@/lib/types";
import { MODEL_LABEL } from "@/lib/types";
import { pct } from "@/lib/format";

const ACCENT: Record<ModelId, string> = {
  fama_french: "var(--ff)",
  black_litterman: "var(--bl)",
  monte_carlo: "var(--mc)",
};

// Sector risk attribution (Euler): how each model splits portfolio volatility
// across sectors. Contributions sum to each model's volatility — the same
// decomposition for all three, which is what makes them comparable.
export default function AttributionChart({
  outcomes,
}: {
  outcomes: OutcomeEnvelope[];
}) {
  const complete = outcomes.filter((o) => o.outcome);
  if (complete.length === 0) return null;

  // Sector ordering from the first model; union across all.
  const sectors: string[] = [];
  for (const env of complete) {
    for (const a of env.outcome!.sector_attribution) {
      if (!sectors.includes(a.sector)) sectors.push(a.sector);
    }
  }
  const maxRisk = Math.max(
    ...complete.flatMap((env) =>
      env.outcome!.sector_attribution.map((a) => a.risk_contribution),
    ),
    1e-9,
  );

  const riskFor = (env: OutcomeEnvelope, sector: string) =>
    env.outcome!.sector_attribution.find((a) => a.sector === sector)
      ?.risk_contribution ?? 0;

  return (
    <div className="card">
      <h2>Where your risk comes from</h2>
      <p className="muted small">
        Volatility contribution by sector (Euler decomposition). Bars are per
        model — where they disagree, the models weigh a sector&apos;s risk
        differently.
      </p>
      <div className="row" style={{ gap: "1rem", margin: "0.5rem 0 1rem" }}>
        {complete.map((env) => (
          <span key={env.model_id} className="small">
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: 2,
                background: ACCENT[env.model_id],
                marginRight: 6,
              }}
            />
            {MODEL_LABEL[env.model_id]}
          </span>
        ))}
      </div>

      <div className="scroll-x">
        <table>
          <tbody>
            {sectors.map((sector) => (
              <tr key={sector}>
                <td style={{ width: 180 }}>{sector}</td>
                <td>
                  <div className="stack" style={{ gap: "0.2rem" }}>
                    {complete.map((env) => {
                      const r = riskFor(env, sector);
                      return (
                        <div
                          key={env.model_id}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          <div
                            className="bar-track"
                            style={{ flex: 1, height: 12 }}
                          >
                            <div
                              className="bar-fill"
                              style={{
                                width: `${(r / maxRisk) * 100}%`,
                                background: ACCENT[env.model_id],
                                height: "100%",
                              }}
                            />
                          </div>
                          <span
                            className="small muted"
                            style={{
                              width: 48,
                              textAlign: "right",
                              fontVariantNumeric: "tabular-nums",
                            }}
                          >
                            {pct(r)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
