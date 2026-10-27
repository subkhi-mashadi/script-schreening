import os
import tempfile
from pathlib import Path

TEST_DB = os.environ.get("SN_TEST_DATABASE_URL", "postgresql+psycopg:///screening_naskah_test?host=/tmp")
os.environ["SN_DATABASE_URL"] = TEST_DB
os.environ["SN_STORAGE_DIR"] = tempfile.mkdtemp(prefix="sn-storage-")
os.environ["SN_SECRET_KEY"] = "test-secret-key-test-secret-key-1234"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.permissions import Role  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "kata-sandi-uji-123"
TABLES = (
    "review_actions, findings, compliance_checks, score_results, screening_runs, rule_set_items, rule_sets, rubric_criteria, rubric_versions, rules, "
    "document_sections, document_versions, manuscript_authors, audit_logs, user_sessions, manuscripts, users"
)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = TEST_DB
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    from app.screening.catalog import seed_catalog

    with SessionLocal() as db:
        seed_catalog(db)
        db.commit()
    yield
    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        # Superuser lokal: matikan trigger append-only/immutable hanya untuk pembersihan test.
        c.execute(text("SET session_replication_role = replica"))
        c.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        c.execute(text("SET session_replication_role = origin"))
        c.execute(text("ALTER SEQUENCE manuscript_code_seq RESTART WITH 1"))
    eng.dispose()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def make_user(role: Role, email: str | None = None, name: str | None = None) -> User:
    with SessionLocal() as db:
        u = User(full_name=name or role.value.title(), email=email or f"{role.value}@uji.id", role=role.value,
                 password_hash=hash_password(PASSWORD))
        db.add(u)
        db.commit()
        db.refresh(u)
        return u


def login(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def users() -> dict[str, User]:
    return {r.value: make_user(r) for r in Role}


@pytest.fixture
def auth(client, users):
    """auth('intake_operator') -> header Authorization untuk peran tersebut."""
    cache: dict[str, dict] = {}

    def _get(role: str) -> dict:
        if role not in cache:
            cache[role] = login(client, users[role].email)
        return cache[role]

    return _get
