const chatInitialState = {
  sessionId: null,
  messages: [],
  toolCalls: [],
  pendingAck: null,
  budget: null,
  providerFallback: null,
  final: null,
  error: null,
  streamEnded: false,
};

function _appendAssistant(messages, delta) {
  const last = messages[messages.length - 1];
  if (last && last.role === 'assistant' && !last.finalized) {
    return messages.slice(0, -1).concat([{ ...last, content: (last.content || '') + delta }]);
  }
  return messages.concat([{ role: 'assistant', content: delta, finalized: false }]);
}

function _finalizeAssistant(messages, finalMessage) {
  const last = messages[messages.length - 1];
  if (last && last.role === 'assistant' && !last.finalized) {
    return messages.slice(0, -1).concat([{ ...last, content: finalMessage, finalized: true }]);
  }
  return messages.concat([{ role: 'assistant', content: finalMessage, finalized: true }]);
}

function chatReducer(state, evt) {
  switch (evt.type) {
    case 'user_input':
      return { ...state, error: null, messages: state.messages.concat([{ role: 'user', content: evt.content }]) };
    case 'session_started':
      return { ...state, sessionId: evt.session_id };
    case 'tool_started':
      // 2026-05-04 方案 A v3：记录 startedAtMs 让 ChatPanel 显示已用时间。
      return { ...state, toolCalls: state.toolCalls.concat([{ tool_call_id: evt.tool_call_id, tool_name: evt.tool_name, status: 'pending', input: evt.input, output: null, startedAtMs: Date.now() }]) };
    case 'tool_progress': {
      const progressEvt = {
        progress_type: evt.progress_type,
        uid: evt.uid,
        module: evt.module,
        result: evt.result,
        status: evt.status,
        completed: evt.completed,
        total: evt.total,
      };
      const updated = state.toolCalls.map((t) => (
        t.tool_call_id === evt.tool_call_id
          ? { ...t, progress: (t.progress || []).concat([progressEvt]) }
          : t
      ));
      return { ...state, toolCalls: updated };
    }
    case 'tool_completed': {
      const updated = state.toolCalls.map((t) => t.tool_call_id === evt.tool_call_id ? { ...t, status: evt.status === 'ok' ? 'ok' : 'error', output: evt.output, finishedAtMs: Date.now() } : t);
      const pendingAck = state.pendingAck && state.pendingAck.tool_call_id === evt.tool_call_id ? null : state.pendingAck;
      return { ...state, toolCalls: updated, pendingAck };
    }
    case 'assistant_thinking':
      return { ...state, messages: _appendAssistant(state.messages, evt.content_delta || '') };
    case 'awaiting_user_ack':
      return { ...state, pendingAck: { tool_call_id: evt.tool_call_id, sql_text: evt.sql_text || '', rows_estimated: evt.rows_estimated ?? null } };
    case 'budget_warning':
      return { ...state, budget: { used: evt.used, limit: evt.limit, percentage: evt.percentage } };
    case 'provider_fallback':
      return { ...state, providerFallback: { from: evt.from, to: evt.to, reason: evt.reason } };
    case 'error':
      return { ...state, error: { error_type: evt.error_type || 'error', message: evt.message || 'unknown error' } };
    case 'final':
      return { ...state, final: { final_message: evt.final_message, total_rounds: evt.total_rounds, total_tokens: evt.total_tokens, confidence: evt.confidence }, messages: _finalizeAssistant(state.messages, evt.final_message || '') };
    case 'done':
      return { ...state, streamEnded: true };
    default:
      return state;
  }
}

window.AppComponents = window.AppComponents || {};
window.AppComponents.chatReducer = chatReducer;
window.AppComponents.chatInitialState = chatInitialState;
