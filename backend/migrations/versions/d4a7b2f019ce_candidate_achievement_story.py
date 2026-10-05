"""Store candidate-owned structured achievement narratives.

Revision ID: d4a7b2f019ce
Revises: 89ea0f2d6c3b
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a7b2f019ce"
down_revision: Union[str, Sequence[str], None] = "89ea0f2d6c3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("candidate_profiles", sa.Column(
        "achievement_story", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
    ))


def downgrade() -> None:
    with op.batch_alter_table("candidate_profiles") as batch:
        batch.drop_column("achievement_story")
