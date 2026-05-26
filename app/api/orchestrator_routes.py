"""Orchestrator Agent FastAPI routes (SSE chat + session GET + ACK).

Plan #04 hotfix: 在保留 `/chat` 一把梭路由（Plan #03 golden test 在用）的基础上，
补 3 个 thin adapter 路由对接前端 chat tab：
- POST /sessions          创建 session（可携带 initial_message 入槽）
- POST /sessions/{id}/messages  追加用户输入到槽
- GET  /sessions/{id}/stream    从槽取 prompt 跑 run_agent_loop

槽是 module-level dict（process-local，单实例 OK；多 worker 需要外部缓存，
Plan #04 V1 不要求多实例）。
"""

from __future__ import annotations

import json
import threading
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.orchestrator_agent.ack_bus import resolve_ack
from app.services.orchestrator_agent.agent_loop import run_agent_loop
from app.services.orchestrator_agent.memory_policy import build_memory_record
from app.services.orchestrator_agent.memory_store import (
    DEFAULT_COUNTRY,
    DEFAULT_PROJECT_ID,
    DEFAULT_USER_ID,
    MemoryStoreConflict,
    MemoryStoreNotFound,
    SQLiteMemoryStore,
    memory_retrieval_top_k,
)
from app.services.orchestrator_agent.schemas import OrchestratorChatRequest
from app.services.orchestrator_agent.session_store import (
    create_session, get_session, save_session,
)


router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


# Pending-prompt 槽：session_id → 下一轮要喂给 agent_loop 的 prompt
# POST /sessions 与 POST /sessions/{id}/messages 写入；GET /sessions/{id}/stream 读取并清空。
_PENDING_PROMPTS_LOCK = threading.Lock()
_PENDING_PROMPTS: dict[str, str] = {}


def _set_pending_prompt(session_id: str, prompt: str) -> None:
    with _PENDING_PROMPTS_LOCK:
        _PENDING_PROMPTS[session_id] = prompt


def _pop_pending_prompt(session_id: str) -> Optional[str]:
    with _PENDING_PROMPTS_LOCK:
        return _PENDING_PROMPTS.pop(session_id, None)


@router.post("/chat")
async def chat_endpoint(req: OrchestratorChatRequest, request: Request) -> StreamingResponse:
    identity = _identity_from_request(request)
    if req.session_id:
        sess = get_session(req.session_id)
        if sess is None:
            raise HTTPException(404, f"Session {req.session_id} not found")
    else:
        sess = create_session(**identity)

    async def event_stream() -> AsyncGenerator[bytes, None]:
        async for evt in run_agent_loop(session=sess, prompt=req.prompt, **identity):
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b'data: {"type": "done"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ===== Plan #04 chat-tab 前端对接路由 =====


class _CreateSessionBody(BaseModel):
    initial_message: Optional[str] = None


@router.post("/sessions")
async def create_session_endpoint(body: _CreateSessionBody, request: Request) -> dict:
    identity = _identity_from_request(request)
    sess = create_session(**identity)
    if body.initial_message:
        _set_pending_prompt(sess.session_id, body.initial_message)
    return {
        "session_id": sess.session_id,
        "created_at": sess.created_at.isoformat(),
        **identity,
    }


class _SendMessageBody(BaseModel):
    content: str


@router.post("/sessions/{session_id}/messages")
async def send_message_endpoint(session_id: str, body: _SendMessageBody, request: Request) -> dict:
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(404, f"Session {session_id} not found")
    _apply_request_identity(sess, request)
    _set_pending_prompt(session_id, body.content)
    return {"ok": True}


@router.get("/sessions/{session_id}/stream")
async def stream_endpoint(session_id: str, request: Request) -> StreamingResponse:
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(404, f"Session {session_id} not found")
    identity = _apply_request_identity(sess, request)
    prompt = _pop_pending_prompt(session_id)

    async def event_stream() -> AsyncGenerator[bytes, None]:
        if not prompt:
            yield b'data: {"type": "done"}\n\n'
            return
        async for evt in run_agent_loop(session=sess, prompt=prompt, **identity):
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b'data: {"type": "done"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class _AckBody(BaseModel):
    """兼容两种 body：
    - 旧（Plan #03 golden test）: {"confirm": true}
    - 新（Plan #04 前端 chat panel）: {"tool_call_id": "...", "decision": "approve"|"reject"}
    """

    confirm: Optional[bool] = None
    tool_call_id: Optional[str] = None
    decision: Optional[str] = None


