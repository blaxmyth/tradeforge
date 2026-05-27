"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("asset_class", sa.String(), nullable=True),
        sa.Column("is_etf", sa.Boolean(), nullable=True),
        sa.Column("is_sp500", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "strategy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "asset_price",
        sa.Column("datetime", sa.DateTime(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("datetime", "asset_id"),
    )
    op.create_index("ix_asset_id", "asset_price", ["asset_id", "datetime"])
    op.create_table(
        "indicator",
        sa.Column("datetime", sa.DateTime(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("rsi", sa.Integer(), nullable=True),
        sa.Column("macd", sa.Integer(), nullable=True),
        sa.Column("macdh", sa.Integer(), nullable=True),
        sa.Column("macds", sa.Integer(), nullable=True),
        sa.Column("adx", sa.Integer(), nullable=True),
        sa.Column("adx_dmp", sa.Integer(), nullable=True),
        sa.Column("adx_dmn", sa.Integer(), nullable=True),
        sa.Column("sma_200", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("datetime", "asset_id"),
    )
    op.create_table(
        "asset_strategy",
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy.id"]),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id"),
    )
    op.create_table(
        "etf_holding",
        sa.Column("etf_id", sa.Integer(), nullable=False),
        sa.Column("holding_id", sa.Integer(), nullable=False),
        sa.Column("dt", sa.Date(), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["etf_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["holding_id"], ["asset.id"]),
        sa.PrimaryKeyConstraint("etf_id", "holding_id", "dt"),
    )


def downgrade() -> None:
    op.drop_table("etf_holding")
    op.drop_table("watchlist")
    op.drop_table("asset_strategy")
    op.drop_table("indicator")
    op.drop_index("ix_asset_id", table_name="asset_price")
    op.drop_table("asset_price")
    op.drop_table("user")
    op.drop_table("strategy")
    op.drop_table("asset")
