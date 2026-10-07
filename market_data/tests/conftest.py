"""Database fixtures: every test gets its own empty schema in the test database."""

import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

import db


@pytest.fixture(scope="session")
def test_url():
    """TEST_DATABASE_URL, or the main credentials with the market_data_test database."""
    return os.environ.get("TEST_DATABASE_URL") or db.database_url(dbname="market_data_test")


@pytest.fixture
def empty_schema(test_url):
    """Conninfo whose search_path is a fresh schema, dropped after the test."""
    schema = f"test_{uuid.uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(test_url, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.fail(f"test database unreachable, start it with `docker compose up -d db`: {exc}")
    admin.execute(f"CREATE SCHEMA {schema}")
    yield make_conninfo(test_url, options=f"-c search_path={schema}")
    admin.execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


@pytest.fixture
def conn(empty_schema):
    conn = db.connect(empty_schema)
    yield conn
    conn.close()
