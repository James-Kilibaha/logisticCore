"""
Tests za SaaS (PostgreSQL halisi): database ya TEST_DATABASE_NAME inafutwa na kuundwa upya.
    pytest -q
"""
import os

os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("BACKUP_ENABLED", "false")
os.environ.setdefault("SMS_AUTO_SEND", "false")
os.environ["ADMIN_USERNAME"] = "superadmin"
os.environ["ADMIN_PASSWORD"] = "Admin12345"
os.environ.setdefault("PLATFORM_DOMAIN", "logistic.test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")

from logistic import config  # noqa: E402

config.DATABASE_NAME = config.TEST_DATABASE_NAME

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from logistic import db as dbmod  # noqa: E402


def _recreate_database():
    admin = create_engine(dbmod.database_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{config.TEST_DATABASE_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{config.TEST_DATABASE_NAME}"'))
    admin.dispose()


_recreate_database()
dbmod.engine.dispose()
dbmod.engine = create_engine(dbmod.database_url(config.TEST_DATABASE_NAME), pool_pre_ping=True)
dbmod.SessionLocal.configure(bind=dbmod.engine)

from fastapi.testclient import TestClient  # noqa: E402

from logistic.app import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def platform(client):
    r = client.post("/api/platform/login", json={"username": "superadmin", "password": "Admin12345"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
