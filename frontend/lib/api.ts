// Thin fetch wrapper: cookie credentials + CSRF header on mutations.
import type {
  ComparisonResource,
  CompareRequest,
  DataSnapshot,
  IngestReport,
  Me,
  ModelId,
  Portfolio,
  SectorLookupResponse,
  SectorOverride,
  SectorWeight,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

interface Opts {
  method?: string;
  json?: unknown;
  body?: BodyInit;
  headers?: Record<string, string>;
}

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers || {}) };
  const method = opts.method || "GET";
  if (method !== "GET") headers["X-Requested-With"] = "XMLHttpRequest";
  let body = opts.body;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
    credentials: "include",
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}

// --- auth ---
export const register = (email: string, password: string, consent: boolean) =>
  api<Me>("/auth/register", { method: "POST", json: { email, password, consent } });

export const login = async (email: string, password: string) => {
  const form = new URLSearchParams({ username: email, password });
  await api<void>("/auth/login", {
    method: "POST",
    body: form,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
};

export const logout = () => api<void>("/auth/logout", { method: "POST" });
export const me = () => api<Me>("/users/me");
export const verify = (token: string) =>
  api<Me>("/auth/verify", { method: "POST", json: { token } });

export const requestVerify = (email: string) =>
  api<void>("/auth/request-verify", { method: "POST", json: { email } });

// Dev-only: fetch the current user's verification token (404 in production).
export const devVerificationToken = () =>
  api<{ verified: boolean; token: string | null }>(
    "/auth/dev/verification-token",
  );

// --- snapshots ---
export const currentSnapshot = () =>
  api<DataSnapshot>("/v1/snapshots/current");

// --- portfolios ---
export const listPortfolios = () => api<Portfolio[]>("/v1/portfolios");
export const getPortfolio = (id: string) =>
  api<Portfolio>(`/v1/portfolios/${id}`);
export const deletePortfolio = (id: string) =>
  api<void>(`/v1/portfolios/${id}`, { method: "DELETE" });

// The portfolio's sector mix under the active snapshot, plus what it leaves
// out: funds are decomposed at evaluation time, so a 60/40 fund reports a
// 0.4 unmodeled_share rather than quietly inflating the equity weights.
export interface PortfolioAllocation {
  portfolio_id: string;
  snapshot_id: string;
  sector_weights: SectorWeight[];
  unmodeled_share: number;
  approximations: string[];
}
export const getPortfolioAllocation = (id: string) =>
  api<PortfolioAllocation>(`/v1/portfolios/${id}/allocation`);

// Re-previewing the same file with the sectors the user has confirmed keeps
// weights and coverage server-computed; the client never does weight math.
export const previewCsv = (
  file: File,
  overrides: Record<string, SectorOverride> = {},
) => {
  const form = new FormData();
  form.append("file", file);
  if (Object.keys(overrides).length > 0) {
    form.append("sector_overrides", JSON.stringify(overrides));
  }
  return api<IngestReport>("/v1/portfolios/preview", {
    method: "POST",
    body: form,
  });
};

export const createPortfolioFromCsv = (
  name: string,
  accepted: {
    ticker: string;
    quantity: number;
    sector?: string;
    sector_source?: "model" | "user";
  }[],
  is_default = false,
) =>
  api<Portfolio>("/v1/portfolios", {
    method: "POST",
    json: { name, accepted, is_default },
  });

// Optional sector lookup. Sends ticker symbols only, on an explicit click.
export const sectorLookupAvailable = () =>
  api<{ available: boolean; max_tickers: number }>(
    "/v1/portfolios/sector-lookup",
  );
export const lookupSectors = (tickers: string[]) =>
  api<SectorLookupResponse>("/v1/portfolios/sector-lookup", {
    method: "POST",
    json: { tickers },
  });

export const createPortfolioManual = (
  name: string,
  sector_weights: { sector: string; weight: number }[],
  is_default = false,
) =>
  api<Portfolio>("/v1/portfolios", {
    method: "POST",
    json: { name, sector_weights, is_default },
  });

// --- comparisons ---
export const createComparison = (req: CompareRequest) =>
  api<ComparisonResource>("/v1/comparisons", { method: "POST", json: req });

export const getComparison = (id: string) =>
  api<ComparisonResource>(`/v1/comparisons/${id}`);

// Optional plain-language wording for a model's suggested shifts. The backend
// decides nothing about *which* moves exist — it only rewrites the sentence.
// `source: "template"` with an empty `moves` means "render your own copy"
// (lib/moves.ts), which is also exactly what a flag-off backend returns, so
// there is no failure case for a caller to handle.
export interface NarratedMove {
  from_sector: string;
  to_sector: string;
  text: string;
}
export interface NarrationResponse {
  model_id: ModelId;
  source: "claude" | "template";
  moves: NarratedMove[];
  prompt_version: string | null;
}
export const getNarration = (comparisonId: string, model_id: ModelId) =>
  api<NarrationResponse>(`/v1/comparisons/${comparisonId}/narration`, {
    method: "POST",
    json: { model_id },
  });

export interface ComparisonSummary {
  id: string;
  status: string;
  created_at: string;
  portfolio_id: string | null;
  snapshot_id: string;
  models: string[];
}
export const listComparisons = () =>
  api<ComparisonSummary[]>("/v1/comparisons");

export interface ProgressSeries {
  portfolio_id: string;
  points: {
    as_of: string;
    total_value: number;
    expected_return: number | null;
    volatility: number | null;
  }[];
}
export const getProgress = () => api<ProgressSeries[]>("/v1/progress");
