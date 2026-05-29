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
    "assistant_thinking", "execution_plan", "plan_step_status", "review_result", "awaiting_user_ack", "awaiting_resolution", "budget_warning",
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
        {"type": "execution_plan", "execution_id": "ex-1", "request_summary": "分析 UID", "intent": "profile_uid", "request_understanding": {"intent": "profile_uid", "route_label": "单 UID 画像分析", "rewritten_goal": "执行 UID u1 的画像分析", "focus": ["summary"], "requires_tools": True, "route_reason": "需要执行画像流程。", "answer_mode": "tool_execution"}, "availability": {"checked_uids": ["u1"]}, "steps": [{"step_id": "s1", "title": "检查数据", "status": "pending"}]},
        {"type": "plan_step_status", "execution_id": "ex-1", "step_id": "s1", "status": "done", "result_summary": "App 数据存在"},
        {"type": "tool_started", "tool_call_id": "tc-1", "tool_name": "run_trace", "input": {}},
        {"type": "tool_progress", "tool_call_id": "tc-1", "tool_name": "run_profile", "progress_type": "profile_module_completed", "uid": "u1", "module": "app", "status": "ok", "completed": 1, "total": 2, "result": {"status": "ok"}},
        {"type": "assistant_thinking", "content_delta": "正在"},
        {"type": "assistant_thinking", "content_delta": "分析"},
        {"type": "tool_completed", "tool_call_id": "tc-1", "status": "ok", "output": {"ok": True}},
        {"type": "review_result", "execution_id": "ex-1", "status": "warning", "issues": [{"type": "missing_data", "bucket": "credit"}], "confidence_impact": "信用相关结论降级", "can_answer": True},
        {"type": "awaiting_user_ack", "tool_call_id": "tc-2", "sql_text": "SELECT 1", "rows_estimated": 10},
        {"type": "awaiting_resolution", "execution_id": "ex-1", "step_id": "clarify_scope", "resolution_type": "clarification", "prompt": "请补充国家和时间范围", "required_slots": ["country", "time_window"], "candidate_defaults": {"country": "mx"}},
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
    assert state["executionTraces"][0]["request_summary"] == "分析 UID"
    assert state["executionTraces"][0]["request_understanding"]["route_label"] == "单 UID 画像分析"
    assert state["executionTraces"][0]["steps"][0]["status"] == "done"
    assert state["executionTraces"][0]["review"]["status"] == "warning"
    assert state["toolCalls"][0]["status"] == "ok"
    assert state["toolCalls"][0]["progress"][0]["module"] == "app"
    assert state["toolCalls"][0]["progress"][0]["completed"] == 1
    assert state["pendingAck"] is None
    assert state["pendingResolution"]["resolution_type"] == "clarification"
    assert state["budget"]["percentage"] == 90
    assert state["providerFallback"]["from"] == "claude"
    assert state["final"]["final_message"] == "完成"
    assert state["streamEnded"] is True


def test_reducer_merges_updated_execution_plan_and_unknown_step() -> None:
    if not shutil.which("node"):
        pytest.fail("Node.js is required for reducer dynamic test; do not skip this test.")
    events = [
        {"type": "execution_plan", "execution_id": "ex-2", "request_summary": "cohort", "intent": "query_data_then_profile", "availability": None, "steps": [{"step_id": "query_data", "title": "查询 cohort UID", "status": "pending"}]},
        {"type": "plan_step_status", "execution_id": "ex-2", "step_id": "query_data", "status": "done", "result_summary": "已获取 1 个 UID"},
        {"type": "execution_plan", "execution_id": "ex-2", "request_summary": "cohort", "intent": "query_data_then_profile", "availability": {"checked_uids": ["u1"]}, "steps": [{"step_id": "query_data", "title": "查询 cohort UID", "status": "done"}, {"step_id": "check_data", "title": "检查数据完整性", "status": "pending"}, {"step_id": "run_profile", "title": "执行画像分析", "status": "pending"}]},
        {"type": "plan_step_status", "execution_id": "ex-2", "step_id": "repair_credit", "status": "blocked", "result_summary": "repair 目前仅支持 mx。"},
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
    steps = state["executionTraces"][0]["steps"]
    step_ids = [step["step_id"] for step in steps]
    assert step_ids[:3] == ["query_data", "check_data", "run_profile"]
    assert "repair_credit" in step_ids
    dynamic_step = next(step for step in steps if step["step_id"] == "repair_credit")
    assert dynamic_step["status"] == "blocked"


def test_reducer_tracks_pending_resolution_separately_from_ack() -> None:
    if not shutil.which("node"):
        pytest.fail("Node.js is required for reducer dynamic test; do not skip this test.")
    events = [
        {"type": "awaiting_user_ack", "tool_call_id": "tc-1", "sql_text": "SELECT 1", "rows_estimated": 1},
        {"type": "awaiting_resolution", "execution_id": "ex-3", "step_id": "repair_strategy", "resolution_type": "repair_strategy", "prompt": "请选择 repair 策略", "options": ["analyze_existing_only", "repair_behavior_only", "repair_all_missing", "refine_scope"]},
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
    assert state["pendingAck"]["tool_call_id"] == "tc-1"
    assert state["pendingResolution"]["step_id"] == "repair_strategy"
