from __future__ import annotations

import asyncio
import csv
import importlib
import json
import sys

import pytest


# Data Agent capability test convention:
# - fake query_data / repair success paths must patch capability as enabled
# - unavailable behavior tests must set DATA_ACQUISITION_ENABLED=false or patch disabled capability
# - fake Data Agent tests must not depend on local DA dependencies being installed
# - direct query_data execute tests must also fake manifest loading
def _patch_enabled_data_acquisition(monkeypatch):
    from app.core.data_acquisition_capability import DataAcquisitionCapability

    cap = DataAcquisitionCapability(mode="auto", enabled=True, reason=None)
    monkeypatch.setattr(
        importlib.import_module("app.services.orchestrator_agent.agent_loop"),
        "get_data_acquisition_capability",
        lambda: cap,
    )
    monkeypatch.setattr(
        importlib.import_module("app.services.orchestrator_agent.repair_profile_data"),
        "get_data_acquisition_capability",
        lambda: cap,
    )
    monkeypatch.setattr(
        importlib.import_module("app.services.orchestrator_agent.tools.query_data"),
        "get_data_acquisition_capability",
        lambda: cap,
    )
    return cap


def _patch_disabled_data_acquisition(monkeypatch):
    from app.core.data_acquisition_capability import DataAcquisitionCapability

    cap = DataAcquisitionCapability(
        mode="disabled",
        enabled=False,
        reason="disabled_by_config",
    )
    monkeypatch.setattr(
        importlib.import_module("app.services.orchestrator_agent.agent_loop"),
        "get_data_acquisition_capability",
        lambda: cap,
    )
    monkeypatch.setattr(
        importlib.import_module("app.services.orchestrator_agent.repair_profile_data"),
        "get_data_acquisition_capability",
        lambda: cap,
    )
    monkeypatch.setattr(
        importlib.import_module("app.services.orchestrator_agent.tools.query_data"),
        "get_data_acquisition_capability",
        lambda: cap,
    )
    return cap


