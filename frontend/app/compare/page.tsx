"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { listPortfolios } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLiveComparison } from "@/lib/useLiveComparison";
import {
  ALL_MODELS,
  MODEL_LABEL,
  SECTORS,
  type CompareRequest,
  type ModelId,
  type Portfolio,
} from "@/lib/types";
import ComparisonView from "@/components/ComparisonView";
import Matrix, { type MatrixItem } from "@/components/Matrix";

function CompareInner() {
  const { me, loading } = useAuth();
  const router = useRouter();
  const params = useSearchParams();

  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [horizon, setHorizon] = useState(120);
  const [nSims, setNSims] = useState(10000);
  const [models, setModels] = useState<ModelId[]>(ALL_MODELS);
  const [viewSector, setViewSector] = useState("");
  const [viewReturn, setViewReturn] = useState(10);
  const [viewConfidence, setViewConfidence] = useState(60);
  const [matrixItems, setMatrixItems] = useState<MatrixItem[] | null>(null);

  const live = useLiveComparison();

  useEffect(() => {
    if (!loading && !me) router.push("/login");
  }, [loading, me, router]);

  useEffect(() => {
    if (!me) return;
    listPortfolios().then((ps) => {
      setPortfolios(ps);
      const pre = params.get("portfolio");
      if (pre && ps.some((p) => p.id === pre)) setSelected([pre]);
      else {
        const def = ps.find((p) => p.is_default) ?? ps[0];
        if (def) setSelected([def.id]);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  const buildRequest = (portfolioId: string): CompareRequest => ({
    allocation: { portfolio_id: portfolioId },
    horizon_months: horizon,
    models,
    n_simulations: nSims,
    views:
      viewSector && models.includes("black_litterman")
        ? [
            {
              sector: viewSector,
              expected_annual_return: viewReturn / 100,
              confidence: viewConfidence / 100,
            },
          ]
        : [],
  });

  function toggle<T>(list: T[], v: T): T[] {
    return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
  }

  function run() {
    if (selected.length === 0 || models.length === 0) return;
    if (selected.length === 1) {
      setMatrixItems(null);
      live.run(buildRequest(selected[0]));
    } else {
      const items = selected
        .map((id) => portfolios.find((p) => p.id === id))
        .filter((p): p is Portfolio => !!p)
        .map((p) => ({ portfolio: p, req: buildRequest(p.id) }));
      setMatrixItems(items);
    }
  }

  const canRun = selected.length > 0 && models.length > 0;
  const showMatrix = matrixItems && matrixItems.length > 1;

  if (loading || !me) return <div className="container">Loading…</div>;

  if (portfolios.length === 0) {
    return (
      <div className="container">
        <div className="card stack">
          <h1>Run a comparison</h1>
          <p className="muted">
            You need a portfolio first. Upload a CSV or enter sector weights.
          </p>
          <Link href="/portfolios" className="btn primary">
            Add a portfolio
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="container stack">
      <h1>Compare</h1>

      <div className="card">
        <div className="row">
          <div style={{ flex: "1 1 260px" }}>
            <label>Portfolios (pick 2+ for a matrix)</label>
            <div className="stack" style={{ gap: "0.35rem" }}>
              {portfolios.map((p) => (
                <label key={p.id} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={selected.includes(p.id)}
                    onChange={() => setSelected((s) => toggle(s, p.id))}
                  />
                  <span>
                    {p.name}{" "}
                    {p.is_default && (
                      <span className="badge default">default</span>
                    )}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div style={{ flex: "1 1 260px" }}>
            <label>Models</label>
            <div className="stack" style={{ gap: "0.35rem" }}>
              {ALL_MODELS.map((m) => (
                <label key={m} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={models.includes(m)}
                    onChange={() => setModels((s) => toggle(s, m))}
                  />
                  <span>{MODEL_LABEL[m]}</span>
                </label>
              ))}
            </div>
          </div>

          <div style={{ flex: "1 1 200px" }}>
            <div className="field">
              <label>Horizon (months)</label>
              <input
                type="number"
                min={1}
                max={480}
                value={horizon}
                onChange={(e) => setHorizon(parseInt(e.target.value) || 1)}
              />
            </div>
            <div className="field">
              <label>Monte Carlo paths</label>
              <input
                type="number"
                min={1000}
                max={200000}
                step={1000}
                value={nSims}
                onChange={(e) => setNSims(parseInt(e.target.value) || 10000)}
              />
            </div>
          </div>
        </div>

        {models.includes("black_litterman") && (
          <div className="row" style={{ marginTop: "0.5rem" }}>
            <div className="field">
              <label>Black-Litterman view — sector (optional)</label>
              <select
                value={viewSector}
                onChange={(e) => setViewSector(e.target.value)}
              >
                <option value="">No view</option>
                {SECTORS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Expected annual return %</label>
              <input
                type="number"
                value={viewReturn}
                onChange={(e) => setViewReturn(parseFloat(e.target.value) || 0)}
                disabled={!viewSector}
              />
            </div>
            <div className="field">
              <label>Confidence %</label>
              <input
                type="number"
                min={1}
                max={100}
                value={viewConfidence}
                onChange={(e) =>
                  setViewConfidence(parseFloat(e.target.value) || 60)
                }
                disabled={!viewSector}
              />
            </div>
          </div>
        )}

        <div style={{ marginTop: "0.75rem" }}>
          <button
            className="btn primary"
            disabled={!canRun || live.running}
            onClick={run}
          >
            {live.running ? "Computing…" : "Run comparison"}
          </button>
          {selected.length > 1 && (
            <span className="muted small" style={{ marginLeft: "0.75rem" }}>
              {selected.length} portfolios → matrix view
            </span>
          )}
        </div>
        {live.error && <div className="error">{live.error}</div>}
      </div>

      {showMatrix ? (
        <Matrix items={matrixItems!} models={models} />
      ) : live.resource ? (
        <ComparisonView resource={live.resource} />
      ) : null}
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="container">Loading…</div>}>
      <CompareInner />
    </Suspense>
  );
}
