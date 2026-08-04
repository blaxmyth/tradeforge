"""add alpaca_order_id to signal_log

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("signal_log", sa.Column("alpaca_order_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("signal_log", "alpaca_order_id")
