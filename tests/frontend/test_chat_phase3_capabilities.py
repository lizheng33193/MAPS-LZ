from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "app" / "static" / "js" / "app.jsx"
CHAT_PANEL = REPO / "app" / "static" / "js" / "components" / "panels" / "chat" / "ChatPanel.jsx"
API = REPO / "app" / "static" / "js" / "services" / "api.js"
MEMORY_INSPECTOR = REPO / "app" / "static" / "js" / "components" / "panels" / "chat" / "MemoryInspector.jsx"


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
