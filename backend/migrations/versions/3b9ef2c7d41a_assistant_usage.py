"""Add privacy-minimal AI assistant request accounting.

Revision ID: 3b9ef2c7d41a
Revises: 5d7a9b2c4f11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3b9ef2c7d41a"
down_revision: Union[str, Sequence[str], None] = "5d7a9b2c4f11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_usage",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "intent IN ('candidate_preferences','candidate_achievement','employer_role')",
            name="assistant_usage_intent",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_usage_user_created", "assistant_usage", ["user_id", "created_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_usage_user_created", table_name="assistant_usage")
    op.drop_table("assistant_usage")