def _patch_fake_query_data_manifest(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        importlib.import_module("app.services.orchestrator_agent.tools.query_data"),
        "_load_manifest",
        lambda country: SimpleNamespace(
            analyst_private_prefix="analyst_private",
        ),
    )


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_check_data_availability_reads_real_bucket_files(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(app_dir / f"{uid}.csv", [{
        "uid": uid,
        "app_name": "WhatsApp",
        "app_package": "com.whatsapp",
        "first_install_time": "2026-05-01T00:00:00Z",
        "last_update_time": "2026-05-15T00:00:00Z",
        "gp_category": "Social",
        "ai_category_level_2_CN": "社交",
    }])
    _write_csv(behavior_dir / f"{uid}.csv", [{
        "uid": uid,
        "event_name": "login",
        "event_time": "2026-05-15T00:00:00Z",
    }])

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")

    assert availability.checked_uids == [uid]
    assert availability.per_uid[0].app.status == "available"
    assert availability.per_uid[0].behavior.status == "available"
    assert availability.per_uid[0].credit.status == "missing"
    assert availability.per_uid[0].missing_buckets == ["credit"]


def test_check_data_availability_ignores_sample_fallback(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"
    app_dir.mkdir(parents=True, exist_ok=True)
    behavior_dir.mkdir(parents=True, exist_ok=True)
    credit_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")

    assert availability.per_uid[0].app.status == "missing"
    assert availability.per_uid[0].behavior.status == "missing"
    assert availability.per_uid[0].credit.status == "missing"


def test_check_data_availability_marks_invalid_csv(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(app_dir / f"{uid}.csv", [{
        "uid": uid,
        "app_name": "WhatsApp",
    }])
    behavior_dir.mkdir(parents=True, exist_ok=True)
    credit_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")

    assert availability.per_uid[0].app.status == "invalid"
    assert availability.per_uid[0].app.detail.startswith("missing_fields:")


def test_check_data_availability_uses_csv_when_prepared_json_schema_mismatches(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    behavior_dir.mkdir(parents=True, exist_ok=True)
    (behavior_dir / f"{uid}.json").write_text(
        '{"schema_version":"wrong","uid":"824812551379353600"}',
        encoding="utf-8",
    )
    _write_csv(behavior_dir / f"{uid}.csv", [{
        "uid": uid,
        "event_name": "login",
        "event_time": "2026-05-15T00:00:00Z",
    }])
    app_dir.mkdir(parents=True, exist_ok=True)
    credit_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")

    assert availability.per_uid[0].behavior.status == "available"
    assert availability.per_uid[0].behavior.source_type == "csv"


def test_check_data_availability_rejects_weak_behavior_and_credit_csv(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(behavior_dir / f"{uid}.csv", [{"uid": uid}])
    _write_csv(credit_dir / f"{uid}.csv", [{"uid": uid}])
    app_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")
    row = availability.per_uid[0]

    assert row.behavior.status == "invalid"
    assert row.behavior.usable_for_profile is False
    assert row.credit.status == "invalid"
    assert row.credit.usable_for_profile is False


def test_check_data_availability_accepts_raw_mx_behavior_csv_aliases(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(behavior_dir / f"{uid}.csv", [{
        "uid": uid,
        "servertimestamp": "1773121104896",
        "timestamp_": "1773121104652",
        "scenetype": "WebViewActivity",
        "processtype": "Native",
        "eventname": "page_onPause",
        "url": "https://www.mexicash.com/m/#/return-refresh-path",
    }])
    app_dir.mkdir(parents=True, exist_ok=True)
    credit_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")
    row = availability.per_uid[0]

    assert row.behavior.status == "available"
    assert row.behavior.usable_for_profile is True


def test_check_data_availability_accepts_camelcase_behavior_and_credit_fields(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(behavior_dir / f"{uid}.csv", [{
        "uid": uid,
        "eventTime": "2026-05-15T00:00:00Z",
        "eventName": "login",
    }])
    _write_csv(credit_dir / f"{uid}.csv", [{
        "uid": uid,
        "creditScore": "720",
        "riskLevel": "low",
    }])
    app_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")
    row = availability.per_uid[0]

    assert row.behavior.usable_for_profile is True
    assert row.credit.usable_for_profile is True


def test_check_data_availability_accepts_real_credit_raw_csv_aliases(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824928257039138816"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(credit_dir / f"{uid}.csv", [{
        "user_uuid": uid,
        "timestamp_": "1772369656095",
        "code": "0",
        "folioconsulta": "1951672304",
        "nombrescore": "FICO",
        "valor": "720",
        "razones": "R1|R2",
        "consultas_detail_json": '[{"fechaConsulta":"2024-01-01"}]',
        "creditos_detail_json": '[{"tipoCredito":"TC","saldoActual":"1000"}]',
    }])
    app_dir.mkdir(parents=True, exist_ok=True)
    behavior_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")
    row = availability.per_uid[0]

    assert row.credit.status == "available"
    assert row.credit.usable_for_profile is True


def test_check_data_availability_marks_credit_csv_mixed_when_strong_raw_and_summary_coexist(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824928257039138816"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(credit_dir / f"{uid}.csv", [{
        "uid": uid,
        "valor": "720",
        "nombrescore": "FICO",
        "creditos_detail_json": "[]",
        "risk_level": "low",
    }])
    app_dir.mkdir(parents=True, exist_ok=True)
    behavior_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")
    row = availability.per_uid[0]

    assert row.credit.status == "available"
    assert row.credit.source_shape == "mixed"


def test_check_data_availability_rejects_credit_csv_with_only_weak_meta_fields(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824928257039138816"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    _write_csv(credit_dir / f"{uid}.csv", [{
        "user_uuid": uid,
        "timestamp_": "1772369656095",
        "code": "0",
        "apply_risk_id": "AR-1",
    }])
    app_dir.mkdir(parents=True, exist_ok=True)
    behavior_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")
    row = availability.per_uid[0]

    assert row.credit.status == "invalid"
    assert row.credit.usable_for_profile is False
    assert row.credit.source_shape is None


def test_check_data_availability_rejects_empty_prepared_payloads(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.scripts.behavior_prepared_builder import BEHAVIOR_PREPARED_SCHEMA_VERSION
    from app.scripts.credit_prepared_builder import CREDIT_PREPARED_SCHEMA_VERSION
    from app.services.orchestrator_agent.data_availability import check_data_availability

    uid = "824812551379353600"
    app_dir = tmp_path / "app" / "by_uid"
    behavior_dir = tmp_path / "behavior" / "by_uid"
    credit_dir = tmp_path / "credit" / "by_uid"

    behavior_dir.mkdir(parents=True, exist_ok=True)
    credit_dir.mkdir(parents=True, exist_ok=True)
    app_dir.mkdir(parents=True, exist_ok=True)
    (behavior_dir / f"{uid}.json").write_text(json.dumps({
        "uid": uid,
        "schema_version": BEHAVIOR_PREPARED_SCHEMA_VERSION,
        "source_meta": {"event_count": 0, "timeline_section_count": 0},
        "session_summary": {"total_events": 0},
        "timeline_sections": [],
    }), encoding="utf-8")
    (credit_dir / f"{uid}.json").write_text(json.dumps({
        "uid": uid,
        "schema_version": CREDIT_PREPARED_SCHEMA_VERSION,
        "source_meta": {"row_count": 0},
        "credit_summary": {"total_accounts": 0},
        "delinquency_summary": {"total_delinquent_accounts": 0},
        "repayment_timeline": [0] * 12,
        "repayment_amount_timeline": [0] * 12,
    }), encoding="utf-8")

    monkeypatch.setattr(settings, "app_by_uid_dir", str(app_dir), raising=False)
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    availability = check_data_availability([uid], country="mx")
    row = availability.per_uid[0]

    assert row.behavior.usable_for_profile is False
    assert row.credit.usable_for_profile is False


def test_normalize_request_covers_known_intents():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    read_only = normalize_request("帮我总结一下这个用户的综合画像", session)
    single_uid = normalize_request("帮我分析一下 824812551379353600 这个用户", session)
    batch = normalize_request("帮我对比 824812551379353600 和 824812551379353601", session)
    trace = normalize_request("帮我看下 UID: TH000123 的轨迹", session)
    cohort = normalize_request("帮我找最近 7 天高流失用户并分析", session)

    assert read_only.intent == "answer_from_workspace"
    assert single_uid.intent == "profile_uid"
    assert single_uid.uids == ["824812551379353600"]
    assert batch.intent == "profile_batch"
    assert batch.uids == ["824812551379353600", "824812551379353601"]
    assert trace.intent == "run_trace"
    assert trace.uids == ["TH000123"]
    assert cohort.intent == "query_data_then_profile"
    assert cohort.query_request == "帮我找最近 7 天高流失用户并分析"


def test_normalize_request_accepts_uid_touching_chinese_text():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    request = normalize_request("请帮我分析824812551379353600这个用户", session)

    assert request.intent == "profile_uid"
    assert request.uids == ["824812551379353600"]


def test_normalize_request_extracts_trace_days():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    request = normalize_request("帮我分析 UID 824812551379353600 最近 30 天轨迹", session)

    assert request.intent == "run_trace"
    assert request.trace_days == 30


def test_normalize_request_routes_uid_file_batch_to_profile_execution():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    request = normalize_request("请批量分析 ./data/id_files/mx/sample.txt 里的用户，看哪些已经流失。", session)

    assert request.intent == "profile_batch"
    assert request.uid_file_path == "./data/id_files/mx/sample.txt"
    assert request.read_only is False


def test_normalize_request_detects_cohort_request_from_pull_batch_phrase():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    request = normalize_request("帮我拉一批墨西哥上周流失且下单过的用户，然后逐个跑 App 画像。", session)

    assert request.intent == "query_data_then_profile"


def test_normalize_request_routes_ambiguous_cohort_to_need_clarification():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    request = normalize_request("找一批高流失用户", session)

    assert request.intent == "need_clarification"
    assert request.request_understanding is not None
    assert set(request.request_understanding.missing_slots) == {"country", "time_window"}
    assert "时间范围" in (request.request_understanding.clarification_prompt or "")


def test_normalize_request_keeps_general_chat_for_plain_summary_prompt():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    request = normalize_request("总结一下我们刚才讨论的方案", session)

    assert request.intent == "general_chat"


def test_normalize_request_enriches_request_understanding_for_followup_and_rerun():
    from app.services.orchestrator_agent.request_router import normalize_request
    from app.services.orchestrator_agent.session_store import create_session

    session = create_session(country="mx")

    followup = normalize_request("帮我解释为什么这个用户流失风险高，并改成客服话术", session)
    rerun = normalize_request("重新分析 UID 824812551379353600 的最新综合画像", session)

    assert followup.intent == "answer_from_workspace"
    assert followup.request_understanding.route_label == "已有画像追问"
    assert followup.request_understanding.rewritten_goal == "基于当前已有画像结果，解释高流失风险并改写为客服话术"
    assert followup.request_understanding.requires_tools is False
    assert followup.request_understanding.answer_mode == "workspace_evidence_answer"
    assert "why" in followup.request_understanding.focus
    assert "customer_script" in followup.request_understanding.focus

    assert rerun.intent == "profile_uid"
    assert rerun.request_understanding.answer_mode == "tool_execution"
    assert "rerun" in rerun.request_understanding.focus


def test_repair_profile_data_module_is_importable_without_executor_dependencies():
    import importlib

    mod = importlib.import_module("app.services.orchestrator_agent.repair_profile_data")

    assert hasattr(mod, "repair_profile_data")


def test_tools_registry_import_does_not_pull_data_agent_executor():
    sys.modules.pop("app.services.orchestrator_agent.tools", None)
    sys.modules.pop("app.services.orchestrator_agent.tools.query_data", None)
    sys.modules.pop("data_acquisition_agent.executor", None)

    mod = importlib.import_module("app.services.orchestrator_agent.tools")

    assert hasattr(mod, "get_tool_registry")
    assert "data_acquisition_agent.executor" not in sys.modules


def test_query_data_module_import_does_not_pull_data_agent_executor():
    sys.modules.pop("app.services.orchestrator_agent.tools.query_data", None)
    sys.modules.pop("data_acquisition_agent.executor", None)

    mod = importlib.import_module("app.services.orchestrator_agent.tools.query_data")

    assert hasattr(mod, "query_data")
    assert "data_acquisition_agent.executor" not in sys.modules


def test_repair_profile_data_writes_csv_and_returns_metadata(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.repair_profile_data import (
        RepairProfileDataInput,
        repair_profile_data,
    )

    _patch_enabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"
    credit_dir = tmp_path / "credit" / "by_uid"
    credit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "credit_by_uid_dir", str(credit_dir), raising=False)

    class _FakeChildAgent:
        def __init__(self, country: str, bucket: str) -> None:
            self.country = country
            self.bucket = bucket

        def run_query(self, request_text: str):
            return type("X", (), {
                "sql_text": "SELECT uid, score FROM bureau WHERE uid IN (...)",
                "rows_estimated": 1,
            })()

        def execute(self, sql_text: str):
            return {
                "uids": [uid],
                "rows_actual": 1,
                "filenames": [f"{uid}.csv"],
                "written_file_count": 1,
            }

    monkeypatch.setattr(
        "app.services.orchestrator_agent.repair_profile_data._RepairChildAgent",
        _FakeChildAgent,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.repair_profile_data._await_user_ack",
        lambda session_id, tool_call_id, sql_text, rows_estimated: True,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.repair_profile_data._write_repair_csv",
        lambda bucket, rows, target_uids: [f"{uid}.csv"],
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.data_availability.check_data_availability",
        lambda uids, country=None: type("X", (), {
            "per_uid": [
                type("Row", (), {
                    "uid": uid,
                    "credit": type("Bucket", (), {"usable_for_profile": True})(),
                })()
            ],
        })(),
        raising=False,
    )

    output = repair_profile_data(
        RepairProfileDataInput(
            uids=[uid],
            country="mx",
            bucket="credit",
            reason="missing credit bucket",
        ),
        session_id="sess-1",
        tool_call_id="repair-1",
    )

    assert output.bucket == "credit"
    assert output.written_uids == [uid]
    assert output.filenames == [f"{uid}.csv"]
    assert output.rows_actual == 1


def test_repair_profile_data_reject_marks_session_cancelled(monkeypatch):
    from app.services.orchestrator_agent.ack_bus import open_ack, wait_ack
    from app.services.orchestrator_agent.repair_profile_data import (
        RepairProfileDataInput,
        repair_profile_data,
    )
    from app.services.orchestrator_agent.session import is_query_cancelled, reset_query_cancelled

    _patch_enabled_data_acquisition(monkeypatch)

    session_id = "repair-reject-sess"
    reset_query_cancelled(session_id)

    class _FakeChildAgent:
        def __init__(self, country: str, bucket: str) -> None:
            self.country = country
            self.bucket = bucket

        def run_query(self, request_text: str):
            return type("X", (), {
                "sql_text": "SELECT uid FROM t",
                "rows_estimated": 1,
            })()

        def execute(self, sql_text: str):
            raise AssertionError("execute should not run after reject")

    monkeypatch.setattr(
        "app.services.orchestrator_agent.repair_profile_data._RepairChildAgent",
        _FakeChildAgent,
    )

    def _fake_open_ack(sid: str):
        return open_ack(sid)

    def _fake_wait_ack(sid: str, timeout_sec: float = 600.0):
        return False

    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.open_ack",
        _fake_open_ack,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.wait_ack",
        _fake_wait_ack,
    )

    with pytest.raises(PermissionError):
        repair_profile_data(
            RepairProfileDataInput(
                uids=["824812551379353600"],
                country="mx",
                bucket="credit",
                reason="missing credit bucket",
            ),
            session_id=session_id,
            tool_call_id="repair-reject",
        )

    assert is_query_cancelled(session_id) is True


def test_repair_profile_data_opens_ack_before_before_ack_callback(monkeypatch):
    from app.services.orchestrator_agent.repair_profile_data import (
        RepairProfileDataInput,
        repair_profile_data,
    )

    _patch_enabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"
    call_order = []

    class _FakeChildAgent:
        def __init__(self, country: str, bucket: str) -> None:
            self.country = country
            self.bucket = bucket

        def run_query(self, request_text: str):
            return type("X", (), {
                "sql_text": "SELECT uid FROM bureau",
                "rows_estimated": 1,
            })()

        def execute(self, sql_text: str):
            return {
                "uids": [uid],
                "rows_actual": 1,
                "filenames": [f"{uid}.csv"],
                "written_file_count": 1,
            }

    monkeypatch.setattr(
        "app.services.orchestrator_agent.repair_profile_data._RepairChildAgent",
        _FakeChildAgent,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.open_ack",
        lambda sid: call_order.append("open_ack"),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.wait_ack",
        lambda sid, timeout_sec=600.0: (call_order.append("wait_ack") or True),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.data_availability.check_data_availability",
        lambda uids, country=None: type("X", (), {
            "per_uid": [
                type("Row", (), {
                    "uid": uid,
                    "credit": type("Bucket", (), {"usable_for_profile": True})(),
                })()
            ],
        })(),
        raising=False,
    )

    output = repair_profile_data(
        RepairProfileDataInput(
            uids=[uid],
            country="mx",
            bucket="credit",
            reason="missing credit bucket",
        ),
        session_id="repair-order-sess",
        tool_call_id="repair-order-call",
        before_ack=lambda sql, rows: call_order.append("before_ack"),
    )

    assert output.written_uids == [uid]
    assert call_order[:3] == ["open_ack", "before_ack", "wait_ack"]


def test_repair_profile_data_respects_pre_cancelled_session():
    from app.services.orchestrator_agent.repair_profile_data import (
        RepairProfileDataInput,
        repair_profile_data,
    )
    from app.services.orchestrator_agent.session import mark_query_cancelled, reset_query_cancelled

    session_id = "repair-pre-cancel"
    reset_query_cancelled(session_id)
    mark_query_cancelled(session_id)

    with pytest.raises(PermissionError, match="user cancelled"):
        repair_profile_data(
            RepairProfileDataInput(
                uids=["824812551379353600"],
                country="mx",
                bucket="credit",
                reason="missing credit bucket",
            ),
            session_id=session_id,
            tool_call_id="repair-cancelled",
        )


def test_query_data_execute_returns_uids_without_bucket_writes(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services.orchestrator_agent.tools.query_data import _ChildAgent

    _patch_enabled_data_acquisition(monkeypatch)
    _patch_fake_query_data_manifest(monkeypatch)

    behavior_dir = tmp_path / "behavior" / "by_uid"
    monkeypatch.setattr(settings, "behavior_by_uid_dir", str(behavior_dir), raising=False)

    class _FakeOrchestrator:
        def generate(self, req):
            return type("Resp", (), {"sql": "SELECT uid FROM t", "reasoning_summary": "ok"})()

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "data_acquisition_agent.orchestrator.DataAcquisitionOrchestrator",
        lambda: _FakeOrchestrator(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.enforce_pre_execution_gates",
        lambda **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.open_starrocks_connection",
        lambda request_id: _FakeConn(),
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.precheck_row_count",
        lambda **kwargs: 2,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.execute_query",
        lambda **kwargs: __import__("pandas").DataFrame([{"uid": "u2"}, {"uid": "u1"}, {"uid": "u1"}]),
        raising=False,
    )

    child = _ChildAgent("mx")
    out = child.execute("SELECT uid FROM t")

    assert out["uids"] == ["u1", "u2"]
    assert out["rows_actual"] == 3
    assert not behavior_dir.exists() or not any(behavior_dir.iterdir())


def test_query_data_execute_accepts_user_uuid_alias(monkeypatch):
    from app.services.orchestrator_agent.tools.query_data import _ChildAgent

    _patch_enabled_data_acquisition(monkeypatch)
    _patch_fake_query_data_manifest(monkeypatch)

    class _FakeOrchestrator:
        def generate(self, req):
            return type("Resp", (), {"sql": "SELECT user_uuid FROM t", "reasoning_summary": "ok"})()

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "data_acquisition_agent.orchestrator.DataAcquisitionOrchestrator",
        lambda: _FakeOrchestrator(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.enforce_pre_execution_gates",
        lambda **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.open_starrocks_connection",
        lambda request_id: _FakeConn(),
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.precheck_row_count",
        lambda **kwargs: 2,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data.execute_query",
        lambda **kwargs: __import__("pandas").DataFrame([{"user_uuid": "u2"}, {"user_uuid": "u1"}]),
        raising=False,
    )

    child = _ChildAgent("mx")
    out = child.execute("SELECT user_uuid FROM t")

    assert out["uids"] == ["u1", "u2"]


def test_repair_profile_data_exposes_prepare_and_execute_stages():
    mod = importlib.import_module("app.services.orchestrator_agent.repair_profile_data")

    assert hasattr(mod, "prepare_repair_query")
    assert hasattr(mod, "execute_repair_query")


def test_build_repair_request_uses_raw_credit_contract():
    from app.services.orchestrator_agent.repair_profile_data import build_repair_request
    from app.services.orchestrator_agent.schemas import RepairProfileDataInput

    prompt = build_repair_request(RepairProfileDataInput(
        uids=["u1"],
        country="mx",
        bucket="credit",
        reason="credit missing",
    ))

    assert "nombrescore" in prompt
    assert "consultas_detail_json" in prompt
    assert "creditos_detail_json" in prompt
    assert "credit_score_band" not in prompt
    assert "repayment_status" not in prompt
    assert "risk_level" not in prompt


def test_query_data_single_shot_prefers_execute_rows_estimated(monkeypatch):
    from app.services.orchestrator_agent.schemas import QueryDataInput
    from app.services.orchestrator_agent.tools.query_data import query_data

    class _FakeChild:
        def __init__(self, country):
            self.country = country

        def run_query(self, request_text):
            return type("QR", (), {"sql_text": "SELECT user_uuid FROM t", "rows_estimated": -1})()

        def execute(self, sql_text):
            return {"uids": ["u1"], "rows_actual": 1, "rows_estimated": 37}

    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data._ChildAgent",
        _FakeChild,
    )

    out = query_data(QueryDataInput(request="拉一批用户", country="mx"))
    assert out.rows_estimated == 37


def test_run_agent_loop_known_profile_request_emits_execution_events(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        ExecutionPlan,
        NormalizedRequest,
        ReviewResult,
        ToolCallRecord,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run for known request"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary=f"分析 UID {uid} 的完整画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/credit.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                )
            ],
        ),
    )

    def _fake_run_profile(inp, progress_callback=None):
        for idx, mod in enumerate(inp.modules, start=1):
            if progress_callback:
                progress_callback({
                    "progress_type": "profile_module_completed",
                    "uid": uid,
                    "module": mod,
                    "result": {
                        "status": "ok",
                        "data": {"summary": f"{mod} done", "structured_result": {}, "charts": [], "report_markdown": ""},
                        "error": None,
                    },
                    "status": "ok",
                    "completed": idx,
                    "total": len(inp.modules),
                })
        return type("X", (), {
            "model_dump": lambda self, mode="json": {
                "results": [
                    {
                        "uid": uid,
                        "module": mod,
                        "result": {
                            "status": "ok",
                            "data": {"summary": f"{mod} done", "structured_result": {}, "charts": [], "report_markdown": ""},
                            "error": None,
                        },
                    }
                    for mod in inp.modules
                ],
                "cache_hits": 0,
                "cache_misses": len(inp.modules),
            },
        })()

    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析一下{uid}这个用户")]

    events = asyncio.run(_drive())
    types = [evt["type"] for evt in events]

    assert "execution_plan" in types
    assert "plan_step_status" in types
    assert "tool_started" in types
    assert "tool_progress" in types
    assert "review_result" in types
    assert "final" in types
    assert types.index("execution_plan") < types.index("tool_started") < types.index("review_result") < types.index("final")


