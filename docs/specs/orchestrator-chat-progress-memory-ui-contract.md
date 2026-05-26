# Orchestrator Chat Progress And Memory UI Contract

## Purpose

This contract defines the NL Chat progress events and the UI boundary between
short-term chat history and long-term memory.

## Profile Progress Events

`run_profile` keeps its final `tool_completed` event, but may also emit
module-level progress events while the tool is still running.

Event shape:

```json
{
  "type": "tool_progress",
  "tool_call_id": "<tool call id>",
  "tool_name": "run_profile",
  "progress_type": "profile_module_completed",
  "uid": "<uid>",
  "module": "app|behavior|credit|comprehensive|product|ops",
  "result": {"uid": "...", "module": "...", "status": "ok", "data": {}, "error": null},
  "status": "ok|error",
  "completed": 1,
  "total": 6
}
```

The frontend must treat `tool_progress` and `tool_completed` as idempotent
sources for the same module result. `tool_completed` remains the durable final
tool output written into the session.

The backend should log module progress with enough fields to locate a stuck
profile run: `session_id`, `tool_call_id`, `uid`, `module`, `completed`,
`total`, `status`, and elapsed time where available. These logs are
observability-only and do not change the SSE wire shape.

## Session History

Short-term chat history is stored as session JSON under
`outputs/orchestrator_sessions/`.

`GET /api/orchestrator/sessions?limit=20` returns recent session metadata for
the request identity. It does not return full messages.

Each session list item contains:

- `session_id`
- `created_at`
- `updated_at`
- `status`
- `user_id`
- `project_id`
- `country`
- `message_count`
- `last_user_message_preview`
- `final_message_preview`

The v1 UI supports listing and opening sessions only. It does not delete or
hard-delete session files.

The UI may add client-side search and filters over this metadata. Search must
not require full message payloads and must keep session history read-only.

## Long-Term Memory

Long-term memory remains SQLite + FTS5 at `outputs/memory/memory.sqlite3`.

UI language must make these statuses explicit:

- `active`: participates in future recall.
- `archived`: does not participate in recall, but can be restored.
- `deleted`: soft-deleted, does not participate in recall, but can still be
  listed and restored.

The v1 UI does not hard delete memory rows and does not clear deleted rows.

The UI should explain recall eligibility in user-facing language:

- Active rows for the current identity can be recalled when query/list filters
  match their content, category, tags, or country.
- Archived and deleted rows do not participate in recall, but can be viewed and
  restored through the inspector.
