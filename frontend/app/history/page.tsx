"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { listComparisons, listPortfolios } from "@/lib/api";
import type { ComparisonSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { MODEL_LABEL, type ModelId, type Portfolio } from "@/lib/types";

export default function HistoryPage() {
  const { me, loading } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<ComparisonSummary[]>([]);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);

  useEffect(() => {
    if (!loading && !me) router.push("/login");
  }, [loading, me, router]);

  useEffect(() => {
    if (!me) return;
    listComparisons().then(setItems);
    listPortfolios().then(setPortfolios);
  }, [me]);

  if (loading || !me) return <div className="container">Loading…</div>;

  const pfName = (id: string | null) =>
    id ? (portfolios.find((p) => p.id === id)?.name ?? "—") : "—";

  return (
    <div className="container stack">
      <h1>History</h1>
      <p className="muted">
        Your comparisons from the last 90 days. Each is reproducible from its
        pinned snapshot; older ones are purged automatically.
      </p>
      <div className="card">
        {items.length === 0 ? (
          <p className="muted">
            No comparisons yet. <Link href="/compare">Run one →</Link>
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Portfolio</th>
                <th>Models</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td className="muted">
                    {new Date(c.created_at).toLocaleString()}
                  </td>
                  <td>{pfName(c.portfolio_id)}</td>
                  <td className="muted small">
                    {c.models
                      .map((m) => MODEL_LABEL[m as ModelId] ?? m)
                      .join(", ")}
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        c.status === "complete"
                          ? "complete"
                          : c.status === "failed"
                            ? "failed"
                            : "default"
                      }`}
                    >
                      {c.status}
                    </span>
                  </td>
                  <td>
                    <Link href={`/comparison/${c.id}`} className="btn small">
                      Reopen
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