def test_run_agent_loop_marks_review_step_done(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary=f"分析 UID {uid} 的画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/credit.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: type("X", (), {
            "model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": 6},
        })(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析 {uid}")]

    asyncio.run(_drive())
    trace = session.execution_traces[-1]
    review_step = next(step for step in trace.steps if step.step_id == "review_final")
    assert review_step.status == "done"


def test_run_agent_loop_parses_uid_file_before_batch_profile(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uids = ["MX0001", "MX0002"]

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_batch",
            country="mx",
            uids=[],
            uid_file_path="./data/id_files/mx/sample.txt",
            modules=[],
            request_summary="分析 UID 文件 ./data/id_files/mx/sample.txt 的批量画像请求",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.parse_uid_file",
        lambda inp: type("X", (), {
            "model_dump": lambda self, mode="json": {
                "uids": uids,
                "source_path": inp.file_path,
                "duplicates_removed": 0,
            },
        })(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda incoming_uids, country=None: DataAvailability(
            country="mx",
            checked_uids=list(incoming_uids),
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path=f"/tmp/{uid}_app.csv"),
                    behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path=f"/tmp/{uid}_behavior.csv"),
                    credit=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path=f"/tmp/{uid}_credit.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                )
                for uid in incoming_uids
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: type("X", (), {
            "model_dump": lambda self, mode="json": {
                "results": [],
                "cache_hits": 0,
                "cache_misses": len(inp.uids) * len(inp.modules),
            },
        })(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="请批量分析 ./data/id_files/mx/sample.txt 里的用户，看哪些已经流失。")]

    events = asyncio.run(_drive())
    tool_starts = [evt["tool_name"] for evt in events if evt["type"] == "tool_started"]

    assert tool_starts[:2] == ["parse_uid_file", "run_profile"]


def test_run_agent_loop_repairs_missing_credit_then_runs_full_modules(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        RepairProfileDataOutput,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"
    availability_seq = iter([
        DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="missing", available=False, source_type="missing", path=None),
                    available_buckets=["app", "behavior"],
                    missing_buckets=["credit"],
                )
            ],
        ),
        DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/credit.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                )
            ],
        ),
    ])
    seen_modules = []
    repair_calls = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary=f"分析 UID {uid} 的画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: next(availability_seq),
    )

    def _fake_repair(input_data, *, session_id: str, tool_call_id: str, before_ack=None):
        repair_calls.append((input_data.bucket, list(input_data.uids)))
        if before_ack:
            before_ack("SELECT uid FROM bureau", 1)
        return RepairProfileDataOutput(
            bucket="credit",
            requested_uids=[uid],
            written_uids=[uid],
            filenames=[f"{uid}.csv"],
            sql_text="SELECT uid FROM bureau",
            rows_estimated=1,
            rows_actual=1,
        )

    def _fake_run_profile(inp, progress_callback=None):
        seen_modules.extend(inp.modules or [])
        return type("X", (), {
            "model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])},
        })()

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.repair_profile_data",
        _fake_repair,
        raising=False,
    )
    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析 {uid}")]

    events = asyncio.run(_drive())
    assert repair_calls == [("credit", [uid])]
    assert seen_modules == ["app", "behavior", "credit", "comprehensive", "product", "ops"]
    assert [evt["type"] for evt in events].count("execution_plan") >= 1
    assert "awaiting_user_ack" in [evt["type"] for evt in events]


