// Extracted from app/ui/live_frontend.py during UI separation Step-1.
// Source: DashboardView at L349-L438.
// Renamed JSX call: <ComprehensivePanelV2> -> <ComprehensivePanel>
// (legacy V2 alias dropped per Phase F.5 user direction).

const { ChevronRight, Bot, Network, Smartphone, Activity, CreditCard, Package, Headphones, MessageCircle } = window.LucideReact || {};
const {
  AppPanel,
  BehaviorPanel,
  RichCreditPanel,
  ComprehensivePanel,
  ProductAdvicePanel,
  OpsAdvicePanel,
  LabelsOverviewCard,
  TracePanel,
  ModuleStatusPanel,
  ChatPanel,
} = window.AppComponents;

const FALLBACK_RESULT_DASHBOARD = {
  uid: '',
  app_profile: window.AppUtils.normalize.buildEmptyAgentOutput('暂无 App 画像结果'),
  behavior_profile: window.AppUtils.normalize.buildEmptyAgentOutput('暂无行为画像结果'),
  credit_profile: window.AppUtils.normalize.buildEmptyAgentOutput('暂无征信画像结果'),
  comprehensive_profile: window.AppUtils.normalize.buildEmptyAgentOutput('暂无综合画像结果'),
  product_advice: null,
  ops_advice: null,
  standardized_labels: null
};

const SEGMENT_KEYS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'];

function computeSegmentDistribution(results) {
  const counts = { S1: 0, S2: 0, S3: 0, S4: 0, S5: 0, S6: 0 };
  let total = 0;
  results.forEach((r) => {
    const seg = r?.comprehensive_profile?.structured_result?.metrics?.segment;
    if (typeof seg === 'string' && counts.hasOwnProperty(seg)) {
      counts[seg] += 1;
      total += 1;
    }
  });
  return { counts, total };
}

function SegmentDistributionCard({ results }) {
  if (!results || results.length <= 1) {
    return null;
  }
  const { counts, total } = computeSegmentDistribution(results);
  if (total === 0) {
    return null;
  }
  return (
    <div className="bg-white rounded-xl shadow-sm p-6 mb-6">
      <h3 className="text-base font-bold text-slate-800 mb-4">批量分析 · 客群分层分布 (S1-S6)</h3>
      <div className="space-y-2">
        {SEGMENT_KEYS.map((key) => {
          const c = counts[key];
          const pct = total > 0 ? (c / total) * 100 : 0;
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="w-8 text-xs font-semibold text-slate-600">{key}</span>
              <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-blue-500 h-2 rounded-full transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="w-12 text-xs text-slate-500 text-right">{c} 人</span>
            </div>
          );
        })}
        <p className="text-xs text-slate-400 mt-2">合计 {total} 个有效分层结果（共 {results.length} 条）</p>
      </div>
    </div>
  );
}

