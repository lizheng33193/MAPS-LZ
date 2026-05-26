"""run_trace — 薄封装 TraceAnalyzer.analyze()。"""

from __future__ import annotations

from app.runtime_skills.trace_analyzer.analyzer import TraceAnalyzer, build_context
from app.services.orchestrator_agent.schemas import RunTraceInput, RunTraceOutput


def run_trace(input_data: RunTraceInput) -> RunTraceOutput:
    """Run trace analysis for a single UID.

    V1：days 字段保留但不传给 build_context（下游 N 天阈值走 trace_analyzer 内部配置）。
    返回 dict 字段不确定，用 .get() fallback 防 KeyError。
    """
    analyzer = TraceAnalyzer()
    ctx = build_context(input_data.uid)
    out = analyzer.analyze(uid=input_data.uid, context=ctx)
    return RunTraceOutput(
        events=out.get("events", []),
        summary=out.get("summary", {}),
    )
