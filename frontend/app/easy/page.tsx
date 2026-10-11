"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getPortfolioAllocation,
  listPortfolios,
  type PortfolioAllocation,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLiveComparison } from "@/lib/useLiveComparison";
import {
  ALL_MODELS,
  DEFAULT_HORIZON_MONTHS,
  DEFAULT_N_SIMULATIONS,
  DEFAULT_RISK_LEVEL,
  RISK_LEVEL_LABEL,
  type ModelId,
  type OutcomeEnvelope,
  type Portfolio,
  type RiskLevel,
} from "@/lib/types";
import { pct } from "@/lib/format";
import { DisclaimerInline } from "@/components/Disclaimer";
import EasyMoves from "@/components/EasyMoves";

const RISK_LEVELS: RiskLevel[] = ["conservative", "moderate", "aggressive"];

function EasyInner() {
  const { me, loading } = useAuth();
  const router = useRouter();
  const params = useSearchParams();

  const [portfolios, setPortfolios] = useState<Portfolio[] | null>(null);
  const [portfolioId, setPortfolioId] = useState("");
  const [model, setModel] = useState<ModelId>("black_litterman");
  const [riskLevel, setRiskLevel] = useState<RiskLevel>(DEFAULT_RISK_LEVEL);
  const [allocation, setAllocation] = useState<PortfolioAllocation | null>(null);

  const live = useLiveComparison();
  // run() clears its resource before the next POST lands, so hold the last
  // outcomes and show them dimmed instead of flashing an empty card. Only
  // valid while the *same* portfolio is in view — another portfolio's moves
  // are not a loading state, they are the wrong answer.
  const lastOutcomes = useRef<OutcomeEnvelope[] | null>(null);
  if (live.resource) lastOutcomes.current = live.resource.outcomes;

  useEffect(() => {
    if (!loading && !me) router.push("/login");
  }, [loading, me, router]);

  useEffect(() => {
    if (!me) return;
    listPortfolios().then((ps) => {
      setPortfolios(ps);
      const pre = params.get("portfolio");
      const chosen =
        (pre && ps.find((p) => p.id === pre)) ||
        ps.find((p) => p.is_default) ||
        ps[0];
      if (chosen) setPortfolioId(chosen.id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  // Auto-run: easy mode lands the user on an answer, not a form. Re-runs when
  // the portfolio or the risk level changes — the risk level is part of the
  // cache key and of how shifts are ranked. Changing model is render-only.
  // Switching portfolio invalidates the held outcomes outright; switching risk
  // level does not, since the same portfolio is simply being re-ranked.
  useEffect(() => {
    lastOutcomes.current = null;
  }, [portfolioId]);

  useEffect(() => {
    if (!portfolioId) return;
    setAllocation(null);
    getPortfolioAllocation(portfolioId)
      .then(setAllocation)
      .catch(() => setAllocation(null));
    live.run({
      allocation: { portfolio_id: portfolioId },
      // Must match /compare's defaults or the two land on different cache
      // entries for the same question (see lib/types.ts).
      horizon_months: DEFAULT_HORIZON_MONTHS,
      n_simulations: DEFAULT_N_SIMULATIONS,
      models: ALL_MODELS,
      risk_level: riskLevel,
      views: [],
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portfolioId, riskLevel]);

  // A failed run shows its error and nothing else: held outcomes are a loading
  // affordance, never a fallback for a request that did not succeed.
  const outcomes = live.error
    ? null
    : live.resource?.outcomes ?? lastOutcomes.current;
  const stale = !live.resource && outcomes !== null;
  const horizonYears = useMemo(
    () => Math.round(DEFAULT_HORIZON_MONTHS / 12),
    [],
  );

  if (loading || !me) return <div className="container">Loading…</div>;

  if (portfolios !== null && portfolios.length === 0) {
    return (
      <div className="container">
        <div className="card stack">
          <h1>Easy mode</h1>
          <p className="muted">
            You need a portfolio first. Upload a broker CSV or enter sector
            weights, and this page will suggest three moves.
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
      <h1>Easy mode</h1>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        Pick a portfolio and a model, and see the three sector shifts that model
        would most like to see — over a {horizonYears}-year horizon, at the risk
        level you choose.
      </p>

      <div className="card">
        <div className="row">
          <div className="field" style={{ flex: "1 1 260px" }}>
            <label htmlFor="easy-portfolio">Portfolio</label>
            <select
              id="easy-portfolio"
              value={portfolioId}
              onChange={(e) => setPortfolioId(e.target.value)}
            >
              {(portfolios ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.is_default ? " (default)" : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="field" style={{ flex: "1 1 200px" }}>
            <label htmlFor="easy-risk">How much risk may a move add?</label>
            <select
              id="easy-risk"
              value={riskLevel}
              onChange={(e) => setRiskLevel(e.target.value as RiskLevel)}
            >
              {RISK_LEVELS.map((r) => (
                <option key={r} value={r}>
                  {RISK_LEVEL_LABEL[r]}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <DisclaimerInline />

      {live.error && <div className="error">{live.error}</div>}

      {allocation && <SleeveNotice allocation={allocation} />}

      {outcomes ? (
        <EasyMoves
          outcomes={outcomes}
          model={model}
          onModelChange={setModel}
          riskLevel={riskLevel}
          stale={stale}
        />
      ) : (
        !live.error && <div className="card muted">Working out your moves…</div>
      )}

      {portfolioId && (
        <p className="muted small">
          Easy mode shows one model at a time.{" "}
          <Link href={`/compare?portfolio=${portfolioId}`}>
            See all three side by side →
          </Link>{" "}
          or read{" "}
          <Link href="/learn/why-models-disagree">why they disagree</Link>.
        </p>
      )}
    </div>
  );
}

/** What the three moves do *not* cover. Funds are decomposed at evaluation
 *  time, so a 60/40 fund contributes its 60 to the sector mix and reports the
 *  rest here rather than quietly inflating the equity weights. */
function SleeveNotice({ allocation }: { allocation: PortfolioAllocation }) {
  const unmodeled = allocation.unmodeled_share;
  if (unmodeled <= 0.005 && allocation.approximations.length === 0) return null;
  return (
    <>
      {unmodeled > 0.005 && (
        <div className="warn-notice">
          {pct(unmodeled)} of this portfolio has no stock-sector exposure to
          model — the bond side of a balanced fund, or metal and commodity
          holdings. Every number below describes the other{" "}
          {pct(1 - unmodeled)}.
        </div>
      )}
      {allocation.approximations.length > 0 && (
        <div className="info-notice">
          <strong>How your funds were read:</strong>
          <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1.1rem" }}>
            {allocation.approximations.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

export default function EasyPage() {
  return (
    <Suspense fallback={<div className="container">Loading…</div>}>
      <EasyInner />
    </Suspense>
  );
}
