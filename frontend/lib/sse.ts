// Progressive delivery over SSE. EventSource cannot set custom headers, but it
// sends cookies with withCredentials — which is exactly why the backend uses
// cookie auth (user_model_spec §1.2).
import { API_BASE } from "./api";
import type { ComparisonStatus, OutcomeEnvelope } from "./types";

export interface SseHandlers {
  onOutcome?: (env: OutcomeEnvelope) => void;
  onProgress?: (modelId: string, pct: number) => void;
  onComparison?: (status: ComparisonStatus) => void;
}

export function subscribeComparison(
  id: string,
  handlers: SseHandlers,
): () => void {
  const es = new EventSource(`${API_BASE}/v1/comparisons/${id}/events`, {
    withCredentials: true,
  });

  es.addEventListener("outcome", (e) => {
    handlers.onOutcome?.(JSON.parse((e as MessageEvent).data));
  });
  es.addEventListener("progress", (e) => {
    const d = JSON.parse((e as MessageEvent).data);
    handlers.onProgress?.(d.model_id, d.pct);
  });
  es.addEventListener("comparison", (e) => {
    const d = JSON.parse((e as MessageEvent).data);
    handlers.onComparison?.(d.status);
    es.close();
  });
  es.onerror = () => es.close();

  return () => es.close();
}