def test_run_agent_loop_rejects_repair_and_downgrades_to_basic_modules(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"
    availability_seq = iter([
        DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="missing", available=False, source_type="missing", path=None),
                    available_buckets=["app", "behavior"],
                    missing_buckets=["credit"],
                )
            ],
        ),
        DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="missing", available=False, source_type="missing", path=None),
                    available_buckets=["app", "behavior"],
                    missing_buckets=["credit"],
                )
            ],
        ),
    ])
    seen_modules = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary=f"分析 UID {uid} 的画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: next(availability_seq),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.repair_profile_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("User rejected SQL execution")),
        raising=False,
    )

    def _fake_run_profile(inp, progress_callback=None):
        seen_modules.extend(inp.modules or [])
        return type("X", (), {
            "model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])},
        })()

    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析 {uid}")]

    events = asyncio.run(_drive())
    types = [evt["type"] for evt in events]
    assert seen_modules == ["app", "behavior"]
    assert "review_result" in types
    assert "部分基础数据缺失" in events[-1]["final_message"]


def test_run_agent_loop_blocks_large_cohort_before_profile(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import NormalizedRequest
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run for large cohort block"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="query_data_then_profile",
            country="mx",
            uids=[],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary="查询最近 7 天高流失用户并生成画像",
            query_request="最近7天高流失用户",
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: {"uids": [f"u{i:03d}" for i in range(201)], "rows_actual": 201, "rows_estimated": 201, "sql_text": "SELECT uid FROM t"},
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我找最近7天高流失用户并分析")]

    events = asyncio.run(_drive())
    types = [evt["type"] for evt in events]
    assert "execution_plan" in types
    assert "review_result" in types
    assert "final" in types
    assert "tool_started" in types
    assert "tool_completed" in types
    assert "缩小时间范围" in events[-1]["final_message"]


def test_run_agent_loop_known_cohort_opens_ack_before_emitting_preview(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import NormalizedRequest
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    call_order = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="query_data_then_profile",
            country="mx",
            uids=[],
            modules=["app"],
            request_summary="查询 cohort 并画像",
            query_request="拉一批用户",
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: {"child": object(), "sql_text": "SELECT uid FROM t", "rows_estimated": 1},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop._complete_query_data_cohort",
        lambda *args, **kwargs: {"uids": ["u1"], "rows_actual": 1, "rows_estimated": 1, "sql_text": "SELECT uid FROM t"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.open_ack",
        lambda sid: call_order.append("open_ack"),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.wait_ack",
        lambda sid, timeout_sec=600.0: (call_order.append("wait_ack") or True),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: __import__("app.services.orchestrator_agent.schemas", fromlist=["DataAvailability"]).DataAvailability(country="mx", checked_uids=["u1"], per_uid=[]),
    )

    session = create_session(country="mx")

    async def _drive():
        seen = []
        async for evt in run_agent_loop(session=session, prompt="帮我拉一批用户并分析"):
            if evt["type"] == "awaiting_user_ack":
                call_order.append("awaiting_user_ack")
            seen.append(evt)
        return seen

    events = asyncio.run(_drive())

    assert "awaiting_user_ack" in [evt["type"] for evt in events]
    assert call_order[:3] == ["open_ack", "awaiting_user_ack", "wait_ack"]


def test_run_agent_loop_blocks_non_mx_cohort_without_tool_dispatch(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import NormalizedRequest
    from app.services.orchestrator_agent.session_store import create_session

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="query_data_then_profile",
            country="th",
            uids=[],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary="查询泰国 cohort 并生成画像",
            query_request="最近7天高流失用户",
            read_only=False,
        ),
    )

    session = create_session(country="th")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我找最近7天高流失用户并分析")]

    events = asyncio.run(_drive())
    types = [evt["type"] for evt in events]
    assert types == ["session_started", "execution_plan", "plan_step_status", "plan_step_status", "review_result", "final"]
    assert "仅支持 mx" in events[-1]["final_message"]


def test_run_agent_loop_blocks_when_no_basic_bucket_exists(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary=f"分析 UID {uid} 的画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="missing", available=False, source_type="missing", path=None),
                    behavior=BucketAvailability(status="missing", available=False, source_type="missing", path=None),
                    credit=BucketAvailability(status="missing", available=False, source_type="missing", path=None),
                    available_buckets=[],
                    missing_buckets=["app", "behavior", "credit"],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.repair_profile_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("User rejected SQL execution")),
        raising=False,
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析 {uid}")]

    events = asyncio.run(_drive())
    types = [evt["type"] for evt in events]
    assert "tool_started" in types
    assert "run_profile" not in [evt.get("tool_name") for evt in events if evt.get("type") == "tool_started"]
    assert "无法生成可信画像" in events[-1]["final_message"]


def test_run_agent_loop_app_only_request_ignores_unrelated_missing_bucket_when_data_acquisition_disabled(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_disabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"
    seen_modules = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app"],
            request_summary=f"分析 UID {uid} 的 app 画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None),
                    credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None),
                    available_buckets=["app"],
                    missing_buckets=["behavior", "credit"],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: (
            seen_modules.extend(inp.modules or []),
            type("X", (), {
                "model_dump": lambda self, mode="json": {
                    "results": [{
                        "uid": uid,
                        "module": "app",
                        "result": {
                            "status": "ok",
                            "data": {"summary": "app ok", "structured_result": {"x": 1}, "charts": [], "report_markdown": ""},
                            "error": None,
                        },
                    }],
                    "cache_hits": 0,
                    "cache_misses": 1,
                },
            })()
        )[1],
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我看 {uid} 的 app 画像")]

    events = asyncio.run(_drive())

    plan_events = [evt for evt in events if evt["type"] == "execution_plan"]
    assert all("data_acquisition_unavailable" not in [step["step_id"] for step in evt["steps"]] for evt in plan_events)
    assert all("repair_credit" not in [step["step_id"] for step in evt["steps"]] for evt in plan_events)
    assert seen_modules == ["app"]
    review_evt = next(evt for evt in events if evt["type"] == "review_result")
    assert review_evt["status"] == "pass"


def test_run_agent_loop_full_profile_partial_when_credit_missing_and_data_acquisition_disabled(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_disabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"
    seen_modules = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary=f"分析 UID {uid} 的完整画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None),
                    available_buckets=["app", "behavior"],
                    missing_buckets=["credit"],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: (
            seen_modules.extend(inp.modules or []),
            type("X", (), {
                "model_dump": lambda self, mode="json": {
                    "results": [
                        {
                            "uid": uid,
                            "module": module,
                            "result": {
                                "status": "ok",
                                "data": {"summary": f"{module} ok", "structured_result": {"module": module}, "charts": [], "report_markdown": ""},
                                "error": None,
                            },
                        }
                        for module in (inp.modules or [])
                    ],
                    "cache_hits": 0,
                    "cache_misses": len(inp.modules or []),
                },
            })()
        )[1],
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析 {uid} 的完整画像")]

    events = asyncio.run(_drive())

    plan_events = [evt for evt in events if evt["type"] == "execution_plan"]
    assert any("data_acquisition_unavailable" in [step["step_id"] for step in evt["steps"]] for evt in plan_events)
    assert not any("repair_credit" in [step["step_id"] for step in evt["steps"]] for evt in plan_events)
    assert seen_modules == ["app", "behavior"]
    review_evt = next(evt for evt in events if evt["type"] == "review_result")
    assert review_evt["status"] == "warning"
    assert any(issue["type"] == "data_acquisition_unavailable" for issue in review_evt["issues"])


def test_run_agent_loop_credit_only_request_blocks_when_credit_missing_and_data_acquisition_disabled(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_disabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["credit"],
            request_summary=f"分析 UID {uid} 的征信画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None),
                    available_buckets=["app", "behavior"],
                    missing_buckets=["credit"],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_profile should not run when requested module is unavailable")),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析 {uid} 的征信画像")]

    events = asyncio.run(_drive())

    plan_events = [evt for evt in events if evt["type"] == "execution_plan"]
    assert any("data_acquisition_unavailable" in [step["step_id"] for step in evt["steps"]] for evt in plan_events)
    assert not any("repair_credit" in [step["step_id"] for step in evt["steps"]] for evt in plan_events)
    assert not any(evt["type"] == "tool_started" and evt.get("tool_name") == "run_profile" for evt in events)
    review_evt = next(evt for evt in events if evt["type"] == "review_result")
    assert review_evt["status"] == "fail"
    assert any(issue["type"] == "data_acquisition_unavailable" for issue in review_evt["issues"])


def test_run_agent_loop_direct_profile_still_plans_repair_when_data_acquisition_enabled(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"
    availability_calls = {"count": 0}

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app", "behavior", "credit"],
            request_summary=f"分析 UID {uid} 的画像",
            query_request=None,
            read_only=False,
        ),
    )

    def _availability(uids, country=None):
        availability_calls["count"] += 1
        credit_status = (
            BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None)
            if availability_calls["count"] == 1
            else BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/credit.csv")
        )
        available_buckets = ["app", "behavior"] if availability_calls["count"] == 1 else ["app", "behavior", "credit"]
        missing_buckets = ["credit"] if availability_calls["count"] == 1 else []
        return DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=credit_status,
                    available_buckets=available_buckets,
                    missing_buckets=missing_buckets,
                )
            ],
        )

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        _availability,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.repair_profile_data",
        lambda *args, **kwargs: type("X", (), {
            "model_dump": lambda self, mode="json": {
                "bucket": "credit",
                "requested_uids": [uid],
                "written_uids": [uid],
                "filenames": [f"{uid}.csv"],
                "sql_text": "SELECT * FROM bureau",
                "rows_estimated": 1,
                "rows_actual": 1,
            },
        })(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: type("X", (), {
            "model_dump": lambda self, mode="json": {
                "results": [
                    {
                        "uid": uid,
                        "module": module,
                        "result": {
                            "status": "ok",
                            "data": {"summary": f"{module} ok", "structured_result": {"module": module}, "charts": [], "report_markdown": ""},
                            "error": None,
                        },
                    }
                    for module in (inp.modules or [])
                ],
                "cache_hits": 0,
                "cache_misses": len(inp.modules or []),
            },
        })(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析 {uid} 的画像")]

    events = asyncio.run(_drive())

    plan_events = [evt for evt in events if evt["type"] == "execution_plan"]
    assert any("repair_credit" in [step["step_id"] for step in evt["steps"]] for evt in plan_events)
    assert not any("data_acquisition_unavailable" in [step["step_id"] for step in evt["steps"]] for evt in plan_events)


def test_run_agent_loop_cohort_emits_updated_execution_plan_for_profile_phase(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    uid = "824812551379353600"

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="query_data_then_profile",
            country="mx",
            uids=[],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary="最近 7 天高流失用户画像",
            query_request="最近7天高流失用户",
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: {"uids": [uid], "rows_actual": 1, "rows_estimated": 1, "sql_text": "SELECT uid FROM t"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/credit.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: type("X", (), {
            "model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])},
        })(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我找最近7天高流失用户并分析")]

    events = asyncio.run(_drive())
    plan_events = [evt for evt in events if evt["type"] == "execution_plan"]
    assert len(plan_events) >= 2


def test_run_agent_loop_need_clarification_emits_resolution_event(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import NormalizedRequest, RequestUnderstanding
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="need_clarification",
            country=None,
            uids=[],
            modules=[],
            trace_days=7,
            request_summary="找一批高流失用户",
            query_request="找一批高流失用户",
            read_only=False,
            request_understanding=RequestUnderstanding(
                intent="need_clarification",
                route_label="需要补充条件",
                rewritten_goal="补充 cohort 查询条件后继续执行",
                focus=["cohort"],
                requires_tools=False,
                route_reason="当前请求明显是在找一批用户，但缺少国家或时间范围。",
                answer_mode="tool_execution",
                missing_slots=["country", "time_window"],
                clarification_prompt="请补充国家和时间范围，例如：墨西哥、最近 7 天。",
                candidate_defaults={"country": "mx"},
            ),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.open_resolution",
        lambda session_id, resolution_id=None: None,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.wait_resolution",
        lambda session_id, timeout_sec=600.0: {"answers": {"country": "mx", "time_window": "最近 7 天"}, "resolution_type": "clarification"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.refine_normalized_request",
        lambda client, prompt, session, normalized_request: normalized_request.model_copy(update={
            "intent": "query_data_then_profile",
            "country": "mx",
            "query_request": "找墨西哥最近 7 天高流失用户并分析",
        }),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: {"uids": ["u1"], "rows_actual": 1, "rows_estimated": 1, "sql_text": "SELECT uid FROM t"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: __import__("app.services.orchestrator_agent.schemas", fromlist=["DataAvailability"]).DataAvailability(country="mx", checked_uids=["u1"], per_uid=[]),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="找一批高流失用户")]

    events = asyncio.run(_drive())

    assert "execution_plan" in [evt["type"] for evt in events]
    resolution_evt = next(evt for evt in events if evt["type"] == "awaiting_resolution")
    assert resolution_evt["resolution_type"] == "clarification"
    assert resolution_evt["required_slots"] == ["country", "time_window"]
    assert any(evt["type"] == "tool_started" and evt.get("tool_name") == "query_data" for evt in events)


def test_run_agent_loop_clarification_auto_profile_false_stops_after_query_data(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import NormalizedRequest, RequestUnderstanding
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="need_clarification",
            country=None,
            uids=[],
            modules=["app", "behavior"],
            trace_days=7,
            request_summary="找一批高流失用户",
            query_request="找一批高流失用户",
            read_only=False,
            request_understanding=RequestUnderstanding(
                intent="need_clarification",
                route_label="需要补充条件",
                rewritten_goal="补充 cohort 查询条件后继续执行",
                focus=["cohort"],
                requires_tools=False,
                route_reason="当前请求明显是在找一批用户，但缺少国家或时间范围。",
                answer_mode="tool_execution",
                missing_slots=["country", "time_window"],
                clarification_prompt="请补充国家和时间范围，例如：墨西哥、最近 7 天。",
                candidate_defaults={"country": "mx", "auto_profile": True},
            ),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.open_resolution",
        lambda session_id, resolution_id=None: None,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.wait_resolution",
        lambda session_id, timeout_sec=600.0: {
            "answers": {"country": "mx", "time_window": "最近 7 天", "auto_profile": False},
            "resolution_type": "clarification",
        },
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.refine_normalized_request",
        lambda client, prompt, session, normalized_request: normalized_request.model_copy(update={
            "intent": "query_data_then_profile",
            "country": "mx",
            "query_request": "找墨西哥最近 7 天高流失用户并分析",
        }),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: {"uids": ["u1", "u2"], "rows_actual": 2, "rows_estimated": 5, "sql_text": "SELECT uid FROM t"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("availability should not run when auto_profile=false")),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_profile should not run when auto_profile=false")),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="找一批高流失用户")]

    events = asyncio.run(_drive())

    assert any(evt["type"] == "tool_started" and evt.get("tool_name") == "query_data" for evt in events)
    final_evt = next(evt for evt in events if evt["type"] == "final")
    assert "如需继续画像" in final_evt["final_message"]
    plan_events = [evt for evt in events if evt["type"] == "execution_plan"]
    assert not any(any(step["step_id"] == "check_data" for step in evt["steps"]) for evt in plan_events)


def test_run_agent_loop_query_data_then_profile_blocked_when_data_acquisition_disabled(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import NormalizedRequest
    from app.services.orchestrator_agent.session_store import create_session

    monkeypatch.setenv("DATA_ACQUISITION_ENABLED", "false")
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="query_data_then_profile",
            country="mx",
            uids=[],
            modules=["app"],
            request_summary="查询 cohort 并画像",
            query_request="找墨西哥最近 7 天高流失用户并分析",
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("query_data should not run when data acquisition is disabled")),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="找墨西哥最近 7 天高流失用户并分析")]

    events = asyncio.run(_drive())

    final_evt = next(evt for evt in events if evt["type"] == "final")
    assert "未启用" in final_evt["final_message"] or "不可用" in final_evt["final_message"]
    assert not any(evt["type"] == "tool_started" and evt.get("tool_name") == "query_data" for evt in events)


def test_run_agent_loop_large_cohort_requires_repair_strategy_resolution(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    uids = [f"u{i:03d}" for i in range(21)]

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="query_data_then_profile",
            country="mx",
            uids=[],
            modules=["app", "behavior", "credit"],
            request_summary="查询 cohort 并画像",
            query_request="找墨西哥最近 7 天高流失用户并分析",
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: {"uids": uids, "rows_actual": len(uids), "rows_estimated": len(uids), "sql_text": "SELECT user_uuid FROM t"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.open_resolution",
        lambda session_id, resolution_id=None: None,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.wait_resolution",
        lambda session_id, timeout_sec=600.0: {"selected_option": "analyze_existing_only", "resolution_type": "repair_strategy"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda resolved_uids, country=None: DataAvailability(
            country="mx",
            checked_uids=list(resolved_uids),
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None),
                    credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None),
                    available_buckets=["app"],
                    missing_buckets=["behavior", "credit"],
                )
                for uid in resolved_uids
            ],
        ),
    )
    seen_modules = []
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: (
            seen_modules.extend(inp.modules or []),
            type("X", (), {
                "model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])},
            })()
        )[1],
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="找墨西哥最近 7 天高流失用户并分析")]

    events = asyncio.run(_drive())

    resolution_evt = next(evt for evt in events if evt["type"] == "awaiting_resolution")
    plan_events = [evt for evt in events if evt["type"] == "execution_plan"]
    assert resolution_evt["resolution_type"] == "repair_strategy"
    assert resolution_evt["selected_option"] is None
    assert resolution_evt["cohort_size"] == 21
    assert resolution_evt["missing_bucket_counts"] == {"behavior": 21, "credit": 21}
    assert "app" in seen_modules
    assert "behavior" not in seen_modules
    assert "credit" not in seen_modules
    assert any(any(step["step_id"] == "run_profile" for step in evt["steps"]) for evt in plan_events)


def test_run_agent_loop_medium_cohort_triggers_repair_strategy_by_uid_threshold(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    uids = [f"u{i:03d}" for i in range(10)]

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="query_data_then_profile",
            country="mx",
            uids=[],
            modules=["app", "behavior"],
            request_summary="查询 cohort 并画像",
            query_request="找墨西哥最近 7 天高流失用户并分析",
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.execute_query_data_cohort",
        lambda *args, **kwargs: {"uids": uids, "rows_actual": len(uids), "rows_estimated": len(uids), "sql_text": "SELECT user_uuid FROM t"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.open_resolution",
        lambda session_id, resolution_id=None: None,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.resolve_bus.wait_resolution",
        lambda session_id, timeout_sec=600.0: {"selected_option": "analyze_existing_only", "resolution_type": "repair_strategy"},
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda resolved_uids, country=None: DataAvailability(
            country="mx",
            checked_uids=list(resolved_uids),
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, source_type="missing", path=None),
                    credit=BucketAvailability(status="available", available=True, usable_for_profile=True, source_type="csv", path="/tmp/credit.csv"),
                    available_buckets=["app", "credit"],
                    missing_buckets=["behavior"],
                )
                for uid in resolved_uids
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: type("X", (), {
            "model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])},
        })(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="找墨西哥最近 7 天高流失用户并分析")]

    events = asyncio.run(_drive())

    resolution_evt = next(evt for evt in events if evt["type"] == "awaiting_resolution")
    assert resolution_evt["resolution_type"] == "repair_strategy"
    assert resolution_evt["cohort_size"] == 10


def test_run_agent_loop_workspace_followup_uses_evidence_llm_without_tool_rerun(monkeypatch):
    from datetime import datetime, timezone

    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import ToolCallRecord
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"
    session = create_session(country="mx")
    session.tool_calls.append(ToolCallRecord(
        tool_name="run_profile",
        tool_call_id="tc-existing",
        input={"uids": [uid], "app_time": None, "modules": ["behavior"]},
        output={
            "results": [
                {
                    "uid": uid,
                    "module": "behavior",
                    "result": {
                        "status": "ok",
                        "data": {
                            "summary": "行为画像：近30天登录2天，流失风险高。",
                            "structured_result": {"risk_level": "high", "engagement": "low"},
                            "charts": [],
                            "report_markdown": "",
                        },
                        "error": None,
                    },
                }
            ],
            "cache_hits": 1,
            "cache_misses": 0,
        },
        status="done",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    ))

    model_calls: list[dict] = []

    class _EvidenceClient:
        last_token_usage = {"prompt": 120, "completion": 40, "total": 160}

        def generate_structured(self, **kwargs):
            model_calls.append(kwargs)
            return {
                "status": "ok",
                "structured_result": {
                    "final_message": "这是基于已有画像证据的聚焦回答：该用户近30天登录显著偏低，因此流失风险高；以下已改写为客服话术。",
                    "confidence": 0.91,
                },
            }

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: _EvidenceClient(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_profile should not rerun for workspace follow-up")),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_trace",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_trace should not rerun for workspace follow-up")),
    )

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我解释为什么这个用户流失风险高，并改成客服话术")]

    events = asyncio.run(_drive())
    plan_evt = next(evt for evt in events if evt["type"] == "execution_plan")

    assert model_calls, "workspace follow-up should call the evidence-constrained LLM path"
    assert plan_evt["request_understanding"]["answer_mode"] == "workspace_evidence_answer"
    assert plan_evt["request_understanding"]["requires_tools"] is False
    assert "这是基于已有画像证据的聚焦回答" in events[-1]["final_message"]
    assert "tool_started" not in [evt["type"] for evt in events]


def test_run_agent_loop_general_query_data_opens_ack_before_emitting_preview(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.session_store import create_session

    call_order = []

    class _GeneralClient:
        last_token_usage = {"prompt": 80, "completion": 20, "total": 100}

        def __init__(self):
            self.calls = 0

        def generate_structured(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "status": "ok",
                    "structured_result": {
                        "tool_call": {
                            "name": "query_data",
                            "arguments": {"request": "拉一批用户", "country": "mx"},
                        }
                    },
                }
            return {
                "status": "ok",
                "structured_result": {"final_message": "done", "confidence": 0.6},
            }

    class _FakeChild:
        def __init__(self, country):
            self.country = country

        def run_query(self, req):
            return type("QR", (), {"sql_text": "SELECT uid FROM t", "rows_estimated": 1})()

        def execute(self, sql):
            return {"uids": ["u1"], "rows_actual": 1}

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: _GeneralClient(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: __import__("app.services.orchestrator_agent.schemas", fromlist=["NormalizedRequest"]).NormalizedRequest(
            intent="general_chat",
            country="mx",
            uids=[],
            modules=[],
            request_summary="普通聊天",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.query_data._ChildAgent",
        _FakeChild,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.open_ack",
        lambda sid: call_order.append("open_ack"),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.ack_bus.wait_ack",
        lambda sid, timeout_sec=600.0: (call_order.append("wait_ack") or True),
    )

    session = create_session(country="mx")

    async def _drive():
        seen = []
        async for evt in run_agent_loop(session=session, prompt="请查询一批用户"):
            if evt["type"] == "awaiting_user_ack":
                call_order.append("awaiting_user_ack")
            seen.append(evt)
        return seen

    events = asyncio.run(_drive())

    assert "awaiting_user_ack" in [evt["type"] for evt in events]
    assert call_order[:3] == ["open_ack", "awaiting_user_ack", "wait_ack"]


def test_run_agent_loop_read_only_followup_without_workspace_emits_blocked_trace(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.session_store import create_session

    class _ShouldNotCallModelClient:
        last_token_usage = {"prompt": 0, "completion": 0, "total": 0}

        def generate_structured(self, **kwargs):
            raise AssertionError("LLM should not run when read-only follow-up has no reusable workspace")

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: _ShouldNotCallModelClient(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我总结一下当前用户画像")]

    events = asyncio.run(_drive())
    types = [evt["type"] for evt in events]
    review_evt = next(evt for evt in events if evt["type"] == "review_result")

    assert types == ["session_started", "execution_plan", "plan_step_status", "plan_step_status", "review_result", "final"]
    assert review_evt["status"] == "fail"
    assert review_evt["issues"][0]["type"] == "no_workspace_context"
    assert "先分析 UID" in events[-1]["final_message"]


def test_run_agent_loop_general_chat_emits_lightweight_execution_plan(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.session_store import create_session

    class _GeneralClient:
        last_token_usage = {"prompt": 80, "completion": 20, "total": 100}

        def generate_structured(self, **kwargs):
            return {
                "status": "ok",
                "structured_result": {
                    "final_message": "我是当前的画像分析助手。",
                    "confidence": 0.6,
                },
            }

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: _GeneralClient(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="你是谁？")]

    events = asyncio.run(_drive())
    types = [evt["type"] for evt in events]
    plan_evt = next(evt for evt in events if evt["type"] == "execution_plan")

    assert types[:3] == ["session_started", "execution_plan", "final"]
    assert plan_evt["request_understanding"]["answer_mode"] == "general_chat"
    assert plan_evt["request_understanding"]["route_label"] == "通用 Agent 对话"
    assert plan_evt["steps"][0]["step_id"] == "general_answer"


def test_run_agent_loop_general_run_profile_forces_strict_mode(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.session_store import create_session

    seen_inputs = []

    class _GeneralClient:
        last_token_usage = {"prompt": 80, "completion": 20, "total": 100}

        def __init__(self):
            self.calls = 0

        def generate_structured(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "status": "ok",
                    "structured_result": {
                        "tool_call": {
                            "name": "run_profile",
                            "arguments": {
                                "uids": ["824812551379353600"],
                                "app_time": None,
                                "modules": ["app"],
                            },
                        }
                    },
                }
            return {
                "status": "ok",
                "structured_result": {"final_message": "done", "confidence": 0.6},
            }

    def _fake_run_profile(inp, progress_callback=None):
        seen_inputs.append(inp.model_dump(mode="json"))
        return type("X", (), {"model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": 1}})()

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: _GeneralClient(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: __import__("app.services.orchestrator_agent.schemas", fromlist=["NormalizedRequest"]).NormalizedRequest(
            intent="general_chat",
            country="mx",
            uids=[],
            modules=[],
            request_summary="普通聊天",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="请执行画像")]

    asyncio.run(_drive())

    assert seen_inputs[0]["strict_data_mode"] is True


def test_run_agent_loop_trace_uses_requested_days(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.session_store import create_session

    seen_inputs = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )

    def _fake_run_trace(input_data):
        seen_inputs.append(input_data.model_dump(mode="json"))
        return type("X", (), {
            "model_dump": lambda self, mode="json": {
                "uid": input_data.uid,
                "status": "ok",
                "events": [],
                "summary": {},
            },
        })()

    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_trace", _fake_run_trace)

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我分析 UID 824812551379353600 最近 30 天轨迹")]

    asyncio.run(_drive())
    assert seen_inputs == [{"uid": "824812551379353600", "days": 30}]


def test_run_agent_loop_profile_uses_workspace_application_time(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"
    seen_inputs = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app"],
            request_summary=f"分析 UID {uid} 的 app 画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                    credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                    available_buckets=["app"],
                    missing_buckets=["behavior", "credit"],
                )
            ],
        ),
    )

    def _fake_run_profile(inp, progress_callback=None):
        seen_inputs.append(inp.model_dump(mode="json"))
        return type("X", (), {"model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": 1}})()

    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)

    session = create_session(country="mx")
    session.active_entities["workspace_snapshot"] = {"applicationTime": "2026-05-15T12:30"}

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析{uid}这个用户的app画像")]

    asyncio.run(_drive())
    assert seen_inputs[0]["app_time"] == "2026-05-15T12:30"


