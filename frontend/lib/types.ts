// Wire types mirroring backend app/contracts/comparison.py (v1.1).

export type ModelId = "fama_french" | "black_litterman" | "monte_carlo";
export type OutcomeStatus =
  | "pending"
  | "running"
  | "provisional"
  | "complete"
  | "failed";
export type ComparisonStatus = "running" | "complete" | "partial" | "failed";
export type RiskLevel = "conservative" | "moderate" | "aggressive";

export const RISK_LEVEL_LABEL: Record<RiskLevel, string> = {
  conservative: "Conservative",
  moderate: "Moderate",
  aggressive: "Aggressive",
};

// Mirrors backend engines/common/shifts.py — every level requires a Sharpe gain.
export const RISK_LEVEL_HINT: Record<RiskLevel, string> = {
  conservative: "Shifts that lower volatility, biggest cut first.",
  moderate: "Volatility no higher than today, best Sharpe gain first.",
  aggressive: "Volatility up to 10% higher, biggest return gain first.",
};

export const MODEL_LABEL: Record<ModelId, string> = {
  fama_french: "Fama-French 5-Factor",
  black_litterman: "Black-Litterman",
  monte_carlo: "Monte Carlo",
};

// Per-model accent, consumed as the `--accent` custom property by .model-col,
// .learn-card and friends in globals.css.
export const ACCENT: Record<ModelId, string> = {
  fama_french: "var(--ff)",
  black_litterman: "var(--bl)",
  monte_carlo: "var(--mc)",
};

export const ALL_MODELS: ModelId[] = [
  "fama_french",
  "black_litterman",
  "monte_carlo",
];

// Shared request defaults. /easy and /compare must agree on these or they land
// on different cache entries for the same question: the key is
// sha256(snapshot_id + canonical_json(request)) over the *fully defaulted*
// model (backend orchestration/cache.py), so an omitted field still counts.
export const DEFAULT_HORIZON_MONTHS = 120;
export const DEFAULT_N_SIMULATIONS = 10000;
export const DEFAULT_RISK_LEVEL: RiskLevel = "moderate";

// GICS 11 — the snapshot universe (matches backend synthetic provider).
export const SECTORS: string[] = [
  "Information Technology",
  "Health Care",
  "Financials",
  "Consumer Discretionary",
  "Communication Services",
  "Industrials",
  "Consumer Staples",
  "Energy",
  "Utilities",
  "Real Estate",
  "Materials",
];

export interface SectorWeight {
  sector: string;
  weight: number;
}

export interface InvestorView {
  sector: string;
  expected_annual_return: number;
  confidence: number;
}

export interface CommonMetrics {
  expected_return: number;
  volatility: number;
  sharpe_ratio: number;
  var_horizon: number;
  cvar_horizon: number;
  prob_loss: number;
}