@router.post("/sessions/{session_id}/ack")
async def ack_endpoint(session_id: str, body: _AckBody) -> dict:
    if body.confirm is not None:
        confirm = body.confirm
    elif body.decision is not None:
        confirm = body.decision == "approve"
    else:
        raise HTTPException(422, "ack body must contain either 'confirm' or 'decision'")
    ok = resolve_ack(session_id, confirm)
    return {"resolved": ok}


@router.get("/sessions/{session_id}")
async def get_session_endpoint(session_id: str) -> dict:
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(404, f"Session {session_id} not found")
    return sess.model_dump(mode="json")


class _MemoryQueryBody(BaseModel):
    query: str = Field("", max_length=2000)
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    top_k: Optional[int] = Field(None, ge=1, le=50)


class _MemoryCreateBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    category: str = "reference"
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    country: Optional[str] = None
    session_id: Optional[str] = None
    scope: str = "user"
    memory_type: str = "semantic"
    tags: list[str] = Field(default_factory=list)
    importance: Optional[float] = Field(None, ge=0, le=1)
    confidence: float = Field(0.8, ge=0, le=1)
    expires_at: Optional[str] = None


class _MemoryUpdateBody(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=4000)
    category: Optional[str] = None
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    country: Optional[str] = None
    tags: Optional[list[str]] = None
    importance: Optional[float] = Field(None, ge=0, le=1)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    expires_at: Optional[str] = None


@router.get("/memory/status")
async def memory_status_endpoint() -> dict:
    return {"success": True, **SQLiteMemoryStore().status()}


@router.get("/memory/list")
async def memory_list_endpoint(
    request: Request,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    country: Optional[str] = None,
    status: Optional[str] = "active",
    category: Optional[str] = None,
    limit: int = 100,
) -> dict:
    identity = _identity_from_request(request, user_id=user_id, project_id=project_id, country=country)
    normalized_status = None if str(status or "").lower() == "all" else (status or "active")
    results = SQLiteMemoryStore().list_records(
        user_id=identity["user_id"],
        project_id=identity["project_id"],
        country=identity["country"],
        status=normalized_status,
        category=category,
        limit=max(1, min(1000, int(limit or 100))),
    )
    return {
        "success": True,
        **identity,
        "status": normalized_status or "all",
        "category": category,
        "results": results,
    }


@router.post("/memory/query")
async def memory_query_endpoint(body: _MemoryQueryBody, request: Request) -> dict:
    identity = _identity_from_request(
        request,
        user_id=body.user_id,
        project_id=body.project_id,
        country=body.country,
    )
    top_k = body.top_k or memory_retrieval_top_k()
    store = SQLiteMemoryStore()
    results = store.search(
        body.query,
        user_id=identity["user_id"],
        project_id=identity["project_id"],
        country=identity["country"],
        category=body.category,
        top_k=top_k,
    )
    return {
        "success": True,
        "query": body.query,
        **identity,
        "category": body.category,
        "top_k": top_k,
        "results": results,
    }


@router.post("/memory")
async def memory_create_endpoint(body: _MemoryCreateBody, request: Request) -> dict:
    identity = _identity_from_request(
        request,
        user_id=body.user_id,
        project_id=body.project_id,
        country=body.country,
    )
    decision = build_memory_record(
        content=body.content,
        category=body.category,
        user_id=identity["user_id"],
        project_id=identity["project_id"],
        session_id=body.session_id,
        country=identity["country"],
        scope=body.scope,
        memory_type=body.memory_type,
        source="memory_admin",
        tags=body.tags,
        importance=body.importance,
        confidence=body.confidence,
        metadata={"admin_action": "create"},
    )
    if not decision.accepted or decision.record is None:
        raise HTTPException(status_code=422, detail={"reason": decision.reason})
    decision.record.expires_at = body.expires_at
    store = SQLiteMemoryStore()
    record = store.add(decision.record)
    memory = store.get(
        record.memory_id,
        user_id=identity["user_id"],
        project_id=identity["project_id"],
        country=identity["country"],
    )
    return {
        "success": True,
        "memory": memory,
        "redaction_hits": decision.redaction_hits,
    }


