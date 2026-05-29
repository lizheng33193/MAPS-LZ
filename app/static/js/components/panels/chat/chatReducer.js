const chatInitialState = {
  sessionId: null,
  messages: [],
  toolCalls: [],
  executionTraces: [],
  pendingAck: null,
  pendingResolution: null,
  budget: null,
  providerFallback: null,
  final: null,
  error: null,
  streamEnded: false,
};

function upsertExecutionTrace(traces, incoming) {
  const executionId = incoming && incoming.execution_id;
  if (!executionId) return traces;
  const idx = traces.findIndex((trace) => trace && trace.execution_id === executionId);
  if (idx === -1) return traces.concat([incoming]);
  return traces.map((trace, traceIdx) => {
    if (traceIdx !== idx) return trace;
    return {
      ...trace,
      ...incoming,
      request_understanding: incoming.request_understanding !== undefined ? incoming.request_understanding : (trace.request_understanding || null),
      availability: incoming.availability !== undefined ? incoming.availability : trace.availability,
      steps: Array.isArray(incoming.steps) ? incoming.steps : (Array.isArray(trace.steps) ? trace.steps : []),
      review: incoming.review !== undefined && incoming.review !== null ? incoming.review : (trace.review || null),
    };
  });
}

function _derivePendingResolutionFromTraces(traces) {
  for (const trace of Array.isArray(traces) ? traces : []) {
    const steps = Array.isArray(trace && trace.steps) ? trace.steps : [];
    for (const step of steps) {
      if (!step || step.status !== 'awaiting_resolution') continue;
      return {
        execution_id: trace.execution_id,
        step_id: step.step_id,
        resolution_type: step.resolution_type || '',
        prompt: step.resolution_prompt || '',
        required_slots: Array.isArray(step.resolution_required_slots) ? step.resolution_required_slots : [],
        candidate_defaults: step.resolution_candidate_defaults || {},
        options: Array.isArray(step.resolution_options) ? step.resolution_options : [],
        missing_bucket_counts: {},
        cohort_size: null,
        selected_option: null,
      };
    }
  }
  return null;
}

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
    case 'reset_session':
      return { ...chatInitialState };
    case 'restore_session':
      {
        const executionTraces = Array.isArray(evt.execution_traces) ? evt.execution_traces : [];
      return {
        ...chatInitialState,
        sessionId: evt.session_id || null,
        messages: Array.isArray(evt.messages) ? evt.messages : [],
        toolCalls: Array.isArray(evt.tool_calls) ? evt.tool_calls : [],
        executionTraces,
        pendingResolution: _derivePendingResolutionFromTraces(executionTraces),
        final: evt.final || null,
        streamEnded: true,
      };
      }
    case 'user_input':
      return { ...state, error: null, messages: state.messages.concat([{ role: 'user', content: evt.content }]) };
    case 'session_started':
      return { ...state, sessionId: evt.session_id };
    case 'tool_started':
      // 2026-05-04 方案 A v3：记录 startedAtMs 让 ChatPanel 显示已用时间。
      return { ...state, toolCalls: state.toolCalls.concat([{ tool_call_id: evt.tool_call_id, tool_name: evt.tool_name, status: 'pending', input: evt.input, output: null, startedAtMs: Date.now(), source: 'live' }]) };
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
    case 'execution_plan':
      return {
        ...state,
        executionTraces: upsertExecutionTrace(state.executionTraces, {
          execution_id: evt.execution_id,
          request_summary: evt.request_summary || '',
          intent: evt.intent || '',
          request_understanding: evt.request_understanding || null,
          availability: evt.availability || null,
          steps: Array.isArray(evt.steps) ? evt.steps : [],
          review: null,
        }),
      };
    case 'plan_step_status': {
      const updated = state.executionTraces.map((trace) => {
        if (!trace || trace.execution_id !== evt.execution_id) return trace;
        const steps = Array.isArray(trace.steps) ? trace.steps : [];
        const hasStep = steps.some((step) => step && step.step_id === evt.step_id);
        const nextSteps = hasStep
          ? steps.map((step) => (
              step && step.step_id === evt.step_id
                ? { ...step, status: evt.status, result_summary: evt.result_summary, tool_call_id: evt.tool_call_id || step.tool_call_id }
                : step
            ))
          : steps.concat([{
              step_id: evt.step_id,
              title: evt.step_id,
              kind: 'dynamic',
              status: evt.status,
              result_summary: evt.result_summary,
              tool_call_id: evt.tool_call_id || null,
            }]);
        return {
          ...trace,
          steps: nextSteps,
        };
      });
      const pendingResolution = state.pendingResolution
        && state.pendingResolution.execution_id === evt.execution_id
        && state.pendingResolution.step_id === evt.step_id
        && evt.status !== 'awaiting_resolution'
          ? null
          : state.pendingResolution;
      return { ...state, executionTraces: updated, pendingResolution };
    }
    case 'review_result': {
      const updated = state.executionTraces.map((trace) => (
        trace && trace.execution_id === evt.execution_id
          ? {
              ...trace,
              review: {
                status: evt.status,
                issues: Array.isArray(evt.issues) ? evt.issues : [],
                confidence_impact: evt.confidence_impact || null,
                can_answer: Boolean(evt.can_answer),
              },
            }
          : trace
      ));
      return { ...state, executionTraces: updated };
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
    case 'awaiting_resolution':
      return {
        ...state,
        pendingResolution: {
          execution_id: evt.execution_id,
          step_id: evt.step_id,
          resolution_type: evt.resolution_type,
          prompt: evt.prompt || '',
          required_slots: Array.isArray(evt.required_slots) ? evt.required_slots : [],
          candidate_defaults: evt.candidate_defaults || {},
          options: Array.isArray(evt.options) ? evt.options : [],
          missing_bucket_counts: evt.missing_bucket_counts || {},
          cohort_size: evt.cohort_size ?? null,
          selected_option: evt.selected_option ?? null,
        },
      };
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
