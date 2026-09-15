"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  createPortfolioFromCsv,
  createPortfolioManual,
  deletePortfolio,
  listPortfolios,
  previewCsv,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type {
  IngestAccepted,
  IngestRejected,
  IngestReport,
  Portfolio,
} from "@/lib/types";
import { BENIGN_REASONS, REJECT_REASON, SECTORS } from "@/lib/types";
import { money, pct } from "@/lib/format";

/** Rows shown before the "more" link kicks in. */
const PREVIEW_ROWS = 15;

export default function PortfoliosPage() {
  const { me, loading } = useAuth();
  const router = useRouter();
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [tab, setTab] = useState<"csv" | "manual">("csv");

  const reload = useCallback(async () => {
    setPortfolios(await listPortfolios());
  }, []);

  useEffect(() => {
    if (!loading && !me) router.push("/login");
  }, [loading, me, router]);

  useEffect(() => {
    if (me) reload();
  }, [me, reload]);

  if (loading || !me) return <div className="container">Loading…</div>;

  return (
    <div className="container stack">
      <h1>Portfolios</h1>
      <p className="muted">
        Hold several named portfolios (IRA, brokerage, hypothetical) and compare
        them side by side. Positions store quantity — weights are derived from
        snapshot prices, so your sector mix drifts with the market.
      </p>

      <div className="card">
        <h2>Your portfolios</h2>
        {portfolios.length === 0 ? (
          <p className="muted">None yet. Add one below.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Source</th>
                <th className="num">Positions</th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {portfolios.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.name}{" "}
                    {p.is_default && <span className="badge default">default</span>}
                  </td>
                  <td className="muted">{p.source}</td>
                  <td className="num">{p.positions.length}</td>
                  <td>
                    <button
                      className="btn small"
                      onClick={() => router.push(`/compare?portfolio=${p.id}`)}
                    >
                      Compare
                    </button>
                  </td>
                  <td>
                    <button
                      className="btn small danger"
                      onClick={async () => {
                        await deletePortfolio(p.id);
                        reload();
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: "1rem" }}>
          <button
            className={`btn ${tab === "csv" ? "primary" : ""}`}
            onClick={() => setTab("csv")}
          >
            Upload CSV
          </button>
          <button
            className={`btn ${tab === "manual" ? "primary" : ""}`}
            onClick={() => setTab("manual")}
          >
            Enter sector weights
          </button>
        </div>
        {tab === "csv" ? (
          <CsvUpload onCreated={reload} />
        ) : (
          <ManualCreate onCreated={reload} />
        )}
      </div>
    </div>
  );
}

function CsvUpload({ onCreated }: { onCreated: () => void }) {
  const [report, setReport] = useState<IngestReport | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError("");
    setReport(null);
    try {
      setReport(await previewCsv(file));
    } catch (err) {
      setError(
        err instanceof ApiError ? String(err.detail) : "Could not read that file.",
      );
    }
  }

  async function commit() {
    if (!report || !name) return;
    setBusy(true);
    setError("");
    try {
      await createPortfolioFromCsv(
        name,
        report.accepted.map((a) => ({ ticker: a.ticker, quantity: a.quantity })),
      );
      setReport(null);
      setName("");
      onCreated();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "You already have a portfolio with that name."
          : "Could not save the portfolio.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <p className="muted small">
        Broker exports welcome — headers like Symbol/Shares are mapped
        automatically. Your raw file is parsed in memory and never stored; only
        ticker, quantity, and sector are kept.
      </p>
      <input type="file" accept=".csv,text/csv,text/plain" onChange={onFile} />
      {error && <div className="error">{error}</div>}

      {report && (
        <>
          <IngestSummary report={report} />
          <FilePreviewTable report={report} />
          {report.warnings.map((w, i) => (
            <div key={i} className="muted small">
              · {w}
            </div>
          ))}

          <div className="row">
            <div className="field">
              <label>Portfolio name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Brokerage"
              />
            </div>
            <div style={{ alignSelf: "flex-end", marginBottom: "0.75rem" }}>
              <button
                className="btn primary"
                disabled={busy || !name || report.accepted.length === 0}
                onClick={commit}
              >
                {busy ? "Saving…" : "Save portfolio"}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Headline result of the preview. Dropped holdings used to be buried in a
 * collapsed <details>, which made a mostly-rejected file look like a
 * three-position portfolio. If anything real was lost, say so up front.
 */
function IngestSummary({ report }: { report: IngestReport }) {
  const lost = report.rejected.filter((r) => !BENIGN_REASONS.has(r.reason));
  const unknown = lost.filter((r) => r.reason === "unknown_ticker").length;
  const noEquity = lost.filter(
    (r) => r.reason === "no_equity_exposure",
  ).length;
  const funds = report.accepted.filter((a) => a.is_fund);
  const unmodeled = report.totals.unmodeled_share;
  const approximations = [
    ...new Set(funds.map((f) => f.note).filter(Boolean)),
  ] as string[];

  return (
    <>
      <div className="notice">
        Understood <strong>{report.totals.positions}</strong>{" "}
        {report.totals.positions === 1 ? "position" : "positions"} worth{" "}
        <strong>{money(report.totals.value)}</strong> · coverage{" "}
        {pct(report.totals.coverage_pct, 0)}
      </div>

      {funds.length > 0 && (
        <div className="info-notice">
          <strong>
            {funds.length} {funds.length === 1 ? "fund was" : "funds were"}{" "}
            broken down into the sectors they hold.
          </strong>
          <p>
            A fund is not a sector, so each one is spread across the eleven GICS
            sectors in its published proportions rather than being forced into a
            single bucket. Expand a fund row below to see its breakdown.
          </p>
          {approximations.length > 0 && (
            <ul>
              {approximations.map((a) => (
                <li key={a}>{a}.</li>
              ))}
            </ul>
          )}
          <p className="muted small">
            Breakdowns are typical published allocations for each fund type, not
            live holdings — treat them as approximately right, not exact.
          </p>
        </div>
      )}

      {unmodeled > 0.005 && (
        <div className="warn-notice">
          <strong>
            {pct(unmodeled, 0)} of this portfolio has no equity sector exposure.
          </strong>
          <p>
            That is the fixed-income side of your balanced or target-date funds,
            plus any bond funds or commodity trusts. Sector weights are computed
            over the equity sleeve only, so the comparison describes{" "}
            <strong>{pct(1 - unmodeled, 0)}</strong> of your money. Expect the
            risk numbers to read differently from how your account actually
            behaves — those holdings diversify in ways the models never see.
          </p>
        </div>
      )}

      {lost.length > 0 && (
        <div className="warn-notice">
          <strong>
            {lost.length} {lost.length === 1 ? "holding was" : "holdings were"}{" "}
            left out of this portfolio.
          </strong>
          <p>
            Only the rows marked <em>Included</em> below will be saved and
            modeled. Sector weights are derived from those rows alone.
          </p>
          <ul>
            {noEquity > 0 && (
              <li>
                <strong>{noEquity}</strong>{" "}
                {noEquity === 1 ? "holding" : "holdings"} with no equity sector
                exposure — bond funds and commodity trusts such as GLD. They
                hold debt or metal, not shares in companies, so there is
                nothing for a sector model to attribute.
              </li>
            )}
            {unknown > 0 && (
              <li>
                <strong>{unknown}</strong>{" "}
                {unknown === 1 ? "ticker is" : "tickers are"} outside the
                snapshot&rsquo;s ticker universe, so no sector or price is
                available for {unknown === 1 ? "it" : "them"}.
              </li>
            )}
          </ul>
        </div>
      )}
    </>
  );
}

type PreviewRow = {
  row: number;
  ticker: string;
  accepted?: IngestAccepted;
  rejected?: IngestRejected;
};

/**
 * The uploaded file played back in its own row order — included and excluded
 * holdings interleaved — capped at PREVIEW_ROWS with a "more" toggle.
 * Showing only the accepted rows hid the reason a big file rendered small.
 */
function FilePreviewTable({ report }: { report: IngestReport }) {
  const [showAll, setShowAll] = useState(false);

  // One entry per file row. A row can appear in both lists (a normalized
  // ticker is accepted *and* reported); the accepted record wins and the
  // rejection becomes a note on it.
  const byRow = new Map<number, PreviewRow>();
  for (const a of report.accepted) {
    byRow.set(a.row, { row: a.row, ticker: a.ticker, accepted: a });
  }
  for (const r of report.rejected) {
    const existing = byRow.get(r.row);
    if (existing?.accepted) continue;
    byRow.set(r.row, {
      row: r.row,
      ticker: r.raw.split(",")[0]?.trim() || "—",
      rejected: r,
    });
  }
  const rows = [...byRow.values()].sort((a, b) => a.row - b.row);
  const visible = showAll ? rows : rows.slice(0, PREVIEW_ROWS);
  const hidden = rows.length - visible.length;

  if (rows.length === 0) return null;

  return (
    <div className="stack">
      <h3 className="preview-title">
        What we read from your file{" "}
        <span className="muted small">
          ({rows.length} {rows.length === 1 ? "row" : "rows"})
        </span>
      </h3>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th className="num">Line</th>
              <th>Ticker</th>
              <th>Status</th>
              <th>Sector</th>
              <th className="num">Qty</th>
              <th className="num">Price</th>
              <th className="num">Value</th>
              <th className="num">Weight</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <PreviewTableRow key={r.row} entry={r} />
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > PREVIEW_ROWS && (
        <button
          className="btn small"
          onClick={() => setShowAll((s) => !s)}
          style={{ alignSelf: "flex-start" }}
        >
          {showAll
            ? `Show fewer — first ${PREVIEW_ROWS} of ${rows.length}`
            : `Show ${hidden} more ${hidden === 1 ? "row" : "rows"} (${rows.length} total)`}
        </button>
      )}
    </div>
  );
}

function PreviewTableRow({ entry }: { entry: PreviewRow }) {
  const { accepted: a, rejected: r } = entry;
  const [open, setOpen] = useState(false);

  if (a) {
    const breakdown = a.sector_breakdown
      ? Object.entries(a.sector_breakdown).sort((x, y) => y[1] - x[1])
      : [];
    return (
      <>
        <tr>
          <td className="num muted">{entry.row}</td>
          <td>
            <strong>{a.ticker}</strong>
            {a.note && !a.is_fund && (
              <div className="muted small">{a.note}</div>
            )}
          </td>
          <td>
            <span className="badge complete">Included</span>
          </td>
          <td className="muted">
            {a.is_fund ? (
              <button className="link-btn" onClick={() => setOpen((o) => !o)}>
                {open ? "▾" : "▸"} {a.fund_name ?? "Fund"} ·{" "}
                {breakdown.length} sectors
                {a.equity_share < 1 && (
                  <> · {pct(a.equity_share, 0)} equity</>
                )}
              </button>
            ) : (
              a.sector
            )}
          </td>
          <td className="num">{a.quantity}</td>
          <td className="num">{money(a.last_price)}</td>
          <td className="num">{money(a.value)}</td>
          <td className="num">{pct(a.weight)}</td>
        </tr>
        {a.is_fund && open && (
          <tr className="row-breakdown">
            <td />
            <td colSpan={7}>
              <div className="breakdown">
                {breakdown.map(([sector, share]) => (
                  <div className="breakdown-row" key={sector}>
                    <span className="breakdown-label">{sector}</span>
                    <span className="bar-track breakdown-bar">
                      <span
                        className="bar-fill"
                        style={{
                          width: `${share * 100}%`,
                          background: "var(--primary)",
                        }}
                      />
                    </span>
                    <span className="num breakdown-pct">{pct(share, 1)}</span>
                  </div>
                ))}
                {a.equity_share < 1 && (
                  <div className="muted small" style={{ marginTop: "0.4rem" }}>
                    Percentages are of the equity sleeve —{" "}
                    {pct(1 - a.equity_share, 0)} of this holding is fixed income
                    and is not modeled.
                  </div>
                )}
                {a.note && (
                  <div className="muted small" style={{ marginTop: "0.4rem" }}>
                    {a.note}.
                  </div>
                )}
              </div>
            </td>
          </tr>
        )}
      </>
    );
  }

  const benign = r ? BENIGN_REASONS.has(r.reason) : false;
  return (
    <tr className={benign ? "row-skipped" : "row-excluded"}>
      <td className="num muted">{entry.row}</td>
      <td className="muted">{entry.ticker}</td>
      <td>
        <span className={`badge ${benign ? "provisional" : "failed"}`}>
          {benign ? "Skipped" : "Excluded"}
        </span>
      </td>
      <td className="muted small" colSpan={5}>
        {r ? REJECT_REASON[r.reason] ?? r.reason : ""}
        {r?.resolution ? ` — ${r.resolution}` : ""}
      </td>
    </tr>
  );
}

function ManualCreate({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const total = Object.values(weights).reduce((a, b) => a + (b || 0), 0);

  function setWeight(sector: string, value: number) {
    setWeights((w) => ({ ...w, [sector]: value }));
  }

  async function submit() {
    setError("");
    const entries = Object.entries(weights).filter(([, v]) => v > 0);
    if (Math.abs(total - 1) > 0.001) {
      setError(`Weights must sum to 100% (currently ${pct(total, 0)}).`);
      return;
    }
    setBusy(true);
    try {
      await createPortfolioManual(
        name,
        entries.map(([sector, weight]) => ({ sector, weight })),
      );
      setName("");
      setWeights({});
      onCreated();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "You already have a portfolio with that name."
          : "Could not save the portfolio.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <p className="muted small">
        Enter target sector weights — useful as a hypothetical laboratory. They
        must sum to 100%.
      </p>
      <div className="field" style={{ maxWidth: 320 }}>
        <label>Portfolio name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Hypothetical"
        />
      </div>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Sector</th>
              <th className="num" style={{ width: 140 }}>
                Weight %
              </th>
            </tr>
          </thead>
          <tbody>
            {SECTORS.map((s) => (
              <tr key={s}>
                <td>{s}</td>
                <td className="num">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={
                      weights[s] !== undefined ? Math.round(weights[s] * 100) : ""
                    }
                    onChange={(e) =>
                      setWeight(s, (parseFloat(e.target.value) || 0) / 100)
                    }
                    style={{ textAlign: "right" }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>
                <strong>Total</strong>
              </td>
              <td
                className="num"
                style={{
                  color:
                    Math.abs(total - 1) < 0.001 ? "var(--gain)" : "var(--loss)",
                }}
              >
                {pct(total, 0)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      {error && <div className="error">{error}</div>}
      <button
        className="btn primary"
        disabled={busy || !name}
        onClick={submit}
        style={{ alignSelf: "flex-start" }}
      >
        {busy ? "Saving…" : "Save portfolio"}
      </button>
    </div>
  );
}
