// Thin fetch wrapper: cookie credentials + CSRF header on mutations.
import type {
  ComparisonResource,
  CompareRequest,
  DataSnapshot,
  IngestReport,
  Me,
  Portfolio,
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

export const previewCsv = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api<IngestReport>("/v1/portfolios/preview", {
    method: "POST",
    body: form,
  });
};

export const createPortfolioFromCsv = (
  name: string,
  accepted: { ticker: string; quantity: number }[],
  is_default = false,
) =>
  api<Portfolio>("/v1/portfolios", {
    method: "POST",
    json: { name, accepted, is_default },
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
