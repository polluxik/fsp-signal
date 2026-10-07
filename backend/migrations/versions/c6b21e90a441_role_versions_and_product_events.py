"""Add immutable role versions and lifecycle metadata.

Revision ID: c6b21e90a441
Revises: 41dbe7c98854
"""
import hashlib
import json
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "c6b21e90a441"
down_revision: Union[str, Sequence[str], None] = "41dbe7c98854"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TERM_FIELDS = (
    "title", "description", "specialization", "grade", "competencies", "stack",
    "salary_min_rub", "salary_max_rub", "work_format",
)


def _legacy_hash(payload: dict) -> str:
    terms = {key: payload[key] for key in TERM_FIELDS if key in payload}
    canonical = json.dumps(terms, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    op.add_column("users", sa.Column("origin", sa.String(length=30), nullable=False,
                                     server_default="legacy_import"))
    if not is_sqlite:
        op.create_check_constraint("user_origin", "users",
                                   "origin IN ('direct_signup','synthetic_fixture','legacy_import')")
    else:
        bind.exec_driver_sql(
            "CREATE TRIGGER users_origin_insert BEFORE INSERT ON users "
            "WHEN NEW.origin NOT IN ('direct_signup','synthetic_fixture','legacy_import') "
            "BEGIN SELECT RAISE(ABORT, 'user_origin_invalid'); END"
        )
        bind.exec_driver_sql(
            "CREATE TRIGGER users_origin_update BEFORE UPDATE OF origin ON users "
            "WHEN NEW.origin NOT IN ('direct_signup','synthetic_fixture','legacy_import') "
            "BEGIN SELECT RAISE(ABORT, 'user_origin_invalid'); END"
        )

    op.add_column("hiring_needs", sa.Column("current_role_version", sa.Integer(), nullable=False,
                                             server_default="0"))
    op.add_column("hiring_needs", sa.Column("publication_state", sa.String(length=20), nullable=False,
                                             server_default="draft"))
    op.add_column("hiring_needs", sa.Column("discoverable", sa.Boolean(), nullable=False,
                                             server_default=sa.false()))
    op.add_column("hiring_needs", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    if not is_sqlite:
        op.create_check_constraint("need_role_version_nonnegative", "hiring_needs", "current_role_version >= 0")
        op.create_check_constraint("need_publication_state", "hiring_needs",
                                   "publication_state IN ('draft','active','paused','closed')")
    else:
        for operation, timing in (("insert", "INSERT"), ("update", "UPDATE")):
            bind.exec_driver_sql(
                f"CREATE TRIGGER hiring_needs_role_state_{operation} BEFORE {timing} ON hiring_needs "
                "WHEN NEW.current_role_version < 0 OR NEW.publication_state NOT IN ('draft','active','paused','closed') "
                "BEGIN SELECT RAISE(ABORT, 'role_state_invalid'); END"
            )

    op.create_table(
        "role_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("need_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("terms_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="role_version_positive"),
        sa.CheckConstraint("source IN ('employer_declared','legacy_import','synthetic_demo')",
                           name="role_version_source"),
        sa.ForeignKeyConstraint(["need_id"], ["hiring_needs.id"], name="fk_role_versions_need_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("need_id", "version", name="role_version_need_version"),
    )
    op.create_index("ix_role_versions_need_id", "role_versions", ["need_id"])
    if is_sqlite:
        bind.exec_driver_sql(
            "CREATE TRIGGER role_versions_no_update BEFORE UPDATE ON role_versions "
            "BEGIN SELECT RAISE(ABORT, 'role_versions_are_immutable'); END"
        )
        bind.exec_driver_sql(
            "CREATE TRIGGER role_versions_no_delete BEFORE DELETE ON role_versions "
            "BEGIN SELECT RAISE(ABORT, 'role_versions_are_immutable'); END"
        )
    else:
        op.execute(
            "CREATE FUNCTION reject_role_version_mutation() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'role_versions_are_immutable'; RETURN OLD; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER role_versions_no_mutation BEFORE UPDATE OR DELETE ON role_versions "
            "FOR EACH ROW EXECUTE FUNCTION reject_role_version_mutation()"
        )

    op.create_table(
        "role_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("need_id", sa.String(length=36), nullable=False),
        sa.Column("role_version_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("preferences_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('saved','hidden','interested','none')", name="role_decision_action"),
        sa.ForeignKeyConstraint(["candidate_id"], ["users.id"], name="fk_role_decisions_candidate_id"),
        sa.ForeignKeyConstraint(["need_id"], ["hiring_needs.id"], name="fk_role_decisions_need_id"),
        sa.ForeignKeyConstraint(["role_version_id"], ["role_versions.id"], name="fk_role_decisions_role_version_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "need_id", name="role_decision_candidate_need"),
    )
    op.create_index("ix_role_decisions_candidate_id", "role_decisions", ["candidate_id"])
    op.create_index("ix_role_decisions_need_id", "role_decisions", ["need_id"])

    op.create_table(
        "product_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("employer_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_mode", sa.String(length=20), nullable=False),
        sa.Column("dedupe_key", sa.String(length=180), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("data_mode IN ('real','synthetic')", name="product_event_data_mode"),
        sa.ForeignKeyConstraint(["employer_id"], ["users.id"], name="fk_product_events_employer_id"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_product_events_actor_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_product_events_dedupe_key"),
    )
    op.create_index("ix_product_events_type", "product_events", ["type"])
    op.create_index("ix_product_events_entity_id", "product_events", ["entity_id"])
    op.create_index("ix_product_events_employer_id", "product_events", ["employer_id"])
    op.create_index("ix_product_events_actor_id", "product_events", ["actor_id"])

    op.add_column("search_snapshots", sa.Column("role_version_id", sa.String(length=36), nullable=True))
    op.add_column("invitations", sa.Column("role_version_id", sa.String(length=36), nullable=True))
    if is_sqlite:
        for table in ("search_snapshots", "invitations"):
            trigger = f"{table}_role_version_fk_insert"
            bind.exec_driver_sql(
                f"CREATE TRIGGER {trigger} BEFORE INSERT ON {table} "
                "WHEN NEW.role_version_id IS NOT NULL AND NOT EXISTS "
                "(SELECT 1 FROM role_versions WHERE id=NEW.role_version_id) "
                "BEGIN SELECT RAISE(ABORT, 'role_version_id foreign key violation'); END"
            )
            trigger = f"{table}_role_version_fk_update"
            bind.exec_driver_sql(
                f"CREATE TRIGGER {trigger} BEFORE UPDATE OF role_version_id ON {table} "
                "WHEN NEW.role_version_id IS NOT NULL AND NOT EXISTS "
                "(SELECT 1 FROM role_versions WHERE id=NEW.role_version_id) "
                "BEGIN SELECT RAISE(ABORT, 'role_version_id foreign key violation'); END"
            )
    else:
        op.create_foreign_key("fk_search_snapshots_role_version_id", "search_snapshots", "role_versions",
                              ["role_version_id"], ["id"])
        op.create_foreign_key("fk_invitations_role_version_id", "invitations", "role_versions",
                              ["role_version_id"], ["id"])

    needs_table = sa.Table("hiring_needs", sa.MetaData(), autoload_with=bind)
    versions_table = sa.Table("role_versions", sa.MetaData(), autoload_with=bind)
    need_rows = bind.execute(sa.select(needs_table)).mappings().all()
    for row in need_rows:
        payload = {
            "title": row["title"], "description": row["description"],
            "specialization": row["specialization"], "grade": row["grade"],
            "competencies": row["competencies"] or [], "stack": row["stack"] or [],
            "salary_min_rub": row["salary_min_rub"], "salary_max_rub": row["salary_max_rub"],
            "work_format": row["work_format"],
        }
        created_at = row["created_at"]
        if created_at is None:
            from datetime import datetime, timezone
            created_at = datetime(1970, 1, 1, tzinfo=timezone.utc)
        bind.execute(versions_table.insert().values(
            id=str(uuid4()), need_id=row["id"], version=1, schema_version=1,
            payload=payload, terms_hash=_legacy_hash(payload), source="legacy_import",
            created_at=created_at,
        ))
        bind.execute(needs_table.update().where(needs_table.c.id == row["id"]).values(
            current_role_version=1, publication_state="draft", discoverable=False, confirmed_at=None,
        ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS users_origin_insert")
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS users_origin_update")
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS hiring_needs_role_state_insert")
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS hiring_needs_role_state_update")
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS role_versions_no_update")
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS role_versions_no_delete")
        for table in ("search_snapshots", "invitations"):
            bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS {table}_role_version_fk_insert")
            bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS {table}_role_version_fk_update")
    else:
        op.execute("DROP TRIGGER role_versions_no_mutation ON role_versions")
        op.execute("DROP FUNCTION reject_role_version_mutation()")
        op.drop_constraint("fk_invitations_role_version_id", "invitations", type_="foreignkey")
        op.drop_constraint("fk_search_snapshots_role_version_id", "search_snapshots", type_="foreignkey")
    op.drop_column("invitations", "role_version_id")
    op.drop_column("search_snapshots", "role_version_id")
    op.drop_index("ix_product_events_actor_id", table_name="product_events")
    op.drop_index("ix_product_events_employer_id", table_name="product_events")
    op.drop_index("ix_product_events_entity_id", table_name="product_events")
    op.drop_index("ix_product_events_type", table_name="product_events")
    op.drop_table("product_events")
    op.drop_index("ix_role_decisions_need_id", table_name="role_decisions")
    op.drop_index("ix_role_decisions_candidate_id", table_name="role_decisions")
    op.drop_table("role_decisions")
    op.drop_index("ix_role_versions_need_id", table_name="role_versions")
    op.drop_table("role_versions")
    if bind.dialect.name != "sqlite":
        op.drop_constraint("need_publication_state", "hiring_needs", type_="check")
        op.drop_constraint("need_role_version_nonnegative", "hiring_needs", type_="check")
        op.drop_constraint("user_origin", "users", type_="check")
    op.drop_column("hiring_needs", "confirmed_at")
    op.drop_column("hiring_needs", "discoverable")
    op.drop_column("hiring_needs", "publication_state")
    op.drop_column("hiring_needs", "current_role_version")
    op.drop_column("users", "origin")
