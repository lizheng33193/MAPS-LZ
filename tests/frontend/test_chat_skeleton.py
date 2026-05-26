from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHAT_DIR = REPO / "app" / "static" / "js" / "components" / "panels" / "chat"

EXPECTED_COMPONENTS = [
    "ChatPanel",
    "ChatMessageList",
    "ChatInputBox",
    "ChatToolCallStream",
    "ChatAckCard",
    "ChatBudgetBanner",
    "ChatProviderFallbackBanner",
    "MemoryInspector",
]


def test_chat_component_files_exist_and_register() -> None:
    assert CHAT_DIR.is_dir(), f"missing dir: {CHAT_DIR}"
    for name in EXPECTED_COMPONENTS:
        path = CHAT_DIR / f"{name}.jsx"
        assert path.is_file(), f"missing component: {path}"
        body = path.read_text(encoding="utf-8")
        assert f"window.AppComponents.{name} = {name};" in body


def test_load_order_contains_chat_files_before_dashboard() -> None:
    bf = (REPO / "app" / "ui" / "build_frontend.py").read_text(encoding="utf-8")
    dash = bf.index('"js/components/DashboardView.jsx"')
    for name in EXPECTED_COMPONENTS:
        needle = f'"js/components/panels/chat/{name}.jsx"'
        assert needle in bf, f"LOAD_ORDER missing {needle}"
        assert bf.index(needle) < dash, f"{needle} must load before DashboardView"


def test_dashboard_has_chat_tab_and_branch() -> None:
    src = (REPO / "app" / "static" / "js" / "components" / "DashboardView.jsx").read_text(encoding="utf-8")
    assert "ChatPanel," in src
    assert re.search(r"id:\s*'chat'", src)
    assert "activeTab === 'chat'" in src
    assert "<ChatPanel" in src
