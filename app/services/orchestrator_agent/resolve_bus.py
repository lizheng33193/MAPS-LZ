"""In-memory generic resolution rendezvous for clarification/strategy cards.

Current keying stays session-scoped for single-process demo/runtime use.
Future pluggable backends should target a composite identity:
`session_id + execution_id + step_id`.
"""

from __future__ import annotations

import threading
from typing import Any


_LOCK = threading.Lock()
_PENDING: dict[str, dict[str, Any]] = {}


def open_resolution(session_id: str, resolution_id: str | None = None) -> threading.Event:
    ev = threading.Event()
    with _LOCK:
        _PENDING[session_id] = {
            "event": ev,
            "result": None,
            "resolution_id": resolution_id,
        }
    return ev


def resolve_pending_resolution(session_id: str, payload: dict[str, Any]) -> bool:
    with _LOCK:
        slot = _PENDING.get(session_id)
    if slot is None:
        return False
    slot["result"] = dict(payload or {})
    slot["event"].set()
    return True


def wait_resolution(session_id: str, timeout_sec: float = 600.0) -> dict[str, Any] | None:
    with _LOCK:
        slot = _PENDING.get(session_id)
    if slot is None:
        return None
    slot["event"].wait(timeout=timeout_sec)
    with _LOCK:
        result = _PENDING.pop(session_id, {}).get("result")
    return result
