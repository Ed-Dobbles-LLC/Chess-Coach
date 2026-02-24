"""Shared test fixtures — separate SQLite test database, FastAPI test client."""

import os
import sys

# Set test environment BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite:///chess_coach_test.db"
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
os.environ["CHESS_COM_USERNAME"] = "eddobbles2021"
os.environ["STOCKFISH_PATH"] = "/usr/games/stockfish"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db

# Ensure we never touch the production database
TEST_DB_PATH = "chess_coach_test.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"

test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})

@event.listens_for(test_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Import app AFTER setting env vars
from main import app

app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create tables and seed once per test session."""
    # Remove stale test DB
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    # Also remove WAL/SHM files
    for suffix in ("-wal", "-shm"):
        path = TEST_DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)

    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    from tests.seed import seed_all
    seed_all(db)
    db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    for suffix in ("-wal", "-shm"):
        path = TEST_DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture
def db():
    """Provide a test database session."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    """Provide a FastAPI test client."""
    return TestClient(app)
