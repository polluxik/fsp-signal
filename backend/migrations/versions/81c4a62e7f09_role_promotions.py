"""Add isolated demo role-promotion campaigns.

Revision ID: 81c4a62e7f09
Revises: 3b9ef2c7d41a
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "81c4a62e7f09"
down_revision: Union[str, Sequence[str], None] = "3b9ef2c7d41a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promotion_campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("need_id", sa.String(length=36), nullable=False),
        sa.Column("employer_id", sa.String(length=36), nullable=False),
        sa.Column("role_version_id", sa.String(length=36), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("demo_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("active_until > active_from", name="promotion_campaign_positive_duration"),
        sa.CheckConstraint("demo_only IS TRUE", name="promotion_campaign_demo_only"),
        sa.ForeignKeyConstraint(["employer_id"], ["users.id"], name="fk_promotion_campaign_employer_id"),
        sa.ForeignKeyConstraint(["need_id"], ["hiring_needs.id"], name="fk_promotion_campaign_need_id"),
        sa.ForeignKeyConstraint(["role_version_id"], ["role_versions.id"],
                                name="fk_promotion_campaign_role_version_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotion_campaigns_need_id", "promotion_campaigns", ["need_id"])
    op.create_index("ix_promotion_campaigns_employer_id", "promotion_campaigns", ["employer_id"])
    op.create_index("ix_promotion_campaigns_role_version_id", "promotion_campaigns", ["role_version_id"])


def downgrade() -> None:
    op.drop_index("ix_promotion_campaigns_role_version_id", table_name="promotion_campaigns")
    op.drop_index("ix_promotion_campaigns_employer_id", table_name="promotion_campaigns")
    op.drop_index("ix_promotion_campaigns_need_id", table_name="promotion_campaigns")
    op.drop_table("promotion_campaigns")
