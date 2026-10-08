"""Store the isolated, unassessed synthetic market corpus."""
from alembic import op
import sqlalchemy as sa

revision = "c918e47a25bf"
down_revision = "b26c19d745ef"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("synthetic_market_records",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("dataset_version", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("family_id", sa.String(64), nullable=False),
        sa.Column("level", sa.String(16), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("kind IN ('family','profile','vacancy')", name="market_record_kind"),
        sa.CheckConstraint("level IS NULL OR level IN ('junior','middle','senior','lead')", name="market_record_level"))
    op.create_index("ix_market_dataset_kind_family", "synthetic_market_records", ["dataset_version", "kind", "family_id"])


def downgrade():
    op.drop_table("synthetic_market_records")
