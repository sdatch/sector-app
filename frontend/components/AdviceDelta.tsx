import type { OutcomeEnvelope } from "@/lib/types";
import { pct } from "@/lib/format";

// Black-Litterman advice delta: model-suggested optimal weights next to the
// user's current weights (PRD G3 / U5).
export default function AdviceDelta({
  outcomes,
}: {
  outcomes: OutcomeEnvelope[];
}) {
  const bl = outcomes.find(
    (o) => o.model_id === "black_litterman" && o.outcome,
  );
  if (!bl?.outcome) return null;

  const current: Record<string, number> = {};
  for (const a of bl.outcome.sector_attribution) current[a.sector] = a.weight;
  const optimal: Record<string, number> =
    bl.outcome.detail?.optimal_weights ?? {};

  const sectors = Array.from(
    new Set([...Object.keys(current), ...Object.keys(optimal)]),
  ).sort((a, b) => (optimal[b] ?? 0) - (optimal[a] ?? 0));

  const maxW = Math.max(
    ...sectors.map((s) => Math.max(current[s] ?? 0, optimal[s] ?? 0)),
    1e-9,
  );

  return (
    <div className="card">
      <h2>Black-Litterman advice delta</h2>
      <p className="muted small">
        Your current sector weights vs. the max-Sharpe allocation under
        Black-Litterman&apos;s posterior (equilibrium updated by your views).
        This is a lens, not a recommendation.
      </p>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Sector</th>
              <th style={{ width: "42%" }}>Current vs. suggested</th>
              <th className="num">Current</th>
              <th className="num">Suggested</th>
              <th className="num">Δ</th>
            </tr>
          </thead>
          <tbody>
            {sectors.map((s) => {
              const cur = current[s] ?? 0;
              const opt = optimal[s] ?? 0;
              const delta = opt - cur;
              return (
                <tr key={s}>
                  <td>{s}</td>
                  <td>
                    <Bar value={cur} max={maxW} color="var(--text-muted)" />
                    <Bar value={opt} max={maxW} color="var(--bl)" />
                  </td>
                  <td className="num">{pct(cur)}</td>
                  <td className="num">{pct(opt)}</td>
                  <td
                    className="num"
                    style={{
                      color:
                        delta > 0.005
                          ? "var(--gain)"
                          : delta < -0.005
                            ? "var(--loss)"
                            : "var(--text-muted)",
                    }}
                  >
                    {delta > 0 ? "+" : ""}
                    {pct(delta)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Bar({
  value,
  max,
  color,
}: {
  value: number;
  max: number;
  color: string;
}) {
  return (
    <div className="bar-track" style={{ height: 10, marginBottom: 3 }}>
      <div
        className="bar-fill"
        style={{ width: `${(value / max) * 100}%`, background: color, height: "100%" }}
      />
    </div>
  );
}
