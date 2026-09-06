"""
Comparison API contract — normalized outcome schema across risk models.

Design principles:
  1. Every model MUST populate CommonMetrics and OutcomeDistribution, even if
     it derives them differently (parametric vs empirical). The derivation is
     declared, never hidden (see EstimationMethod).
  2. All models run against the same DataSnapshot and the same RequestScope
     (horizon, confidence, allocation), so differences in outcomes reflect
     model assumptions — not data drift.
  3. Sector attribution is a first-class common block, since the app's advice
     surface is sector-oriented.
  4. Model-specific detail lives in a discriminated union — typed, but new
     models can be added without touching the common core.

Pydantic v2. Target: FastAPI POST /v1/compare
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "1.0"


# --------------------------------------------------------------------------
# Enums / vocabulary
# --------------------------------------------------------------------------

class ModelId(str, Enum):
    FAMA_FRENCH = "fama_french"
    BLACK_LITTERMAN = "black_litterman"
    MONTE_CARLO = "monte_carlo"


class EstimationMethod(str, Enum):
    """How the common metrics were derived. Surfaced in the UI so users
    understand a parametric VaR and a simulated VaR are not identical
    quantities, even at the same confidence level."""
    PARAMETRIC_NORMAL = "parametric_normal"       # mean/cov -> closed form
    PARAMETRIC_FACTOR = "parametric_factor"       # factor cov + residual
    EMPIRICAL_SIMULATED = "empirical_simulated"   # Monte Carlo paths


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------

class SectorWeight(BaseModel):
    sector: str = Field(description="GICS sector name or FF industry label")
    weight: float = Field(ge=0.0, le=1.0)


class Allocation(BaseModel):
    """The candidate allocation being evaluated. Sector-level is the primary
    mode for the advice app; ticker-level supported for power users."""
    sector_weights: list[SectorWeight] | None = None
    ticker_weights: dict[str, float] | None = None

    @model_validator(mode="after")
    def exactly_one_mode(self) -> "Allocation":
        if bool(self.sector_weights) == bool(self.ticker_weights):
            raise ValueError("Provide sector_weights XOR ticker_weights")
        weights = (
            [w.weight for w in self.sector_weights]
            if self.sector_weights
            else list(self.ticker_weights.values())
        )
        if abs(sum(weights) - 1.0) > 1e-6:
            raise ValueError("Weights must sum to 1.0")
        return self


class InvestorView(BaseModel):
    """Black-Litterman view. Ignored by other models (echoed in assumptions
    so the comparison UI can show which models consumed it)."""
    sector: str
    expected_annual_return: float
    confidence: float = Field(gt=0.0, le=1.0)


class CompareRequest(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    allocation: Allocation
    horizon_months: int = Field(ge=1, le=480)
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1.0)
    initial_value: float = Field(default=100_000.0, gt=0)
    models: list[ModelId] = Field(min_length=1)
    views: list[InvestorView] = Field(default_factory=list)
    n_simulations: int | None = Field(
        default=10_000, description="Monte Carlo only; ignored elsewhere"
    )


# --------------------------------------------------------------------------
# Common outcome blocks (every model must fill these)
# --------------------------------------------------------------------------

class CommonMetrics(BaseModel):
    """Annualized unless suffixed otherwise. The comparison table renders
    exactly these fields, one column per model."""
    expected_return: float
    volatility: float
    sharpe_ratio: float
    var_horizon: float = Field(
        description="Loss (positive number, currency units) not exceeded at "
                    "confidence_level over the full horizon"
    )
    cvar_horizon: float = Field(
        description="Expected loss beyond VaR (currency units)"
    )
    prob_loss: float = Field(
        ge=0, le=1, description="P(terminal value < initial_value)"
    )


class OutcomeDistribution(BaseModel):
    """Terminal portfolio value at horizon. Parametric models fill this from
    the implied lognormal; Monte Carlo from empirical quantiles."""
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


class SectorAttribution(BaseModel):
    sector: str
    weight: float
    return_contribution: float = Field(
        description="Contribution to expected_return (annualized, additive)"
    )
    risk_contribution: float = Field(
        description="Component contribution to volatility (additive across "
                    "sectors, Euler decomposition)"
    )


class Diagnostics(BaseModel):
    estimation_method: EstimationMethod
    data_coverage_pct: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    fit_r2: float | None = Field(
        default=None, description="Fama-French only: regression R^2"
    )
    convergence_std_error: float | None = Field(
        default=None, description="Monte Carlo only: SE of mean estimate"
    )


# --------------------------------------------------------------------------
# Model-specific payloads (discriminated union)
# --------------------------------------------------------------------------

class FamaFrenchDetail(BaseModel):
    model_id: Literal[ModelId.FAMA_FRENCH] = ModelId.FAMA_FRENCH
    factor_loadings: dict[str, float] = Field(
        description="e.g. {'MKT': 1.02, 'SMB': -0.15, 'HML': 0.30, ...}"
    )
    factor_premia_annual: dict[str, float]
    residual_volatility: float


class BlackLittermanDetail(BaseModel):
    model_id: Literal[ModelId.BLACK_LITTERMAN] = ModelId.BLACK_LITTERMAN
    equilibrium_returns: dict[str, float]
    posterior_returns: dict[str, float]
    views_applied: list[InvestorView]
    optimal_weights: dict[str, float] = Field(
        description="Model-suggested weights — shown next to the user's "
                    "allocation as the 'advice delta'"
    )


class MonteCarloDetail(BaseModel):
    model_id: Literal[ModelId.MONTE_CARLO] = ModelId.MONTE_CARLO
    n_simulations: int
    return_model: str = Field(description="e.g. 'gbm', 'bootstrap_block'")
    max_drawdown_p50: float
    prob_double: float = Field(
        description="P(terminal >= 2x initial) — upside framing for advice UI"
    )


ModelDetail = Annotated[
    Union[FamaFrenchDetail, BlackLittermanDetail, MonteCarloDetail],
    Field(discriminator="model_id"),
]


# --------------------------------------------------------------------------
# Normalized outcome + response envelope
# --------------------------------------------------------------------------

class ModelOutcome(BaseModel):
    model_id: ModelId
    model_version: str
    metrics: CommonMetrics
    distribution: OutcomeDistribution
    sector_attribution: list[SectorAttribution]
    diagnostics: Diagnostics
    detail: ModelDetail


class DataSnapshot(BaseModel):
    """Pin the inputs so all models are comparable and results reproducible."""
    snapshot_id: str
    prices_start: date
    prices_end: date
    risk_free_rate_annual: float = Field(description="From FRED, as-of end")
    factor_data_vintage: date | None = None


class CompareResponse(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    request_id: str
    generated_at: datetime
    request: CompareRequest = Field(description="Echo for reproducibility")
    snapshot: DataSnapshot
    outcomes: list[ModelOutcome]
    normalization_notes: list[str] = Field(
        default_factory=list,
        description="Human-readable caveats, e.g. 'FF VaR is parametric; "
                    "MC VaR is empirical — tail estimates differ by design'",
    )
