"""Track bilateral confirmation that an interview was held.

Revision ID: 5d7a9b2c4f11
Revises: e8a1c4d57b20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5d7a9b2c4f11"
down_revision: Union[str, Sequence[str], None] = "e8a1c4d57b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column("candidate_interview_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column("employer_interview_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("invitations") as batch:
        batch.drop_column("employer_interview_confirmed_at")
        batch.drop_column("candidate_interview_confirmed_at")
