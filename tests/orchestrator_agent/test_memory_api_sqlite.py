from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.orchestrator_agent.memory_policy import build_memory_record
from app.services.orchestrator_agent.memory_store import SQLiteMemoryStore


@pytest.mark.timeout(3)
def test_session_creation_uses_identity_headers():
    client = TestClient(app)
    resp = client.post(
        "/api/orchestrator/sessions",
        json={"initial_message": "hello"},
        headers={"X-User-ID": "analyst-1", "X-Project-ID": "proj-1", "X-Country": "th"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "analyst-1"
    assert body["project_id"] == "proj-1"
    assert body["country"] == "th"


@pytest.mark.timeout(3)
def test_memory_status_and_query_api():
    decision = build_memory_record(
        content="用户偏好中文输出",
        category="preference",
        user_id="analyst-1",
        project_id="proj-1",
        country="mx",
    )
    assert decision.accepted and decision.record
    SQLiteMemoryStore().add(decision.record)
    project_decision = build_memory_record(
        content="项目事实：当前项目使用 SQLite 长期记忆",
        category="project",
        user_id="analyst-1",
        project_id="proj-1",
        country="mx",
    )
    assert project_decision.accepted and project_decision.record
    SQLiteMemoryStore().add(project_decision.record)

    client = TestClient(app)
    status = client.get("/api/orchestrator/memory/status")
    assert status.status_code == 200
    assert status.json()["total"] >= 1

    query = client.post(
        "/api/orchestrator/memory/query",
        json={"query": "中文输出", "top_k": 3},
        headers={"X-User-ID": "analyst-1", "X-Project-ID": "proj-1", "X-Country": "mx"},
    )
    assert query.status_code == 200
    results = query.json()["results"]
    assert results
    assert results[0]["content"] == "用户偏好中文输出"
    assert "score_parts" in results[0]

    recent = client.post(
        "/api/orchestrator/memory/query",
        json={"query": "", "category": "project", "top_k": 5},
        headers={"X-User-ID": "analyst-1", "X-Project-ID": "proj-1", "X-Country": "mx"},
    )
    assert recent.status_code == 200
    body = recent.json()
    assert body["category"] == "project"
    assert body["results"]
    assert all(item["category"] == "project" for item in body["results"])
    assert any(item["content"] == "项目事实：当前项目使用 SQLite 长期记忆" for item in body["results"])


@pytest.mark.timeout(3)
def test_memory_management_api_create_edit_archive_restore_delete():
    client = TestClient(app)
    identity = {"user_id": "admin-user", "project_id": "admin-project", "country": "mx"}

    created = client.post(
        "/api/orchestrator/memory",
        json={
            **identity,
            "content": "请记住：我偏好中文输出",
            "category": "preference",
            "tags": ["manual"],
        },
    )
    assert created.status_code == 200
    memory = created.json()["memory"]
    memory_id = memory["memory_id"]
    assert memory["source"] == "memory_admin"

    listed = client.get("/api/orchestrator/memory/list", params={**identity, "status": "active"})
    assert listed.status_code == 200
    assert any(item["memory_id"] == memory_id for item in listed.json()["results"])

    updated = client.patch(
        f"/api/orchestrator/memory/{memory_id}",
        json={**identity, "content": "请记住：我偏好英文输出", "category": "preference"},
    )
    assert updated.status_code == 200
    assert "英文输出" in updated.json()["memory"]["content"]

    archive = client.post(f"/api/orchestrator/memory/{memory_id}/archive", params=identity)
    assert archive.status_code == 200
    assert archive.json()["memory"]["status"] == "archived"
    archived_query = client.post("/api/orchestrator/memory/query", json={**identity, "query": "英文输出"})
    assert archived_query.status_code == 200
    assert archived_query.json()["results"] == []

    restore = client.post(f"/api/orchestrator/memory/{memory_id}/restore", params=identity)
    assert restore.status_code == 200
    assert restore.json()["memory"]["status"] == "active"
    restored_query = client.post("/api/orchestrator/memory/query", json={**identity, "query": "英文输出"})
    assert restored_query.status_code == 200
    assert any(item["memory_id"] == memory_id for item in restored_query.json()["results"])

    delete = client.delete(f"/api/orchestrator/memory/{memory_id}", params=identity)
    assert delete.status_code == 200
    assert delete.json()["memory"]["status"] == "deleted"
    deleted_query = client.post("/api/orchestrator/memory/query", json={**identity, "query": "英文输出"})
    assert deleted_query.status_code == 200
    assert deleted_query.json()["results"] == []


@pytest.mark.timeout(3)
def test_memory_management_api_identity_isolation_and_duplicate_update_conflict():
    client = TestClient(app)
    identity = {"user_id": "admin-user-2", "project_id": "admin-project", "country": "mx"}
    first = client.post(
        "/api/orchestrator/memory",
        json={**identity, "content": "请记住：我偏好中文输出", "category": "preference"},
    ).json()["memory"]
    second = client.post(
        "/api/orchestrator/memory",
        json={**identity, "content": "请记住：我偏好英文输出", "category": "preference"},
    ).json()["memory"]

    isolated = client.patch(
        f"/api/orchestrator/memory/{first['memory_id']}",
        json={**identity, "user_id": "other-user", "content": "请记住：我偏好西语输出"},
    )
    assert isolated.status_code == 404

    conflict = client.patch(
        f"/api/orchestrator/memory/{second['memory_id']}",
        json={**identity, "content": "请记住：我偏好中文输出", "category": "preference"},
    )
    assert conflict.status_code == 409

    rejected = client.post(
        "/api/orchestrator/memory",
        json={**identity, "content": "你好", "category": "preference"},
    )
    assert rejected.status_code == 422
