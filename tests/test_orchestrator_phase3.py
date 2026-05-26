"""Phase 3 RED contract tests: ack_bus + agent_loop main loop + ACK branch + routes."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest


# ---- ack_bus ----

def test_ack_bus_resolve_returns_value():
    from app.services.orchestrator_agent.ack_bus import (
        open_ack, resolve_ack, wait_ack,
    )
    sid = "phase3-ack-1"
    ev = open_ack(sid)
    # 在另一个线程 resolve
    def resolver():
        time.sleep(0.05)
        resolve_ack(sid, True)
    t = threading.Thread(target=resolver)
    t.start()
    result = wait_ack(sid, timeout_sec=2.0)
    t.join()
    assert result is True


def test_ack_bus_timeout_returns_none():
    from app.services.orchestrator_agent.ack_bus import open_ack, wait_ack
    sid = "phase3-ack-timeout"
    open_ack(sid)
    result = wait_ack(sid, timeout_sec=0.1)
    assert result is None


def test_ack_bus_unknown_session_resolve_returns_false():
    from app.services.orchestrator_agent.ack_bus import resolve_ack
    assert resolve_ack("definitely-not-opened", True) is False


# ---- agent_loop main loop (mock LLM) ----

# R8 P0-A：用 asyncio.run 同步驱动 async generator，不依赖 pytest-asyncio
# （requirements.txt 未含 pytest-asyncio，与 Task 4.2 Golden runner 风格一致）。
def test_agent_loop_mock_run_trace_completes(monkeypatch):
    """Mock LLM 返回 run_trace tool_call → 然后 final → 验证 SSE 事件序列。"""
    import asyncio

    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.session_store import create_session

    # Patch ModelClient.generate_structured 返回 deterministic decisions
    decisions = iter([
        {"status": "ok", "structured_result": {
            "tool_call": {"name": "run_trace", "arguments": {"uid": "MX0001", "days": 7}},
        }},
        {"status": "ok", "structured_result": {
            "final_message": "## 用户请求理解\n查 MX0001 轨迹\n", "confidence": 0.7,
        }},
    ])
    class _FakeClient:
        last_token_usage = {"prompt": 100, "completion": 50, "total": 150}
        def generate_structured(self, **kwargs):
            return next(decisions)
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: _FakeClient(),
    )
    # Patch run_trace 直接返回固定值，避免依赖 trace_analyzer 真实数据
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_trace",
        lambda inp: type("X", (), {
            "model_dump": lambda self, mode="json": {"events": [], "summary": {}},
        })(),
    )

    sess = create_session()

    async def _drive():
        events = []
        async for evt in run_agent_loop(session=sess, prompt="看 MX0001 轨迹"):
            events.append(evt)
        return events

    events = asyncio.run(_drive())

    types = [e.get("type") for e in events]
    assert "session_started" in types
    assert "tool_started" in types
    assert "tool_completed" in types
    assert "final" in types


def test_agent_loop_run_profile_emits_module_progress(monkeypatch):
    """run_profile should stream module-level progress before final completion."""
    import asyncio

    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.session_store import create_session

    decisions = iter([
        {"status": "ok", "structured_result": {
            "tool_call": {
                "name": "run_profile",
                "arguments": {
                    "uids": ["824812551379353600"],
                    "app_time": None,
                    "modules": ["app", "behavior"],
                },
            },
        }},
        {"status": "ok", "structured_result": {
            "final_message": "## 用户请求理解\n画像完成\n", "confidence": 0.8,
        }},
    ])

    class _FakeClient:
        last_token_usage = {"prompt": 100, "completion": 50, "total": 150}
        def generate_structured(self, **kwargs):
            return next(decisions)

    def _fake_run_profile(inp, progress_callback=None):
        results = []
        for idx, mod in enumerate(inp.modules or ["app"], start=1):
            result = {
                "uid": inp.uids[0],
                "module": mod,
                "status": "ok",
                "data": {"summary": f"{mod} done", "structured_result": {}, "charts": [], "report_markdown": ""},
                "error": None,
            }
            if progress_callback:
                progress_callback({
                    "progress_type": "profile_module_completed",
                    "uid": inp.uids[0],
                    "module": mod,
                    "result": result,
                    "status": "ok",
                    "completed": idx,
                    "total": 2,
                })
            results.append({"uid": inp.uids[0], "module": mod, "result": result})
        return type("X", (), {
            "model_dump": lambda self, mode="json": {
                "results": results,
                "cache_hits": 0,
                "cache_misses": 2,
            },
        })()

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: _FakeClient(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        _fake_run_profile,
    )

    sess = create_session()

    async def _drive():
        return [evt async for evt in run_agent_loop(session=sess, prompt="帮我分析一下824812551379353600这个用户")]

    events = asyncio.run(_drive())
    types = [e.get("type") for e in events]

    assert types.index("tool_started") < types.index("tool_progress") < types.index("tool_completed")
    progress_events = [e for e in events if e.get("type") == "tool_progress"]
    assert [e["module"] for e in progress_events] == ["app", "behavior"]
    assert progress_events[-1]["completed"] == 2
    assert events[-1]["type"] == "final"


# ---- FastAPI routes ----

def test_orchestrator_chat_route_returns_sse(monkeypatch):
    monkeypatch.setenv("MODEL_MODE", "mock")
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    with client.stream(
        "POST", "/api/orchestrator/chat",
        json={"prompt": "你好"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")


def test_get_session_returns_404_for_unknown():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/orchestrator/sessions/definitely-not-existing")
    assert r.status_code == 404


def test_ack_route_unresolved_returns_false():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.post(
        "/api/orchestrator/sessions/never-opened/ack",
        json={"confirm": True},
    )
    assert r.status_code == 200
    assert r.json() == {"resolved": False}
