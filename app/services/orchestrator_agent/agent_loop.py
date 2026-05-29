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
from typing import Any, AsyncGenerator

from app.core.data_acquisition_capability import (
    data_acquisition_unavailable_message,
    get_data_acquisition_capability,
)
from app.core.model_client import ModelClient
from app.services.orchestrator_agent.budget import (
    BudgetExceeded, check_and_increment,
)
from app.services.orchestrator_agent.data_availability import check_data_availability
from app.services.orchestrator_agent.resilience import (
    ConsecutiveFailures, check_consecutive_failures,
)
from app.services.orchestrator_agent.repair_profile_data import (
    RepairProfileDataInput,
    execute_repair_query,
    prepare_repair_query,
    repair_profile_data,
)
from app.services.orchestrator_agent.request_understanding import build_request_understanding
from app.services.orchestrator_agent.request_router import normalize_request
from app.services.orchestrator_agent.routing_classifier import refine_normalized_request
from app.services.orchestrator_agent.review_rules import (
    build_no_workspace_review,
    build_profile_review as build_profile_review_rule,
    review_step_summary as review_step_summary_rule,
)
from app.services.orchestrator_agent.schemas import (
    DataAvailability,
    ExecutionPlan,
    ExecutionTraceRecord,
    NormalizedRequest,
    OrchestratorMessage,
    OrchestratorSession,
    PlanStep,
    ReviewResult,
    ToolCallRecord,
)
from app.services.orchestrator_agent.session_store import save_session
from app.services.orchestrator_agent.system_prompt import assemble_system_prompt
from app.services.orchestrator_agent.visible_execution import (
    answer_from_workspace_with_evidence,
    build_workspace_evidence_bundle,
)
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
_ORIGINAL_REPAIR_PROFILE_DATA = repair_profile_data

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

