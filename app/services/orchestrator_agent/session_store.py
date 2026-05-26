"""JSON-based session store with atexit flush and resume support."""

from __future__ import annotations

import atexit
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services.orchestrator_agent.schemas import OrchestratorSession


_LOCK = threading.Lock()
_DIRTY: set[str] = set()
_CACHE: dict[str, OrchestratorSession] = {}


def _sessions_dir() -> Path:
    p = settings.project_root / "outputs" / "orchestrator_sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_session(
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    country: str | None = None,
) -> OrchestratorSession:
    sid = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    sess = OrchestratorSession(
        session_id=sid,
        created_at=now,
        updated_at=now,
        user_id=user_id or "local-default-user",
        project_id=project_id or "agent-user-profile-fork",
        country=country,
    )
    with _LOCK:
        _CACHE[sid] = sess
        _DIRTY.add(sid)
    return sess


def get_session(session_id: str) -> OrchestratorSession | None:
    with _LOCK:
        if session_id in _CACHE:
            return _CACHE[session_id]
    path = _sessions_dir() / f"{session_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    sess = OrchestratorSession.model_validate(data)
    with _LOCK:
        _CACHE[session_id] = sess
    return sess


def save_session(sess: OrchestratorSession) -> None:
    sess.updated_at = datetime.now(timezone.utc)
    with _LOCK:
        _CACHE[sess.session_id] = sess
        _DIRTY.add(sess.session_id)


def flush() -> None:
    with _LOCK:
        for sid in list(_DIRTY):
            sess = _CACHE.get(sid)
            if not sess:
                continue
            path = _sessions_dir() / f"{sid}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(sess.model_dump_json(indent=2), encoding="utf-8")
        _DIRTY.clear()


atexit.register(flush)
