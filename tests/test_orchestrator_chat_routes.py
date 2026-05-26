"""Plan #04 hotfix: chat-tab adapter routes (sessions / messages / stream)."""

from __future__ import annotations


def test_create_session_with_initial_message_returns_id_and_iso_created_at(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/orchestrator/sessions",
        json={"initial_message": "test prompt"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data and len(data["session_id"]) > 0
    assert "created_at" in data and "T" in data["created_at"]


def test_send_message_404_for_unknown_session(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/orchestrator/sessions/non-existent/messages",
        json={"content": "hi"},
    )
    assert r.status_code == 404


def test_send_message_writes_pending_prompt(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import orchestrator_routes as routes

    client = TestClient(app)
    sid = client.post(
        "/api/orchestrator/sessions", json={}
    ).json()["session_id"]

    ok = client.post(
        f"/api/orchestrator/sessions/{sid}/messages",
        json={"content": "second turn"},
    )
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    with routes._PENDING_PROMPTS_LOCK:
        assert routes._PENDING_PROMPTS.get(sid) == "second turn"


def test_stream_endpoint_runs_loop_and_terminates_with_done(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    sid = client.post(
        "/api/orchestrator/sessions",
        json={"initial_message": "hello"},
    ).json()["session_id"]

    with client.stream("GET", f"/api/orchestrator/sessions/{sid}/stream") as r:
        assert r.status_code == 200
        body = b"".join(chunk for chunk in r.iter_bytes()).decode("utf-8")
    assert '"type": "session_started"' in body
    assert '"type": "final"' in body
    assert '"type": "done"' in body


def test_stream_without_pending_prompt_yields_done_only(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    sid = client.post(
        "/api/orchestrator/sessions", json={}
    ).json()["session_id"]

    with client.stream("GET", f"/api/orchestrator/sessions/{sid}/stream") as r:
        body = b"".join(chunk for chunk in r.iter_bytes()).decode("utf-8")
    assert '"type": "done"' in body
    assert '"type": "session_started"' not in body


def test_ack_endpoint_accepts_decision_body(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/orchestrator/sessions/no-such-session/ack",
        json={"tool_call_id": "x", "decision": "approve"},
    )
    assert r.status_code == 200
    assert r.json() == {"resolved": False}


def test_ack_endpoint_rejects_empty_body(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/orchestrator/sessions/x/ack",
        json={},
    )
    assert r.status_code == 422


def test_get_session_after_chat_includes_assistant_message(monkeypatch):
    """Plan #04 hotfix 二段：agent_loop final 分支应把 assistant 也写入 session.messages，
    否则 TC-4 刷新恢复时只能看到 user 气泡。"""
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    sid = client.post(
        "/api/orchestrator/sessions",
        json={"initial_message": "hello"},
    ).json()["session_id"]

    with client.stream("GET", f"/api/orchestrator/sessions/{sid}/stream") as r:
        b"".join(chunk for chunk in r.iter_bytes())

    sess = client.get(f"/api/orchestrator/sessions/{sid}").json()
    roles = [m["role"] for m in sess["messages"]]
    assert "user" in roles
    assert "assistant" in roles
