"""create hypertables for asset_price and indicator

Revision ID: 0003
Revises: ed7cf509f6e1
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "ed7cf509f6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "SELECT create_hypertable('asset_price', 'datetime', if_not_exists => TRUE, migrate_data => TRUE);"
    )
    op.execute(
        "SELECT create_hypertable('indicator', 'datetime', if_not_exists => TRUE, migrate_data => TRUE);"
    )


def downgrade() -> None:
    # TimescaleDB has no direct way to convert a hypertable back to a plain table
    # without dropping and recreating it. Downgrade is intentionally a no-op.
    pass
