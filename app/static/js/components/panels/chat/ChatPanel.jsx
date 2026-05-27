const {
  ChatMessageList,
  ChatInputBox,
  ChatToolCallStream,
  ChatAckCard,
  ChatBudgetBanner,
  ChatProviderFallbackBanner,
  MemoryInspector,
  chatReducer,
  chatInitialState,
} = window.AppComponents;
const { createOrchestratorSession, sendOrchestratorMessage, openOrchestratorStream, ackOrchestratorTool, fetchOrchestratorSession } = window.AppServices.api;
const { Bot, Clock3, PanelRightClose, X } = window.LucideReact || {};
const { useReducer, useState, useRef, useEffect, useCallback } = React;

const PROFILE_MODULE_ORDER = ['app', 'behavior', 'credit', 'comprehensive', 'product', 'ops'];
const PROFILE_MODULE_LABELS = {
  comprehensive: '综合画像',
  app: 'App画像',
  behavior: '行为画像',
  credit: '征信画像',
  product: '产品策略',
  ops: '运营策略',
};

function _restoreMessages(history) {
  return (Array.isArray(history && history.messages) ? history.messages : [])
    .filter((message) => message && (message.role === 'user' || message.role === 'assistant'))
    .map((message) => ({
      role: message.role,
      content: message.content || '',
      finalized: true,
    }));
}

function _restoreToolCalls(history) {
  return (Array.isArray(history && history.tool_calls) ? history.tool_calls : []).map((toolCall) => ({
    tool_call_id: toolCall.tool_call_id,
    tool_name: toolCall.tool_name,
    status: toolCall.status === 'done' ? 'ok' : (toolCall.status === 'error' ? 'error' : 'pending'),
    input: toolCall.input || {},
    output: toolCall.output || null,
    progress: Array.isArray(toolCall.progress) ? toolCall.progress : [],
    startedAtMs: toolCall.started_at ? (Date.parse(toolCall.started_at) || Date.now()) : Date.now(),
    finishedAtMs: toolCall.finished_at ? (Date.parse(toolCall.finished_at) || Date.now()) : undefined,
    source: 'history',
  }));
}