export interface OutcomeDistribution {
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

export interface SectorAttribution {
  sector: string;
  weight: number;
  return_contribution: number;
  risk_contribution: number;
}

export interface Diagnostics {
  estimation_method: string;
  data_coverage_pct: number;
  warnings: string[];
  fit_r2: number | null;
  convergence_std_error: number | null;
}

export interface ModelOutcome {
  model_id: ModelId;
  model_version: string;
  metrics: CommonMetrics;
  distribution: OutcomeDistribution;
  sector_attribution: SectorAttribution[];
  diagnostics: Diagnostics;
  detail: any;
  suggested_shifts?: SectorShift[] | null;
}

export interface SectorShift {
  from_sector: string;
  to_sector: string;
  fraction: number;
  metrics_before: CommonMetrics;
  metrics_after: CommonMetrics;
  estimation_method: string;
  warnings: string[];
}

export interface OutcomeError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface OutcomeEnvelope {
  model_id: ModelId;
  status: OutcomeStatus;
  progress_pct: number | null;
  outcome: ModelOutcome | null;
  error: OutcomeError | null;
}

export interface DataSnapshot {
  snapshot_id: string;
  prices_start: string;
  prices_end: string;
  risk_free_rate_annual: number;
  factor_data_vintage: string | null;
}

export interface CompareRequest {
  allocation: {
    portfolio_id?: string | null;
    sector_weights?: SectorWeight[] | null;
    ticker_weights?: Record<string, number> | null;
  };
  horizon_months: number;
  confidence_level?: number;
  initial_value?: number;
  models: ModelId[];
  views?: InvestorView[];
  n_simulations?: number;
  risk_level?: RiskLevel;
}

export interface ComparisonResource {
  schema_version: string;
  id: string;
  status: ComparisonStatus;
  generated_at: string;
  request: CompareRequest;
  snapshot: DataSnapshot;
  outcomes: OutcomeEnvelope[];
  normalization_notes: string[];
}

export interface Position {
  ticker: string;
  quantity: number;
  sector: string;
}

export interface Portfolio {
  id: string;
  name: string;
  source: "csv" | "manual";
  is_default: boolean;
  created_at: string;
  positions: Position[];
}

/** Sentinel stored in place of a sector for a pooled vehicle. */
export const FUND_SECTOR = "(fund)";

export interface IngestAccepted {
  ticker: string;
  quantity: number;
  sector: string;
  last_price: number;
  value: number;
  weight: number;
  row: number;
  note: string | null;
  is_fund: boolean;
  fund_name: string | null;
  /** Fraction of the holding that maps to a modelable equity sector. */
  equity_share: number;
  /** sector -> share of this fund's equity sleeve. */
  sector_breakdown: Record<string, number> | null;
}

export interface IngestRejected {
  row: number;
  raw: string;
  reason: string;
  resolution: string | null;
}

export interface IngestReport {
  accepted: IngestAccepted[];
  rejected: IngestRejected[];
  warnings: string[];
  totals: {
    value: number;
    positions: number;
    coverage_pct: number;
    /** Share of accepted value with no modelable sector exposure. */
    unmodeled_share: number;
  };
}

/** Plain-language labels for IngestRejected.reason (backend ingest.py). */
export const REJECT_REASON: Record<string, string> = {
  unknown_ticker: "Not in the modelable universe",
  no_equity_exposure: "No equity sector exposure to model",
  summary_line: "Summary line — not a position",
  missing_quantity: "No quantity given",
  invalid_number: "Quantity could not be read",
  non_positive: "Quantity is zero or negative",
  malformed_row: "Row could not be parsed",
  ticker_normalized: "Ticker normalized",
};

/** Reasons that are informational rather than a lost holding. */
export const BENIGN_REASONS = new Set(["summary_line", "ticker_normalized"]);

export interface Me {
  id: string;
  email: string;
  is_verified: boolean;
  consented_at: string;
}

export const DISCLAIMER_SHORT =
  "Educational tool — not financial advice. Model outputs are estimates; three models are shown because reasonable models disagree.";

// PRD §13. The generated-text sentence is part of the consent copy because the
// narration layer can be switched on by an operator, and NFR-3 is a promise to
// the user — so what may be sent, and what never is, is stated up front rather
// than only at the point it happens.
export const DISCLAIMER_FULL = `Educational tool — not financial advice. Sector Insight is provided for education and research. Nothing in this application constitutes investment, legal, or tax advice, or a recommendation to buy, sell, or hold any security. Model outputs are estimates derived from historical data and simplifying assumptions that may not hold in the future; three models are shown precisely because reasonable models disagree. Past performance does not guarantee future results. Some explanatory wording may be generated by an AI language model from figures the risk models computed; where it is, this is labelled, and producing it sends only sector weights and those figures to the AI provider — never your holdings, their quantities, or your account value. You are solely responsible for your investment decisions. Consider consulting a licensed financial professional before acting on any information shown here.`;