def test_run_agent_loop_tool_record_does_not_expose_uid_modules(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app"],
            request_summary=f"分析 UID {uid} 的 app 画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                    credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                    available_buckets=["app"],
                    missing_buckets=["behavior", "credit"],
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: type("X", (), {"model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": 1}})(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我分析{uid}这个用户的app画像")]

    asyncio.run(_drive())

    run_profile_record = next(record for record in session.tool_calls if record.tool_name == "run_profile")
    assert "uid_modules" not in run_profile_record.input


def test_run_agent_loop_only_runs_requested_app_module(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"
    seen_modules = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["app"],
            request_summary=f"分析 UID {uid} 的 app 画像",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/credit.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                )
            ],
        ),
    )

    def _fake_run_profile(inp, progress_callback=None):
        seen_modules.append(list(inp.modules or []))
        return type("X", (), {"model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])}})()

    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"只分析这个 UID {uid} 的 App画像")]

    asyncio.run(_drive())
    assert seen_modules == [["app"]]


def test_run_agent_loop_only_runs_requested_product_dependency_chain(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    uid = "824812551379353600"
    seen_modules = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_uid",
            country="mx",
            uids=[uid],
            modules=["product"],
            request_summary=f"分析 UID {uid} 的产品策略",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[uid],
            per_uid=[
                UidAvailability(
                    uid=uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app.csv"),
                    behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/behavior.csv"),
                    credit=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/credit.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                )
            ],
        ),
    )

    def _fake_run_profile(inp, progress_callback=None):
        seen_modules.append(list(inp.modules or []))
        return type("X", (), {"model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])}})()

    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt=f"帮我给 UID {uid} 生成产品策略")]

    asyncio.run(_drive())
    assert seen_modules == [["app", "behavior", "credit", "comprehensive", "product"]]


