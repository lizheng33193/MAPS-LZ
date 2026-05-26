const {
  archiveMemory,
  createMemory,
  deleteMemory,
  fetchMemoryStatus,
  listMemories,
  queryMemory,
  restoreMemory,
  updateMemory,
} = window.AppServices.api;
const { useCallback, useEffect, useMemo, useState } = React;
const {
  Archive,
  ChevronDown,
  ChevronUp,
  Database,
  Edit3,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} = window.LucideReact || {};

const CATEGORY_OPTIONS = ['preference', 'feedback', 'project', 'reference', 'task', 'insight'];
const STATUS_OPTIONS = ['active', 'archived', 'deleted', 'all'];

function MemoryInspector() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState([]);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [statusFilter, setStatusFilter] = useState('active');
  const [topK, setTopK] = useState(8);
  const [userId, setUserId] = useState('local-default-user');
  const [projectId, setProjectId] = useState('agent-user-profile-fork');
  const [country, setCountry] = useState('mx');
  const [draft, setDraft] = useState(_emptyDraft());
  const [editingId, setEditingId] = useState('');
  const [editDraft, setEditDraft] = useState(_emptyDraft());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const identity = useMemo(() => ({
    user_id: userId.trim() || undefined,
    project_id: projectId.trim() || undefined,
    country: country.trim() || undefined,
  }), [country, projectId, userId]);

  const loadStatus = useCallback(async () => {
    const body = await fetchMemoryStatus();
    setStatus(body);
  }, []);

  const loadList = useCallback(async (overrides = {}) => {
    const nextQuery = Object.prototype.hasOwnProperty.call(overrides, 'query') ? overrides.query : query;
    const nextCategory = Object.prototype.hasOwnProperty.call(overrides, 'category') ? overrides.category : category;
    const nextStatus = Object.prototype.hasOwnProperty.call(overrides, 'status') ? overrides.status : statusFilter;
    setLoading(true);
    setError('');
    try {
      const payload = nextQuery.trim()
        ? await queryMemory({
            query: nextQuery,
            ...identity,
            category: nextCategory || undefined,
            top_k: Number(topK) || 8,
          })
        : await listMemories({
            ...identity,
            category: nextCategory || undefined,
            status: nextStatus || 'active',
            limit: Number(topK) || 8,
          });
      setResults(Array.isArray(payload.results) ? payload.results : []);
      await loadStatus();
    } catch (err) {
      setError(String((err && err.message) || err));
    } finally {
      setLoading(false);
    }
  }, [category, identity, loadStatus, query, statusFilter, topK]);

  useEffect(() => {
    if (!open) return;
    loadStatus().catch((err) => setError(String((err && err.message) || err)));
    loadList();
  }, [open]);

  const create = useCallback(async () => {
    if (!draft.content.trim()) return;
    setLoading(true);
    setError('');
    try {
      await createMemory({
        ...identity,
        content: draft.content,
        category: draft.category,
        tags: _tags(draft.tags),
        importance: Number(draft.importance),
        confidence: Number(draft.confidence),
      });
      setDraft(_emptyDraft());
      await loadList({ query: '' });
    } catch (err) {
      setError(String((err && err.message) || err));
    } finally {
      setLoading(false);
    }
  }, [draft, identity, loadList]);

  const startEdit = (item) => {
    setEditingId(item.memory_id);
    setEditDraft({
      content: item.content || '',
      category: item.category || 'reference',
      tags: Array.isArray(item.tags) ? item.tags.join(', ') : '',
      importance: item.importance ?? 0.7,
      confidence: item.confidence ?? 0.8,
    });
  };

  const saveEdit = useCallback(async (memoryId) => {
    setLoading(true);
    setError('');
    try {
      await updateMemory(memoryId, {
        ...identity,
        content: editDraft.content,
        category: editDraft.category,
        tags: _tags(editDraft.tags),
        importance: Number(editDraft.importance),
        confidence: Number(editDraft.confidence),
      });
      setEditingId('');
      await loadList();
    } catch (err) {
      setError(String((err && err.message) || err));
    } finally {
      setLoading(false);
    }
  }, [editDraft, identity, loadList]);

  const setRowStatus = useCallback(async (item, action) => {
    setLoading(true);
    setError('');
    try {
      if (action === 'archive') await archiveMemory(item.memory_id, identity);
      if (action === 'restore') await restoreMemory(item.memory_id, identity);
      if (action === 'delete') await deleteMemory(item.memory_id, identity);
      await loadList({ query: '' });
    } catch (err) {
      setError(String((err && err.message) || err));
    } finally {
      setLoading(false);
    }
  }, [identity, loadList]);

  const ToggleIcon = open ? ChevronUp : ChevronDown;
  const total = status && typeof status.total === 'number' ? status.total : 0;
  const byCategory = status && status.by_category ? Object.entries(status.by_category) : [];
  const byStatus = status && status.by_status ? Object.entries(status.by_status) : [];

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="flex min-w-0 items-center gap-2">
          {Database ? <Database className="h-4 w-4 shrink-0 text-slate-500" /> : null}
          <span className="font-semibold text-slate-800">记忆</span>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">{total}</span>
        </span>
        {ToggleIcon ? <ToggleIcon className="h-4 w-4 shrink-0 text-slate-500" /> : null}
      </button>

      {open ? (
        <div className="border-t border-slate-200 px-4 py-4">
          <div className="grid gap-3 md:grid-cols-[1.2fr_0.75fr_0.55fr_0.45fr]">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-slate-500">Query</span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') loadList();
                }}
                className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
                placeholder="空查询返回列表"
              />
            </label>
            <SelectField label="Category" value={category} onChange={setCategory} options={['', ...CATEGORY_OPTIONS]} emptyLabel="全部" />
            <SelectField label="Status" value={statusFilter} onChange={setStatusFilter} options={STATUS_OPTIONS} />
            <label className="block">
              <span className="mb-1 block text-xs font-semibold text-slate-500">Limit</span>
              <input
                type="number"
                min="1"
                max="50"
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
              />
            </label>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <input value={userId} onChange={(e) => setUserId(e.target.value)} className="h-9 rounded-lg border border-slate-200 px-3 text-xs outline-none focus:border-blue-400" aria-label="user id" />
            <input value={projectId} onChange={(e) => setProjectId(e.target.value)} className="h-9 rounded-lg border border-slate-200 px-3 text-xs outline-none focus:border-blue-400" aria-label="project id" />
            <input value={country} onChange={(e) => setCountry(e.target.value)} className="h-9 rounded-lg border border-slate-200 px-3 text-xs outline-none focus:border-blue-400" aria-label="country" />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => loadList()} disabled={loading} className="inline-flex h-9 items-center gap-2 rounded-lg bg-slate-900 px-3 text-sm font-semibold text-white disabled:opacity-60">
              {loading && RefreshCw ? <RefreshCw className="h-4 w-4 animate-spin" /> : Search ? <Search className="h-4 w-4" /> : null}
              查询
            </button>
            <button type="button" onClick={() => { setQuery(''); loadList({ query: '' }); }} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 px-3 text-sm font-semibold text-slate-700">
              {SlidersHorizontal ? <SlidersHorizontal className="h-4 w-4" /> : null}
              列表
            </button>
            {byCategory.map(([key, value]) => <Badge key={key} tone="blue">{key}: {value}</Badge>)}
            {byStatus.map(([key, value]) => <Badge key={key}>{key}: {value}</Badge>)}
          </div>

          <div className="mt-4 rounded-lg border border-slate-200 p-3">
            <div className="grid gap-3 md:grid-cols-[1fr_0.32fr]">
              <textarea
                value={draft.content}
                onChange={(e) => setDraft({ ...draft, content: e.target.value })}
                className="min-h-[74px] rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400"
                placeholder="新增记忆内容"
              />
              <div className="grid gap-2">
                <SelectField value={draft.category} onChange={(v) => setDraft({ ...draft, category: v })} options={CATEGORY_OPTIONS} />
                <input value={draft.tags} onChange={(e) => setDraft({ ...draft, tags: e.target.value })} className="h-9 rounded-lg border border-slate-200 px-3 text-xs outline-none focus:border-blue-400" placeholder="tags" />
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <NumberField label="importance" value={draft.importance} onChange={(v) => setDraft({ ...draft, importance: v })} />
              <NumberField label="confidence" value={draft.confidence} onChange={(v) => setDraft({ ...draft, confidence: v })} />
              <button type="button" onClick={create} disabled={loading || !draft.content.trim()} className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-semibold text-white disabled:opacity-60">
                {Plus ? <Plus className="h-4 w-4" /> : null}
                新增
              </button>
            </div>
          </div>

          {status && status.db_path ? <div className="mt-3 truncate text-xs text-slate-500">{status.db_path}</div> : null}
          {error ? <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}

          <div className="mt-4 space-y-2">
            {results.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500">暂无结果</div>
            ) : results.map((item) => (
              <article key={item.memory_id} className="rounded-lg border border-slate-200 px-3 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-semibold text-slate-700">{item.category}</span>
                    <span className="text-slate-500">{item.status}</span>
                    {item.score !== undefined ? <span className="text-slate-500">score {item.score}</span> : null}
                    <span className="text-slate-500">importance {item.importance}</span>
                    <span className="text-slate-500">confidence {item.confidence}</span>
                    <span className="text-slate-400">{item.source}</span>
                    <span className="text-slate-400">{item.created_at}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <IconButton title="编辑" onClick={() => startEdit(item)} icon={Edit3} />
                    {item.status === 'active' ? <IconButton title="归档" onClick={() => setRowStatus(item, 'archive')} icon={Archive} /> : null}
                    {item.status !== 'active' && item.status !== 'deleted' ? <IconButton title="恢复" onClick={() => setRowStatus(item, 'restore')} icon={RotateCcw} /> : null}
                    {item.status !== 'deleted' ? <IconButton title="删除" onClick={() => setRowStatus(item, 'delete')} icon={Trash2} /> : null}
                  </div>
                </div>
                {editingId === item.memory_id ? (
                  <EditForm draft={editDraft} setDraft={setEditDraft} onSave={() => saveEdit(item.memory_id)} onCancel={() => setEditingId('')} loading={loading} />
                ) : (
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{item.content}</p>
                )}
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function SelectField({ label, value, onChange, options, emptyLabel }) {
  return (
    <label className="block">
      {label ? <span className="mb-1 block text-xs font-semibold text-slate-500">{label}</span> : null}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-blue-400">
        {options.map((option) => <option key={option || 'empty'} value={option}>{option || emptyLabel || option}</option>)}
      </select>
    </label>
  );
}

function NumberField({ label, value, onChange }) {
  return (
    <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-500">
      {label}
      <input type="number" min="0" max="1" step="0.05" value={value} onChange={(e) => onChange(e.target.value)} className="h-9 w-20 rounded-lg border border-slate-200 px-2 text-xs outline-none focus:border-blue-400" />
    </label>
  );
}

function EditForm({ draft, setDraft, onSave, onCancel, loading }) {
  return (
    <div className="mt-3 rounded-lg bg-slate-50 p-3">
      <textarea value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} className="min-h-[86px] w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400" />
      <div className="mt-2 grid gap-2 md:grid-cols-[0.7fr_1fr_0.4fr_0.4fr_auto]">
        <SelectField value={draft.category} onChange={(v) => setDraft({ ...draft, category: v })} options={CATEGORY_OPTIONS} />
        <input value={draft.tags} onChange={(e) => setDraft({ ...draft, tags: e.target.value })} className="h-10 rounded-lg border border-slate-200 px-3 text-xs outline-none focus:border-blue-400" placeholder="tags" />
        <NumberField label="importance" value={draft.importance} onChange={(v) => setDraft({ ...draft, importance: v })} />
        <NumberField label="confidence" value={draft.confidence} onChange={(v) => setDraft({ ...draft, confidence: v })} />
        <div className="flex items-center gap-1">
          <IconButton title="保存" onClick={onSave} icon={Save} disabled={loading} />
          <IconButton title="取消" onClick={onCancel} icon={X} />
        </div>
      </div>
    </div>
  );
}

function IconButton({ title, onClick, icon: Icon, disabled }) {
  return (
    <button type="button" title={title} aria-label={title} onClick={onClick} disabled={disabled} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50">
      {Icon ? <Icon className="h-4 w-4" /> : title.slice(0, 1)}
    </button>
  );
}

function Badge({ children, tone }) {
  const cls = tone === 'blue'
    ? 'rounded bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700'
    : 'rounded bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600';
  return <span className={cls}>{children}</span>;
}

function _emptyDraft() {
  return { content: '', category: 'preference', tags: '', importance: 0.75, confidence: 0.8 };
}

function _tags(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
}

window.AppComponents = window.AppComponents || {};
window.AppComponents.MemoryInspector = MemoryInspector;
