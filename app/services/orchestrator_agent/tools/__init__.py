"""Orchestrator Agent tools registry.

V1 注册 6 个工具入口。memory_write / memory_read 是 V1 minimal 实装（本地 JSON 写盘），
其它 4 工具在 Task 1.4-1.5 实装；Task 1.3 阶段 4 工具均为 NotImplementedError stub。
"""

from app.services.orchestrator_agent.tools.parse_uid_file import parse_uid_file
from app.services.orchestrator_agent.tools.run_profile import run_profile
from app.services.orchestrator_agent.tools.run_trace import run_trace
from app.services.orchestrator_agent.tools.query_data import query_data
from app.services.orchestrator_agent.tools.memory import memory_write, memory_read

__all__ = [
    "parse_uid_file", "run_profile", "run_trace",
    "query_data", "memory_write", "memory_read",
    "get_tool_registry",
]


def get_tool_registry() -> dict:
    return {
        "parse_uid_file": parse_uid_file,
        "run_profile": run_profile,
        "run_trace": run_trace,
        "query_data": query_data,
        "memory_write": memory_write,
        "memory_read": memory_read,
    }
