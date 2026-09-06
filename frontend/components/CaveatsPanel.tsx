import type { OutcomeEnvelope } from "@/lib/types";
import { MODEL_LABEL } from "@/lib/types";
import { num, pct } from "@/lib/format";

const METHOD_LABEL: Record<string, string> = {
  parametric_normal: "Parametric (normal)",
  parametric_factor: "Parametric (factor)",
  empirical_simulated: "Empirical (simulated)",
};

// The education layer is rendered from the API's transparency fields, not
// hand-maintained copy (PRD FR-4).
export default function CaveatsPanel({
  outcomes,
  notes,
}: {
  outcomes: OutcomeEnvelope[];
  notes: string[];
}) {
  return (
    <div className="card">
      <h2>Assumptions &amp; caveats</h2>
      {notes.length > 0 && (
        <ul className="small muted" style={{ marginTop: 0 }}>
          {notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Estimation method</th>
              <th className="num">Coverage</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {outcomes.map((env) => {
              const d = env.outcome?.diagnostics;
              return (
                <tr key={env.model_id}>
                  <td>{MODEL_LABEL[env.model_id]}</td>
                  <td className="muted">
                    {d ? METHOD_LABEL[d.estimation_method] ?? d.estimation_method : "—"}
                  </td>
                  <td className="num">{d ? pct(d.data_coverage_pct, 0) : "—"}</td>
                  <td className="muted small">
                    {env.model_id === "fama_french" && d?.fit_r2 != null && (
                      <>Fit R² {num(d.fit_r2, 2)}. </>
                    )}
                    {env.model_id === "monte_carlo" &&
                      d?.convergence_std_error != null && (
                        <>SE of mean ±{Math.round(d.convergence_std_error)}. </>
                      )}
                    {d?.warnings
                      .filter((w) => w !== "provisional_estimate")
                      .join("; ")}
                    {env.error && <span className="loss">{env.error.message}</span>}
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