function DashboardView({
  activeTab,
  setActiveTab,
  analysisResults,
  selectedResultIndex,
  setSelectedResultIndex,
  moduleStates,
  onRetryModule,
  onBack,
  onChatProfileReady,
  onChatProfilesPending,
  onChatTraceReady,
  traceSeedByUid,
  moduleStatesByUid,
  country = 'mx',
  onCountryChange,
}) {
  const selectedResult = analysisResults[selectedResultIndex] || FALLBACK_RESULT_DASHBOARD;
  const uid = selectedResult.uid || 'unknown_user';
  // 2026-05-04 方案 A v2：多 UID 隔离 — 优先读 moduleStatesByUid[uid]，
  // 找不到再 fallback 到旧 moduleStates（单 UID / 批量文件路径走旧逻辑）。
  const effectiveModuleStates = (moduleStatesByUid && moduleStatesByUid[uid]) || moduleStates;
  // 2026-05-05 修复 trace 卡片在行为数据缺失时一直“分析中...”的 BUG：
  // 行为画像返回 data_missing 说明该 uid 的 behavior CSV 不存在，trace 不可能有数据，
  // 直接锁定为 data_missing 不发 /api/trace 请求，避免卡片長期停在 loading。
  const behaviorStructured = (selectedResult
    && selectedResult.behavior_profile
    && selectedResult.behavior_profile.structured_result) || {};
  const behaviorDataMissing = behaviorStructured.status === 'data_missing';
  const activeModuleState = (activeTab === 'trace' || activeTab === 'chat')
    ? { status: 'success', error: '' }
    : (effectiveModuleStates && effectiveModuleStates[activeTab]) || { status: 'success', error: '' };

  const [traceCacheByUid, setTraceCacheByUid] = React.useState({});

  // 2026-05-04 方案 A：把 NL Chat 跑过的 trace 种子合并进本地 traceCacheByUid，
  // 让 trace tab 直接命中 chat 跑过的结果，省一次 /api/trace 调用与 LLM 推理。
  React.useEffect(() => {
    if (!traceSeedByUid) return;
    setTraceCacheByUid((prev) => {
      let changed = false;
      const next = { ...prev };
      Object.keys(traceSeedByUid).forEach((seedUid) => {
        if (!next[seedUid]) {
          next[seedUid] = traceSeedByUid[seedUid];
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [traceSeedByUid]);

  React.useEffect(() => {
    if (activeTab !== 'trace') return;
    if (!uid || uid === 'unknown_user') return;
    if (traceCacheByUid[uid]) return;
    // 2026-05-05 行为数据缺失 → trace 直接置 data_missing，不发请求
    if (behaviorDataMissing) {
      setTraceCacheByUid((prev) => ({
        ...prev,
        [uid]: {
          requestStatus: 'success',
          response: { uid, status: 'data_missing', errors: ['behavior_data_missing'] }
        }
      }));
      return;
    }
    let cancelled = false;
    setTraceCacheByUid((prev) => ({
      ...prev,
      [uid]: { requestStatus: 'loading' }
    }));
    // 2026-05-05 修复 trace “一直分析中”：
    // 以前 cleanup 同时做两件事造成调度问题：
    //  (1) 置 cancelled=true 让 then/catch 跳过写 state（in-flight 结果丢了）
    //  (2) 从 state 里 delete loading entry，下次入 tab useEffect 又发一轮
    //  → 用户每切一次 trace tab 都重发，LLM 资源响应不上，前端永远 loading。
    // 正确处理：**不走取消路径**。in-flight 请求以前端调度为准，
    //   哪怕用户切走了也让响应居中写入缓存，下次切回直接命中不重发。
    window.AppServices.api.fetchTrace(uid).then((response) => {
      setTraceCacheByUid((prev) => ({
        ...prev,
        [uid]: { requestStatus: 'success', response }
      }));
    }).catch((err) => {
      setTraceCacheByUid((prev) => ({
        ...prev,
        [uid]: { requestStatus: 'error', errorMessage: (err && err.message) || '请求失败' }
      }));
    });
  }, [activeTab, uid, behaviorDataMissing]);

  function handleTraceRetry(targetUid) {
    setTraceCacheByUid((prev) => {
      const next = { ...prev };
      delete next[targetUid];
      return next;
    });
  }
  const tabs = [
    { id: 'comprehensive', title: '综合画像', sub: 'Comprehensive', icon: Network, bg: 'from-amber-400 to-fuchsia-600', shadow: 'shadow-fuchsia-500/30' },
    { id: 'app', title: 'App画像', sub: 'App Usage', icon: Smartphone, bg: 'from-cyan-400 to-blue-600', shadow: 'shadow-blue-500/30' },
    { id: 'behavior', title: '行为画像', sub: 'Behavioral', icon: Activity, bg: 'from-orange-400 to-red-500', shadow: 'shadow-red-500/30' },
    { id: 'credit', title: '征信画像', sub: 'Credit Report', icon: CreditCard, bg: 'from-slate-500 to-slate-700', shadow: 'shadow-slate-500/30' },
    { id: 'product', title: '产品策略', sub: 'Product Advice', icon: Package, bg: 'from-emerald-400 to-teal-500', shadow: 'shadow-emerald-500/30' },
    { id: 'ops', title: '运营策略', sub: 'Operations', icon: Headphones, bg: 'from-violet-400 to-purple-500', shadow: 'shadow-violet-500/30' },
    { id: 'trace', title: '深度行为解析', sub: 'Trace Analysis', icon: Activity, bg: 'from-purple-400 to-violet-600', shadow: 'shadow-violet-500/30' },
    { id: 'chat', title: '自然语言对话', sub: 'NL Chat', icon: MessageCircle, bg: 'from-sky-400 to-blue-600', shadow: 'shadow-blue-500/30' }
  ];

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-2 hover:bg-slate-100 rounded-full text-slate-500 transition-colors">
            <ChevronRight className="w-6 h-6 rotate-180" />
          </button>
          <div className="w-10 h-10 bg-blue-600 rounded-full flex items-center justify-center"><Bot className="w-6 h-6 text-white" /></div>
          <div>
            <h1 className="text-xl font-bold text-slate-800">Multi-Agent Profiling System</h1>
            <p className="text-xs text-slate-500">当前用户 UID: {uid}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <select
            value={country}
            onChange={(e) => onCountryChange && onCountryChange(e.target.value)}
            className="text-sm border border-slate-300 rounded-md px-2 py-1 bg-white"
            title="切换国家"
          >
            <option value="mx">墨西哥 (MX)</option>
            <option value="th">泰国 (TH)</option>
          </select>
          <span className="text-sm text-slate-500">当前模式: <span className="font-semibold text-slate-700 bg-slate-100 px-2 py-1 rounded">api-live</span></span>
          <span className="text-sm text-slate-500">返回结果数: <span className="text-blue-600 font-semibold">{analysisResults.length}</span></span>
        </div>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 flex flex-col gap-6">
        <div className="bg-white rounded-2xl border border-slate-200 p-4 shadow-sm">
          <div className="text-sm font-semibold text-slate-700 mb-3">用户结果切换</div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {analysisResults.map((item, index) => {
              const isActive = selectedResultIndex === index;
              const label = item.uid || `user_${index + 1}`;
              return (
                <button
                  key={`${label}-${index}`}
                  onClick={() => setSelectedResultIndex(index)}
                  className={`px-4 py-2 rounded-xl text-sm font-medium whitespace-nowrap border transition-colors ${
                    isActive
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {selectedResult.standardized_labels ? (
          <LabelsOverviewCard labels={selectedResult.standardized_labels} />
        ) : null}

        <SegmentDistributionCard results={analysisResults} />

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {tabs.map(tab => {
            const isActive = activeTab === tab.id;
            const Icon = tab.icon;
            // 2026-05-05 trace 卡片状态联动 behavior data_missing，避免一直“分析中...”
            let tabModuleState;
            if (tab.id === 'trace') {
              const traceEntry = traceCacheByUid[uid];
              if (traceEntry) {
                if (traceEntry.requestStatus === 'success') {
                  const respStatus = traceEntry.response && traceEntry.response.status;
                  tabModuleState = { status: (respStatus === 'data_missing' || respStatus === 'insufficient_events') ? 'no_data' : 'success' };
                } else if (traceEntry.requestStatus === 'error') {
                  tabModuleState = { status: 'error' };
                } else {
                  tabModuleState = { status: 'loading' };
                }
              } else if (behaviorDataMissing) {
                tabModuleState = { status: 'no_data' };
              } else {
                tabModuleState = { status: 'idle' };
              }
            } else if (tab.id === 'chat') {
              tabModuleState = { status: 'success' };
            } else {
              tabModuleState = effectiveModuleStates && effectiveModuleStates[tab.id];
            }
            const tabStatus = tabModuleState && tabModuleState.status;
            const statusLabel = tabStatus === 'success' ? '已完成'
              : tabStatus === 'loading' ? '分析中...'
              : tabStatus === 'error' ? '模块报错'
              : tabStatus === 'no_data' ? '暂无可用数据'
              : '等待依赖';
            return (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)} className={`relative overflow-hidden rounded-xl p-5 text-left transition-all duration-300 transform ${isActive ? `scale-105 shadow-xl ${tab.shadow} ring-2 ring-white ring-offset-2` : 'hover:scale-105 shadow-md hover:shadow-lg opacity-80 hover:opacity-100'} bg-gradient-to-br ${tab.bg}`}>
                <div className="relative z-10 flex justify-between items-start">
                  <div>
                    <h3 className="text-xl font-bold text-white mb-1">{tab.title}</h3>
                    <p className="text-xs text-white/80 uppercase tracking-wider">{tab.sub}</p>
                    <p className="mt-3 text-xs font-semibold text-white/90">{statusLabel}</p>
                  </div>
                  {Icon ? <Icon className={`w-8 h-8 text-white ${isActive ? 'animate-pulse' : 'opacity-70'}`} /> : null}
                </div>
                <div className="absolute -bottom-6 -right-6 w-24 h-24 bg-white opacity-10 rounded-full blur-xl"></div>
                <div className="absolute top-0 right-0 w-full h-full bg-gradient-to-t from-black/20 to-transparent pointer-events-none"></div>
              </button>
            );
          })}
        </div>

        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-8 min-h-[560px]">
          {activeTab === 'trace' ? (
            <TracePanel uid={uid} cacheEntry={traceCacheByUid[uid]} onRetry={() => handleTraceRetry(uid)} />
          ) : (
            <ModuleStatusPanel state={activeModuleState} onRetry={() => onRetryModule && onRetryModule(activeTab)}>
              {activeTab === 'comprehensive' && <ComprehensivePanel profile={selectedResult.comprehensive_profile} />}
              {activeTab === 'app' && <AppPanel profile={selectedResult.app_profile} />}
              {activeTab === 'behavior' && <BehaviorPanel profile={selectedResult.behavior_profile} />}
              {activeTab === 'credit' && <RichCreditPanel profile={selectedResult.credit_profile} />}
              {activeTab === 'product' && <ProductAdvicePanel profile={selectedResult.product_advice} />}
              {activeTab === 'ops' && <OpsAdvicePanel profile={selectedResult.ops_advice} />}
            </ModuleStatusPanel>
          )}
          {/* 2026-05-05 修复 NL Chat 切走后历史丢失：
              原本 `activeTab === 'chat' ? <ChatPanel/> : ...` 是条件渲染，切走 unmount 会丢掉
              messages / sessionId / dispatchedToolsRef 等全部内部 state，切回只能从 URL 碄复。
              改为始终 mount，仅用 display 切换可见性 — 保留运行中的 SSE 与全部会话 state。 */}
          <div style={{ display: activeTab === 'chat' ? 'block' : 'none' }}>
            <ChatPanel
              onProfileReady={onChatProfileReady}
              onProfilesPending={onChatProfilesPending}
              onTraceReady={onChatTraceReady}
              onJumpToTab={(tabId, targetUid) => {
                setActiveTab(tabId);
                if (targetUid) {
                  const idx = analysisResults.findIndex((r) => r && r.uid === targetUid);
                  if (idx >= 0) setSelectedResultIndex(idx);
                }
              }}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

window.AppComponents = window.AppComponents || {};
window.AppComponents.DashboardView = DashboardView;