_UID_RE = re.compile(r"\b\d{18}\b")
_RERUN_HINTS = ("重新分析", "重新跑", "刷新", "最新", "重新生成")
_READ_ONLY_HINTS = (
    "综合画像", "用户画像", "行为画像", "行为摘要", "行为特点", "征信画像", "app画像",
    "产品策略", "运营策略", "挽留方式", "总结", "简单描述", "概括", "特点",
)
_MODULE_PROMPT_HINTS: dict[str, tuple[str, ...]] = {
    "app": ("app画像", "应用画像", "app 使用", "安装应用", "app安装"),
    "behavior": ("行为画像", "行为摘要", "行为特点", "活跃度", "流失风险"),
    "credit": ("征信画像", "信用画像", "征信", "信用分", "负债"),
    "comprehensive": ("综合画像", "用户画像", "总体画像", "整体画像"),
    "product": ("产品策略", "挽留方式", "续贷策略", "产品建议"),
    "ops": ("运营策略", "催收策略", "触达策略", "运营建议"),
}
_PROFILE_MODULE_LABELS = {
    "app": "App画像",
    "behavior": "行为画像",
    "credit": "征信画像",
    "comprehensive": "综合画像",
    "product": "产品策略",
    "ops": "运营策略",
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


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _detect_requested_modules(prompt: str) -> list[str]:
    matched: list[str] = []
    for module_name, hints in _MODULE_PROMPT_HINTS.items():
        if _has_any(prompt, hints):
            matched.append(module_name)
    if matched:
        return matched
    if _has_any(prompt, _READ_ONLY_HINTS):
        return ["comprehensive"]
    return []


def _extract_requested_uid(prompt: str) -> str | None:
    matched = _UID_RE.search(prompt or "")
    return matched.group(0) if matched else None


def _normalize_snapshot_row(
    row: dict[str, Any],
    *,
    default_country: str | None,
    default_app_time: str | None,
) -> dict[str, Any] | None:
    uid = str(row.get("uid") or "").strip()
    module = str(row.get("module") or "").strip()
    if not uid or not module:
        return None
    structured_result = row.get("structured_result")
    if not isinstance(structured_result, dict):
        structured_result = {}
    return {
        "uid": uid,
        "module": module,
        "summary": str(row.get("summary") or "").strip(),
        "structured_result": structured_result,
        "country": row.get("country") or default_country,
        "applicationTime": row.get("applicationTime") or default_app_time,
    }


def _extract_reusable_profile_results(session: OrchestratorSession) -> dict[str, dict[str, dict[str, Any]]]:
    reusable: dict[str, dict[str, dict[str, Any]]] = {}

    def _put(entry: dict[str, Any], *, overwrite: bool) -> None:
        uid = entry["uid"]
        module = entry["module"]
        reusable.setdefault(uid, {})
        if overwrite or module not in reusable[uid]:
            reusable[uid][module] = entry

    for record in session.tool_calls:
        if record.tool_name != "run_profile" or record.status != "done" or not isinstance(record.output, dict):
            continue
        default_app_time = record.input.get("app_time") if isinstance(record.input, dict) else None
        rows = record.output.get("results")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            result = row.get("result")
            data = result.get("data") if isinstance(result, dict) else None
            if not (isinstance(result, dict) and result.get("status") == "ok" and isinstance(data, dict)):
                continue
            normalized = _normalize_snapshot_row(
                {
                    "uid": row.get("uid"),
                    "module": row.get("module"),
                    "summary": data.get("summary"),
                    "structured_result": data.get("structured_result"),
                },
                default_country=session.country,
                default_app_time=default_app_time,
            )
            if normalized:
                _put(normalized, overwrite=True)

    session_snapshot = session.active_entities.get("workspace_snapshot")
    if isinstance(session_snapshot, dict):
        default_country = session_snapshot.get("country") or session.country
        default_app_time = session_snapshot.get("applicationTime")
        rows = session_snapshot.get("results")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized = _normalize_snapshot_row(
                    row,
                    default_country=default_country,
                    default_app_time=default_app_time,
                )
                if normalized:
                    _put(normalized, overwrite=False)

    return reusable


def _pick_snapshot_uid(
    prompt: str,
    reusable_results: dict[str, dict[str, dict[str, Any]]],
) -> str | None:
    requested_uid = _extract_requested_uid(prompt)
    if requested_uid and requested_uid in reusable_results:
        return requested_uid
    if len(reusable_results) == 1:
        return next(iter(reusable_results.keys()))
    if reusable_results:
        return next(iter(reusable_results.keys()))
    return None


def _build_snapshot_final_message(
    prompt: str,
    *,
    uid: str,
    modules: list[str],
    entries: dict[str, dict[str, Any]],
) -> str:
    if modules == ["behavior"] and entries.get("behavior"):
        behavior = entries["behavior"]
        return (
            f"## 行为画像分析报告：UID {uid}\n\n"
            f"{behavior.get('summary') or '暂无行为画像摘要。'}"
        )

    if modules == ["app"] and entries.get("app"):
        app_result = entries["app"]
        return (
            f"## App画像分析报告：UID {uid}\n\n"
            f"{app_result.get('summary') or '暂无 App 画像摘要。'}"
        )

    if modules == ["credit"] and entries.get("credit"):
        credit = entries["credit"]
        return (
            f"## 征信画像分析报告：UID {uid}\n\n"
            f"{credit.get('summary') or '暂无征信画像摘要。'}"
        )

    if modules == ["product"] and entries.get("product"):
        product = entries["product"]
        return (
            f"## 产品策略建议：UID {uid}\n\n"
            f"{product.get('summary') or '暂无产品策略摘要。'}"
        )

    if modules == ["ops"] and entries.get("ops"):
        ops = entries["ops"]
        return (
            f"## 运营策略建议：UID {uid}\n\n"
            f"{ops.get('summary') or '暂无运营策略摘要。'}"
        )

    comprehensive = entries.get("comprehensive")
    lines = [f"## 综合画像分析报告：UID {uid}", ""]
    if comprehensive:
        lines.append(comprehensive.get("summary") or "暂无综合画像摘要。")
    else:
        lines.append("暂无综合画像摘要。")

    detail_modules = ["app", "behavior", "credit", "product", "ops"]
    detail_lines = []
    for module_name in detail_modules:
        entry = entries.get(module_name)
        if not entry:
            continue
        detail_lines.append(
            f"- **{_PROFILE_MODULE_LABELS[module_name]}**：{entry.get('summary') or '暂无摘要。'}"
        )
    if detail_lines:
        lines.extend(["", "### 已有模块结论", *detail_lines])
    return "\n".join(lines)


def _maybe_answer_from_reusable_results(
    session: OrchestratorSession,
    prompt: str,
    detected_country: str | None,
) -> str | None:
    if _has_any(prompt, _RERUN_HINTS):
        return None
    required_modules = _detect_requested_modules(prompt)
    if not required_modules:
        return None

    reusable_results = _extract_reusable_profile_results(session)
    if not reusable_results:
        return None

    uid = _pick_snapshot_uid(prompt, reusable_results)
    if not uid:
        return None
    entries = reusable_results.get(uid) or {}
    if any(module_name not in entries for module_name in required_modules):
        return None

    if detected_country:
        for module_name in required_modules:
            entry_country = str(entries[module_name].get("country") or "").strip().lower()
            if entry_country and entry_country != detected_country.lower():
                return None

    return _build_snapshot_final_message(
        prompt,
        uid=uid,
        modules=required_modules,
        entries=entries,
    )


def _persist_final_message(
    session: OrchestratorSession,
    *,
    prompt: str,
    final_message: str,
    confidence: float,
    detected_country: str | None,
) -> dict[str, Any]:
    session.final_message = final_message
    session.confidence = confidence
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
    maybe_write_task_memory(
        session=session,
        user_text=prompt,
        assistant_text=final_message,
        country=detected_country,
    )
    save_session(session)
    return {
        "type": "final",
        "final_message": final_message,
        "total_rounds": 1,
        "total_tokens": session.total_tokens,
        "confidence": confidence,
    }


def _create_execution_trace(
    session: OrchestratorSession,
    *,
    execution_id: str,
    prompt: str,
    normalized_request: NormalizedRequest,
    availability: DataAvailability | None,
    steps: list[PlanStep],
) -> ExecutionTraceRecord:
    now = datetime.now(timezone.utc)
    trace = ExecutionTraceRecord(
        execution_id=execution_id,
        prompt=prompt,
        request_summary=normalized_request.request_summary,
        intent=normalized_request.intent,
        request_understanding=normalized_request.request_understanding,
        availability=availability,
        steps=steps,
        created_at=now,
        updated_at=now,
    )
    session.execution_traces.append(trace)
    save_session(session)
    return trace


def _save_trace(session: OrchestratorSession, trace: ExecutionTraceRecord) -> None:
    trace.updated_at = datetime.now(timezone.utc)
    save_session(session)


def _set_trace_availability(
    session: OrchestratorSession,
    trace: ExecutionTraceRecord,
    availability: DataAvailability,
) -> None:
    trace.availability = availability
    _save_trace(session, trace)


def _append_trace_steps(
    session: OrchestratorSession,
    trace: ExecutionTraceRecord,
    steps: list[PlanStep],
) -> None:
    trace.steps.extend(steps)
    _save_trace(session, trace)


def _update_trace_step(
    session: OrchestratorSession,
    trace: ExecutionTraceRecord,
    *,
    step_id: str,
    status: str,
    result_summary: str | None = None,
    tool_call_id: str | None = None,
) -> dict[str, Any]:
    for step in trace.steps:
        if step.step_id != step_id:
            continue
        step.status = status
        if result_summary is not None:
            step.result_summary = result_summary
        if tool_call_id is not None:
            step.tool_call_id = tool_call_id
        _save_trace(session, trace)
        return {
            "type": "plan_step_status",
            "execution_id": trace.execution_id,
            "step_id": step_id,
            "status": status,
            "result_summary": step.result_summary,
            "tool_call_id": step.tool_call_id,
        }
    return {
        "type": "plan_step_status",
        "execution_id": trace.execution_id,
        "step_id": step_id,
        "status": status,
        "result_summary": result_summary,
        "tool_call_id": tool_call_id,
    }


def _set_trace_review(
    session: OrchestratorSession,
    trace: ExecutionTraceRecord,
    review: ReviewResult,
) -> dict[str, Any]:
    trace.review = review
    _save_trace(session, trace)
    return {
        "type": "review_result",
        "execution_id": trace.execution_id,
        "status": review.status,
        "issues": review.issues,
        "confidence_impact": review.confidence_impact,
        "can_answer": review.can_answer,
    }


def _review_step_summary(review: ReviewResult) -> str:
    return review_step_summary_rule(review)


def _finalize_trace(
    session: OrchestratorSession,
    trace: ExecutionTraceRecord,
    *,
    final_status: str,
    final_message: str,
) -> None:
    trace.final_status = final_status
    trace.final_message = final_message
    _save_trace(session, trace)


def _build_execution_plan_event(
    trace: ExecutionTraceRecord,
) -> dict[str, Any]:
    plan = ExecutionPlan(
        execution_id=trace.execution_id,
        request_summary=trace.request_summary,
        intent=trace.intent,
        request_understanding=trace.request_understanding,
        availability=trace.availability,
        steps=trace.steps,
    )
    return {"type": "execution_plan", **plan.model_dump(mode="json")}


def _build_awaiting_resolution_event(
    trace: ExecutionTraceRecord,
    *,
    step_id: str,
    resolution_type: str,
    prompt: str,
    required_slots: list[str] | None = None,
    candidate_defaults: dict[str, Any] | None = None,
    options: list[str] | None = None,
    missing_bucket_counts: dict[str, int] | None = None,
    cohort_size: int | None = None,
) -> dict[str, Any]:
    return {
        "type": "awaiting_resolution",
        "execution_id": trace.execution_id,
        "step_id": step_id,
        "resolution_type": resolution_type,
        "prompt": prompt,
        "required_slots": list(required_slots or []),
        "candidate_defaults": dict(candidate_defaults or {}),
        "options": list(options or []),
        "missing_bucket_counts": dict(missing_bucket_counts or {}),
        "cohort_size": cohort_size,
        "selected_option": None,
    }


def _availability_summary(availability: DataAvailability) -> str:
    parts: list[str] = []
    for row in availability.per_uid:
        available = "/".join(row.available_buckets) if row.available_buckets else "none"
        missing = "/".join(row.missing_buckets) if row.missing_buckets else "none"
        parts.append(f"{row.uid}: available={available}; missing={missing}")
    return " | ".join(parts) if parts else "暂无可用性结果"


def _apply_clarification_answers(prompt: str, answers: dict[str, Any]) -> str:
    country = str((answers or {}).get("country") or "").strip()
    time_window = str((answers or {}).get("time_window") or "").strip()
    auto_profile = (answers or {}).get("auto_profile")
    extra: list[str] = []
    if country:
        extra.append(f"国家：{country}")
    if time_window:
        extra.append(f"时间范围：{time_window}")
    if auto_profile is not None:
        extra.append(f"自动继续画像：{'是' if bool(auto_profile) else '否'}")
    if not extra:
        return prompt
    return f"{prompt}\n" + "\n".join(extra)


def _missing_bucket_counts(availability: DataAvailability, requested_missing: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bucket in requested_missing:
        counts[bucket] = sum(1 for row in availability.per_uid if bucket in row.missing_buckets)
    return counts


def _expand_requested_modules(requested_modules: list[str], available_buckets: list[str]) -> list[str]:
    available_base = [module for module in ["app", "behavior", "credit"] if module in set(available_buckets)]
    if not requested_modules:
        if set(available_base) == {"app", "behavior", "credit"}:
            return ["app", "behavior", "credit", "comprehensive", "product", "ops"]
        return available_base

    requested = set(requested_modules)
    resolved: list[str] = []

    if any(module in requested for module in {"comprehensive", "product", "ops"}):
        if set(available_base) == {"app", "behavior", "credit"}:
            resolved.extend(["app", "behavior", "credit", "comprehensive"])
            if "product" in requested:
                resolved.append("product")
            if "ops" in requested:
                resolved.append("ops")
        else:
            resolved.extend(available_base)
    else:
        for module in ["app", "behavior", "credit"]:
            if module in requested and module in available_base:
                resolved.append(module)

    ordered: list[str] = []
    seen: set[str] = set()
    for module in resolved:
        if module in seen:
            continue
        seen.add(module)
        ordered.append(module)
    return ordered


def _build_uid_module_plan(
    availability: DataAvailability,
    normalized_request: NormalizedRequest,
) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {}
    requested_modules = list(normalized_request.modules or [])
    for row in availability.per_uid:
        plan[row.uid] = _expand_requested_modules(requested_modules, row.available_buckets)
    return plan


def _group_uid_module_plan(uid_plan: dict[str, list[str]]) -> list[tuple[list[str], list[str]]]:
    grouped: dict[tuple[str, ...], list[str]] = {}
    for uid, modules in uid_plan.items():
        grouped.setdefault(tuple(modules), []).append(uid)
    return [(list(modules), uids) for modules, uids in grouped.items()]


def _flatten_planned_modules(uid_plan: dict[str, list[str]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for module in ["app", "behavior", "credit", "comprehensive", "product", "ops"]:
        if any(module in modules for modules in uid_plan.values()) and module not in seen:
            seen.add(module)
            ordered.append(module)
    return ordered


def _required_buckets_for_request(requested_modules: list[str]) -> set[str]:
    if not requested_modules:
        return {"app", "behavior", "credit"}
    requested = set(requested_modules)
    required: set[str] = set()
    for module in {"app", "behavior", "credit"} & requested:
        required.add(module)
    if any(module in requested for module in {"comprehensive", "product", "ops"}):
        required.update({"app", "behavior", "credit"})
    return required


def _build_profile_review(
    availability: DataAvailability,
    uid_modules_run: dict[str, list[str]],
    profile_output: dict[str, Any] | None = None,
    normalized_request: NormalizedRequest | None = None,
) -> ReviewResult:
    return build_profile_review_rule(availability, uid_modules_run, profile_output, normalized_request)


def _append_data_acquisition_issue(
    review: ReviewResult,
    *,
    missing_buckets: list[str],
    blocked: bool,
) -> ReviewResult:
    issues = list(review.issues)
    issues.append({
        "type": "data_acquisition_unavailable",
        "severity": "error" if blocked else "warning",
        "missing_buckets": list(missing_buckets),
        "message": (
            "用户请求的必要数据缺失，且当前无法自动补齐。"
            if blocked
            else "缺失 bucket 当前无法自动补齐。"
        ),
    })
    confidence_impact = review.confidence_impact
    if blocked:
        confidence_impact = confidence_impact or "用户请求的必要数据当前不可用，无法生成可信画像"
    else:
        confidence_impact = confidence_impact or "缺失 bucket 当前无法自动补齐，结果基于已有数据降级输出"
    return review.model_copy(update={
        "status": "fail" if blocked else ("warning" if review.status == "pass" else review.status),
        "issues": issues,
        "can_answer": False if blocked else review.can_answer,
        "confidence_impact": confidence_impact,
    })


def _build_known_final_message(
    normalized_request: NormalizedRequest,
    *,
    profile_output: dict[str, Any] | None = None,
    trace_output: dict[str, Any] | None = None,
    review: ReviewResult | None = None,
    availability: DataAvailability | None = None,
    extra_note: str | None = None,
) -> str:
    request_understanding = normalized_request.request_understanding
    lines = [
        "## 用户请求理解",
        (request_understanding.rewritten_goal if request_understanding else normalized_request.request_summary),
        "",
    ]
    if request_understanding:
        lines.extend(["## 路径说明", request_understanding.route_reason, ""])
    if availability is not None:
        lines.extend(["## 数据完整性检查", _availability_summary(availability), ""])
    if profile_output is not None:
        lines.append("## 执行结果")
        results = profile_output.get("results") or []
        if results:
            for row in results:
                result = row.get("result") or {}
                data = result.get("data") or {}
                summary = data.get("summary") or "暂无摘要"
                lines.append(f"- {row.get('uid')} / {row.get('module')}: {summary}")
        else:
            lines.append("- 无画像结果")
        lines.append("")
    if trace_output is not None:
        lines.append("## 执行结果")
        summary = trace_output.get("summary") or {}
        story = summary.get("churn_story") or trace_output.get("churn_story") or "暂无 trace 摘要"
        lines.append(story)
        lines.append("")
    if review is not None:
        lines.append("## 规则审核")
        if review.status == "pass":
            lines.append("- 所需步骤已完成，结论可直接使用。")
        else:
            for issue in review.issues:
                if issue.get("bucket") and issue.get("uid"):
                    lines.append(f"- UID {issue['uid']} 缺少 {issue['bucket']} 数据。")
                else:
                    lines.append(f"- {issue.get('message') or issue.get('type') or '存在待关注项'}")
        if review.confidence_impact:
            lines.append(f"- 影响：{review.confidence_impact}")
        lines.append("")
    if extra_note:
        lines.extend(["## 下一步建议", extra_note])
    return "\n".join(lines).strip()


def _build_query_only_final_message(
    normalized_request: NormalizedRequest,
    *,
    output: dict[str, Any],
) -> str:
    uids = list(output.get("uids") or [])
    sql_text = str(output.get("sql_text") or "").strip() or "暂无 SQL"
    rows_actual = int(output.get("rows_actual") or 0)
    rows_estimated = int(output.get("rows_estimated") or -1)
    uid_preview = ", ".join(uids[:10]) if uids else "无"
    more_note = f"（其余 {len(uids) - 10} 个已省略）" if len(uids) > 10 else ""
    lines = [
        "## 用户请求理解",
        (normalized_request.request_understanding.rewritten_goal if normalized_request.request_understanding else normalized_request.request_summary),
        "",
        "## Query 结果",
        f"- UID 数量：{len(uids)}",
        f"- UID 列表：{uid_preview}{more_note}",
        f"- rows_estimated：{rows_estimated}",
        f"- rows_actual：{rows_actual}",
        f"- SQL：{sql_text}",
        "",
        "## 下一步建议",
        "如需继续画像，请再次提交这些 UID，或重新开启自动继续画像。",
    ]
    return "\n".join(lines).strip()


async def execute_query_data_cohort(session: OrchestratorSession, request_text: str, country: str) -> dict[str, Any]:
    """Query cohort UIDs through data_acquisition_agent with session-level cancel semantics."""
    if country != "mx":
        raise ValueError("query_data_then_profile only supports mx in v1")
    from app.services.orchestrator_agent.session import is_query_cancelled
    from app.services.orchestrator_agent.tools.query_data import _ChildAgent

    if is_query_cancelled(session.session_id):
        raise PermissionError("user cancelled in this session")

    child = _ChildAgent(country=country)
    qr = await asyncio.to_thread(child.run_query, request_text)
    return {
        "child": child,
        "sql_text": qr.sql_text,
        "rows_estimated": qr.rows_estimated,
    }


async def _complete_query_data_cohort(
    session: OrchestratorSession,
    child,
    sql_text: str,
) -> dict[str, Any]:
    execute_out = await asyncio.to_thread(child.execute, sql_text)
    return {
        "uids": list(execute_out.get("uids") or []),
        "rows_actual": int(execute_out.get("rows_actual") or 0),
        "sql_text": sql_text,
        "rows_estimated": int(execute_out.get("rows_estimated") or -1),
    }


async def _run_known_request(
    session: OrchestratorSession,
    *,
    prompt: str,
    normalized_request: NormalizedRequest,
    detected_country: str | None,
    client: ModelClient,
    workspace_evidence: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    import app.services.orchestrator_agent.tools as tools_mod

    execution_id = uuid.uuid4().hex
    query_only_after_clarification = False

    if normalized_request.intent == "answer_from_workspace" and workspace_evidence:
        trace = _create_execution_trace(
            session,
            execution_id=execution_id,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=None,
            steps=[
                PlanStep(
                    step_id="reuse_workspace",
                    title="复用现有画像结果",
                    kind="answer_from_workspace",
                    user_visible_reason="当前问题是只读追问，优先复用已有画像结果。",
                ),
                PlanStep(
                    step_id="review_final",
                    title="规则审核",
                    kind="review",
                    user_visible_reason="确认已有结果足以回答当前问题。",
                ),
            ],
        )
        yield _build_execution_plan_event(trace)
        yield _update_trace_step(
            session, trace, step_id="reuse_workspace", status="done",
            result_summary="已复用 session/tool_calls/workspace snapshot 中的画像结果，并装载证据回答上下文。",
        )
        final_message, confidence = answer_from_workspace_with_evidence(
            client,
            prompt=prompt,
            normalized_request=normalized_request,
            evidence_bundle=workspace_evidence,
        )
        review = ReviewResult(status="pass", issues=[], can_answer=True, confidence_impact=None)
        yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
        yield _set_trace_review(session, trace, review)
        _finalize_trace(session, trace, final_status="completed", final_message=final_message)
        yield _persist_final_message(
            session,
            prompt=prompt,
            final_message=final_message,
            confidence=confidence,
            detected_country=detected_country,
        )
        return

    if normalized_request.intent == "answer_from_workspace":
        trace = _create_execution_trace(
            session,
            execution_id=execution_id,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=None,
            steps=[
                PlanStep(
                    step_id="reuse_workspace",
                    title="复用现有画像结果",
                    kind="answer_from_workspace",
                    user_visible_reason="当前问题是只读追问，优先复用已有画像结果。",
                ),
                PlanStep(
                    step_id="review_final",
                    title="规则审核",
                    kind="review",
                    user_visible_reason="确认当前会话是否已有足够的画像上下文。",
                ),
            ],
        )
        yield _build_execution_plan_event(trace)
        yield _update_trace_step(
            session,
            trace,
            step_id="reuse_workspace",
            status="blocked",
            result_summary="当前会话没有可复用的画像结果。",
        )
        review = build_no_workspace_review()
        yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
        yield _set_trace_review(session, trace, review)
        final_message = _build_known_final_message(
            normalized_request,
            review=review,
            extra_note="请先分析 UID 或恢复历史 workspace 后再继续追问。",
        )
        _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
        yield _persist_final_message(
            session,
            prompt=prompt,
            final_message=final_message,
            confidence=0.0,
            detected_country=detected_country,
        )
        return

    if normalized_request.intent == "need_clarification":
        trace = _create_execution_trace(
            session,
            execution_id=execution_id,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=None,
            steps=[
                PlanStep(
                    step_id="clarify_scope",
                    title="补充 cohort 查询条件",
                    kind="clarification",
                    user_visible_reason="当前请求明显是在筛选一批用户，但还缺少国家或时间范围。",
                    resolution_type="clarification",
                    resolution_prompt=(normalized_request.request_understanding.clarification_prompt if normalized_request.request_understanding else None),
                    resolution_required_slots=list((normalized_request.request_understanding.missing_slots if normalized_request.request_understanding else []) or []),
                    resolution_candidate_defaults=dict((normalized_request.request_understanding.candidate_defaults if normalized_request.request_understanding else {}) or {}),
                ),
                PlanStep(
                    step_id="review_final",
                    title="规则审核",
                    kind="review",
                    user_visible_reason="等待补充关键条件后再继续执行。",
                ),
            ],
        )
        yield _build_execution_plan_event(trace)
        yield _update_trace_step(
            session,
            trace,
            step_id="clarify_scope",
            status="awaiting_resolution",
            result_summary="等待用户补充国家和时间范围。",
        )
        from app.services.orchestrator_agent.resolve_bus import open_resolution, wait_resolution

        open_resolution(session.session_id, resolution_id=f"{execution_id}:clarify_scope")
        yield _build_awaiting_resolution_event(
            trace,
            step_id="clarify_scope",
            resolution_type="clarification",
            prompt=(normalized_request.request_understanding.clarification_prompt if normalized_request.request_understanding else "请补充国家和时间范围。"),
            required_slots=list((normalized_request.request_understanding.missing_slots if normalized_request.request_understanding else []) or []),
            candidate_defaults=dict((normalized_request.request_understanding.candidate_defaults if normalized_request.request_understanding else {}) or {}),
        )
        resolution = await asyncio.to_thread(wait_resolution, session.session_id, 600.0)
        answers = dict((resolution or {}).get("answers") or {})
        country_answer = str(answers.get("country") or "").strip()
        time_window_answer = str(answers.get("time_window") or "").strip()
        auto_profile = (answers or {}).get("auto_profile")
        if not country_answer or not time_window_answer:
            review = ReviewResult(
                status="fail",
                issues=[{"type": "clarification_required", "message": "缺少国家或时间范围，无法继续 cohort 执行。"}],
                can_answer=False,
                confidence_impact="缺少 cohort 关键条件，已阻断执行",
            )
            yield _update_trace_step(session, trace, step_id="clarify_scope", status="blocked", result_summary="未补充完整的国家和时间范围。")
            yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(
                normalized_request,
                review=review,
                extra_note="请补充国家和时间范围后重试，例如：墨西哥、最近 7 天。",
            )
            _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
            yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
            return

        enriched_prompt = _apply_clarification_answers(prompt, answers)
        clarified_request = normalize_request(enriched_prompt, session, country_answer or detected_country)
        clarified_request = refine_normalized_request(
            client,
            prompt=enriched_prompt,
            session=session,
            normalized_request=clarified_request,
        )
        if clarified_request.intent == "need_clarification":
            clarified_request = clarified_request.model_copy(update={
                "intent": "query_data_then_profile",
                "country": country_answer or clarified_request.country or detected_country,
                "query_request": enriched_prompt,
            })
            clarified_request.request_understanding = build_request_understanding(
                prompt=enriched_prompt,
                intent="query_data_then_profile",
                uids=list(clarified_request.uids),
                focus=list((clarified_request.request_understanding.focus if clarified_request.request_understanding else []) or ["cohort"]),
                trace_days=clarified_request.trace_days,
            )
        query_only_after_clarification = (
            clarified_request.intent == "query_data_then_profile"
            and auto_profile is False
        )

        trace.intent = clarified_request.intent
        trace.request_summary = clarified_request.request_summary
        trace.request_understanding = clarified_request.request_understanding
        _save_trace(session, trace)
        yield _update_trace_step(
            session,
            trace,
            step_id="clarify_scope",
            status="done",
            result_summary=f"已补充国家={country_answer}，时间范围={time_window_answer}。",
        )
        yield _build_execution_plan_event(trace)
        normalized_request = clarified_request

    if normalized_request.intent == "run_trace" and normalized_request.uids:
        trace = _create_execution_trace(
            session,
            execution_id=execution_id,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=None,
            steps=[
                PlanStep(
                    step_id="run_trace",
                    title="执行轨迹分析",
                    kind="run_trace",
                    user_visible_reason="用户显式请求深度行为轨迹分析。",
                    tool_name="run_trace",
                ),
                PlanStep(
                    step_id="review_final",
                    title="规则审核",
                    kind="review",
                    user_visible_reason="确认轨迹分析结果可回答当前问题。",
                ),
            ],
        )
        yield _build_execution_plan_event(trace)
        yield _update_trace_step(session, trace, step_id="run_trace", status="running")
        tool_call_id = uuid.uuid4().hex
        record = ToolCallRecord(
            tool_name="run_trace",
            tool_call_id=tool_call_id,
            input={"uid": normalized_request.uids[0], "days": normalized_request.trace_days},
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.tool_calls.append(record)
        save_session(session)
        yield {"type": "tool_started", "tool_call_id": tool_call_id, "tool_name": "run_trace", "input": record.input}
        try:
            output_obj = await asyncio.to_thread(
                tools_mod.run_trace,
                _input_schema_for("run_trace")(**record.input),
            )
            output = output_obj.model_dump(mode="json")
            record.output = output
            record.status = "done"
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "run_trace", "output": output, "status": "ok"}
            yield _update_trace_step(session, trace, step_id="run_trace", status="done", result_summary="已完成轨迹分析。", tool_call_id=tool_call_id)
            review = ReviewResult(status="pass", issues=[], can_answer=True, confidence_impact=None)
            yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(
                normalized_request,
                trace_output=output,
                review=review,
                extra_note="可继续结合左侧画像模块核对关键风险信号。",
            )
            _finalize_trace(session, trace, final_status="completed", final_message=final_message)
            yield _persist_final_message(
                session,
                prompt=prompt,
                final_message=final_message,
                confidence=0.88,
                detected_country=detected_country,
            )
            return
        except Exception as exc:  # noqa: BLE001
            record.status = "error"
            record.output = {"error": str(exc)}
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "run_trace", "output": {"error": str(exc)}, "status": "error"}
            yield _update_trace_step(session, trace, step_id="run_trace", status="failed", result_summary=str(exc), tool_call_id=tool_call_id)
            review = ReviewResult(status="fail", issues=[{"type": "tool_error", "message": str(exc)}], can_answer=False, confidence_impact="轨迹分析执行失败")
            yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(normalized_request, review=review, extra_note="请稍后重试或改为查看已有画像模块。")
            _finalize_trace(session, trace, final_status="error", final_message=final_message)
            yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
            return

    if normalized_request.intent not in {"profile_uid", "profile_batch", "query_data_then_profile"}:
        return

    country_for_execution = normalized_request.country or detected_country or session.country or "mx"
    if normalized_request.intent == "query_data_then_profile":
        trace = _create_execution_trace(
            session,
            execution_id=execution_id,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=None,
            steps=[
                PlanStep(
                    step_id="query_data",
                    title="查询 cohort UID",
                    kind="query_data",
                    user_visible_reason="先通过 Data Agent 找到符合条件的 UID 集合。",
                    tool_name="query_data",
                ),
                PlanStep(
                    step_id="review_final",
                    title="规则审核",
                    kind="review",
                    user_visible_reason="确认 cohort 范围和后续画像条件。",
                ),
            ],
        )
        yield _build_execution_plan_event(trace)
        if country_for_execution != "mx":
            yield _update_trace_step(
                session,
                trace,
                step_id="query_data",
                status="blocked",
                result_summary="query_data_then_profile 目前仅支持 mx。",
            )
            review = ReviewResult(
                status="fail",
                issues=[{"type": "unsupported_country", "message": "query_data_then_profile 目前仅支持 mx"}],
                can_answer=False,
                confidence_impact="非 mx Data Agent 闭环尚未支持，已阻断执行",
            )
            yield _update_trace_step(
                session,
                trace,
                step_id="review_final",
                status="done",
                result_summary=_review_step_summary(review),
            )
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(
                normalized_request,
                review=review,
                extra_note="当前补数/取数闭环只支持 mx，请切换到 mx 或改为已有画像上的只读追问。",
            )
            _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
            yield _persist_final_message(
                session,
                prompt=prompt,
                final_message=final_message,
                confidence=0.0,
                detected_country=detected_country,
            )
            return
        capability = get_data_acquisition_capability()
        if not capability.enabled:
            reason_message = data_acquisition_unavailable_message(capability)
            yield _update_trace_step(
                session,
                trace,
                step_id="query_data",
                status="blocked",
                result_summary=reason_message,
            )
            review = ReviewResult(
                status="fail",
                issues=[{"type": "data_acquisition_unavailable", "message": reason_message}],
                can_answer=False,
                confidence_impact="数据获取能力当前不可用，已阻断 cohort 自动执行",
            )
            yield _update_trace_step(
                session,
                trace,
                step_id="review_final",
                status="done",
                result_summary=_review_step_summary(review),
            )
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(
                normalized_request,
                review=review,
                extra_note=reason_message,
            )
            _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
            yield _persist_final_message(
                session,
                prompt=prompt,
                final_message=final_message,
                confidence=0.0,
                detected_country=detected_country,
            )
            return
        yield _update_trace_step(session, trace, step_id="query_data", status="running")
        tool_call_id = uuid.uuid4().hex
        record = ToolCallRecord(
            tool_name="query_data",
            tool_call_id=tool_call_id,
            input={"request": normalized_request.query_request or prompt, "country": country_for_execution},
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.tool_calls.append(record)
        save_session(session)
        yield {"type": "tool_started", "tool_call_id": tool_call_id, "tool_name": "query_data", "input": record.input}
        try:
            preview_maybe = execute_query_data_cohort(session, normalized_request.query_request or prompt, country_for_execution)
            preview = await preview_maybe if inspect.isawaitable(preview_maybe) else preview_maybe
            if "uids" in preview and "child" not in preview:
                output = preview
            else:
                from app.services.orchestrator_agent.ack_bus import open_ack, wait_ack

                open_ack(session.session_id)
                yield {"type": "awaiting_user_ack", "tool_call_id": tool_call_id, "sql_text": preview["sql_text"], "rows_estimated": preview["rows_estimated"]}
                confirmed = await asyncio.to_thread(wait_ack, session.session_id, 600.0)
                if not confirmed:
                    from app.services.orchestrator_agent.session import mark_query_cancelled

                    mark_query_cancelled(session.session_id)
                    raise PermissionError("User rejected SQL execution")
                output = await _complete_query_data_cohort(session, preview["child"], preview["sql_text"])
            record.output = output
            record.status = "done"
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "query_data", "output": output, "status": "ok"}
            yield _update_trace_step(session, trace, step_id="query_data", status="done", result_summary=f"已获取 {len(output['uids'])} 个 UID。", tool_call_id=tool_call_id)
            if len(output["uids"]) > 200:
                review = ReviewResult(
                    status="fail",
                    issues=[{"type": "cohort_too_large", "message": "cohort 返回 UID 数量超过 200"}],
                    can_answer=False,
                    confidence_impact="范围过大，已阻断自动画像",
                )
                yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
                yield _set_trace_review(session, trace, review)
                final_message = _build_known_final_message(
                    normalized_request,
                    review=review,
                    extra_note="本次 cohort 超过 200 个 UID，请缩小时间范围、国家或风险条件后重试。",
                )
                _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
                yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
                return
            if query_only_after_clarification:
                review = ReviewResult(status="pass", issues=[], can_answer=True, confidence_impact=None)
                yield _update_trace_step(
                    session,
                    trace,
                    step_id="review_final",
                    status="done",
                    result_summary="已按用户要求仅返回 cohort 查询结果，不继续自动画像。",
                )
                yield _set_trace_review(session, trace, review)
                final_message = _build_query_only_final_message(
                    normalized_request,
                    output=output,
                )
                _finalize_trace(session, trace, final_status="completed", final_message=final_message)
                yield _persist_final_message(
                    session,
                    prompt=prompt,
                    final_message=final_message,
                    confidence=0.85,
                    detected_country=detected_country,
                )
                return
            normalized_request = normalized_request.model_copy(update={"uids": output["uids"]})
        except Exception as exc:  # noqa: BLE001
            record.status = "error"
            record.output = {"error": str(exc)}
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "query_data", "output": {"error": str(exc)}, "status": "error"}
            yield _update_trace_step(session, trace, step_id="query_data", status="failed", result_summary=str(exc), tool_call_id=tool_call_id)
            review = ReviewResult(status="fail", issues=[{"type": "tool_error", "message": str(exc)}], can_answer=False, confidence_impact="取数阶段失败")
            yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(normalized_request, review=review, extra_note="请调整取数条件或重新发起会话。")
            _finalize_trace(session, trace, final_status="error", final_message=final_message)
            yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
            return
    else:
        trace = None

    profile_steps: list[PlanStep] = []
    if normalized_request.uid_file_path:
        profile_steps.append(
            PlanStep(
                step_id="parse_uid_file",
                title="解析 UID 文件",
                kind="parse_uid_file",
                user_visible_reason="先从本地 UID 文件中提取待分析的用户列表。",
                tool_name="parse_uid_file",
            )
        )
    if trace is None and profile_steps:
        trace = _create_execution_trace(
            session,
            execution_id=execution_id,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=None,
            steps=profile_steps,
        )
        yield _build_execution_plan_event(trace)

    if normalized_request.uid_file_path:
        tool_call_id = uuid.uuid4().hex
        record = ToolCallRecord(
            tool_name="parse_uid_file",
            tool_call_id=tool_call_id,
            input={"file_path": normalized_request.uid_file_path},
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.tool_calls.append(record)
        save_session(session)
        if trace is not None:
            yield _update_trace_step(session, trace, step_id="parse_uid_file", status="running", tool_call_id=tool_call_id)
        yield {"type": "tool_started", "tool_call_id": tool_call_id, "tool_name": "parse_uid_file", "input": record.input}
        try:
            output_obj = await asyncio.to_thread(
                tools_mod.parse_uid_file,
                _input_schema_for("parse_uid_file")(**record.input),
            )
            output = output_obj.model_dump(mode="json")
            record.output = output
            record.status = "done"
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "parse_uid_file", "output": output, "status": "ok"}
            parsed_uids = list(output.get("uids") or [])
            normalized_request = normalized_request.model_copy(update={"uids": parsed_uids})
            if trace is not None:
                yield _update_trace_step(
                    session,
                    trace,
                    step_id="parse_uid_file",
                    status="done",
                    result_summary=f"已从文件中解析出 {len(parsed_uids)} 个 UID。",
                    tool_call_id=tool_call_id,
                )
            if not parsed_uids:
                review = ReviewResult(
                    status="fail",
                    issues=[{"type": "empty_uid_file", "message": "UID 文件中没有可用 UID"}],
                    can_answer=False,
                    confidence_impact="没有可执行的 UID，已阻断画像",
                )
                if trace is not None:
                    _append_trace_steps(
                        session,
                        trace,
                        [
                            PlanStep(
                                step_id="review_final",
                                title="规则审核",
                                kind="review",
                                user_visible_reason="确认文件中是否存在可执行 UID。",
                            )
                        ],
                    )
                    yield _build_execution_plan_event(trace)
                    yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
                    yield _set_trace_review(session, trace, review)
                    final_message = _build_known_final_message(
                        normalized_request,
                        review=review,
                        extra_note="请检查 UID 文件内容是否有效，或改为直接输入 UID。",
                    )
                    _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
                    yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
                return
        except Exception as exc:  # noqa: BLE001
            record.status = "error"
            record.output = {"error": str(exc)}
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "parse_uid_file", "output": {"error": str(exc)}, "status": "error"}
            if trace is not None:
                yield _update_trace_step(session, trace, step_id="parse_uid_file", status="failed", result_summary=str(exc), tool_call_id=tool_call_id)
                review = ReviewResult(status="fail", issues=[{"type": "tool_error", "message": str(exc)}], can_answer=False, confidence_impact="UID 文件解析失败")
                _append_trace_steps(
                    session,
                    trace,
                    [
                        PlanStep(
                            step_id="review_final",
                            title="规则审核",
                            kind="review",
                            user_visible_reason="确认 UID 文件是否可用于继续执行。",
                        )
                    ],
                )
                yield _build_execution_plan_event(trace)
                yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
                yield _set_trace_review(session, trace, review)
                final_message = _build_known_final_message(
                    normalized_request,
                    review=review,
                    extra_note="请检查文件路径是否正确，且文件位于 data/id_files/ 下。",
                )
                _finalize_trace(session, trace, final_status="error", final_message=final_message)
                yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
            return

    availability = check_data_availability(normalized_request.uids, country=country_for_execution)
    repair_steps: list[PlanStep] = []
    missing_uids_by_bucket: dict[str, list[str]] = {}
    required_buckets = _required_buckets_for_request(normalized_request.modules)
    for row in availability.per_uid:
        for bucket in row.missing_buckets:
            if bucket in required_buckets:
                missing_uids_by_bucket.setdefault(bucket, []).append(row.uid)
    requested_missing = sorted(missing_uids_by_bucket.keys())
    capability = get_data_acquisition_capability() if requested_missing else None
    repair_available = bool(capability and capability.enabled)
    unavailable_missing_buckets = requested_missing if requested_missing and not repair_available else []
    initial_uid_modules_plan = _build_uid_module_plan(availability, normalized_request)
    has_runnable_modules = any(initial_uid_modules_plan.values())
    estimated_repair_sql_count = len(requested_missing)
    strategy_required = (
        normalized_request.intent == "query_data_then_profile"
        and repair_available
        and bool(requested_missing)
        and (
            len(normalized_request.uids) >= 10
            or len(requested_missing) >= 2
            or estimated_repair_sql_count >= 2
        )
    )
    profile_steps.extend([
        PlanStep(
            step_id="check_data",
            title="检查数据完整性",
            kind="check_data",
            user_visible_reason="直接检查本地 by_uid bucket，不使用 sample fallback。",
        ),
    ])
    if unavailable_missing_buckets:
        profile_steps.append(PlanStep(
            step_id="data_acquisition_unavailable",
            title="无法自动补数",
            kind="data_acquisition_unavailable",
            user_visible_reason="当前环境未启用或缺少 Data Agent 依赖，无法补齐本次请求真正缺失的 bucket。",
        ))
        if has_runnable_modules:
            profile_steps.extend([
                PlanStep(
                    step_id="run_profile",
                    title="执行画像分析",
                    kind="run_profile",
                    user_visible_reason="对有真实数据支撑的模块执行画像。",
                    tool_name="run_profile",
                ),
                PlanStep(
                    step_id="review_final",
                    title="规则审核",
                    kind="review",
                    user_visible_reason="核对缺失数据、执行结果和置信度影响。",
                ),
            ])
        else:
            profile_steps.append(PlanStep(
                step_id="review_final",
                title="规则审核",
                kind="review",
                user_visible_reason="确认当前请求是否还有可运行的画像模块。",
            ))
    elif strategy_required:
        profile_steps.append(PlanStep(
            step_id="repair_strategy",
            title="选择补数策略",
            kind="repair_strategy",
            user_visible_reason="cohort 较大且缺失 bucket 较多，先确认补数策略再继续执行。",
            resolution_type="repair_strategy",
            resolution_prompt="本次 cohort 用户较多，且缺多个 bucket。请选择只分析已有数据、只补 behavior、补齐全部，或先缩小范围。",
            resolution_options=[
                "analyze_existing_only",
                "repair_behavior_only",
                "repair_all_missing",
                "refine_scope",
            ],
        ))
    else:
        for bucket in requested_missing:
            repair_steps.append(PlanStep(
                step_id=f"repair_{bucket}",
                title=f"补齐 {bucket} 数据",
                kind="repair_profile_data",
                user_visible_reason=f"本地缺少 {bucket} bucket，尝试通过 Data Agent 补数。",
                tool_name="repair_profile_data",
            ))
        profile_steps.extend([
            *repair_steps,
            PlanStep(
                step_id="run_profile",
                title="执行画像分析",
                kind="run_profile",
                user_visible_reason="对有真实数据支撑的模块执行画像。",
                tool_name="run_profile",
            ),
            PlanStep(
                step_id="review_final",
                title="规则审核",
                kind="review",
                user_visible_reason="核对缺失数据、执行结果和置信度影响。",
            ),
        ])
    if trace is None:
        trace = _create_execution_trace(
            session,
            execution_id=execution_id,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=availability,
            steps=profile_steps,
        )
        yield _build_execution_plan_event(trace)
    else:
        _set_trace_availability(session, trace, availability)
        _append_trace_steps(session, trace, profile_steps)
        yield _build_execution_plan_event(trace)

    yield _update_trace_step(session, trace, step_id="check_data", status="done", result_summary=_availability_summary(availability))

    if unavailable_missing_buckets:
        reason_message = data_acquisition_unavailable_message(capability)
        step_status = "skipped" if has_runnable_modules else "blocked"
        yield _update_trace_step(
            session,
            trace,
            step_id="data_acquisition_unavailable",
            status=step_status,
            result_summary=f"缺失 {', '.join(unavailable_missing_buckets)} 数据，{reason_message}",
        )
        if not has_runnable_modules:
            review = _append_data_acquisition_issue(
                _build_profile_review(availability, initial_uid_modules_plan, None, normalized_request),
                missing_buckets=unavailable_missing_buckets,
                blocked=True,
            )
            yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(
                normalized_request,
                availability=availability,
                review=review,
                extra_note=f"{reason_message} 请直接提供 UID/UID 文件，或补齐本地 bucket 后重试。",
            )
            _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
            yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
            return
        requested_missing = []

    if strategy_required:
        from app.services.orchestrator_agent.resolve_bus import open_resolution, wait_resolution

        missing_counts = _missing_bucket_counts(availability, requested_missing)
        yield _update_trace_step(
            session,
            trace,
            step_id="repair_strategy",
            status="awaiting_resolution",
            result_summary=f"cohort 共 {len(normalized_request.uids)} 个 UID，缺失 bucket 包括 {', '.join(requested_missing)}。",
        )
        open_resolution(session.session_id, resolution_id=f"{execution_id}:repair_strategy")
        yield _build_awaiting_resolution_event(
            trace,
            step_id="repair_strategy",
            resolution_type="repair_strategy",
            prompt="本次 cohort 返回的 UID 较多且缺多个 bucket，请先选择执行策略。",
            options=["analyze_existing_only", "repair_behavior_only", "repair_all_missing", "refine_scope"],
            missing_bucket_counts=missing_counts,
            cohort_size=len(normalized_request.uids),
        )
        resolution = await asyncio.to_thread(wait_resolution, session.session_id, 600.0)
        selected_option = str((resolution or {}).get("selected_option") or "").strip() or "refine_scope"
        if selected_option == "refine_scope":
            review = ReviewResult(
                status="fail",
                issues=[{"type": "scope_refinement_requested", "message": "用户选择先缩小 cohort 范围后再执行。"}],
                can_answer=False,
                confidence_impact="当前 cohort 范围过大，已等待进一步缩小条件",
            )
            _append_trace_steps(session, trace, [
                PlanStep(
                    step_id="review_final",
                    title="规则审核",
                    kind="review",
                    user_visible_reason="记录本次 cohort 执行被用户主动收窄范围。",
                )
            ])
            yield _build_execution_plan_event(trace)
            yield _update_trace_step(session, trace, step_id="repair_strategy", status="blocked", result_summary="已请求用户缩小时间范围或筛选条件。")
            yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
            yield _set_trace_review(session, trace, review)
            final_message = _build_known_final_message(
                normalized_request,
                availability=availability,
                review=review,
                extra_note="请缩小时间范围、风险条件或国家范围后重新发起 cohort 请求。",
            )
            _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
            yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
            return
        yield _update_trace_step(session, trace, step_id="repair_strategy", status="done", result_summary=f"已选择策略：{selected_option}。")
        if selected_option == "analyze_existing_only":
            requested_missing = []
        elif selected_option == "repair_behavior_only":
            requested_missing = ["behavior"] if "behavior" in requested_missing else []
        else:
            requested_missing = sorted(requested_missing)

        repair_steps = []
        for bucket in requested_missing:
            repair_steps.append(PlanStep(
                step_id=f"repair_{bucket}",
                title=f"补齐 {bucket} 数据",
                kind="repair_profile_data",
                user_visible_reason=f"根据选定策略，尝试补齐 {bucket} bucket。",
                tool_name="repair_profile_data",
            ))
        _append_trace_steps(session, trace, [
            *repair_steps,
            PlanStep(
                step_id="run_profile",
                title="执行画像分析",
                kind="run_profile",
                user_visible_reason="对有真实数据支撑的模块执行画像。",
                tool_name="run_profile",
            ),
            PlanStep(
                step_id="review_final",
                title="规则审核",
                kind="review",
                user_visible_reason="核对缺失数据、执行结果和置信度影响。",
            ),
        ])
        yield _build_execution_plan_event(trace)

    for bucket in requested_missing:
        step_id = f"repair_{bucket}"
        if country_for_execution != "mx":
            yield _update_trace_step(session, trace, step_id=step_id, status="blocked", result_summary="repair 目前仅支持 mx。")
            continue

        tool_call_id = uuid.uuid4().hex
        missing_uids = list(missing_uids_by_bucket.get(bucket) or [])
        repair_input = RepairProfileDataInput(
            uids=missing_uids,
            country=country_for_execution,
            bucket=bucket,
            reason=f"{bucket} bucket 缺失，需继续执行画像",
        )
        record = ToolCallRecord(
            tool_name="repair_profile_data",
            tool_call_id=tool_call_id,
            input=repair_input.model_dump(mode="json"),
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.tool_calls.append(record)
        save_session(session)
        yield _update_trace_step(session, trace, step_id=step_id, status="running", tool_call_id=tool_call_id)
        yield {"type": "tool_started", "tool_call_id": tool_call_id, "tool_name": "repair_profile_data", "input": record.input}
        try:
            from app.services.orchestrator_agent.ack_bus import open_ack, wait_ack
            from app.services.orchestrator_agent.session import mark_query_cancelled

            if repair_profile_data is not _ORIGINAL_REPAIR_PROFILE_DATA:
                repair_q: queue.Queue = queue.Queue()

                def _before_ack(sql_text: str, rows_estimated: int) -> None:
                    repair_q.put(("awaiting_ack", {"sql_text": sql_text, "rows_estimated": rows_estimated}, None))

                def _repair_worker() -> None:
                    try:
                        output_obj = repair_profile_data(
                            repair_input,
                            session_id=session.session_id,
                            tool_call_id=tool_call_id,
                            before_ack=_before_ack,
                        )
                        repair_q.put(("done", output_obj, None))
                    except Exception as worker_exc:  # noqa: BLE001
                        repair_q.put(("error", None, worker_exc))

                threading.Thread(target=_repair_worker, daemon=True).start()
                awaiting_emitted = False
                while True:
                    kind, payload, worker_exc = await asyncio.to_thread(repair_q.get)
                    if kind == "awaiting_ack":
                        open_ack(session.session_id)
                        yield {
                            "type": "awaiting_user_ack",
                            "tool_call_id": tool_call_id,
                            "sql_text": (payload or {}).get("sql_text", ""),
                            "rows_estimated": (payload or {}).get("rows_estimated", -1),
                        }
                        awaiting_emitted = True
                        continue
                    if kind == "error":
                        raise worker_exc
                    output_obj = payload
                    if not awaiting_emitted:
                        open_ack(session.session_id)
                        yield {
                            "type": "awaiting_user_ack",
                            "tool_call_id": tool_call_id,
                            "sql_text": "",
                            "rows_estimated": -1,
                        }
                    break
            else:
                prepared = await asyncio.to_thread(prepare_repair_query, repair_input)
                open_ack(session.session_id)
                yield {
                    "type": "awaiting_user_ack",
                    "tool_call_id": tool_call_id,
                    "sql_text": prepared.sql_text,
                    "rows_estimated": prepared.rows_estimated,
                }
                confirmed = await asyncio.to_thread(wait_ack, session.session_id, 600.0)
                if not confirmed:
                    mark_query_cancelled(session.session_id)
                    raise PermissionError("User rejected SQL execution")
                output_obj = await asyncio.to_thread(execute_repair_query, prepared)
            output = output_obj.model_dump(mode="json")
            record.output = output
            record.status = "done"
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "repair_profile_data", "output": output, "status": "ok"}
            yield _update_trace_step(session, trace, step_id=step_id, status="done", result_summary=f"已补齐 {bucket} 数据。", tool_call_id=tool_call_id)
        except Exception as exc:  # noqa: BLE001
            record.status = "error"
            record.output = {"error": str(exc)}
            record.finished_at = datetime.now(timezone.utc)
            save_session(session)
            yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "repair_profile_data", "output": {"error": str(exc)}, "status": "error"}
            yield _update_trace_step(session, trace, step_id=step_id, status="blocked", result_summary=str(exc), tool_call_id=tool_call_id)

    availability = check_data_availability(normalized_request.uids, country=country_for_execution)
    _set_trace_availability(session, trace, availability)
    uid_modules_plan = _build_uid_module_plan(availability, normalized_request)
    execution_groups = [
        (modules, uids)
        for modules, uids in _group_uid_module_plan(uid_modules_plan)
        if modules
    ]
    if not execution_groups:
        yield _update_trace_step(session, trace, step_id="run_profile", status="blocked", result_summary="没有任何基础 bucket 可用于画像。")
        review = _build_profile_review(availability, uid_modules_plan, None, normalized_request)
        yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
        yield _set_trace_review(session, trace, review)
        final_message = _build_known_final_message(
            normalized_request,
            review=review,
            availability=availability,
            extra_note="请先补齐至少一个基础 bucket，再重新发起画像。",
        )
        _finalize_trace(session, trace, final_status="blocked", final_message=final_message)
        yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
        return

    run_profile_input = {
        "uids": normalized_request.uids,
        "app_time": normalized_request.application_time_hint,
        "modules": _flatten_planned_modules(uid_modules_plan),
        "strict_data_mode": True,
    }
    tool_call_id = uuid.uuid4().hex
    record = ToolCallRecord(
        tool_name="run_profile",
        tool_call_id=tool_call_id,
        input=run_profile_input,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    session.tool_calls.append(record)
    save_session(session)
    yield _update_trace_step(session, trace, step_id="run_profile", status="running", tool_call_id=tool_call_id)
    yield {"type": "tool_started", "tool_call_id": tool_call_id, "tool_name": "run_profile", "input": run_profile_input}
    try:
        progress_q: queue.Queue = queue.Queue()

        def _progress_cb(progress_evt: dict) -> None:
            progress_q.put(("progress", progress_evt, None))

        def _worker() -> None:
            try:
                combined_results: list[dict[str, Any]] = []
                total_cache_hits = 0
                total_cache_misses = 0
                total = sum(len(modules) * len(uids) for modules, uids in execution_groups)
                completed_offset = 0

                for modules, group_uids in execution_groups:
                    group_input = {
                        "uids": group_uids,
                        "app_time": normalized_request.application_time_hint,
                        "modules": modules,
                        "strict_data_mode": True,
                    }

                    def _group_progress(progress_evt: dict, *, offset: int = completed_offset) -> None:
                        progress_q.put((
                            "progress",
                            {
                                **(progress_evt or {}),
                                "completed": offset + int((progress_evt or {}).get("completed", 0)),
                                "total": total,
                            },
                            None,
                        ))

                    group_output = _call_tool_with_optional_progress(
                        tools_mod.run_profile,
                        _input_schema_for("run_profile")(**group_input),
                        _group_progress,
                    )
                    group_dump = group_output.model_dump(mode="json")
                    combined_results.extend(group_dump.get("results") or [])
                    total_cache_hits += int(group_dump.get("cache_hits") or 0)
                    total_cache_misses += int(group_dump.get("cache_misses") or 0)
                    completed_offset += len(group_uids) * len(modules)

                progress_q.put((
                    "done",
                    {
                        "results": combined_results,
                        "cache_hits": total_cache_hits,
                        "cache_misses": total_cache_misses,
                    },
                    None,
                ))
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
                yield {"type": "tool_progress", "tool_call_id": tool_call_id, "tool_name": "run_profile", **(payload or {})}
                continue
            if kind == "error":
                raise worker_exc
            output = payload
            break
        record.output = output
        record.status = "done"
        record.finished_at = datetime.now(timezone.utc)
        save_session(session)
        yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "run_profile", "output": output, "status": "ok"}
        executed_count = sum(len(modules) * len(uids) for modules, uids in execution_groups)
        yield _update_trace_step(session, trace, step_id="run_profile", status="done", result_summary=f"已完成 {executed_count} 个模块任务。", tool_call_id=tool_call_id)
        review = _build_profile_review(availability, uid_modules_plan, output, normalized_request)
        if unavailable_missing_buckets:
            review = _append_data_acquisition_issue(
                review,
                missing_buckets=unavailable_missing_buckets,
                blocked=False,
            )
        yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
        yield _set_trace_review(session, trace, review)
        final_message = _build_known_final_message(
            normalized_request,
            profile_output=output,
            review=review,
            availability=availability,
            extra_note="可继续追问具体模块或切到左侧 dashboard 查看结构化结果。",
        )
        _finalize_trace(session, trace, final_status="completed", final_message=final_message)
        yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.89 if review.status == "pass" else 0.72, detected_country=detected_country)
        return
    except Exception as exc:  # noqa: BLE001
        record.status = "error"
        record.output = {"error": str(exc)}
        record.finished_at = datetime.now(timezone.utc)
        save_session(session)
        yield {"type": "tool_completed", "tool_call_id": tool_call_id, "tool_name": "run_profile", "output": {"error": str(exc)}, "status": "error"}
        yield _update_trace_step(session, trace, step_id="run_profile", status="failed", result_summary=str(exc), tool_call_id=tool_call_id)
        review = ReviewResult(status="fail", issues=[{"type": "tool_error", "message": str(exc)}], can_answer=False, confidence_impact="画像执行失败")
        yield _update_trace_step(session, trace, step_id="review_final", status="done", result_summary=_review_step_summary(review))
        yield _set_trace_review(session, trace, review)
        final_message = _build_known_final_message(normalized_request, review=review, availability=availability, extra_note="请稍后重试，或先检查本地 bucket 数据。")
        _finalize_trace(session, trace, final_status="error", final_message=final_message)
        yield _persist_final_message(session, prompt=prompt, final_message=final_message, confidence=0.0, detected_country=detected_country)
        return


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

    normalized_request = normalize_request(prompt, session, detected_country)
    if not normalized_request.application_time_hint:
        snapshot = session.active_entities.get("workspace_snapshot")
        if isinstance(snapshot, dict) and snapshot.get("applicationTime"):
            normalized_request = normalized_request.model_copy(update={
                "application_time_hint": snapshot.get("applicationTime"),
            })
    if normalized_request.intent != "need_clarification":
        normalized_request = refine_normalized_request(
            client,
            prompt=prompt,
            session=session,
            normalized_request=normalized_request,
        )
    workspace_evidence = None
    if normalized_request.intent == "answer_from_workspace":
        workspace_evidence = build_workspace_evidence_bundle(
            session,
            normalized_request,
            prompt,
            detected_country,
        )
    if normalized_request.intent == "answer_from_workspace" and not workspace_evidence and normalized_request.uids:
        promoted_intent = "profile_uid" if len(normalized_request.uids) == 1 else "profile_batch"
        focus = list((normalized_request.request_understanding.focus if normalized_request.request_understanding else []) or [])
        normalized_request = normalized_request.model_copy(update={
            "intent": promoted_intent,
            "read_only": False,
            "request_understanding": build_request_understanding(
                prompt=prompt,
                intent=promoted_intent,
                uids=normalized_request.uids,
                focus=focus,
                trace_days=normalized_request.trace_days,
            ),
        })

    if normalized_request.intent != "general_chat":
        async for evt in _run_known_request(
            session,
            prompt=prompt,
            normalized_request=normalized_request,
            detected_country=detected_country,
            client=client,
            workspace_evidence=workspace_evidence,
        ):
            yield evt
        if session.final_message:
            return

    general_trace: ExecutionTraceRecord | None = None
    if normalized_request.intent == "general_chat":
        general_trace = _create_execution_trace(
            session,
            execution_id=uuid.uuid4().hex,
            prompt=prompt,
            normalized_request=normalized_request,
            availability=None,
            steps=[
                PlanStep(
                    step_id="general_answer",
                    title="进入通用 Agent 模式",
                    kind="general_chat",
                    user_visible_reason="当前问题不匹配稳定的画像、取数或轨迹执行路径，先按通用问答处理。",
                ),
            ],
        )
        yield _build_execution_plan_event(general_trace)

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
            if general_trace is not None:
                _update_trace_step(session, general_trace, step_id="general_answer", status="failed", result_summary=str(exc))
                _finalize_trace(session, general_trace, final_status="error", final_message=str(exc))
            yield {"type": "error", "message": str(exc)}
            session.status = "error"
            save_session(session)
            return

        # 2) Budget 累加（last_token_usage 来自 Plan #01 R5 契约）
        try:
            usage = getattr(client, "last_token_usage", {}) or {}
            budget = check_and_increment(session, int(usage.get("total", 0)))
        except BudgetExceeded as exc:
            if general_trace is not None:
                _update_trace_step(session, general_trace, step_id="general_answer", status="failed", result_summary=str(exc))
                _finalize_trace(session, general_trace, final_status="error", final_message=str(exc))
            yield {"type": "error", "message": str(exc)}
            session.status = "budget_exceeded"
            save_session(session)
            return
        if budget["warn"]:
            yield {"type": "budget_warning", **budget}

        decision = llm_out.get("structured_result", {}) or {}

        # 3) Final?
        if decision.get("final_message"):
            if general_trace is not None:
                _update_trace_step(session, general_trace, step_id="general_answer", status="done", result_summary="已按通用 Agent 模式完成回答。")
                _finalize_trace(session, general_trace, final_status="completed", final_message=decision["final_message"])
            yield _persist_final_message(
                session,
                prompt=prompt,
                final_message=decision["final_message"],
                confidence=decision.get("confidence") or 0.0,
                detected_country=detected_country,
            ) | {"total_rounds": round_idx + 1}
            return

        # 4) Tool call
        tool_call = decision.get("tool_call")
        if not tool_call:
            if general_trace is not None:
                _update_trace_step(session, general_trace, step_id="general_answer", status="failed", result_summary="LLM did not produce final or tool_call")
                _finalize_trace(session, general_trace, final_status="error", final_message="LLM did not produce final or tool_call")
            yield {"type": "error", "message": "LLM did not produce final or tool_call"}
            session.status = "error"
            save_session(session)
            return

        tool_name = tool_call["name"]
        tool_input = tool_call["arguments"]
        if tool_name == "run_profile":
            tool_input = {**tool_input, "strict_data_mode": True}
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

                open_ack(session.session_id)
                # Step B: 显式 yield awaiting_user_ack（非阻塞，立即 flush 给前端）
                yield {
                    "type": "awaiting_user_ack",
                    "tool_call_id": tool_call_id,
                    "sql_text": qr.sql_text,
                    "rows_estimated": qr.rows_estimated,
                }

                # Step C: 等 ACK（threading.Event 用 to_thread 包，不卡 event loop）
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
            if general_trace is not None:
                _finalize_trace(session, general_trace, final_status="error", final_message=str(exc))
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
    if general_trace is not None:
        _finalize_trace(session, general_trace, final_status="error", final_message=f"Max rounds {MAX_ROUNDS} reached")
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
