"""run_profile — 薄封装 AnalysisOrchestrator.analyze_module()。

V1 决策：per-call 实例化 AnalysisOrchestrator（成本可接受），不引入模块级单例。
modules 默认 ["app"]；遍历 (uid × module) 调 analyze_module。
"""

from __future__ import annotations

from typing import Any

from app.services.orchestrator import AnalysisOrchestrator
from app.services.orchestrator_agent.schemas import (
    RunProfileInput, RunProfileOutput,
)


def run_profile(input_data: RunProfileInput) -> RunProfileOutput:
    orch = AnalysisOrchestrator()
    modules = input_data.modules or ["app"]
    results: list[dict[str, Any]] = []
    for uid in input_data.uids:
        for mod in modules:
            r = orch.analyze_module(
                uid=uid, module=mod, application_time=input_data.app_time,
            )
            results.append({"uid": uid, "module": mod, "result": r})
    return RunProfileOutput(
        results=results,
        cache_hits=0,
        cache_misses=len(input_data.uids) * len(modules),
    )
