"""Runtime safety contracts that don't need an external database."""

from backend.db import engine as test_engine, make_engine
from backend.main import app, ready
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request

from backend.security import csrf_guard


def test_sqlite_connections_enforce_foreign_keys():
    engine = make_engine("sqlite://")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))"
            )
            try:
                connection.exec_driver_sql("INSERT INTO child (parent_id) VALUES (404)")
            except IntegrityError:
                pass
            else:
                raise AssertionError("SQLite accepted a child without a parent")
    finally:
        engine.dispose()


def test_readiness_rejects_a_reachable_but_unmigrated_schema():
    engine = make_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE users (id TEXT PRIMARY KEY)")

        with Session(engine) as session:
            try:
                ready(session)
            except HTTPException as error:
                assert error.status_code == 503
                assert error.detail == "SCHEMA_NOT_READY"
            else:
                raise AssertionError("Readiness accepted an incomplete application schema")
    finally:
        engine.dispose()


def test_pytest_database_is_initialized_by_the_current_alembic_revision():
    with test_engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
    assert revision == "f7c2a1d93e10"


def test_csrf_guard_accepts_the_configured_origin_and_rejects_another_origin():
    def request_for(origin: str) -> Request:
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"origin", origin.encode()),
                (b"cookie", b"fsp_csrf=matching-token"),
                (b"x-csrf-token", b"matching-token"),
            ],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 12345),
        })

    csrf_guard(request_for("http://testserver"))
    try:
        csrf_guard(request_for("https://untrusted.example"))
    except HTTPException as error:
        assert error.status_code == 403
        assert error.detail == "ORIGIN_FORBIDDEN"
    else:
        raise AssertionError("CSRF guard accepted a different origin")


def test_openapi_documents_error_envelope_and_cookie_csrf_security():
    schema = app.openapi()
    schemes = schema["components"]["securitySchemes"]
    assert schemes["CookieSession"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "fsp_session",
        "description": "HttpOnly session cookie issued by POST /api/v1/auth/login.",
    }
    protected = schema["paths"]["/api/v1/candidate/profile"]["put"]
    assert protected["security"] == [{
        "CookieSession": [],
        "CsrfCookie": [],
        "CsrfHeader": [],
    }]
    included_router_operation = schema["paths"]["/api/v1/candidate/preferences"]["put"]
    assert included_router_operation["security"] == protected["security"]
    assert protected["responses"]["409"] == {"$ref": "#/components/responses/Error409"}
    live = schema["paths"]["/api/v1/health/live"]["get"]
    assert "security" not in live
    assert "401" not in live["responses"]
    assert "security" not in schema["paths"]["/api/v1/calendars/{token}"]["get"]
