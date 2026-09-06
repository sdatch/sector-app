import type { ComparisonResource, ModelId } from "@/lib/types";
import { MODEL_LABEL } from "@/lib/types";
import { money } from "@/lib/format";
import { DisclaimerInline } from "./Disclaimer";
import ModelColumns from "./ModelColumns";
import AttributionChart from "./AttributionChart";
import AdviceDelta from "./AdviceDelta";
import CaveatsPanel from "./CaveatsPanel";

const ACCENT: Record<ModelId, string> = {
  fama_french: "var(--ff)",
  black_litterman: "var(--bl)",
  monte_carlo: "var(--mc)",
};

export default function ComparisonView({
  resource,
}: {
  resource: ComparisonResource;
}) {
  return (
    <div className="stack">
      <DisclaimerInline />
      <ModelColumns outcomes={resource.outcomes} />
      <DistributionBands resource={resource} />
      <AttributionChart outcomes={resource.outcomes} />
      <AdviceDelta outcomes={resource.outcomes} />
      <CaveatsPanel
        outcomes={resource.outcomes}
        notes={resource.normalization_notes}
      />
    </div>
  );
}

function DistributionBands({ resource }: { resource: ComparisonResource }) {
  const complete = resource.outcomes.filter((o) => o.outcome);
  if (complete.length === 0) return null;

  const initial = resource.request.initial_value ?? 100000;
  const lo = Math.min(...complete.map((o) => o.outcome!.distribution.p5));
  const hi = Math.max(...complete.map((o) => o.outcome!.distribution.p95));
  const span = hi - lo || 1;
  const x = (v: number) => ((v - lo) / span) * 100;

  return (
    <div className="card">
      <h2>Range of outcomes at horizon</h2>
      <p className="muted small">
        Terminal portfolio value from an initial {money(initial)} — the box
        spans the 25th–75th percentile, whiskers the 5th–95th, tick at the
        median. Parametric and simulated ranges differ by design.
      </p>
      <div className="stack" style={{ gap: "0.9rem", marginTop: "0.8rem" }}>
        {complete.map((env) => {
          const d = env.outcome!.distribution;
          return (
            <div key={env.model_id}>
              <div className="small muted" style={{ marginBottom: 4 }}>
                {MODEL_LABEL[env.model_id]}
              </div>
              <div style={{ position: "relative", height: 22 }}>
                {/* whisker */}
                <div
                  style={{
                    position: "absolute",
                    top: 10,
                    left: `${x(d.p5)}%`,
                    width: `${x(d.p95) - x(d.p5)}%`,
                    height: 2,
                    background: "var(--border)",
                  }}
                />
                {/* box */}
                <div
                  style={{
                    position: "absolute",
                    top: 4,
                    left: `${x(d.p25)}%`,
                    width: `${x(d.p75) - x(d.p25)}%`,
                    height: 14,
                    background: `color-mix(in srgb, ${ACCENT[env.model_id]} 25%, transparent)`,
                    border: `1px solid ${ACCENT[env.model_id]}`,
                    borderRadius: 3,
                  }}
                />
                {/* median */}
                <div
                  style={{
                    position: "absolute",
                    top: 2,
                    left: `${x(d.p50)}%`,
                    width: 2,
                    height: 18,
                    background: ACCENT[env.model_id],
                  }}
                />
              </div>
              <div
                className="small muted"
                style={{ display: "flex", justifyContent: "space-between" }}
              >
                <span>{money(d.p5)}</span>
                <span>{money(d.p50)}</span>
                <span>{money(d.p95)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
