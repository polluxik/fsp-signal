"""Give tests an owned database before any application modules are imported."""

import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


_temporary_database = None
_configured_test_url = os.environ.get("TEST_DATABASE_URL")
if _configured_test_url:
    _url = make_url(_configured_test_url)
    if _url.get_backend_name() != "postgresql" or not (_url.database or "").endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must point to a dedicated PostgreSQL database ending in _test")
    _database_url = _configured_test_url
else:
    _temporary_database = tempfile.TemporaryDirectory(prefix="fsp-signal-tests-")
    _database_path = Path(_temporary_database.name) / "signal.sqlite3"
    _database_url = f"sqlite:///{_database_path}"

os.environ["APP_MODE"] = "test"
os.environ["DATABASE_URL"] = _database_url
os.environ["TEST_DATABASE_URL"] = _database_url
os.environ["PUBLIC_BASE_URL"] = "http://testserver"

_repo_root = Path(__file__).resolve().parents[1]
_alembic_config = Config(str(_repo_root / "alembic.ini"))
command.upgrade(_alembic_config, "head")


def pytest_unconfigure(config):
    del config
    database_module = sys.modules.get("backend.db")
    if database_module is not None:
        database_module.engine.dispose()
    if _temporary_database is not None:
        _temporary_database.cleanup()
