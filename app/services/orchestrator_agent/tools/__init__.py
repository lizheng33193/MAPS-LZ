"""Orchestrator Agent tools registry with lazy imports.

Keep tool loading lightweight so generic orchestrator imports do not pull in
optional Data Agent execution dependencies unless `query_data` is actually used.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any


_TOOL_EXPORTS = {
    "parse_uid_file": "app.services.orchestrator_agent.tools.parse_uid_file",
    "run_profile": "app.services.orchestrator_agent.tools.run_profile",
    "run_trace": "app.services.orchestrator_agent.tools.run_trace",
    "query_data": "app.services.orchestrator_agent.tools.query_data",
    "memory_write": "app.services.orchestrator_agent.tools.memory",
    "memory_read": "app.services.orchestrator_agent.tools.memory",
}

__all__ = [*list(_TOOL_EXPORTS.keys()), "get_tool_registry"]


def __getattr__(name: str) -> Any:
    module_path = _TOOL_EXPORTS.get(name)
    if not module_path:
        raise AttributeError(name)
    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value
    return value


def get_tool_registry() -> dict[str, Any]:
    current_module = sys.modules[__name__]
    return {
        name: getattr(current_module, name)
        for name in _TOOL_EXPORTS
    }
