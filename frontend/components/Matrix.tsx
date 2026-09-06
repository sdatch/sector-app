"use client";

import { useEffect, useRef, useState } from "react";
import { createComparison } from "@/lib/api";
import { subscribeComparison } from "@/lib/sse";
import type {
  CompareRequest,
  ComparisonResource,
  ModelId,
  Portfolio,
} from "@/lib/types";
import { MODEL_LABEL } from "@/lib/types";
import { pct } from "@/lib/format";
import { DisclaimerInline } from "./Disclaimer";

export interface MatrixItem {
  portfolio: Portfolio;
  req: CompareRequest;
}

// Multi-portfolio comparison is composed client-side: one POST per portfolio,
// rendered as a portfolios × models matrix. No backend "comparison set"
// resource exists — deterministic caching makes re-selection nearly free
// (PRD FR-3 / U6).
export default function Matrix({
  items,
  models,
}: {
  items: MatrixItem[];
  models: ModelId[];
}) {
  const [results, setResults] = useState<
    Record<string, ComparisonResource | null>
  >({});
  const unsubs = useRef<(() => void)[]>([]);

  useEffect(() => {
    unsubs.current.forEach((u) => u());
    unsubs.current = [];
    setResults({});

    const update = (
      pid: string,
      fn: (r: ComparisonResource) => ComparisonResource,
    ) =>
      setResults((prev) => {
        const r = prev[pid];
        return r ? { ...prev, [pid]: fn(r) } : prev;
      });

    for (const { portfolio, req } of items) {
      createComparison(req)
        .then((res) => {
          setResults((prev) => ({ ...prev, [portfolio.id]: res }));
          if (res.status === "running") {
            const u = subscribeComparison(res.id, {
              onOutcome: (env) =>
                update(portfolio.id, (r) => ({
                  ...r,
                  outcomes: r.outcomes.map((o) =>
                    o.model_id === env.model_id ? env : o,
                  ),
                })),
              onComparison: (status) =>
                update(portfolio.id, (r) => ({ ...r, status })),
            });
            unsubs.current.push(u);
          }
        })
        .catch(() =>
          setResults((prev) => ({ ...prev, [portfolio.id]: null })),
        );
    }

    return () => {
      unsubs.current.forEach((u) => u());
      unsubs.current = [];
    };
  }, [items]);

  return (
    <div className="card">
      <DisclaimerInline />
      <h2>Portfolios × models</h2>
      <p className="muted small">
        Each portfolio evaluated under every model. Compare expected return and
        volatility across both dimensions at once.
      </p>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Portfolio</th>
              {models.map((m) => (
                <th key={m} className="num">
                  {MODEL_LABEL[m]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map(({ portfolio }) => {
              const res = results[portfolio.id];
              return (
                <tr key={portfolio.id}>
                  <td>{portfolio.name}</td>
                  {models.map((m) => {
                    const env = res?.outcomes.find((o) => o.model_id === m);
                    if (!res)
                      return (
                        <td key={m} className="num muted">
                          …
                        </td>
                      );
                    if (!env || env.status === "failed")
                      return (
                        <td key={m} className="num loss">
                          failed
                        </td>
                      );
                    if (!env.outcome)
                      return (
                        <td key={m} className="num muted">
                          running…
                        </td>
                      );
                    return (
                      <td key={m} className="num">
                        <div style={{ fontWeight: 600 }}>
                          {pct(env.outcome.metrics.expected_return)}
                        </div>
                        <div className="small muted">
                          σ {pct(env.outcome.metrics.volatility)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
