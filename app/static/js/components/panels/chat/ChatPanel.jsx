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

function ChatPanel({ onProfileReady, onProfilesPending, onTraceReady, onJumpToTab }) {
  const [state, dispatch] = useReducer(chatReducer, chatInitialState);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
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
  const onProfileReadyRef = useRef(onProfileReady);
  const onProfilesPendingRef = useRef(onProfilesPending);
  const onTraceReadyRef = useRef(onTraceReady);
  useEffect(() => { onProfileReadyRef.current = onProfileReady; }, [onProfileReady]);
  useEffect(() => { onProfilesPendingRef.current = onProfilesPending; }, [onProfilesPending]);
  useEffect(() => { onTraceReadyRef.current = onTraceReady; }, [onTraceReady]);

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

  // 2026-05-04 方案 A v3：tool_started 时立即把 (uids × modules) 全置 loading，
  // 让上面 6 个 Tab 卡片立即显示"分析中..."动画，避免 chat 跑大批量时 UI 像卡死。
  useEffect(() => {
    state.toolCalls.forEach((t) => {
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

  // run_profile 在工具运行中会推送模块级 tool_progress；
  // 这里即时把已完成模块写回 Dashboard，最终 tool_completed 再做补漏。
  useEffect(() => {
    state.toolCalls.forEach((t) => {
      if (t.tool_name !== 'run_profile') return;
      const progress = Array.isArray(t.progress) ? t.progress : [];
      progress.forEach((p, idx) => {
        if (!p || p.progress_type !== 'profile_module_completed') return;
        const progressKey = `${t.tool_call_id}:${p.uid || ''}:${p.module || ''}:${idx}`;
        if (dispatchedProgressRef.current.has(progressKey)) return;
        dispatchedProgressRef.current.add(progressKey);
        dispatchProfileRow(
          { uid: p.uid, module: p.module, result: p.result },
          `${t.tool_call_id}:${p.uid}:${p.module}`,
        );
      });
    });
  }, [state.toolCalls]);

  // 2026-05-04 方案 A：把 tool_completed 的画像/trace 结构化结果上报给 app.jsx。
  // 用 useEffect 而非 onEvent 拦截，可同时拿到 reducer 已保存的 tool_started.input
  // （run_trace 的 uid 来自这里），并用 ref-Set 跨 StrictMode 双调用做幂等。
  useEffect(() => {
    state.toolCalls.forEach((t) => {
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
        // 2026-05-05 修复：EventSource 错误事件是 DOM Event，没有 .message 字段，
        // 过去 String(Event) 得 "[object Event]" 是无用提示。给出友好提示。
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
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get('session');
    if (!sessionId) return undefined;
    let cancelled = false;
    fetchOrchestratorSession(sessionId).then((history) => {
      if (cancelled) return;
      dispatch({ type: 'session_started', session_id: sessionId });
      (history.messages || []).forEach((message) => {
        if (message.role === 'user') dispatch({ type: 'user_input', content: message.content || '' });
        if (message.role === 'assistant') dispatch({ type: 'final', final_message: message.content || '', total_rounds: 0, total_tokens: 0, confidence: 1 });
      });
    }).catch((err) => {
      if (cancelled) return;
      // 2026-05-04 hotfix：服务器重启后旧 session 已失效（404），静默清掉过期 URL 参数，
      // 不再向用户展示红色错误条，让用户直接进入空白对话状态。
      const msg = String((err && err.message) || err);
      const is404 = msg.includes('404');
      if (is404) {
        const params = new URLSearchParams(window.location.search);
        params.delete('session');
        const next = `${window.location.pathname}${params.toString() ? '?' + params.toString() : ''}${window.location.hash}`;
        window.history.replaceState({}, '', next);
      } else {
        dispatch({ type: 'error', error_type: 'restore', message: msg });
      }
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!state.sessionId) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('session') !== state.sessionId || params.get('tab') !== 'chat') {
      params.set('session', state.sessionId);
      params.set('tab', 'chat');
      window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}${window.location.hash}`);
    }
  }, [state.sessionId]);

  // 2026-05-04 方案 A v3：每秒 tick，让运行中的 run_profile 显示已用时间。
  useEffect(() => {
    const hasPending = state.toolCalls.some((t) => t.status === 'pending');
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
    try {
      if (!state.sessionId) {
        const payload = await createOrchestratorSession(content);
        dispatch({ type: 'session_started', session_id: payload.session_id });
        startStream(payload.session_id);
      } else {
        await sendOrchestratorMessage(state.sessionId, content);
        if (!esRef.current || esRef.current.readyState === 2) startStream(state.sessionId);
      }
    } catch (err) {
      dispatch({ type: 'error', error_type: 'send', message: String((err && err.message) || err) });
      setStreaming(false);
    }
  }, [input, state.sessionId, startStream]);

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

  return (
    <section className="flex flex-col gap-4 min-h-[520px]">
      <div>
        <h2 className="text-xl font-bold text-slate-800">自然语言对话</h2>
        <p className="text-sm text-slate-500">NL Chat</p>
      </div>
      <ChatBudgetBanner used={state.budget && state.budget.used} limit={state.budget && state.budget.limit} />
      <ChatProviderFallbackBanner from={state.providerFallback && state.providerFallback.from} to={state.providerFallback && state.providerFallback.to} reason={state.providerFallback && state.providerFallback.reason} />
      <MemoryInspector />
      {state.error ? <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{state.error.error_type}: {state.error.message}</div> : null}
      <div className="flex-1 rounded-xl border border-slate-200 bg-slate-50 p-4 overflow-y-auto">
        <ChatMessageList messages={state.messages} />
        <ChatToolCallStream toolCalls={state.toolCalls} now={now} />
        {streaming && !state.pendingAck ? (() => {
          // 2026-05-04 方案 A v3：显示精细进度 — 当 run_profile 跑批时，按 (uids × modules)
          // 算分母，已完成 (status='ok' 的 sub-result) 算分子；估算每个子任务 ~40s。
          const pendingProfile = state.toolCalls.find((t) => t.tool_name === 'run_profile' && t.status === 'pending');
          let label = 'AI 正在思考，可能需要 30~60 秒…';
          let elapsedSec = 0;
          let etaSec = null;
          if (pendingProfile) {
            const inp = pendingProfile.input || {};
            const totalUids = (Array.isArray(inp.uids) ? inp.uids : []).length || 1;
            const totalModules = (Array.isArray(inp.modules) ? inp.modules : ['app']).length;
            const totalTasks = totalUids * totalModules;
            elapsedSec = Math.max(0, Math.floor((now - (pendingProfile.startedAtMs || now)) / 1000));
            etaSec = Math.max(0, totalTasks * 40 - elapsedSec); // 40s/任务 经验值
            const fmt = (s) => `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
            label = `画像分析进行中 · ${totalUids} 位用户 × ${totalModules} 个模块（共 ${totalTasks} 个子任务）· 已用 ${fmt(elapsedSec)} / 预计还需 ~${fmt(etaSec)}`;
          }
          return (
            <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
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
              模块完成后会立即出现在下方，可先查看已完成模块；最终完成后再展示完整画像。
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
            <div className="mt-1 text-xs text-emerald-700 font-mono">{jumpUids[0]}</div>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {jumpTabs.length > 0 ? jumpTabs.map((t) => (
              <button
                key={t.id}
                onClick={() => onJumpToTab(t.id, selectedDashboardUid)}
                className="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-emerald-700 border border-emerald-300 hover:bg-emerald-100 transition-colors"
              >
                {t.label} →
              </button>
            )) : (
              <span className="text-xs text-emerald-700">等待第一个画像模块完成...</span>
            )}
          </div>
        </div>
      ) : null}
      <ChatInputBox value={input} onChange={setInput} onSend={onSend} disabled={streaming || !!state.pendingAck} />
    </section>
  );
}

window.AppComponents = window.AppComponents || {};
window.AppComponents.ChatPanel = ChatPanel;
