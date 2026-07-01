"""add signal_log table

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_log",
        sa.Column("id",              sa.Integer(),  nullable=False, primary_key=True),
        sa.Column("strategy_name",   sa.String(),   nullable=False),
        sa.Column("symbol",          sa.String(),   nullable=False),
        sa.Column("direction",       sa.String(),   nullable=False),
        sa.Column("entry_price",     sa.Float(),    nullable=True),
        sa.Column("or_high",         sa.Float(),    nullable=True),
        sa.Column("or_low",          sa.Float(),    nullable=True),
        sa.Column("entry_time",      sa.String(),   nullable=True),
        sa.Column("fired_at",        sa.DateTime(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(),     nullable=True),
    )
    op.create_index("ix_signal_log_fired_at", "signal_log", ["fired_at"])
    op.create_index("ix_signal_log_symbol",   "signal_log", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_signal_log_symbol",   table_name="signal_log")
    op.drop_index("ix_signal_log_fired_at", table_name="signal_log")
    op.drop_table("signal_log")