def test_requirements_include_tenacity():
    from pathlib import Path

    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    assert "tenacity" in requirements


def test_run_agent_loop_mixed_batch_runs_per_uid_module_plan(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    full_uid = "824812551379353600"
    partial_uid = "824812551379353601"
    seen_calls = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_batch",
            country="mx",
            uids=[full_uid, partial_uid],
            modules=[],
            request_summary="批量分析 2 个 UID",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: DataAvailability(
            country="mx",
            checked_uids=[full_uid, partial_uid],
            per_uid=[
                UidAvailability(
                    uid=full_uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app1.csv"),
                    behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/behavior1.csv"),
                    credit=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/credit1.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                ),
                UidAvailability(
                    uid=partial_uid,
                    app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app2.csv"),
                    behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                    credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                    available_buckets=["app"],
                    missing_buckets=["behavior", "credit"],
                ),
            ],
        ),
    )

    def _fake_run_profile(inp, progress_callback=None):
        seen_calls.append({"uids": list(inp.uids), "modules": list(inp.modules or [])})
        return type("X", (), {
            "model_dump": lambda self, mode="json": {
                "results": [],
                "cache_hits": 0,
                "cache_misses": len(inp.uids) * len(inp.modules or []),
            },
        })()

    monkeypatch.setattr("app.services.orchestrator_agent.tools.run_profile", _fake_run_profile)
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.repair_profile_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("repair disabled")),
        raising=False,
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我批量分析两个 UID")]

    asyncio.run(_drive())
    assert seen_calls == [
        {"uids": [full_uid], "modules": ["app", "behavior", "credit", "comprehensive", "product", "ops"]},
        {"uids": [partial_uid], "modules": ["app"]},
    ]


