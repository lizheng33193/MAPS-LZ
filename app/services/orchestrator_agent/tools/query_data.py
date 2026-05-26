"""query_data — Parent-Child 隔离 + ACK；不动 data_acquisition_agent 任何文件。

ACK 时序由 agent_loop.py 接管（避免同步 wait_ack 阻塞 SSE event loop）。
本文件提供 _ChildAgent facade（agent_loop 直接调）+ query_data() 单测/兼容函数。

V1 国别支持：mx → mexico；th → thailand（da-agent 抛 ManifestNotImplemented）；
co/pe/cl/br 直接拒绝；其它 country code 在 QueryDataInput 已被 Pydantic 拒绝。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

# 仅 import，不修改 data_acquisition_agent 任何文件
from data_acquisition_agent.orchestrator import DataAcquisitionOrchestrator
from data_acquisition_agent.executor import run_execute_pipeline
from data_acquisition_agent.schemas import (
    GenerateRequest, ExecuteRequest, TargetCountry, TargetAction,
)

from app.services.orchestrator_agent.schemas import QueryDataInput, QueryDataOutput


_PROHIBITED_SQL = re.compile(
    r"\b(DELETE|DROP|TRUNCATE|UPDATE|INSERT)\b", re.IGNORECASE,
)

# Plan #03 短码 → da-agent TargetCountry 映射
_COUNTRY_MAP: dict[str, TargetCountry] = {
    "mx": TargetCountry.MEXICO,
    "th": TargetCountry.THAILAND,
    # co/pe/cl/br 不在 da-agent，工具入口直接拒绝
}


@dataclass
class _ChildResult:
    sql_text: str
    rows_estimated: int  # V1 由 da-agent execute 阶段返回；generate 阶段固定 -1


class _ChildAgent:
    """Per-call facade；不保留状态，不修改 data_acquisition_agent。"""

    def __init__(self, country: str) -> None:
        if country not in _COUNTRY_MAP:
            raise ValueError(
                f"V1 query_data does not support country={country!r}; "
                f"only mx (and stub th) supported. See Plan #03 Scope."
            )
        self._country = _COUNTRY_MAP[country]
        self._orch = DataAcquisitionOrchestrator()

    def run_query(self, request_text: str) -> _ChildResult:
        """Generate SQL via da-agent. Returns sql_text；rows_estimated=-1（待 execute 阶段）。"""
        gen_req = GenerateRequest(
            natural_language_request=request_text,
            target_country=self._country,
            target_action=TargetAction.EXTRACT,
        )
        gen_resp = self._orch.generate(gen_req)
        sql_text = gen_resp.sql or ""
        return _ChildResult(sql_text=sql_text, rows_estimated=-1)

    def execute(
        self,
        sql_text: str,
        *,
        approved_by: str = "orchestrator_agent",
        output_bucket: str = "behavior",
        output_format: str = "json",
    ) -> dict:
        """Execute approved SQL. Returns {uids, rows_actual}.

        - output_bucket V1 默认 "behavior"（与 query_data 用法对齐：拉一批 UID 用于跑画像）
        - output_format V1 默认 "json"（避免 app bucket→csv 强制约束）
        - UID 列表从 rows_per_uid.keys() 反推（ExecuteResponse 无 uids 字段）
        """
        rid = uuid.uuid4().hex
        exe_req = ExecuteRequest(
            approved_sql=sql_text,
            sql_kind="query_only",
            target_country=self._country,
            approved_by=approved_by,
            output_bucket=output_bucket,
            output_format=output_format,
        )
        exe_resp = run_execute_pipeline(exe_req, request_id=rid)
        rows_per_uid = exe_resp.get("rows_per_uid", {}) or {}
        uids = list(rows_per_uid.keys())
        rows_actual = int(exe_resp.get("metadata", {}).get("row_count_total", 0))
        return {"uids": uids, "rows_actual": rows_actual}


# ANTI-PATTERN: Do not expose require_confirmation as a tool argument.
# If the LLM can pass require_confirmation=False, prompt injection can
# bypass the security ACK gate. ACK is hardcoded inside agent_loop.

def query_data(input_data: QueryDataInput) -> QueryDataOutput:
    """Single-shot query path — 仅供单测 / 外部调用者 facade。

    生产路径（agent_loop.py）**不**走本函数——agent_loop 直接导入 `_ChildAgent`,
    拆成6 个阶段调用：run_query → SSE preview → ACK gate → wait_ack → execute → SSE final.
    ACK 控制仅在 agent_loop 内部硬编码，本函数不涉及 ACK（所以单测能同步跑完）。
    """
    child = _ChildAgent(country=input_data.country)
    try:
        gen = child.run_query(input_data.request)
        sql_text = gen.sql_text
        if _PROHIBITED_SQL.search(sql_text):
            raise ValueError("Prohibited SQL keyword detected in generated SQL")
        execute_out = child.execute(sql_text)
        return QueryDataOutput(
            uids=execute_out["uids"],
            rows_actual=execute_out["rows_actual"],
            sql_text=sql_text,
            rows_estimated=gen.rows_estimated,
        )
    finally:
        del child  # per-call 即丢
