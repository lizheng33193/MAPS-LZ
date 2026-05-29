"""In-memory ACK rendezvous via threading.Event.

Current keying stays session-scoped for single-process demo/runtime use.
Future pluggable backends should target a composite identity:
`session_id + execution_id + step_id`.
"""

from __future__ import annotations

import threading
from typing import Optional

_LOCK = threading.Lock()
_PENDING: dict[str, dict] = {}


def open_ack(session_id: str) -> threading.Event:
    """Register a session as awaiting ACK."""
    ev = threading.Event()
    with _LOCK:
        _PENDING[session_id] = {"event": ev, "result": None}
    return ev


def resolve_ack(session_id: str, confirm: bool) -> bool:
    """SSE handler calls this when user POST /sessions/{id}/ack."""
    with _LOCK:
        slot = _PENDING.get(session_id)
    if slot is None:
        return False
    slot["result"] = confirm
    slot["event"].set()
    return True


def wait_ack(session_id: str, timeout_sec: float = 600.0) -> Optional[bool]:
    """Block until resolve_ack or timeout. Returns confirm value or None on timeout."""
    with _LOCK:
        slot = _PENDING.get(session_id)
    if slot is None:
        return None
    slot["event"].wait(timeout=timeout_sec)
    with _LOCK:
        result = _PENDING.pop(session_id, {}).get("result")
    return result
