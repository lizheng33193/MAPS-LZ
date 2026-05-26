"""Pydantic v2 schemas for Orchestrator Agent inputs / outputs / sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# 6 国短码（与 docs/skills/orchestrator/*.md 文件名对齐）
# 注意：与 data_acquisition_agent.TargetCountry 全称（mexico/...）不一致，
# V1 只 mexico 走真，其它 5 国 query_data 直接 reject（见 Task 1.5）。
CountryCode = Literal["th", "mx", "co", "pe", "cl", "br"]

# Profile 模块（与 AnalysisOrchestrator.SUPPORTED_MODULES 对齐）
ProfileModule = Literal["app", "behavior", "credit", "comprehensive", "product", "ops"]


# ===== Top-level chat request =====

class OrchestratorChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None


# ===== 6 工具的 Input / Output Schemas =====

class ParseUidFileInput(BaseModel):
    file_path: str = Field(..., description="UID 文件本地路径，必须在 data/id_files/ 下")


class ParseUidFileOutput(BaseModel):
    uids: list[str]
    source_path: str
    duplicates_removed: int


class RunProfileInput(BaseModel):
    uids: list[str] = Field(..., min_length=1, max_length=200)
    app_time: Optional[str] = Field(None, description="ISO8601 格式 application_time；未提供时由模块走默认口径")
    modules: Optional[list[ProfileModule]] = None  # None = 默认 ["app"]


class RunProfileOutput(BaseModel):
    results: list[dict[str, Any]]
    cache_hits: int = 0
    cache_misses: int = 0


class RunTraceInput(BaseModel):
    uid: str
    days: int = Field(7, ge=1, le=90)


class RunTraceOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    uid: Optional[str] = None
    status: str = "unknown"
    events: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class QueryDataInput(BaseModel):
    request: str = Field(..., min_length=1, max_length=2000)
    country: CountryCode


class QueryDataOutput(BaseModel):
    uids: list[str]
    rows_actual: int
    sql_text: str          # 已脱敏
    rows_estimated: int = -1


class MemoryWriteInput(BaseModel):
    key: str = Field(..., pattern=r"^[a-zA-Z0-9_/.-]+$", max_length=200)
    value: str = Field(..., max_length=20000)


class MemoryWriteOutput(BaseModel):
    ok: bool
    path: str


class MemoryReadInput(BaseModel):
    key_pattern: str = Field(..., max_length=200)


class MemoryReadOutput(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


# ===== Session 持久化 schemas =====

class ToolCallRecord(BaseModel):
    tool_name: str
    tool_call_id: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    status: Literal["pending", "running", "done", "error"]
    started_at: datetime
    finished_at: datetime | None = None


class OrchestratorMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    timestamp: datetime


class OrchestratorSession(BaseModel):
    session_id: str
    created_at: datetime
    updated_at: datetime
    user_id: str = "local-default-user"
    project_id: str = "agent-user-profile-fork"
    country: str | None = None
    rolling_summary: str | None = None
    active_entities: dict[str, Any] = Field(default_factory=dict)
    last_memory_sync_at: datetime | None = None
    messages: list[OrchestratorMessage] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    total_tokens: int = 0
    final_message: str | None = None
    confidence: float | None = None
    status: Literal["active", "completed", "error", "budget_exceeded"] = "active"
    # 同 session 内任一 query_data ACK 被拒绝则置 True，后续 query_data 直接 reject
    query_cancelled: bool = False
    # 连续工具失败计数，达 K=3 强制结束 session
    consecutive_failures: int = 0
