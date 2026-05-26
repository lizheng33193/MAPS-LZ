"""Agent Loop: drive LLM ↔ tools ↔ session for one user prompt.

Phase 3 Task 3.3 — 主循环（含工具 dispatch + budget + consecutive_failures），
**query_data 走普通工具路径**（无 ACK 时序）。

Phase 3 Task 3.4 在本文件追加 ACK 分支特殊处理，工具中 query_data 单独拆开。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import queue
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from app.core.model_client import ModelClient
from app.services.orchestrator_agent.budget import (
    BudgetExceeded, check_and_increment,
)
from app.services.orchestrator_agent.resilience import (
    ConsecutiveFailures, check_consecutive_failures,
)
from app.services.orchestrator_agent.schemas import (
    OrchestratorMessage, OrchestratorSession, ToolCallRecord,
)
from app.services.orchestrator_agent.session_store import save_session
from app.services.orchestrator_agent.system_prompt import assemble_system_prompt
from app.services.orchestrator_agent.context_fit import (
    ensure_context_fits, load_session_memories,
    MODEL_MAX_TOKENS_PER_TURN,
)
from app.services.orchestrator_agent.memory_context import (
    apply_identity,
    append_rolling_summary,
    build_retrieved_memory_context,
    maybe_write_task_memory,
)
from app.services.orchestrator_agent.memory_policy import classify_user_memory_content
from app.services.orchestrator_agent.tools import get_tool_registry


MAX_ROUNDS = 15
LOGGER = logging.getLogger(__name__)

# R7 P0-3 Knowledge 层注入：在首轮 LLM call 前用 keyword regex 从 prompt 中提取 country code，
# 传给 assemble_system_prompt(country) 动态拼接对应 docs/skills/orchestrator/{country}.md。
# V1 只走名字/短码粗粒度匹配，匹不到 → country=None → base prompt 不含国别规则段（LLM 需问用户）。
# R9 P0-1：使用中文字面量而非 unicode escape，避免 \u5893 (墓) 与 \u58a8 (墨) 视觉混淆造成的隐蔽 bug。
_COUNTRY_RE = re.compile(
    r"\b(th|mx|co|pe|cl|br)\b|墨西哥|泰国|哥伦比亚|秘鲁|智利|巴西|"
    r"thailand|mexico|colombia|peru|chile|brazil",
    re.IGNORECASE,
)
_NAME_TO_CODE = {
    "墨西哥": "mx", "mexico": "mx",
    "泰国": "th", "thailand": "th",
    "哥伦比亚": "co", "colombia": "co",
    "秘鲁": "pe", "peru": "pe",
    "智利": "cl", "chile": "cl",
    "巴西": "br", "brazil": "br",
}


def _detect_country(prompt: str) -> str | None:
    """V1 粗粒度提取：keyword + 2-位短码 regex。匹不到返回 None。"""
    m = _COUNTRY_RE.search(prompt)
    if not m:
        return None
    raw = m.group(0).lower()
    return raw if len(raw) == 2 else _NAME_TO_CODE.get(raw)


def _input_schema_for(tool_name: str):
    from app.services.orchestrator_agent import schemas as S
    return {
        "parse_uid_file": S.ParseUidFileInput,
        "run_profile": S.RunProfileInput,
        "run_trace": S.RunTraceInput,
        "query_data": S.QueryDataInput,
        "memory_write": S.MemoryWriteInput,
        "memory_read": S.MemoryReadInput,
    }[tool_name]


def _build_llm_input(system_prompt: str, messages: list) -> str:
    parts = [system_prompt, "\n\n--- 对话历史 ---\n"]
    for m in messages:
        parts.append(f"[{m.role}] {m.content}\n")
    parts.append("\n--- 请输出下一步决策 JSON ---\n")
    return "".join(parts)


async def run_agent_loop(
    session: OrchestratorSession,
    prompt: str,
    user_id: str | None = None,
    project_id: str | None = None,
    country: str | None = None,
) -> AsyncGenerator[dict, None]:
    yield {"type": "session_started", "session_id": session.session_id}

    detected_country = (country or _detect_country(prompt) or session.country)
    apply_identity(
        session,
        user_id=user_id,
        project_id=project_id,
        country=detected_country,
    )
    session.messages.append(OrchestratorMessage(
        role="user", content=prompt, timestamp=datetime.now(timezone.utc),
    ))
    save_session(session)

    client = ModelClient()
    tool_registry = get_tool_registry()
    # R7 P0-3 Knowledge 层注入：从 prompt 提取 country code，动态拼接国别规则段。
    # 匹不到 → country=None → base prompt 不含国别规则，LLM 需问用户。
    system_prompt = assemble_system_prompt(detected_country)
    system_prompt = append_rolling_summary(system_prompt, session)

    retrieved_context, retrieved_memories = build_retrieved_memory_context(
        session=session,
        query=prompt,
        country=detected_country,
    )
    if retrieved_context:
        system_prompt = system_prompt + "\n\n" + retrieved_context

    # Plan 10 Phase 4 集成点 1：首轮拼接长期记忆（不进 messages，仅拼 system_prompt）。
    if detected_country and len(session.messages) == 1 and not retrieved_memories:
        memory_context = load_session_memories(session.session_id, detected_country)
        if memory_context:
            system_prompt = system_prompt + "\n\n" + memory_context

    for round_idx in range(MAX_ROUNDS):
        # 1) LLM 决策（同步 generate_structured 用 to_thread 包装）
        llm_input = _build_llm_input(system_prompt, session.messages)
        try:
            llm_out = await asyncio.to_thread(
                client.generate_structured,
                skill_name="orchestrator_agent",
                prompt=llm_input,
                fallback_result={
                    "final_message": "AI 服务暂时不可用，请稍后重试",
                    "tool_call": None,
                    "confidence": 0.0,
                },
                route_key="orchestrator_agent.decide",
            )
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            session.status = "error"
            save_session(session)
            return

        # 2) Budget 累加（last_token_usage 来自 Plan #01 R5 契约）
        try:
            usage = getattr(client, "last_token_usage", {}) or {}
            budget = check_and_increment(session, int(usage.get("total", 0)))
        except BudgetExceeded as exc:
            yield {"type": "error", "message": str(exc)}
            session.status = "budget_exceeded"
            save_session(session)
            return
        if budget["warn"]:
            yield {"type": "budget_warning", **budget}

        decision = llm_out.get("structured_result", {}) or {}

        # 3) Final?
        if decision.get("final_message"):
            session.final_message = decision["final_message"]
            session.confidence = decision.get("confidence")
            session.status = "completed"
            # Plan #04 hotfix：把 assistant final 也 append 进 messages，
            # 否则 GET /sessions/{id} 拿不到 assistant 气泡 → TC-4 刷新恢复缺 AI 回复。
            session.messages.append(OrchestratorMessage(
                role="assistant",
                content=decision["final_message"],
                timestamp=datetime.now(timezone.utc),
            ))
            session.rolling_summary = _append_summary_line(
                session.rolling_summary,
                prompt,
                decision["final_message"],
            )
            maybe_write_task_memory(
                session=session,
                user_text=prompt,
                assistant_text=decision["final_message"],
                country=detected_country,
            )
            save_session(session)
            yield {
                "type": "final",
                "final_message": decision["final_message"],
                "total_rounds": round_idx + 1,
                "total_tokens": session.total_tokens,
                "confidence": session.confidence or 0.0,
            }
            return

        # 4) Tool call
        tool_call = decision.get("tool_call")
        if not tool_call:
            yield {"type": "error", "message": "LLM did not produce final or tool_call"}
            session.status = "error"
            save_session(session)
            return

        tool_name = tool_call["name"]
        tool_input = tool_call["arguments"]
        tool_call_id = uuid.uuid4().hex

        record = ToolCallRecord(
            tool_name=tool_name, tool_call_id=tool_call_id,
            input=tool_input, status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.tool_calls.append(record)
        save_session(session)
        yield {
            "type": "tool_started",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "input": tool_input,
        }

        # 5) Execute tool
        # query_data 走 ACK 时序分支（Step A: generate → Step B: yield awaiting → 
        # Step C: wait_ack → Step D: execute）；其它工具走普通路径。
        try:
            if tool_name == "query_data":
                # ⚠️ R7 P0-4：以下 3 个 function-local import **必须保持在函数体内**，
                # 不能上提到 module top。原因：Task 4.2 Golden runner 用
                # `monkeypatch.setattr(ack_bus, "open_ack", _patched_open_ack)` 自动放行 ACK，
                # 该 patch 生效依赖于函数运行时才从 module 重新取 open_ack。
                # 一旦上提到 module top → monkeypatch 失效 → case_05 卡 600s 超时。
                from app.services.orchestrator_agent.tools.query_data import _ChildAgent
                from app.services.orchestrator_agent.ack_bus import open_ack, wait_ack
                from app.services.orchestrator_agent.session import (
                    is_query_cancelled, mark_query_cancelled,
                )

                # 同 session 内之前 ACK 拒绝过 → 直接拒，不进 generate
                if is_query_cancelled(session.session_id):
                    raise PermissionError("user cancelled in this session")

                child = _ChildAgent(country=tool_input["country"])

                # Step A: 同步阻塞操作放 to_thread（generate SQL）
                qr = await asyncio.to_thread(child.run_query, tool_input["request"])

                # Step B: 显式 yield awaiting_user_ack（非阻塞，立即 flush 给前端）
                yield {
                    "type": "awaiting_user_ack",
                    "tool_call_id": tool_call_id,
                    "sql_text": qr.sql_text,
                    "rows_estimated": qr.rows_estimated,
                }

                # Step C: 等 ACK（threading.Event 用 to_thread 包，不卡 event loop）
                open_ack(session.session_id)
                confirm = await asyncio.to_thread(wait_ack, session.session_id, 600.0)
                if not confirm:
                    mark_query_cancelled(session.session_id)
                    raise PermissionError("User rejected SQL execution")

                # Step D: ACK 通过 → 执行
                execute_out = await asyncio.to_thread(child.execute, qr.sql_text)
                output = {
                    "uids": execute_out["uids"],
                    "rows_actual": execute_out["rows_actual"],
                    "sql_text": qr.sql_text,
                    "rows_estimated": qr.rows_estimated,
                }
            else:
                tool_fn = tool_registry[tool_name]
                schema_cls = _input_schema_for(tool_name)
                input_obj = schema_cls(**tool_input)
                if tool_name in {"memory_write", "memory_read"}:
                    from app.services.orchestrator_agent.tools.memory import (
                        memory_read_scoped,
                        memory_write_scoped,
                    )

                    scoped_fn = memory_write_scoped if tool_name == "memory_write" else memory_read_scoped
                    output_obj = await asyncio.to_thread(
                        scoped_fn,
                        input_obj,
                        user_id=session.user_id,
                        project_id=session.project_id,
                        default_country=detected_country or session.country or "mx",
                    )
                else:
                    if tool_name == "run_profile":
                        progress_q: queue.Queue = queue.Queue()

                        def _progress_cb(progress_evt: dict) -> None:
                            progress_q.put(("progress", progress_evt, None))

                        def _worker() -> None:
                            try:
                                progress_output = _call_tool_with_optional_progress(
                                    tool_fn,
                                    input_obj,
                                    _progress_cb,
                                )
                                progress_q.put(("done", progress_output, None))
                            except Exception as worker_exc:  # noqa: BLE001
                                progress_q.put(("error", None, worker_exc))

                        threading.Thread(target=_worker, daemon=True).start()
                        while True:
                            kind, payload, worker_exc = await asyncio.to_thread(progress_q.get)
                            if kind == "progress":
                                _log_run_profile_progress(
                                    session_id=session.session_id,
                                    tool_call_id=tool_call_id,
                                    payload=payload or {},
                                )
                                if (payload or {}).get("progress_type") != "profile_module_completed":
                                    continue
                                yield {
                                    "type": "tool_progress",
                                    "tool_call_id": tool_call_id,
                                    "tool_name": tool_name,
                                    **(payload or {}),
                                }
                                continue
                            if kind == "error":
                                raise worker_exc
                            output_obj = payload
                            break
                    else:
                        output_obj = await asyncio.to_thread(tool_fn, input_obj)
                output = output_obj.model_dump(mode="json")

            record.output = output
            record.status = "done"
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {
                "type": "tool_completed",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "output": output,
                "status": "ok",
            }
            classified_user_memory = classify_user_memory_content(prompt)
            if (
                tool_name == "memory_write"
                and output.get("ok")
                and classified_user_memory
                and classified_user_memory[0] in {"preference", "feedback", "project", "reference"}
            ):
                final_message = "已记住。"
                session.final_message = final_message
                session.confidence = 0.95
                session.status = "completed"
                session.messages.append(OrchestratorMessage(
                    role="assistant",
                    content=final_message,
                    timestamp=datetime.now(timezone.utc),
                ))
                session.rolling_summary = _append_summary_line(
                    session.rolling_summary,
                    prompt,
                    final_message,
                )
                save_session(session)
                yield {
                    "type": "final",
                    "final_message": final_message,
                    "total_rounds": round_idx + 1,
                    "total_tokens": session.total_tokens,
                    "confidence": session.confidence,
                }
                return
        except Exception as exc:
            record.status = "error"
            record.output = {"error": str(exc)}
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {
                "type": "tool_completed",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "output": {"error": str(exc)},
                "status": "error",
            }
        # 6) Consecutive failure tripwire
        try:
            check_consecutive_failures(session, record.status)
        except ConsecutiveFailures as exc:
            yield {"type": "consecutive_tool_failures", "message": str(exc)}
            session.status = "error"
            save_session(session)
            return

        # 7) Append tool result for next round
        session.messages.append(OrchestratorMessage(
            role="tool", tool_call_id=tool_call_id,
            content=json.dumps(record.output, ensure_ascii=False),
            timestamp=datetime.now(timezone.utc),
        ))
        save_session(session)

        # Plan 10 Phase 4 集成点 2：本轮工具结果落盘后、下一轮 LLM 调用前检查压缩。
        ensure_context_fits(
            session,
            country=detected_country or "mx",
            max_tokens=MODEL_MAX_TOKENS_PER_TURN,
        )

    # MAX_ROUNDS reached without final
    yield {"type": "error", "message": f"Max rounds {MAX_ROUNDS} reached"}
    session.status = "error"
    save_session(session)


def _append_summary_line(existing: str | None, prompt: str, final_message: str) -> str:
    line = (
        f"- User: {prompt[:220].strip()} | "
        f"Assistant: {final_message[:320].strip()}"
    )
    combined = "\n".join(part for part in [existing, line] if part)
    return combined[-2500:]


def _call_tool_with_optional_progress(tool_fn, input_obj, progress_callback):
    """Call tools that may support a progress_callback without breaking old fakes."""
    try:
        params = inspect.signature(tool_fn).parameters.values()
        supports_progress = any(
            p.name == "progress_callback" or p.kind == inspect.Parameter.VAR_KEYWORD
            for p in params
        )
    except (TypeError, ValueError):
        supports_progress = False
    if supports_progress:
        return tool_fn(input_obj, progress_callback=progress_callback)
    return tool_fn(input_obj)


def _log_run_profile_progress(session_id: str, tool_call_id: str, payload: dict) -> None:
    progress_type = payload.get("progress_type") or "profile_module_progress"
    event = {
        "profile_module_started": "run_profile_module_started",
        "profile_module_completed": "run_profile_module_completed",
        "profile_module_error": "run_profile_module_error",
    }.get(progress_type, "run_profile_module_progress")
    extra = {
        "event": event,
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "uid": payload.get("uid"),
        # `module` is a reserved LogRecord attribute, so keep the structured
        # value under profile_module while preserving module=... in the message.
        "profile_module": payload.get("module"),
        "completed": payload.get("completed"),
        "total": payload.get("total"),
        "status": payload.get("status"),
        "elapsed_ms": payload.get("elapsed_ms"),
    }
    LOGGER.info(
        "%s session_id=%s tool_call_id=%s uid=%s module=%s completed=%s total=%s status=%s elapsed_ms=%s",
        event,
        session_id,
        tool_call_id,
        payload.get("uid"),
        payload.get("module"),
        payload.get("completed"),
        payload.get("total"),
        payload.get("status"),
        payload.get("elapsed_ms"),
        extra=extra,
    )