@router.patch("/memory/{memory_id}")
async def memory_update_endpoint(memory_id: str, body: _MemoryUpdateBody, request: Request) -> dict:
    identity = _identity_from_request(
        request,
        user_id=body.user_id,
        project_id=body.project_id,
        country=body.country,
    )
    store = SQLiteMemoryStore()
    existing = _get_memory_or_404(store, memory_id, identity)

    expires_at = existing.get("expires_at")
    if "expires_at" in body.model_fields_set:
        expires_at = body.expires_at
    metadata = dict(existing.get("metadata") or {})
    metadata["admin_action"] = "update"
    decision = build_memory_record(
        content=body.content if body.content is not None else existing["content"],
        category=body.category if body.category is not None else existing["category"],
        user_id=identity["user_id"],
        project_id=identity["project_id"],
        session_id=existing.get("session_id"),
        country=identity["country"],
        scope=existing.get("scope") or "user",
        memory_type=existing.get("memory_type") or "semantic",
        source="memory_admin",
        tags=body.tags if body.tags is not None else existing.get("tags", []),
        importance=body.importance if body.importance is not None else existing.get("importance"),
        confidence=body.confidence if body.confidence is not None else existing.get("confidence", 0.8),
        metadata=metadata,
    )
    if not decision.accepted or decision.record is None:
        raise HTTPException(status_code=422, detail={"reason": decision.reason})
    decision.record.memory_id = memory_id
    decision.record.status = existing.get("status") or "active"
    decision.record.created_at = existing.get("created_at") or decision.record.created_at
    decision.record.expires_at = expires_at
    try:
        record = store.update(decision.record)
    except MemoryStoreConflict as exc:
        raise HTTPException(status_code=409, detail={"reason": "duplicate_memory", "memory_id": str(exc)}) from exc
    except MemoryStoreNotFound as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc
    memory = store.get(
        record.memory_id,
        user_id=identity["user_id"],
        project_id=identity["project_id"],
        country=identity["country"],
    )
    return {"success": True, "memory": memory, "redaction_hits": decision.redaction_hits}


@router.post("/memory/{memory_id}/archive")
async def memory_archive_endpoint(
    memory_id: str,
    request: Request,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    country: Optional[str] = None,
) -> dict:
    return _set_memory_status(memory_id, "archived", request, user_id, project_id, country)


@router.post("/memory/{memory_id}/restore")
async def memory_restore_endpoint(
    memory_id: str,
    request: Request,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    country: Optional[str] = None,
) -> dict:
    return _set_memory_status(memory_id, "active", request, user_id, project_id, country)


@router.delete("/memory/{memory_id}")
async def memory_delete_endpoint(
    memory_id: str,
    request: Request,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    country: Optional[str] = None,
) -> dict:
    return _set_memory_status(memory_id, "deleted", request, user_id, project_id, country)


def _identity_from_request(
    request: Request,
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    country: str | None = None,
) -> dict[str, str]:
    return {
        "user_id": user_id or request.headers.get("X-User-ID") or DEFAULT_USER_ID,
        "project_id": project_id or request.headers.get("X-Project-ID") or DEFAULT_PROJECT_ID,
        "country": (country or request.headers.get("X-Country") or DEFAULT_COUNTRY).lower(),
    }


def _apply_request_identity(sess, request: Request) -> dict[str, str]:
    identity = _identity_from_request(request)
    sess.user_id = identity["user_id"]
    sess.project_id = identity["project_id"]
    sess.country = identity["country"]
    save_session(sess)
    return identity


def _get_memory_or_404(
    store: SQLiteMemoryStore,
    memory_id: str,
    identity: dict[str, str],
) -> dict:
    memory = store.get(
        memory_id,
        user_id=identity["user_id"],
        project_id=identity["project_id"],
        country=identity["country"],
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return memory


def _set_memory_status(
    memory_id: str,
    status: str,
    request: Request,
    user_id: str | None,
    project_id: str | None,
    country: str | None,
) -> dict:
    identity = _identity_from_request(
        request,
        user_id=user_id,
        project_id=project_id,
        country=country,
    )
    try:
        memory = SQLiteMemoryStore().set_status(memory_id, status=status, **identity)
    except MemoryStoreNotFound as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc
    return {"success": True, "memory": memory}
