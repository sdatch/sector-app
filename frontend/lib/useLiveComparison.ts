"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, createComparison } from "./api";
import { subscribeComparison } from "./sse";
import type { CompareRequest, ComparisonResource } from "./types";

export function useLiveComparison() {
  const [resource, setResource] = useState<ComparisonResource | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const unsub = useRef<(() => void) | null>(null);

  const run = useCallback(async (req: CompareRequest) => {
    unsub.current?.();
    setError("");
    setResource(null);
    setRunning(true);
    try {
      const res = await createComparison(req);
      setResource(res);
      if (res.status === "running") {
        // Refine in place over SSE (MC provisional -> complete).
        unsub.current = subscribeComparison(res.id, {
          onOutcome: (env) =>
            setResource((prev) =>
              prev
                ? {
                    ...prev,
                    outcomes: prev.outcomes.map((o) =>
                      o.model_id === env.model_id ? env : o,
                    ),
                  }
                : prev,
            ),
          onProgress: (mid, pct) =>
            setResource((prev) =>
              prev
                ? {
                    ...prev,
                    outcomes: prev.outcomes.map((o) =>
                      o.model_id === mid ? { ...o, progress_pct: pct } : o,
                    ),
                  }
                : prev,
            ),
          onComparison: (status) => {
            setResource((prev) => (prev ? { ...prev, status } : prev));
            setRunning(false);
          },
        });
      } else {
        setRunning(false);
      }
    } catch (err) {
      setRunning(false);
      if (err instanceof ApiError && err.status === 403) {
        setError("Verify your email before running a comparison.");
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Rate limit reached — wait a moment and try again.");
      } else if (err instanceof ApiError) {
        setError(String(err.detail));
      } else {
        setError("Comparison failed.");
      }
    }
  }, []);

  useEffect(() => () => unsub.current?.(), []);

  return { resource, error, running, run };
}
