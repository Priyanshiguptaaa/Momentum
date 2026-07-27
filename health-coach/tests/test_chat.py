"""Chat endpoint with mocked OpenAI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.db.session import Base, get_db


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSession()

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    monkeypatch.setenv("HC_SYNC_API_KEY", "test-secret")
    monkeypatch.setenv("HC_OPENAI_API_KEY", "sk-test")
    from src.db.config import settings

    settings.sync_api_key = "test-secret"
    settings.openai_api_key = "sk-test"
    settings.openai_model = "gpt-4o-mini"

    with TestClient(app) as test_client:
        yield test_client, session

    app.dependency_overrides.clear()
    session.close()


def test_chat_page(client):
    test_client, _ = client
    res = test_client.get("/chat")
    assert res.status_code == 200
    assert "Momentum" in res.text


def test_chat_ask_requires_key(client):
    test_client, _ = client
    denied = test_client.post("/chat/ask", json={"message": "hello"})
    assert denied.status_code == 401


def test_chat_ask_mocked(client, monkeypatch):
    test_client, _ = client

    def _fake_ask(db, message, thread_id=None):
        return {
            "reply": f"echo:{message}",
            "model": "gpt-4o-mini",
            "context_days": 0,
            "thread_id": thread_id or 1,
            "patterns_used": 0,
            "interventions_in_context": 0,
            "reasoning_trace": None,
        }

    monkeypatch.setattr("src.api.main.ask_health_question", _fake_ask)
    ok = test_client.post(
        "/chat/ask",
        json={"message": "How is my trend?"},
        headers={"X-API-Key": "test-secret"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["reply"] == "echo:How is my trend?"
    assert body["thread_id"] == 1
