"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.daily_summary import rebuild_daily_summaries
from src.api.main import app
from src.db.config import ROOT_DIR, settings
from src.db.session import Base, get_db
from src.ingestion.csv_daily import import_daily_metrics_csv


@pytest.fixture(autouse=True)
def _statistical_reasoning(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_mode", "statistical")
    monkeypatch.setattr(settings, "openai_api_key", "")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def loaded_db(db_session):
    csv_path = ROOT_DIR / "data" / "raw" / "synthetic" / "daily_metrics.csv"
    result = import_daily_metrics_csv(
        db_session,
        csv_path,
        user_email="test@example.com",
        user_name="Test User",
        source="synthetic",
    )
    rebuild_daily_summaries(db_session, result["user_id"])
    return db_session, result["user_id"]


@pytest.fixture()
def client(loaded_db, monkeypatch):
    session, _user_id = loaded_db
    monkeypatch.setattr(settings, "sync_api_key", "test-key")

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
