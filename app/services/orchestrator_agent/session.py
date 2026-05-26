"""Session-bound ACK gateway + per-session query_cancelled flag.

Phase 2 Task 2.2 接入真实 SessionStore 时只追加 wire-up，本文件结构不再变。
"""

from __future__ import annotations

import threading
from typing import Callable

_LOCK = threading.Lock()
_ACK_PROVIDER: Callable[..., bool] | None = None
_PER_SESSION_CANCEL: dict[str, bool] = {}


def register_ack_provider(provider: Callable[..., bool]) -> None:
    """Wire SSE handler's ack_bus.wait_ack into this gateway.

    Provider signature:
        provider(session_id, sql_text, artifact_path, rows_estimated) -> bool
    """
    global _ACK_PROVIDER
    _ACK_PROVIDER = provider


def get_active_session_ack(
    session_id: str,
    sql_text: str,
    artifact_path: str = "",
    rows_estimated: int = -1,
) -> bool:
    """Block until user ACKs (via SSE → ack_bus). Default deny if not wired."""
    if _ACK_PROVIDER is None:
        return False
    return _ACK_PROVIDER(
        session_id=session_id,
        sql_text=sql_text,
        artifact_path=artifact_path,
        rows_estimated=rows_estimated,
    )


def is_query_cancelled(session_id: str) -> bool:
    with _LOCK:
        return _PER_SESSION_CANCEL.get(session_id, False)


def mark_query_cancelled(session_id: str) -> None:
    with _LOCK:
        _PER_SESSION_CANCEL[session_id] = True


def reset_query_cancelled(session_id: str) -> None:
    with _LOCK:
        _PER_SESSION_CANCEL.pop(session_id, None)
