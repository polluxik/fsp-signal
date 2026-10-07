"""Pin invitation terms/evidence and enforce one active invitation per pair.

Revision ID: e8a1c4d57b20
Revises: d4a7b2f019ce
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a1c4d57b20"
down_revision: Union[str, Sequence[str], None] = "d4a7b2f019ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTIVE_STATES = ("sent", "viewed")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _diagnose_legacy_rows(bind: sa.Connection) -> None:
    invalid = bind.execute(sa.text(
        "SELECT id, state FROM invitations WHERE state NOT IN "
        "('sent','viewed','accepted','rejected','withdrawn','expired') LIMIT 10"
    )).all()
    if invalid:
        raise RuntimeError(f"Cannot migrate invitations with unknown states: {invalid!r}")

    accepted_without_grant = bind.execute(sa.text(
        "SELECT i.id FROM invitations i LEFT JOIN contact_grants g ON g.invitation_id=i.id "
        "WHERE i.state='accepted' AND g.id IS NULL LIMIT 10"
    )).all()
    if accepted_without_grant:
        raise RuntimeError(
            "Cannot migrate accepted invitations without a contact grant; "
            f"manual reconciliation required: {accepted_without_grant!r}"
        )

    active_grant_without_accept = bind.execute(sa.text(
        "SELECT g.id, i.state FROM contact_grants g JOIN invitations i ON i.id=g.invitation_id "
        "WHERE g.revoked_at IS NULL AND i.state!='accepted' LIMIT 10"
    )).all()
    if active_grant_without_accept:
        raise RuntimeError(
            "Cannot migrate active contact grants for non-accepted invitations; "
            f"manual reconciliation required: {active_grant_without_accept!r}"
        )


def _expire_legacy_pending(bind: sa.Connection) -> None:
    invitations = sa.table(
        "invitations",
        sa.column("id", sa.String()), sa.column("state", sa.String()),
        sa.column("expires_at", sa.DateTime(timezone=True)),
    )
    current = datetime.now(timezone.utc)
    due = bind.execute(sa.select(invitations.c.id, invitations.c.expires_at).where(
        invitations.c.state.in_(ACTIVE_STATES)
    )).all()
    expired_ids = [invitation_id for invitation_id, expires_at in due
                   if _utc(expires_at) <= current]
    if expired_ids:
        bind.execute(sa.text(
            "UPDATE invitations SET state='expired', decided_at=:at, state_version=2 "
            "WHERE id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True)), {"at": current, "ids": expired_ids})


def _diagnose_active_duplicates(bind: sa.Connection) -> None:
    duplicates = bind.execute(sa.text(
        "SELECT employer_id, candidate_id, COUNT(*) AS active_count "
        "FROM invitations WHERE state IN ('sent','viewed') "
        "GROUP BY employer_id, candidate_id HAVING COUNT(*) > 1 LIMIT 10"
    )).all()
    if duplicates:
        raise RuntimeError(
            "Cannot create active invitation uniqueness index; resolve live duplicate pairs "
            f"without deleting records: {duplicates!r}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    op.add_column("invitations", sa.Column("terms_snapshot", sa.JSON(), nullable=True))
    op.add_column("invitations", sa.Column("terms_hash", sa.String(length=64), nullable=True))
    op.add_column("invitations", sa.Column("evidence_refs", sa.JSON(), nullable=True))
    op.add_column("invitations", sa.Column("explanation_snapshot", sa.JSON(), nullable=True))
    op.add_column("invitations", sa.Column("compatibility_snapshot", sa.JSON(), nullable=True))
    op.add_column("invitations", sa.Column(
        "state_version", sa.Integer(), nullable=False, server_default=sa.text("1")
    ))
    op.add_column("invitations", sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=True))

    _diagnose_legacy_rows(bind)
    _expire_legacy_pending(bind)
    _diagnose_active_duplicates(bind)

    if is_sqlite:
        for operation, timing in (("insert", "INSERT"), ("update", "UPDATE")):
            bind.exec_driver_sql(
                f"CREATE TRIGGER invitations_state_constraints_{operation} "
                f"BEFORE {timing} ON invitations WHEN "
                "NEW.state NOT IN ('sent','viewed','accepted','rejected','withdrawn','expired') "
                "OR NEW.state_version < 1 "
                "BEGIN SELECT RAISE(ABORT, 'invitation_state_invalid'); END"
            )
    else:
        op.create_check_constraint(
            "invitation_state", "invitations",
            "state IN ('sent','viewed','accepted','rejected','withdrawn','expired')",
        )
        op.create_check_constraint("invitation_state_version", "invitations", "state_version >= 1")

    op.create_index(
        "uq_invitations_active_pair", "invitations", ["employer_id", "candidate_id"],
        unique=True, sqlite_where=sa.text("state IN ('sent','viewed')"),
        postgresql_where=sa.text("state IN ('sent','viewed')"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS invitations_state_constraints_insert")
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS invitations_state_constraints_update")
    else:
        op.drop_constraint("invitation_state_version", "invitations", type_="check")
        op.drop_constraint("invitation_state", "invitations", type_="check")
    op.drop_index("uq_invitations_active_pair", table_name="invitations")
    with op.batch_alter_table("invitations") as batch:
        batch.drop_column("response_due_at")
        batch.drop_column("state_version")
        batch.drop_column("compatibility_snapshot")
        batch.drop_column("explanation_snapshot")
        batch.drop_column("evidence_refs")
        batch.drop_column("terms_hash")
        batch.drop_column("terms_snapshot")
