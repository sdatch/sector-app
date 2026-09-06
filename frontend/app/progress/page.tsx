"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getProgress, listPortfolios } from "@/lib/api";
import type { ProgressSeries } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Portfolio } from "@/lib/types";
import { money, pct } from "@/lib/format";

const PALETTE = [
  "#4557d6",
  "#0f9488",
  "#c77d20",
  "#a3459b",
  "#2f8f4e",
  "#c8442f",
];

export default function ProgressPage() {
  const { me, loading } = useAuth();
  const router = useRouter();
  const [series, setSeries] = useState<ProgressSeries[]>([]);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!loading && !me) router.push("/login");
  }, [loading, me, router]);

  useEffect(() => {
    if (!me) return;
    getProgress().then(setSeries);
    listPortfolios().then(setPortfolios);
  }, [me]);

  const name = (id: string) =>
    portfolios.find((p) => p.id === id)?.name ?? id.slice(0, 8);

  const visible = series.filter((s) => !hidden.has(s.portfolio_id));

  if (loading || !me) return <div className="container">Loading…</div>;

  return (
    <div className="container stack">
      <h1>Progress</h1>
      <p className="muted">
        Every portfolio&apos;s value and risk trajectory, tracked automatically.
        Progress is value + risk over time — not profit-and-loss accounting.
      </p>

      {series.length === 0 ? (
        <div className="card">
          <p className="muted">
            No trajectory yet. <Link href="/portfolios">Add a portfolio →</Link>
          </p>
        </div>
      ) : (
        <>
          <div className="card">
            <h2>Portfolio value over time</h2>
            <TrajectoryChart series={visible} names={name} />
            <div className="row" style={{ marginTop: "0.8rem" }}>
              {series.map((s, i) => (
                <label
                  key={s.portfolio_id}
                  className="checkbox-row small"
                  style={{ cursor: "pointer" }}
                >
                  <input
                    type="checkbox"
                    checked={!hidden.has(s.portfolio_id)}
                    onChange={() =>
                      setHidden((h) => {
                        const n = new Set(h);
                        n.has(s.portfolio_id)
                          ? n.delete(s.portfolio_id)
                          : n.add(s.portfolio_id);
                        return n;
                      })
                    }
                  />
                  <span
                    style={{
                      display: "inline-block",
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      background: PALETTE[i % PALETTE.length],
                    }}
                  />
                  {name(s.portfolio_id)}
                </label>
              ))}
            </div>
          </div>

          <div className="card">
            <h2>Latest snapshot</h2>
            <table>
              <thead>
                <tr>
                  <th>Portfolio</th>
                  <th className="num">Value</th>
                  <th className="num">Exp. return</th>
                  <th className="num">Volatility</th>
                </tr>
              </thead>
              <tbody>
                {series.map((s) => {
                  const last = s.points[s.points.length - 1];
                  return (
                    <tr key={s.portfolio_id}>
                      <td>{name(s.portfolio_id)}</td>
                      <td className="num">{money(last.total_value)}</td>
                      <td className="num">
                        {last.expected_return != null
                          ? pct(last.expected_return)
                          : "—"}
                      </td>
                      <td className="num">
                        {last.volatility != null ? pct(last.volatility) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function TrajectoryChart({
  series,
  names,
}: {
  series: ProgressSeries[];
  names: (id: string) => string;
}) {
  const W = 820;
  const H = 300;
  const PAD = { l: 64, r: 16, t: 12, b: 28 };

  const { paths, yTicks, xLabels } = useMemo(() => {
    const all = series.flatMap((s) => s.points);
    if (all.length === 0)
      return { paths: [], yTicks: [] as number[], xLabels: [] as string[] };
    const values = all.map((p) => p.total_value);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const span = hi - lo || 1;
    const dates = Array.from(new Set(all.map((p) => p.as_of))).sort();
    const dmin = dates[0];
    const dmax = dates[dates.length - 1];
    const t0 = new Date(dmin).getTime();
    const t1 = new Date(dmax).getTime();
    const tspan = t1 - t0 || 1;

    const x = (d: string) =>
      PAD.l + ((new Date(d).getTime() - t0) / tspan) * (W - PAD.l - PAD.r);
    const y = (v: number) =>
      PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);

    const paths = series.map((s, i) => ({
      id: s.portfolio_id,
      color: PALETTE[i % PALETTE.length],
      d: s.points
        .map((p, j) => `${j === 0 ? "M" : "L"}${x(p.as_of)},${y(p.total_value)}`)
        .join(" "),
    }));
    const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => lo + f * span);
    const xLabels = [dmin, dmax];
    return { paths, yTicks, xLabels };
  }, [series]);

  if (paths.length === 0)
    return <p className="muted small">No data to plot.</p>;

  const y = (v: number) => {
    const all = series.flatMap((s) => s.points).map((p) => p.total_value);
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const span = hi - lo || 1;
    return PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);
  };

  return (
    <div className="scroll-x">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", minWidth: 560, height: "auto" }}
      >
        {yTicks.map((v, i) => (
          <g key={i}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={y(v)}
              y2={y(v)}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <text
              x={PAD.l - 8}
              y={y(v) + 4}
              textAnchor="end"
              fontSize={11}
              fill="var(--text-muted)"
            >
              {money(v)}
            </text>
          </g>
        ))}
        {xLabels.map((d, i) => (
          <text
            key={i}
            x={i === 0 ? PAD.l : W - PAD.r}
            y={H - 8}
            textAnchor={i === 0 ? "start" : "end"}
            fontSize={11}
            fill="var(--text-muted)"
          >
            {new Date(d).toLocaleDateString()}
          </text>
        ))}
        {paths.map((p) => (
          <path
            key={p.id}
            d={p.d}
            fill="none"
            stroke={p.color}
            strokeWidth={2}
            strokeLinejoin="round"
          />
        ))}
      </svg>
    </div>
  );
}