def test_build_profile_review_flags_module_errors_and_degraded_outputs():
    from app.services.orchestrator_agent.review_rules import build_profile_review
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )

    uid = "824812551379353600"
    availability = DataAvailability(
        country="mx",
        checked_uids=[uid],
        per_uid=[
            UidAvailability(
                uid=uid,
                app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app.csv"),
                behavior=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/behavior.csv"),
                credit=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/credit.csv"),
                available_buckets=["app", "behavior", "credit"],
                missing_buckets=[],
            )
        ],
    )
    profile_output = {
        "results": [
            {
                "uid": uid,
                "module": "app",
                "result": {
                    "status": "ok",
                    "data": {
                        "summary": "",
                        "structured_result": {},
                        "model_trace": {"used_llm": False, "fallback_reason": "model_unavailable"},
                    },
                    "error": None,
                },
            },
            {
                "uid": uid,
                "module": "behavior",
                "result": {
                    "status": "error",
                    "data": None,
                    "error": "boom",
                },
            },
        ],
    }
    normalized_request = NormalizedRequest(
        intent="profile_uid",
        country="mx",
        uids=[uid],
        modules=["app", "behavior"],
        request_summary="分析 UID 画像",
        query_request=None,
        read_only=False,
    )

    review = build_profile_review(
        availability,
        {uid: ["app", "behavior"]},
        profile_output,
        normalized_request,
    )

    issue_types = {issue["type"] for issue in review.issues}
    assert review.status == "fail"
    assert "module_error" in issue_types
    assert "empty_summary" in issue_types
    assert "missing_structured_result" in issue_types
    assert "degraded_model_output" in issue_types


