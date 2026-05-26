from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "app" / "static" / "js" / "app.jsx"
CHAT_PANEL = REPO / "app" / "static" / "js" / "components" / "panels" / "chat" / "ChatPanel.jsx"
API = REPO / "app" / "static" / "js" / "services" / "api.js"
MEMORY_INSPECTOR = REPO / "app" / "static" / "js" / "components" / "panels" / "chat" / "MemoryInspector.jsx"
DASHBOARD = REPO / "app" / "static" / "js" / "components" / "DashboardView.jsx"
MODULE_STATUS = REPO / "app" / "static" / "js" / "components" / "common" / "ModuleStatusPanel.jsx"


def test_app_owns_tab_url_routing() -> None:
    src = APP.read_text(encoding="utf-8")
    assert "VALID_DASHBOARD_TABS" in src
    assert "function getInitialDashboardTab()" in src
    assert "function getInitialViewFromUrl()" in src
    assert re.search(r"new\s+URLSearchParams\s*\(\s*window\.location\.search\s*\)", src)
    assert re.search(r"\.get\(\s*['\"]tab['\"]\s*\)", src)
    assert re.search(r"\.get\(\s*['\"]session['\"]\s*\)", src)
    assert re.search(r"useState\s*\(\s*getInitialViewFromUrl\s*\)", src)
    assert re.search(r"useState\s*\(\s*getInitialDashboardTab\s*\)", src)
    assert re.search(r"tab\s*===\s*['\"]chat['\"]\s*\|\|\s*params\.get\(\s*['\"]session['\"]\s*\)", src)
    assert "window.history.replaceState" in src


def test_chat_panel_restores_and_writes_session_url() -> None:
    src = CHAT_PANEL.read_text(encoding="utf-8")
    assert re.search(r"\.get\(\s*['\"]session['\"]\s*\)", src)
    assert "fetchOrchestratorSession" in src
    assert re.search(r"\.set\(\s*['\"]session['\"]", src)
    assert re.search(r"\.set\(\s*['\"]tab['\"]\s*,\s*['\"]chat['\"]", src)
    assert "window.history.replaceState" in src


def test_memory_inspector_wires_management_api() -> None:
    api_src = API.read_text(encoding="utf-8")
    inspector_src = MEMORY_INSPECTOR.read_text(encoding="utf-8")
    panel_src = CHAT_PANEL.read_text(encoding="utf-8")

    assert "function fetchMemoryStatus" in api_src
    assert "/api/orchestrator/memory/status" in api_src
    assert "function queryMemory" in api_src
    assert "/api/orchestrator/memory/query" in api_src
    assert "function listMemories" in api_src
    assert "/api/orchestrator/memory/list" in api_src
    assert "function createMemory" in api_src
    assert "function updateMemory" in api_src
    assert "function archiveMemory" in api_src
    assert "function restoreMemory" in api_src
    assert "function deleteMemory" in api_src
    assert "window.AppComponents.MemoryInspector = MemoryInspector;" in inspector_src
    assert "fetchMemoryStatus" in inspector_src
    assert "queryMemory" in inspector_src
    assert "listMemories" in inspector_src
    assert "createMemory" in inspector_src
    assert "updateMemory" in inspector_src
    assert "archiveMemory" in inspector_src
    assert "restoreMemory" in inspector_src
    assert "deleteMemory" in inspector_src
    assert "MemoryInspector" in panel_src


def test_chat_panel_wires_profile_progress_and_safe_success_copy() -> None:
    src = CHAT_PANEL.read_text(encoding="utf-8")
    assert "tool_progress" in (REPO / "app" / "static" / "js" / "components" / "panels" / "chat" / "chatReducer.js").read_text(encoding="utf-8")
    assert "profile_module_completed" in src
    assert "dispatchProfileRow" in src
    assert "完整画像已生成" in src
    assert "画像分析进行中" in src
    assert "可查看完整 dashboard" not in src


def test_memory_inspector_separates_session_history_and_long_term_memory() -> None:
    api_src = API.read_text(encoding="utf-8")
    inspector_src = MEMORY_INSPECTOR.read_text(encoding="utf-8")

    assert "function fetchOrchestratorSessions" in api_src
    assert "/api/orchestrator/sessions" in api_src
    assert "短期会话历史" in inspector_src
    assert "长期记忆" in inspector_src
    assert "不参与长期记忆召回" in inspector_src
    assert "移入已删除" in inspector_src
    assert "active 会被召回" in inspector_src


def test_memory_inspector_explains_session_filters_and_recall_reason() -> None:
    inspector_src = MEMORY_INSPECTOR.read_text(encoding="utf-8")

    assert "搜索会话" in inspector_src
    assert "会话状态" in inspector_src
    assert "会话国家" in inspector_src
    assert "为什么会被召回" in inspector_src
    assert "会被召回：active + 当前 identity + 查询相关" in inspector_src
    assert "不参与召回" in inspector_src


def test_dashboard_loading_states_use_skeleton_progress() -> None:
    dashboard_src = DASHBOARD.read_text(encoding="utf-8")
    module_status_src = MODULE_STATUS.read_text(encoding="utf-8")

    assert "skeleton-shimmer" in dashboard_src
    assert "loading-progress-bar" in dashboard_src
    assert "模块分析骨架屏" in module_status_src
    assert "skeleton-shimmer" in module_status_src
