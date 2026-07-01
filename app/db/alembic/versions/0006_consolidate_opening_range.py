"""consolidate opening_range_breakout/breakdown into opening_range

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Insert the unified strategy (idempotent)
    conn.execute(sa.text(
        "INSERT INTO strategy (name) "
        "SELECT 'opening_range' WHERE NOT EXISTS "
        "(SELECT 1 FROM strategy WHERE name = 'opening_range')"
    ))

    new_id = conn.execute(
        sa.text("SELECT id FROM strategy WHERE name = 'opening_range'")
    ).scalar()

    # 2. Migrate asset_strategy rows from old strategies to the new one.
    #    Each asset_id may appear in breakout AND breakdown — deduplicate by
    #    migrating only assets not already assigned to opening_range.
    conn.execute(sa.text("""
        UPDATE asset_strategy
        SET strategy_id = :new_id
        WHERE strategy_id IN (
            SELECT id FROM strategy
            WHERE name IN ('opening_range_breakout', 'opening_range_breakdown')
        )
        AND asset_id NOT IN (
            SELECT asset_id FROM asset_strategy WHERE strategy_id = :new_id
        )
    """), {"new_id": new_id})

    # 3. Drop any leftover duplicates that couldn't be migrated
    conn.execute(sa.text("""
        DELETE FROM asset_strategy
        WHERE strategy_id IN (
            SELECT id FROM strategy
            WHERE name IN ('opening_range_breakout', 'opening_range_breakdown')
        )
    """))

    # 4. Remove the old strategy rows
    conn.execute(sa.text(
        "DELETE FROM strategy "
        "WHERE name IN ('opening_range_breakout', 'opening_range_breakdown')"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    for name in ('opening_range_breakout', 'opening_range_breakdown'):
        conn.execute(sa.text(
            f"INSERT INTO strategy (name) SELECT '{name}' WHERE NOT EXISTS "
            f"(SELECT 1 FROM strategy WHERE name = '{name}')"
        ))
    # Note: asset_strategy rows are not restored on downgrade — re-run populate_strats
