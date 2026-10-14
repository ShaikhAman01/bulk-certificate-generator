import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://certs:certs@localhost:5433/certs_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text

from app.config import settings
from app.db import Base, SessionLocal, engine, init_db
from app.main import app
from app.worker import run_once

if not make_url(settings.database_url).database.endswith("_test"):
    raise RuntimeError("refusing to run tests against a non-test database")


def _create_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _create_test_database()
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE certificates, certificate_jobs"))
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def run_worker():
    def _run() -> int:
        total = 0
        while processed := run_once(SessionLocal, 50):
            total += processed
        return total

    return _run


@pytest.fixture
def certificate_info():
    return {"course_name": "Drone Mapping 101", "issued_on": "2026-10-01", "issuer": "Aereo Academy"}




@pytest.fixture
def submit(client, certificate_info):
    def _submit(recipients, certificate=None):
        body = {"certificate": certificate or certificate_info, "recipients": recipients}
        return client.post("/api/v1/certificate-jobs", json=body)

    return _submit
