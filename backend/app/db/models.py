"""
SQL schema (user_model_spec §2.2). Portable types so the same models run on
Postgres (container/Railway) and SQLite (tests). Postgres-specific niceties
(JSONB, TIMESTAMPTZ) degrade to JSON / timezone-aware DateTime elsewhere.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """fastapi-users base (id, email, hashed_password, is_active, is_superuser,
    is_verified) + consent + created_at. Registration requires affirmative
    consent, recorded here (PRD FR-7 / user_model_spec §1.1)."""

    __tablename__ = "users"

    consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    positions: Mapped[list[Position]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('csv','manual')", name="portfolios_source_check"
        ),
        UniqueConstraint("user_id", "name", name="portfolios_user_name_uq"),
        # At most one default portfolio per user (partial unique index).
        Index(
            "one_default_portfolio",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )


class Position(Base):
    __tablename__ = "positions"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    sector: Mapped[str] = mapped_column(Text, nullable=False)

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="positions_quantity_positive"),
    )


class Comparison(Base):
    """Durable comparison state (also the deterministic cache's source of
    truth). 90-day retention via expires_at + a daily purge task (M5)."""

    __tablename__ = "comparisons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True
    )
    snapshot_id: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    cache_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("comparisons_by_user", "user_id", "created_at"),
        Index("comparisons_by_cache", "cache_key"),
        Index("comparisons_by_expiry", "expires_at"),
    )


class ProgressPoint(Base):
    """Per-portfolio value + risk trajectory (M5). Tracked for EVERY portfolio,
    appended on snapshot rotation; no cost-basis / P&L."""

    __tablename__ = "progress_points"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    total_value: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
