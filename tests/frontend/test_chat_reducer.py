from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REDUCER = REPO / "app" / "static" / "js" / "components" / "panels" / "chat" / "chatReducer.js"

REQUIRED = [
    "user_input", "session_started", "tool_started", "tool_progress", "tool_completed",
    "assistant_thinking", "awaiting_user_ack", "budget_warning",
    "provider_fallback", "error", "final", "done",
]


def test_reducer_file_contains_required_cases() -> None:
    assert REDUCER.is_file(), f"missing {REDUCER}"
    body = REDUCER.read_text(encoding="utf-8")
    for action in REQUIRED:
        assert f"case '{action}'" in body or f'case "{action}"' in body
    assert "window.AppComponents.chatReducer" in body
    assert "window.AppComponents.chatInitialState" in body


def test_reducer_walks_full_session() -> None:
    if not shutil.which("node"):
        pytest.fail("Node.js is required for reducer dynamic test; do not skip this test.")
    events = [
        {"type": "user_input", "content": "hello"},
        {"type": "session_started", "session_id": "s-1"},
        {"type": "tool_started", "tool_call_id": "tc-1", "tool_name": "run_trace", "input": {}},
        {"type": "tool_progress", "tool_call_id": "tc-1", "tool_name": "run_profile", "progress_type": "profile_module_completed", "uid": "u1", "module": "app", "status": "ok", "completed": 1, "total": 2, "result": {"status": "ok"}},
        {"type": "assistant_thinking", "content_delta": "正在"},
        {"type": "assistant_thinking", "content_delta": "分析"},
        {"type": "tool_completed", "tool_call_id": "tc-1", "status": "ok", "output": {"ok": True}},
        {"type": "awaiting_user_ack", "tool_call_id": "tc-2", "sql_text": "SELECT 1", "rows_estimated": 10},
        {"type": "tool_completed", "tool_call_id": "tc-2", "status": "ok", "output": {}},
        {"type": "budget_warning", "used": 9000, "limit": 10000, "percentage": 90},
        {"type": "provider_fallback", "from": "claude", "to": "openai", "reason": "rate_limit"},
        {"type": "final", "final_message": "完成", "total_rounds": 1, "total_tokens": 100, "confidence": 0.8},
        {"type": "done"},
    ]
    js = f"""
const fs = require('fs');
const window = {{}};
eval(fs.readFileSync({json.dumps(str(REDUCER))}, 'utf8'));
let state = window.AppComponents.chatInitialState;
for (const evt of {json.dumps(events)}) state = window.AppComponents.chatReducer(state, evt);
process.stdout.write(JSON.stringify(state));
"""
    out = subprocess.check_output(["node", "-e", js], cwd=REPO)
    state = json.loads(out)
    assert state["sessionId"] == "s-1"
    assert len(state["messages"]) >= 2
    assert state["toolCalls"][0]["status"] == "ok"
    assert state["toolCalls"][0]["progress"][0]["module"] == "app"
    assert state["toolCalls"][0]["progress"][0]["completed"] == 1
    assert state["pendingAck"] is None
    assert state["budget"]["percentage"] == 90
    assert state["providerFallback"]["from"] == "claude"
    assert state["final"]["final_message"] == "完成"
    assert state["streamEnded"] is True
