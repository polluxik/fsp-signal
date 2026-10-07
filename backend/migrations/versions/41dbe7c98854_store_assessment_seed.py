"""store assessment seed

Revision ID: 41dbe7c98854
Revises: 2ef663c4542b
Create Date: 2026-10-05 11:04:55.745450

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41dbe7c98854'
down_revision: Union[str, Sequence[str], None] = '2ef663c4542b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assessment_attempts', sa.Column('seed', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('assessment_attempts', 'seed')
