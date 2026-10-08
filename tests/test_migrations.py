"""Upgrade the previous schema using an isolated, throwaway SQLite database."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _alembic_result(database_url: str, revision: str) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment.update({"APP_MODE": "test", "DATABASE_URL": database_url})
    environment.pop("TEST_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", revision],
        cwd=ROOT, env=environment, text=True, capture_output=True,
    )


def _alembic(database_url: str, revision: str) -> None:
    result = _alembic_result(database_url, revision)
    assert result.returncode == 0, result.stdout + result.stderr


def test_upgrade_backfills_only_known_legacy_role_and_keeps_it_private():
    with tempfile.TemporaryDirectory(prefix="signal-role-upgrade-") as directory:
        database = Path(directory) / "legacy.sqlite3"
        url = f"sqlite:///{database}"
        _alembic(url, "41dbe7c98854")

        connection = sqlite3.connect(database)
        connection.execute(
            "INSERT INTO users (id,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            ("employer-1", "legacy@example.test", "not-a-login-hash", "employer", "2026-10-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO users (id,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            ("candidate-1", "candidate@example.test", "not-a-login-hash", "candidate", "2026-10-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO candidate_profiles (user_id,full_name,contact_email,contact_phone,city,summary,skills,"
            "experience_months,verified_specialization,verified_grade,test_score,verification_source,competencies,"
            "available,min_salary_rub,work_format,fsp_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("candidate-1", "Legacy Candidate", "candidate@example.test", "", "Москва", "Legacy profile",
             json.dumps(["Python"]), 36, "backend", "middle", 80, "assessment",
             json.dumps({"event_idempotency": 0.8}), 1, 220000, "any", "unlinked"),
        )
        connection.execute(
            "INSERT INTO hiring_needs (id,employer_id,title,description,specialization,grade,competencies,stack,"
            "salary_min_rub,salary_max_rub,work_format,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("need-1", "employer-1", "Backend", "Known description", "backend", "middle",
             json.dumps(["event_idempotency"]), json.dumps(["Python"]), 180000, 230000, "remote",
             "2026-10-01T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO invitations (id,employer_id,candidate_id,need_id,company_name,offer_text,reason,"
            "employer_contact,salary_min_rub,salary_max_rub,work_format,state,idempotency_key,request_hash,"
            "created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("invite-1", "employer-1", "candidate-1", "need-1", "Old company", "Old offer", "Old reason",
             "old@example.test", 180000, 200000, "remote", "sent", "key-12345678", "f" * 64,
             "2026-10-01T00:00:00+00:00", "2026-10-08T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO search_snapshots (id,employer_id,need_id,parent_id,filters,results,algorithm_version,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("search-1", "employer-1", "need-1", None, "{}", "[]", "match_v1", "2026-10-01T00:00:00+00:00"),
        )
        connection.commit()
        connection.close()

        _alembic(url, "head")
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        user = connection.execute("SELECT origin FROM users WHERE id='employer-1'").fetchone()
        profile = connection.execute("SELECT * FROM candidate_profiles WHERE user_id='candidate-1'").fetchone()
        need = connection.execute("SELECT * FROM hiring_needs WHERE id='need-1'").fetchone()
        role = connection.execute("SELECT * FROM role_versions WHERE need_id='need-1'").fetchone()
        invitation = connection.execute("SELECT role_version_id FROM invitations WHERE id='invite-1'").fetchone()
        search = connection.execute("SELECT role_version_id FROM search_snapshots WHERE id='search-1'").fetchone()
        events = connection.execute("SELECT count(*) FROM product_events").fetchone()[0]
        promotion_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(promotion_campaigns)").fetchall()
        }
        promotion_table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='promotion_campaigns'"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="role_versions_are_immutable"):
            connection.execute("UPDATE role_versions SET terms_hash=? WHERE id=?", ("0" * 64, role["id"]))
        with pytest.raises(sqlite3.IntegrityError, match="foreign key violation"):
            connection.execute("UPDATE invitations SET role_version_id='missing' WHERE id='invite-1'")
        with pytest.raises(sqlite3.IntegrityError, match="user_origin_invalid"):
            connection.execute("UPDATE users SET origin='claimed_verified' WHERE id='employer-1'")
        with pytest.raises(sqlite3.IntegrityError, match="role_state_invalid"):
            connection.execute("UPDATE hiring_needs SET publication_state='published' WHERE id='need-1'")
        connection.close()

        assert user["origin"] == "legacy_import"
        assert json.loads(profile["preferences"]) == {
            "salary_min_rub": 220000, "allowed_work_formats": ["remote", "hybrid", "office"],
            "allowed_cities": [], "excluded_industries": [], "preferred_stack": [],
            "preferred_tasks": [], "max_take_home_minutes": None, "available": True,
        }
        assert profile["adult_attested_at"] is None
        assert json.loads(profile["blocked_employer_ids"]) == []
        assert profile["verified_attempt_id"] is None
        assert json.loads(profile["achievement_story"]) == {}
        assert json.loads(profile["fsp_achievement"]) == {}
        assert need["current_role_version"] == 1
        assert need["publication_state"] == "draft"
        assert not need["discoverable"] and need["confirmed_at"] is None
        payload = json.loads(role["payload"])
        assert payload == {
            "title": "Backend", "description": "Known description", "specialization": "backend",
            "grade": "middle", "competencies": ["event_idempotency"], "stack": ["Python"],
            "salary_min_rub": 180000, "salary_max_rub": 230000, "work_format": "remote",
        }
        assert role["source"] == "legacy_import"
        assert invitation["role_version_id"] is None
        assert search["role_version_id"] is None
        assert events == 0
        assert {
            "id", "need_id", "employer_id", "role_version_id", "active_from", "active_until",
            "demo_only", "created_at",
        }.issubset(promotion_columns)
        assert not {"price_rub", "revenue_rub", "charged_amount"}.intersection(promotion_columns)
        assert "active_until > active_from" in promotion_table_sql


def _legacy_invitation_database(database: Path, invitations: list[tuple[str, str]]) -> str:
    url = f"sqlite:///{database}"
    _alembic(url, "d4a7b2f019ce")
    connection = sqlite3.connect(database)
    connection.executemany(
        "INSERT INTO users (id,email,password_hash,role,origin,created_at) VALUES (?,?,?,?,?,?)",
        [
            ("employer-duplicate", "duplicate-employer@example.test", "not-a-login-hash",
             "employer", "direct_signup", "2026-10-01T00:00:00+00:00"),
            ("candidate-duplicate", "duplicate-candidate@example.test", "not-a-login-hash",
             "candidate", "direct_signup", "2026-10-01T00:00:00+00:00"),
        ],
    )
    connection.executemany(
        "INSERT INTO invitations (id,employer_id,candidate_id,need_id,role_version_id,company_name,"
        "offer_text,reason,employer_contact,salary_min_rub,salary_max_rub,work_format,state,"
        "idempotency_key,request_hash,created_at,expires_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(
            f"invite-{suffix}", "employer-duplicate", "candidate-duplicate", None, None,
            "Duplicate Co", "Discuss the role with our team.", "Legacy invitation.",
            "team@example.test", 180000, 220000, "remote", state, f"key-{suffix}",
            (suffix[0] * 64), "2026-10-01T00:00:00+00:00",
            (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), None,
        ) for suffix, state in invitations],
    )
    connection.commit()
    connection.close()
    return url


def test_invitation_migration_diagnoses_live_duplicate_pairs_without_deleting_them():
    with tempfile.TemporaryDirectory(prefix="signal-invitation-upgrade-") as directory:
        database = Path(directory) / "duplicates.sqlite3"
        url = _legacy_invitation_database(database, [("one", "sent"), ("two", "sent")])
        result = _alembic_result(url, "head")
        diagnostic = result.stdout + result.stderr
        assert result.returncode != 0
        assert "resolve live duplicate pairs without deleting records" in diagnostic
        connection = sqlite3.connect(database)
        invitation_ids = {row[0] for row in connection.execute("SELECT id FROM invitations")}
        connection.close()
        assert invitation_ids == {"invite-one", "invite-two"}


def test_invitation_migration_diagnoses_accepted_rows_without_a_grant():
    with tempfile.TemporaryDirectory(prefix="signal-invitation-grant-upgrade-") as directory:
        database = Path(directory) / "accepted.sqlite3"
        url = _legacy_invitation_database(database, [("accepted", "accepted")])
        result = _alembic_result(url, "head")
        diagnostic = result.stdout + result.stderr
        assert result.returncode != 0
        assert "accepted invitations without a contact grant" in diagnostic
        connection = sqlite3.connect(database)
        invitation_ids = {row[0] for row in connection.execute("SELECT id FROM invitations")}
        connection.close()
        assert invitation_ids == {"invite-accepted"}


def test_interview_outcome_migration_preserves_existing_invitations():
    with tempfile.TemporaryDirectory(prefix="signal-interview-outcome-upgrade-") as directory:
        database = Path(directory) / "accepted.sqlite3"
        url = _legacy_invitation_database(database, [("accepted", "sent")])
        _alembic(url, "e8a1c4d57b20")

        connection = sqlite3.connect(database)
        connection.execute("UPDATE invitations SET state='accepted' WHERE id='invite-accepted'")
        connection.execute(
            "INSERT INTO contact_grants (id,invitation_id,employer_id,candidate_id,granted_at,revoked_at) "
            "VALUES (?,?,?,?,?,?)",
            ("grant-accepted", "invite-accepted", "employer-duplicate", "candidate-duplicate",
             "2026-10-01T00:00:00+00:00", None),
        )
        connection.commit()
        connection.close()

        _alembic(url, "head")

        connection = sqlite3.connect(database)
        invitation = connection.execute(
            "SELECT state,candidate_interview_confirmed_at,employer_interview_confirmed_at "
            "FROM invitations WHERE id='invite-accepted'"
        ).fetchone()
        connection.close()

        assert invitation == ("accepted", None, None)


def test_interview_outcome_downgrade_preserves_invitation_constraints():
    with tempfile.TemporaryDirectory(prefix="signal-interview-outcome-downgrade-") as directory:
        database = Path(directory) / "invitation.sqlite3"
        url = _legacy_invitation_database(database, [("pending", "sent")])
        _alembic(url, "head")
        _alembic(url, "e8a1c4d57b20")

        connection = sqlite3.connect(database)
        with pytest.raises(sqlite3.IntegrityError, match="invitation_state_invalid"):
            connection.execute("UPDATE invitations SET state='invalid' WHERE id='invite-pending'")
        connection.close()
