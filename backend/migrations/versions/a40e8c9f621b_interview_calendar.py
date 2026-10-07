"""HR availability, bookings and participant-owned meeting materials."""
from alembic import op
import sqlalchemy as sa

revision = "a40e8c9f621b"
down_revision = "81c4a62e7f09"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("candidate_profiles", sa.Column("recommendation_consent", sa.Boolean(),
                                                 nullable=False, server_default=sa.false()))
    with op.batch_alter_table("assistant_usage") as batch:
        batch.drop_constraint("assistant_usage_intent", type_="check")
        batch.create_check_constraint("assistant_usage_intent",
            "intent IN ('candidate_preferences','candidate_achievement','employer_role','meeting_summary','meeting_transcription')")
    op.create_table("interview_calendars",
        sa.Column("employer_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("public_token", sa.String(64), nullable=False, unique=True),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("call_url", sa.String(500), nullable=False))
    op.create_table("availability_slots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="slot_positive_duration"))
    op.create_index("ix_availability_slots_employer_id", "availability_slots", ["employer_id"])
    op.create_index("ix_availability_slots_starts_at", "availability_slots", ["starts_at"])
    op.create_table("interview_meetings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slot_id", sa.String(36), sa.ForeignKey("availability_slots.id"), nullable=False),
        sa.Column("invitation_id", sa.String(36), sa.ForeignKey("invitations.id"), nullable=False),
        sa.Column("employer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("call_url", sa.String(500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("candidate_recording_consent", sa.Boolean(), nullable=False),
        sa.Column("employer_recording_consent", sa.Boolean(), nullable=False),
        sa.Column("recording_data", sa.LargeBinary(), nullable=True),
        sa.Column("recording_type", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('scheduled','cancelled')", name="meeting_state"),
        sa.CheckConstraint("version >= 1", name="meeting_version"))
    for field in ("slot_id", "invitation_id", "employer_id", "candidate_id"):
        op.create_index(f"ix_interview_meetings_{field}", "interview_meetings", [field])
    op.create_index("uq_meeting_active_slot", "interview_meetings", ["slot_id"], unique=True,
                    sqlite_where=sa.text("state = 'scheduled'"), postgresql_where=sa.text("state = 'scheduled'"))


def downgrade():
    op.drop_table("interview_meetings")
    op.drop_table("availability_slots")
    op.drop_table("interview_calendars")
    op.drop_column("candidate_profiles", "recommendation_consent")
    op.execute("DELETE FROM assistant_usage WHERE intent IN ('meeting_summary','meeting_transcription')")
    with op.batch_alter_table("assistant_usage") as batch:
        batch.drop_constraint("assistant_usage_intent", type_="check")
        batch.create_check_constraint("assistant_usage_intent",
            "intent IN ('candidate_preferences','candidate_achievement','employer_role')")
