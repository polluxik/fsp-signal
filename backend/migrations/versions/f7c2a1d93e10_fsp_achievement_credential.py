"""Store a structured, provenance-aware FSP achievement credential.

Revision ID: f7c2a1d93e10
Revises: a40e8c9f621b
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7c2a1d93e10"
down_revision: Union[str, Sequence[str], None] = "a40e8c9f621b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("candidate_profiles", sa.Column(
        "fsp_achievement", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
    ))


def downgrade() -> None:
    with op.batch_alter_table("candidate_profiles") as batch:
        batch.drop_column("fsp_achievement")
