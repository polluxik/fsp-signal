"""Versioned candidate preferences and explicit adult/hard-constraint state.

Revision ID: 89ea0f2d6c3b
Revises: c6b21e90a441
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "89ea0f2d6c3b"
down_revision: Union[str, Sequence[str], None] = "c6b21e90a441"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    op.add_column("candidate_profiles", sa.Column(
        "preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
    ))
    op.add_column("candidate_profiles", sa.Column("preferences_version", sa.Integer(), nullable=False,
                                                   server_default="1"))
    op.add_column("candidate_profiles", sa.Column("preferences_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("candidate_profiles", sa.Column("adult_attested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("candidate_profiles", sa.Column(
        "blocked_employer_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
    ))
    with op.batch_alter_table("candidate_profiles") as batch:
        batch.add_column(sa.Column(
            "verified_attempt_id", sa.String(length=36),
            sa.ForeignKey("assessment_attempts.id", name="fk_candidate_profiles_verified_attempt_id"), nullable=True,
        ))
    if is_sqlite:
        bind.exec_driver_sql(
            "CREATE TRIGGER candidate_preferences_version_insert BEFORE INSERT ON candidate_profiles "
            "WHEN NEW.preferences_version < 1 BEGIN SELECT RAISE(ABORT, 'preferences_version_invalid'); END"
        )
        bind.exec_driver_sql(
            "CREATE TRIGGER candidate_preferences_version_update BEFORE UPDATE OF preferences_version "
            "ON candidate_profiles WHEN NEW.preferences_version < 1 "
            "BEGIN SELECT RAISE(ABORT, 'preferences_version_invalid'); END"
        )
    else:
        op.create_check_constraint("candidate_preferences_version", "candidate_profiles",
                                   "preferences_version >= 1")

    profiles = sa.Table("candidate_profiles", sa.MetaData(), autoload_with=bind)
    attempts = sa.Table("assessment_attempts", sa.MetaData(), autoload_with=bind)
    for profile in bind.execute(sa.select(profiles)).mappings().all():
        old_format = profile["work_format"]
        allowed_formats = (["remote", "hybrid", "office"] if old_format == "any"
                           else [old_format] if old_format in ("remote", "hybrid", "office") else [])
        preferences = {
            "salary_min_rub": profile["min_salary_rub"] or None,
            "allowed_work_formats": allowed_formats,
            "allowed_cities": [],
            "excluded_industries": [],
            "preferred_stack": [],
            "preferred_tasks": [],
            "max_take_home_minutes": None,
            "available": bool(profile["available"]),
        }
        verified_attempt_id = None
        if profile["verification_source"] == "assessment" and profile["test_score"] is not None:
            candidate_attempts = bind.execute(sa.select(attempts).where(
                attempts.c.candidate_id == profile["user_id"],
                attempts.c.specialization == profile["verified_specialization"],
                attempts.c.grade == profile["verified_grade"],
                attempts.c.state == "scored", attempts.c.outcome == "passed",
                attempts.c.score == profile["test_score"],
            )).mappings().all()
            if len(candidate_attempts) == 1:
                verified_attempt_id = candidate_attempts[0]["id"]
        bind.execute(profiles.update().where(profiles.c.user_id == profile["user_id"]).values(
            preferences=preferences, preferences_version=1, blocked_employer_ids=[],
            verified_attempt_id=verified_attempt_id,
        ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS candidate_preferences_version_insert")
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS candidate_preferences_version_update")
    else:
        op.drop_constraint("candidate_preferences_version", "candidate_profiles", type_="check")
    with op.batch_alter_table("candidate_profiles") as batch:
        batch.drop_constraint("fk_candidate_profiles_verified_attempt_id", type_="foreignkey")
        batch.drop_column("verified_attempt_id")
        batch.drop_column("blocked_employer_ids")
        batch.drop_column("adult_attested_at")
        batch.drop_column("preferences_confirmed_at")
        batch.drop_column("preferences_version")
        batch.drop_column("preferences")
