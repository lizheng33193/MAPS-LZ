"""V2 Output Layer. See docs/specs/data_acquisition_agent_v2.md §8.

Bucket 切片 + schema 校验 + .tmp_<rid> + os.replace 流程。
单文件层面 atomic；跨多文件 crash-consistency trade-off 见 §8.4。
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Optional

import pandas as pd

from .schemas import ErrorType


class OutputWriterError(Exception):
    """输出层错误；沿用 V1 OrchestratorError 风格。"""

    def __init__(self, error_type: ErrorType, message: str, request_id: str = ""):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.request_id = request_id


APP_BUCKET_REQUIRED_COLUMNS: tuple[str, ...] = (
    "uid",
    "app_name",
    "app_package",
    "first_install_time",
    "last_update_time",
    "gp_category",
    "ai_category_level_2_CN",
)


def validate_bucket_schema(
    df: pd.DataFrame,
    *,
    output_bucket: str,
    output_format: str,
    uid_column: str,
    request_id: str,
) -> None:
    """§8.1 schema 校验：app bucket 强制 csv + 7 字段；uid_column 缺失 → result_validation_failed。"""
    if uid_column not in df.columns:
        raise OutputWriterError(ErrorType.RESULT_VALIDATION_FAILED,
            "result validation failed", request_id=request_id)
    if output_bucket == "app":
        if output_format != "csv":
            raise OutputWriterError(ErrorType.RESULT_VALIDATION_FAILED,
                "result validation failed", request_id=request_id)
        missing = set(APP_BUCKET_REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            raise OutputWriterError(ErrorType.RESULT_VALIDATION_FAILED,
                "result validation failed", request_id=request_id)


def build_per_uid_payloads(
    df: pd.DataFrame,
    *,
    output_bucket: str,
    output_format: str,
    uid_column: str,
    approved_by: str,
    source_request_id: Optional[str],
    executed_at: str,
    request_id: str,
) -> list[tuple[str, bytes]]:
    """§8.1 内存切片：groupby(uid_column) → list[(uid, payload_bytes)]。

    behavior / credit + json：包 schema_version="da_agent_v2" 外壳。
    app + csv：utf-8-sig 编码。
    """
    import io, json
    items: list[tuple[str, bytes]] = []
    for uid, group in df.groupby(uid_column, sort=True):
        uid_str = str(uid)
        if output_format == "csv":
            buf = io.StringIO()
            group.to_csv(buf, index=False)
            items.append((uid_str, buf.getvalue().encode("utf-8-sig")))
        else:  # json
            wrapper = {
                "schema_version": "da_agent_v2",
                "source_meta": {
                    "executed_at": executed_at,
                    "approved_by": approved_by,
                    "source_request_id": source_request_id,
                    "row_count": len(group),
                },
                "uid": uid_str,
                "rows": group.to_dict(orient="records"),
            }
            items.append((uid_str,
                json.dumps(wrapper, ensure_ascii=False).encode("utf-8")))
    return items


def write_per_uid_atomic(
    items: list[tuple[str, bytes]],
    *,
    bucket_dir: Path,
    output_format: str,
    overwrite: bool,
    request_id: str,
) -> list[str]:
    """§8.3 .tmp_<rid> + os.replace 原子流程。

    返回 filenames（仅文件名，不含目录）；失败 rmtree(.tmp) + output_write_failed 500。
    """
    tmp_dir = bucket_dir / f".tmp_{request_id}"
    try:
        tmp_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        raise OutputWriterError(ErrorType.OUTPUT_WRITE_FAILED,
            "output write failed", request_id=request_id)
    filenames: list[str] = []
    try:
        for uid, payload in items:
            if not re.fullmatch(r'[a-zA-Z0-9_\-]+', uid):
                raise ValueError("Invalid UID format")
            fn = f"{uid}.{output_format}"
            (tmp_dir / fn).write_bytes(payload)
            filenames.append(fn)
        if not overwrite:
            for fn in filenames:
                if (bucket_dir / fn).exists():
                    raise OutputWriterError(ErrorType.RESULT_VALIDATION_FAILED,
                        "result validation failed", request_id=request_id)
        for fn in filenames:
            os.replace(tmp_dir / fn, bucket_dir / fn)
    except OutputWriterError:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise OutputWriterError(ErrorType.OUTPUT_WRITE_FAILED,
            "output write failed", request_id=request_id) from None
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return filenames


def resolve_bucket_dir(output_bucket: str) -> Path:
    """从 settings.{app,behavior,credit}_by_uid_dir 解析 bucket 目标目录。"""
    from app.core.config import settings
    _BUCKET_TO_ATTR = {
        "app": "app_by_uid_dir",
        "behavior": "behavior_by_uid_dir",
        "credit": "credit_by_uid_dir",
    }
    return settings.resolve_path(getattr(settings, _BUCKET_TO_ATTR[output_bucket]))
