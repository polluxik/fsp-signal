"""Employer-private, version-pinned shortlist with CAS state."""
from alembic import op
import sqlalchemy as sa

revision = "b26c19d745ef"
down_revision = "f7c2a1d93e10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("employer_shortlist",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("need_id", sa.String(36), sa.ForeignKey("hiring_needs.id"), nullable=False),
        sa.Column("role_version_id", sa.String(36), sa.ForeignKey("role_versions.id"), nullable=False),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("saved", sa.Boolean(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("employer_id", "role_version_id", "candidate_id", name="uq_shortlist_employer_role_candidate"),
        sa.CheckConstraint("state_version >= 1", name="shortlist_state_version"))


def downgrade():
    op.drop_table("employer_shortlist")
