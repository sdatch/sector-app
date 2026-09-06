"""
Application configuration — env-driven so local docker-compose and Railway
share one codebase (only environment variables differ). Railway injects
DATABASE_URL and PORT automatically; everything else has a local default.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Environment ---
    environment: str = "development"  # development | production

    # --- Data / snapshots ---
    # Directory holding memory-mapped snapshot artifacts (mounted volume both
    # locally and on Railway).
    artifacts_dir: Path = Path("./data/artifacts")
    market_data_provider: str = "synthetic"  # synthetic | yfinance | tiingo | ...
    active_snapshot_id: str = "synthetic-2024-12-31"

    # --- Compute budget (endpoint spec §3) ---
    sync_budget_ms: int = 500
    compute_cap_s: int = 30
    mc_provisional_paths: int = 1_000
    mc_chunk_paths: int = 2_000
    # ProcessPoolExecutor keeps numpy off the event loop (endpoint spec §9).
    # Off by default in dev (avoids Windows spawn issues under --reload); the
    # default thread executor suffices since numpy releases the GIL.
    use_process_pool: bool = False

    # --- Auth / persistence (M3) ---
    database_url: str = (
        "postgresql+asyncpg://sector:sector@localhost:5432/sector"
    )
    # Bootstrap tables on startup (dev convenience). Alembic owns schema
    # evolution; set false in prod once migrations are the source of truth.
    auto_create_tables: bool = True
    jwt_secret: str = "dev-insecure-change-me"
    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 7 * 24 * 3600
    cookie_secure: bool = False  # True in production (HTTPS)
    cookie_samesite: str = "lax"

    # --- CORS ---
    frontend_origin: str = "http://localhost:3000"

    # --- Rate limiting (endpoint spec §8) ---
    comparisons_per_minute: int = 10

    # --- Daily maintenance (progress + purge) ---
    maintenance_interval_s: int = 24 * 3600
    run_maintenance_on_startup: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
