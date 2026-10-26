"""positions.sector_source — who chose a position's sector

NULL means the reference table, so existing rows need no backfill. "model" is a
lookup suggestion the user accepted; "user" is a sector picked by hand.

Revision ID: c3f1a2d4e5b6
Revises: b6727271869f
Create Date: 2026-10-25 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3f1a2d4e5b6'
down_revision: Union[str, None] = 'b6727271869f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('positions', sa.Column('sector_source', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('positions', 'sector_source')