function ChatPanel({
  layoutMode = 'dock',
  collapsed = false,
  onRequestClose,
  onToggleCollapse,
  onProfileReady,
  onProfilesPending,
  onTraceReady,
  onJumpToTab,
  externalSessionId = '',
  onSessionChange,
  workspaceSnapshot = null,
  onRestoreWorkspaceSession,
}) {
  const [state, dispatch] = useReducer(chatReducer, chatInitialState);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [ingestedUids, setIngestedUids] = useState([]);
  const [traceUids, setTraceUids] = useState([]);
  const [profileModulesByUid, setProfileModulesByUid] = useState({});
  const [profileExpectedModulesByUid, setProfileExpectedModulesByUid] = useState({});
  const [selectedJumpUid, setSelectedJumpUid] = useState(null);
  const [now, setNow] = useState(Date.now());
  const esRef = useRef(null);
  const dispatchedToolsRef = useRef(new Set());
  const dispatchedProfileResultsRef = useRef(new Set());
  const dispatchedProgressRef = useRef(new Set());
  const pendingNotifiedRef = useRef(new Set());
  const skipRestoreSessionIdRef = useRef('');
  const lastHydratedSessionIdRef = useRef('');
  const onProfileReadyRef = useRef(onProfileReady);
  const onProfilesPendingRef = useRef(onProfilesPending);
  const onTraceReadyRef = useRef(onTraceReady);
  const onSessionChangeRef = useRef(onSessionChange);
  const onRestoreWorkspaceSessionRef = useRef(onRestoreWorkspaceSession);
  useEffect(() => { onProfileReadyRef.current = onProfileReady; }, [onProfileReady]);
  useEffect(() => { onProfilesPendingRef.current = onProfilesPending; }, [onProfilesPending]);
  useEffect(() => { onTraceReadyRef.current = onTraceReady; }, [onTraceReady]);
  useEffect(() => { onSessionChangeRef.current = onSessionChange; }, [onSessionChange]);
  useEffect(() => { onRestoreWorkspaceSessionRef.current = onRestoreWorkspaceSession; }, [onRestoreWorkspaceSession]);

  const resetSessionArtifacts = useCallback(() => {
    if (esRef.current) esRef.current.close();
    esRef.current = null;
    dispatchedToolsRef.current = new Set();
    dispatchedProfileResultsRef.current = new Set();
    dispatchedProgressRef.current = new Set();
    pendingNotifiedRef.current = new Set();
    setStreaming(false);
    setIngestedUids([]);
    setTraceUids([]);
    setProfileModulesByUid({});
    setProfileExpectedModulesByUid({});
    setSelectedJumpUid(null);
  }, []);

  function rememberProfileUid(targetUid) {
    if (!targetUid) return;
    setIngestedUids((prev) => prev.includes(targetUid) ? prev : prev.concat([targetUid]));
  }

  function rememberExpectedModules(uids, modules) {
    const normalizedModules = Array.isArray(modules) && modules.length ? modules : ['app'];
    setProfileExpectedModulesByUid((prev) => {
      const next = { ...prev };
      (uids || []).forEach((u) => {
        if (u) next[u] = normalizedModules;
      });
      return next;
    });
  }

  function rememberCompletedModule(targetUid, moduleName) {
    if (!targetUid || !moduleName) return;
    setProfileModulesByUid((prev) => {
      const current = prev[targetUid] || {};
      if (current[moduleName]) return prev;
      return {
        ...prev,
        [targetUid]: { ...current, [moduleName]: true },
      };
    });
  }

  function dispatchProfileRow(row, resultKey) {
    if (!row || !row.uid || !row.module || !row.result) return;
    const key = resultKey || `${row.uid}:${row.module}`;
    const isOk = row.result.status === 'ok' && row.result.data;
    rememberProfileUid(row.uid);
    if (isOk) rememberCompletedModule(row.uid, row.module);
    if (dispatchedProfileResultsRef.current.has(key)) return;
    dispatchedProfileResultsRef.current.add(key);
    const cb = onProfileReadyRef.current;
    if (cb) cb({ uid: row.uid, module: row.module, payload: row.result });
  }

  useEffect(() => {
    state.toolCalls.forEach((t) => {
      if (t.source !== 'live') return;
      if (t.tool_name !== 'run_profile') return;
      if (pendingNotifiedRef.current.has(t.tool_call_id)) return;
      if (t.status !== 'pending' && t.status !== 'ok' && t.status !== 'error') return;
      const inp = t.input || {};
      const uids = Array.isArray(inp.uids) ? inp.uids : [];
      const modules = Array.isArray(inp.modules) && inp.modules.length ? inp.modules : ['app'];
      if (uids.length === 0) return;
      uids.forEach((u) => rememberProfileUid(u));
      rememberExpectedModules(uids, modules);
      const cb = onProfilesPendingRef.current;
      if (cb) cb({ uids, modules });
      pendingNotifiedRef.current.add(t.tool_call_id);
    });
  }, [state.toolCalls]);

  useEffect(() => {
    state.toolCalls.forEach((t) => {
      if (t.source !== 'live') return;
      if (t.tool_name !== 'run_profile') return;
      const progress = Array.isArray(t.progress) ? t.progress : [];
      progress.forEach((p, idx) => {
        if (!p || p.progress_type !== 'profile_module_completed') return;
        const progressKey = `${t.tool_call_id}:${p.uid || ''}:${p.module || ''}:${idx}`;
        if (dispatchedProgressRef.current.has(progressKey)) return;
        dispatchedProgressRef.current.add(progressKey);
        if (window.console && typeof window.console.info === 'function') {
          window.console.info('[tool_progress]', {
            tool_call_id: t.tool_call_id,
            uid: p.uid,
            module: p.module,
            completed: p.completed,
            total: p.total,
          });
        }
        dispatchProfileRow(
          { uid: p.uid, module: p.module, result: p.result },
          `${t.tool_call_id}:${p.uid}:${p.module}`,
        );
      });
    });
  }, [state.toolCalls]);

  useEffect(() => {
    state.toolCalls.forEach((t) => {
      if (t.source !== 'live') return;
      if (t.status !== 'ok' || !t.output) return;
      if (dispatchedToolsRef.current.has(t.tool_call_id)) return;
      if (t.tool_name === 'run_profile' && Array.isArray(t.output.results)) {
        t.output.results.forEach((row) => {
          dispatchProfileRow(row, `${t.tool_call_id}:${row && row.uid}:${row && row.module}`);
        });
        dispatchedToolsRef.current.add(t.tool_call_id);
      } else if (t.tool_name === 'run_trace' && t.output) {
        const traceUid = (t.input && t.input.uid) || null;
        const cb = onTraceReadyRef.current;
        if (traceUid && cb) {
          cb({ uid: traceUid, payload: t.output });
          setTraceUids((prev) => prev.includes(traceUid) ? prev : prev.concat([traceUid]));
        }
        dispatchedToolsRef.current.add(t.tool_call_id);
      }
    });
  }, [state.toolCalls]);

  const startStream = useCallback((sessionId) => {
    if (esRef.current) esRef.current.close();
    const es = openOrchestratorStream(sessionId, {
      onEvent: (evt) => dispatch(evt),
      onError: (err) => {
        const msg = (err && err.message)
          ? String(err.message)
          : 'SSE 连接中断（可能是服务器重启或网络抖动）。请重新发送问题。';
        dispatch({ type: 'error', error_type: 'sse', message: msg });
        setStreaming(false);
        if (esRef.current === es) esRef.current = null;
      },
      onClose: () => {
        setStreaming(false);
        if (esRef.current === es) esRef.current = null;
      },
    });
    esRef.current = es;
  }, []);

  useEffect(() => {
    const sessionId = externalSessionId;
    if (!sessionId) {
      lastHydratedSessionIdRef.current = '';
      return undefined;
    }
    if (skipRestoreSessionIdRef.current === sessionId) {
      skipRestoreSessionIdRef.current = '';
      lastHydratedSessionIdRef.current = sessionId;
      return undefined;
    }
    if (lastHydratedSessionIdRef.current === sessionId) return undefined;
    let cancelled = false;
    dispatch({ type: 'reset_session' });
    resetSessionArtifacts();
    fetchOrchestratorSession(sessionId).then((history) => {
      if (cancelled) return;
      lastHydratedSessionIdRef.current = sessionId;
      dispatch({
        type: 'restore_session',
        session_id: sessionId,
        messages: _restoreMessages(history),
        tool_calls: _restoreToolCalls(history),
        final: history && history.final_message ? {
          final_message: history.final_message,
          total_rounds: 0,
          total_tokens: history.total_tokens || 0,
          confidence: history.confidence || 1,
        } : null,
      });
    }).catch((err) => {
      if (cancelled) return;
      const msg = String((err && err.message) || err);
      const is404 = msg.includes('404');
      if (is404) {
        if (onSessionChangeRef.current) {
          onSessionChangeRef.current('');
        } else {
          const currentParams = new URLSearchParams(window.location.search);
          currentParams.delete('session');
          const next = `${window.location.pathname}${currentParams.toString() ? '?' + currentParams.toString() : ''}${window.location.hash}`;
          window.history.replaceState({}, '', next);
        }
      } else {
        dispatch({ type: 'error', error_type: 'restore', message: msg });
      }
    });
    return () => { cancelled = true; };
  }, [externalSessionId, resetSessionArtifacts]);

  useEffect(() => {
    if (!state.sessionId || onSessionChangeRef.current) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('session') !== state.sessionId || params.get('tab') !== 'chat') {
      params.set('session', state.sessionId);
      params.set('tab', 'chat');
      window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}${window.location.hash}`);
    }
  }, [state.sessionId]);

  useEffect(() => {
    const hasPending = state.toolCalls.some((t) => t.source === 'live' && t.status === 'pending');
    if (!hasPending) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [state.toolCalls]);

  const onSend = useCallback(async () => {
    const content = input.trim();
    if (!content) return;
    setInput('');
    dispatch({ type: 'user_input', content });
    setStreaming(true);
    const compactWorkspaceSnapshot = workspaceSnapshot && Array.isArray(workspaceSnapshot.results) && workspaceSnapshot.results.length
      ? workspaceSnapshot
      : undefined;
    try {
      if (!state.sessionId) {
        const payload = await createOrchestratorSession(content, compactWorkspaceSnapshot);
        dispatch({ type: 'session_started', session_id: payload.session_id });
        skipRestoreSessionIdRef.current = payload.session_id;
        if (onSessionChangeRef.current) onSessionChangeRef.current(payload.session_id);
        startStream(payload.session_id);
      } else {
        await sendOrchestratorMessage(state.sessionId, content, compactWorkspaceSnapshot);
        if (!esRef.current || esRef.current.readyState === 2) startStream(state.sessionId);
      }
    } catch (err) {
      dispatch({ type: 'error', error_type: 'send', message: String((err && err.message) || err) });
      setStreaming(false);
    }
  }, [input, startStream, state.sessionId, workspaceSnapshot]);

  const onApprove = useCallback(async () => {
    if (!state.pendingAck || !state.sessionId) return;
    try {
      await ackOrchestratorTool(state.sessionId, state.pendingAck.tool_call_id, 'approve');
    } catch (err) {
      dispatch({ type: 'error', error_type: 'ack', message: String((err && err.message) || err) });
    }
  }, [state.pendingAck, state.sessionId]);

  const onReject = useCallback(async () => {
    if (!state.pendingAck || !state.sessionId) return;
    try {
      await ackOrchestratorTool(state.sessionId, state.pendingAck.tool_call_id, 'reject');
    } catch (err) {
      dispatch({ type: 'error', error_type: 'ack', message: String((err && err.message) || err) });
    }
  }, [state.pendingAck, state.sessionId]);

  useEffect(() => {
    if (!state.pendingAck) return undefined;
    const handler = (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        onApprove();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        onReject();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [state.pendingAck, onApprove, onReject]);

  useEffect(() => () => {
    if (esRef.current) esRef.current.close();
  }, []);

  function onOpenMemory() {
    setMemoryOpen(true);
  }

  const onOpenSession = useCallback((sessionId) => {
    if (!sessionId) return;
    setMemoryOpen(false);
    const currentSessionId = externalSessionId || state.sessionId || '';
    if (sessionId === currentSessionId) return;
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
      setStreaming(false);
    }
    if (onSessionChangeRef.current) {
      onSessionChangeRef.current(sessionId);
      return;
    }
    const params = new URLSearchParams(window.location.search);
    params.set('session', sessionId);
    params.set('tab', 'chat');
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }, [externalSessionId, state.sessionId]);

  const onRestoreSession = useCallback(async (sessionId) => {
    if (!sessionId) return;
    const currentSessionId = externalSessionId || state.sessionId || '';
    if (sessionId !== currentSessionId) {
      onOpenSession(sessionId);
    }
    if (!onRestoreWorkspaceSessionRef.current) return;
    const history = await fetchOrchestratorSession(sessionId);
    onRestoreWorkspaceSessionRef.current(history);
    setMemoryOpen(false);
  }, [externalSessionId, onOpenSession, state.sessionId]);

  const jumpUids = ingestedUids.length > 0 ? ingestedUids : traceUids;
  const selectedDashboardUid = jumpUids.includes(selectedJumpUid) ? selectedJumpUid : jumpUids[0];
  const canJumpTrace = selectedDashboardUid ? traceUids.includes(selectedDashboardUid) : false;
  const expectedModulesForUid = (selectedDashboardUid && profileExpectedModulesByUid[selectedDashboardUid]) || PROFILE_MODULE_ORDER;
  const completedModulesForUid = selectedDashboardUid
    ? expectedModulesForUid.filter((m) => profileModulesByUid[selectedDashboardUid] && profileModulesByUid[selectedDashboardUid][m])
    : [];
  const profileComplete = expectedModulesForUid.length > 0 && completedModulesForUid.length >= expectedModulesForUid.length;
  const jumpTabs = ingestedUids.length > 0
    ? [
        ...completedModulesForUid.map((id) => ({ id, label: PROFILE_MODULE_LABELS[id] || id })),
        ...(canJumpTrace ? [{ id: 'trace', label: '深度行为解析' }] : []),
      ]
    : [{ id: 'trace', label: '深度行为解析' }];
  const isCollapsedDock = layoutMode === 'dock' && collapsed;

  if (isCollapsedDock) {
    return (
      <div className="flex h-full flex-col bg-transparent">
        <header id="chat-panel-header" className="h-full bg-transparent">
          <div id="chat-panel-header-inner" className="flex h-full flex-col items-center justify-start gap-3 px-0 py-4">
            <button
              id="chat-launcher"
              type="button"
              onClick={onToggleCollapse}
              className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-blue-600 text-white shadow-[0_12px_24px_rgba(37,99,235,0.25)] transition-colors hover:bg-blue-700"
              title="展开 NL Chat"
            >
              {Bot ? <Bot className="h-5 w-5" /> : null}
            </button>
          </div>
        </header>
        <MemoryInspector
          open={memoryOpen}
          onClose={() => setMemoryOpen(false)}
          onOpenSession={onOpenSession}
          onRestoreSession={onRestoreSession}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-white/95 backdrop-blur-xl">
      <header id="chat-panel-header" className="h-14 shrink-0 border-b border-slate-100 bg-white/85 backdrop-blur">
        <div id="chat-panel-header-inner" className="flex h-full items-center justify-between gap-3 px-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <button
                id="chat-launcher"
                type="button"
                onClick={layoutMode === 'dock' && onToggleCollapse ? onToggleCollapse : undefined}
                className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-100 text-blue-600"
                title={layoutMode === 'dock' && onToggleCollapse ? '收起 NL Chat' : '自然语言助手'}
              >
                {Bot ? <Bot className="h-4 w-4" /> : null}
              </button>
              <div className="min-w-0">
                <h2 id="chat-panel-title" className="truncate text-sm font-semibold text-slate-800">自然语言助手 (NL Chat)</h2>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              id="chat-history-btn"
              type="button"
              onClick={onOpenMemory}
              className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-200"
            >
              {Clock3 ? <Clock3 className="h-3.5 w-3.5" /> : null}
              历史记忆
            </button>
            {layoutMode === 'dock' && onToggleCollapse ? (
              <button
                id="collapse-chat-btn"
                type="button"
                onClick={onToggleCollapse}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 text-slate-500 transition-colors hover:border-blue-200 hover:bg-blue-50 hover:text-blue-600"
                title="折叠 NL Chat"
              >
                {PanelRightClose ? <PanelRightClose className="h-4 w-4" /> : null}
              </button>
            ) : null}
            {layoutMode === 'sheet' && onRequestClose ? (
              <button
                type="button"
                onClick={onRequestClose}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-100"
              >
                {X ? <X className="h-4 w-4" /> : null}
              </button>
            ) : null}
          </div>
        </div>
      </header>

      <div id="chat-panel-body" className="flex min-h-0 flex-1 flex-col">
        <div id="chat-container" className="flex-1 overflow-y-auto bg-slate-50/50 p-4 scroll-smooth">
          <div className="space-y-6">
            <ChatBudgetBanner used={state.budget && state.budget.used} limit={state.budget && state.budget.limit} />
            <ChatProviderFallbackBanner from={state.providerFallback && state.providerFallback.from} to={state.providerFallback && state.providerFallback.to} reason={state.providerFallback && state.providerFallback.reason} />
            {state.error ? <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{state.error.error_type}: {state.error.message}</div> : null}

            <div className="space-y-4">
              <ChatMessageList messages={state.messages} />
              <ChatToolCallStream toolCalls={state.toolCalls} now={now} />
              {streaming && !state.pendingAck ? (() => {
                const pendingProfile = state.toolCalls.find((t) => t.tool_name === 'run_profile' && t.status === 'pending');
                let label = 'AI 正在思考，可能需要 30~60 秒...';
                if (pendingProfile) {
                  const inp = pendingProfile.input || {};
                  const totalUids = (Array.isArray(inp.uids) ? inp.uids : []).length || 1;
                  const totalModules = (Array.isArray(inp.modules) ? inp.modules : ['app']).length;
                  const totalTasks = totalUids * totalModules;
                  const elapsedSec = Math.max(0, Math.floor((now - (pendingProfile.startedAtMs || now)) / 1000));
                  const etaSec = Math.max(0, totalTasks * 40 - elapsedSec);
                  const fmt = (value) => `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
                  label = `画像分析进行中 · ${totalUids} 位用户 × ${totalModules} 个模块（共 ${totalTasks} 个子任务）· 已用 ${fmt(elapsedSec)} / 预计还需 ~${fmt(etaSec)}`;
                }
                return (
                  <div className="flex items-center gap-2 text-sm text-slate-600">
                    <span className="inline-block h-2 w-2 animate-bounce rounded-full bg-blue-400" style={{ animationDelay: '0ms' }}></span>
                    <span className="inline-block h-2 w-2 animate-bounce rounded-full bg-blue-400" style={{ animationDelay: '150ms' }}></span>
                    <span className="inline-block h-2 w-2 animate-bounce rounded-full bg-blue-400" style={{ animationDelay: '300ms' }}></span>
                    <span className="ml-1">{label}</span>
                  </div>
                );
              })() : null}
            </div>

            <ChatAckCard pending={state.pendingAck} onApprove={onApprove} onReject={onReject} />

            {jumpUids.length > 0 && onJumpToTab ? (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                <div className="text-sm font-semibold text-emerald-800">
                  {ingestedUids.length > 0
                    ? `${profileComplete ? '完整画像已生成' : '画像分析进行中'}：${selectedDashboardUid || ingestedUids.length + ' 位用户'} 已完成 ${completedModulesForUid.length}/${expectedModulesForUid.length} 个画像模块`
                    : `已生成 ${traceUids.length} 位用户的深度行为解析，可查看 trace dashboard：`}
                </div>
                {ingestedUids.length > 0 ? (
                  <div className="mt-1 text-xs text-emerald-700">
                    模块完成后会立即出现在左侧分析区，可先查看已完成模块；最终完成后再展示完整画像。
                  </div>
                ) : null}
                {jumpUids.length > 1 ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="text-xs text-emerald-700">目标 UID：</span>
                    {jumpUids.map((u) => {
                      const active = selectedDashboardUid === u;
                      return (
                        <button
                          key={u}
                          onClick={() => setSelectedJumpUid(u)}
                          className={`rounded px-2 py-1 text-xs font-mono transition-colors border ${
                            active
                              ? 'bg-emerald-600 text-white border-emerald-600'
                              : 'bg-white text-emerald-700 border-emerald-300 hover:bg-emerald-100'
                          }`}
                        >
                          {u}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="mt-1 text-xs font-mono text-emerald-700">{jumpUids[0]}</div>
                )}
                <div className="mt-2 flex flex-wrap gap-2">
                  {jumpTabs.length > 0 ? jumpTabs.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => onJumpToTab(t.id, selectedDashboardUid)}
                      className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-700 transition-colors hover:bg-emerald-100"
                    >
                      {t.label} →
                    </button>
                  )) : (
                    <span className="text-xs text-emerald-700">等待第一个画像模块完成...</span>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div id="chat-panel-footer" className="shrink-0 border-t border-slate-100 bg-white p-4">
        <ChatInputBox value={input} onChange={setInput} onSend={onSend} disabled={streaming || !!state.pendingAck} />
        <p className="mt-2 text-center text-[10px] text-slate-400">AI 助手可能会犯错，请结合左侧结构化结果核实。</p>
      </div>

      <MemoryInspector
        open={memoryOpen}
        onClose={() => setMemoryOpen(false)}
        onOpenSession={onOpenSession}
        onRestoreSession={onRestoreSession}
      />
    </div>
  );
}

window.AppComponents = window.AppComponents || {};
window.AppComponents.ChatPanel = ChatPanel;
