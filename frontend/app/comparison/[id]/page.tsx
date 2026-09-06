"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { getComparison } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ComparisonResource } from "@/lib/types";
import ComparisonView from "@/components/ComparisonView";

export default function ComparisonDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { me, loading } = useAuth();
  const router = useRouter();
  const [resource, setResource] = useState<ComparisonResource | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !me) router.push("/login");
  }, [loading, me, router]);

  useEffect(() => {
    if (!me) return;
    getComparison(id)
      .then(setResource)
      .catch(() => setError("Comparison not found or expired."));
  }, [me, id]);

  if (loading || !me) return <div className="container">Loading…</div>;

  return (
    <div className="container stack">
      <div>
        <Link href="/history" className="muted small">
          ← Back to history
        </Link>
      </div>
      <h1>Comparison</h1>
      {error && <div className="error">{error}</div>}
      {resource && <ComparisonView resource={resource} />}
    </div>
  );
}