def test_build_profile_review_passes_when_single_requested_module_is_satisfied():
    from app.services.orchestrator_agent.review_rules import build_profile_review
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )

    uid = "824812551379353600"
    availability = DataAvailability(
        country="mx",
        checked_uids=[uid],
        per_uid=[
            UidAvailability(
                uid=uid,
                app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app.csv"),
                behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                credit=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                available_buckets=["app"],
                missing_buckets=["behavior", "credit"],
            )
        ],
    )
    profile_output = {
        "results": [
            {
                "uid": uid,
                "module": "app",
                "result": {
                    "status": "ok",
                    "data": {
                        "summary": "app ok",
                        "structured_result": {"segment": "A"},
                    },
                    "error": None,
                },
            }
        ],
    }
    normalized_request = NormalizedRequest(
        intent="profile_uid",
        country="mx",
        uids=[uid],
        modules=["app"],
        request_summary="只分析 App 画像",
        query_request=None,
        read_only=False,
    )

    review = build_profile_review(
        availability,
        {uid: ["app"]},
        profile_output,
        normalized_request,
    )

    assert review.status == "pass"
    assert review.issues == []


def test_build_profile_review_ignores_weak_non_requested_bucket():
    from app.services.orchestrator_agent.review_rules import build_profile_review
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        UidAvailability,
    )

    uid = "824812551379353600"
    availability = DataAvailability(
        country="mx",
        checked_uids=[uid],
        per_uid=[
            UidAvailability(
                uid=uid,
                app=BucketAvailability(status="available", available=True, usable_for_profile=True, checked_sources=["csv"], source_type="csv", path="/tmp/app.csv"),
                behavior=BucketAvailability(status="missing", available=False, usable_for_profile=False, checked_sources=["missing"], source_type="missing", path=None),
                credit=BucketAvailability(
                    status="available",
                    available=True,
                    usable_for_profile=True,
                    checked_sources=["csv"],
                    source_type="csv",
                    source_shape="summary",
                    path="/tmp/credit.csv",
                    weak_reasons=["legacy_credit_summary_fallback"],
                    quality_score=0.8,
                ),
                available_buckets=["app", "credit"],
                missing_buckets=["behavior"],
            )
        ],
    )
    profile_output = {
        "results": [
            {
                "uid": uid,
                "module": "app",
                "result": {
                    "status": "ok",
                    "data": {
                        "summary": "app ok",
                        "structured_result": {"segment": "A"},
                    },
                    "error": None,
                },
            }
        ],
    }
    normalized_request = NormalizedRequest(
        intent="profile_uid",
        country="mx",
        uids=[uid],
        modules=["app"],
        request_summary="只分析 App 画像",
        query_request=None,
        read_only=False,
    )

    review = build_profile_review(
        availability,
        {uid: ["app"]},
        profile_output,
        normalized_request,
    )

    assert review.status == "pass"
    assert review.issues == []


def test_run_agent_loop_repairs_only_missing_uids_for_bucket(monkeypatch):
    from app.services.orchestrator_agent.agent_loop import run_agent_loop
    from app.services.orchestrator_agent.schemas import (
        BucketAvailability,
        DataAvailability,
        NormalizedRequest,
        RepairProfileDataOutput,
        UidAvailability,
    )
    from app.services.orchestrator_agent.session_store import create_session

    _patch_enabled_data_acquisition(monkeypatch)

    missing_uid = "824812551379353600"
    complete_uid = "824812551379353601"
    availability_seq = iter([
        DataAvailability(
            country="mx",
            checked_uids=[missing_uid, complete_uid],
            per_uid=[
                UidAvailability(
                    uid=missing_uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app1.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior1.csv"),
                    credit=BucketAvailability(status="missing", available=False, source_type="missing", path=None),
                    available_buckets=["app", "behavior"],
                    missing_buckets=["credit"],
                ),
                UidAvailability(
                    uid=complete_uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app2.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior2.csv"),
                    credit=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/credit2.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                ),
            ],
        ),
        DataAvailability(
            country="mx",
            checked_uids=[missing_uid, complete_uid],
            per_uid=[
                UidAvailability(
                    uid=missing_uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app1.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior1.csv"),
                    credit=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/credit1.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                ),
                UidAvailability(
                    uid=complete_uid,
                    app=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/app2.csv"),
                    behavior=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/behavior2.csv"),
                    credit=BucketAvailability(status="available", available=True, source_type="csv", path="/tmp/credit2.csv"),
                    available_buckets=["app", "behavior", "credit"],
                    missing_buckets=[],
                ),
            ],
        ),
    ])
    repair_calls: list[list[str]] = []

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.ModelClient",
        lambda: type("NoLLM", (), {"generate_structured": lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not run"))})(),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.normalize_request",
        lambda prompt, session, detected_country=None: NormalizedRequest(
            intent="profile_batch",
            country="mx",
            uids=[missing_uid, complete_uid],
            modules=["app", "behavior", "credit", "comprehensive", "product", "ops"],
            request_summary="批量分析 2 个 UID",
            query_request=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.check_data_availability",
        lambda uids, country=None: next(availability_seq),
    )

    def _fake_repair(input_data, *, session_id: str, tool_call_id: str, before_ack=None):
        repair_calls.append(list(input_data.uids))
        if before_ack:
            before_ack("SELECT uid FROM bureau", 1)
        return RepairProfileDataOutput(
            bucket="credit",
            requested_uids=list(input_data.uids),
            written_uids=list(input_data.uids),
            filenames=[f"{uid}.csv" for uid in input_data.uids],
            sql_text="SELECT uid FROM bureau",
            rows_estimated=1,
            rows_actual=len(input_data.uids),
        )

    monkeypatch.setattr(
        "app.services.orchestrator_agent.agent_loop.repair_profile_data",
        _fake_repair,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.orchestrator_agent.tools.run_profile",
        lambda inp, progress_callback=None: type("X", (), {
            "model_dump": lambda self, mode="json": {"results": [], "cache_hits": 0, "cache_misses": len(inp.modules or [])},
        })(),
    )

    session = create_session(country="mx")

    async def _drive():
        return [evt async for evt in run_agent_loop(session=session, prompt="帮我批量分析这两个 UID")]

    asyncio.run(_drive())
    assert repair_calls == [[missing_uid]]
