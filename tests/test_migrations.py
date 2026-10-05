"""Upgrade the previous schema using an isolated, throwaway SQLite database."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _alembic(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment.update({"APP_MODE": "test", "DATABASE_URL": database_url})
    environment.pop("TEST_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", revision],
        cwd=ROOT, env=environment, text=True, capture_output=True,
    )
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
        need = connection.execute("SELECT * FROM hiring_needs WHERE id='need-1'").fetchone()
        role = connection.execute("SELECT * FROM role_versions WHERE need_id='need-1'").fetchone()
        invitation = connection.execute("SELECT role_version_id FROM invitations WHERE id='invite-1'").fetchone()
        search = connection.execute("SELECT role_version_id FROM search_snapshots WHERE id='search-1'").fetchone()
        events = connection.execute("SELECT count(*) FROM product_events").fetchone()[0]
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
