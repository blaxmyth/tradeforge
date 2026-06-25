"""add continuous aggregates for 5min, 15min, 1hr, 1day

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-08
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TIMEFRAMES = [
    # (name, bucket_size, start_offset, end_offset, schedule_interval)
    # start_offset - end_offset must span >= 2 buckets
    ("5min",  "5 minutes",  "1 hour",  "1 minute",  "5 minutes"),
    ("15min", "15 minutes", "2 hours", "1 minute",  "15 minutes"),
    ("1hr",   "1 hour",     "1 day",   "5 minutes", "1 hour"),
    ("1day",  "1 day",      "3 days",  "2 hours",   "1 day"),
]


def upgrade() -> None:
    for name, bucket, start_offset, end_offset, schedule in _TIMEFRAMES:
        view = f"asset_price_{name}"

        op.execute(f"""
            CREATE MATERIALIZED VIEW {view}
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('{bucket}', datetime) AS bucket,
                asset_id,
                first(open, datetime)  AS open,
                max(high)              AS high,
                min(low)               AS low,
                last(close, datetime)  AS close,
                sum(volume)            AS volume
            FROM asset_price
            GROUP BY 1, 2
            WITH NO DATA;
        """)

        op.execute(f"""
            SELECT add_continuous_aggregate_policy('{view}',
                start_offset      => INTERVAL '{start_offset}',
                end_offset        => INTERVAL '{end_offset}',
                schedule_interval => INTERVAL '{schedule}');
        """)


def downgrade() -> None:
    for name, *_ in reversed(_TIMEFRAMES):
        view = f"asset_price_{name}"
        op.execute(f"SELECT remove_continuous_aggregate_policy('{view}');")
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE;")
