function ChatInputBox({ value, onChange, onSend, disabled }) {
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !disabled) {
      e.preventDefault();
      onSend();
    }
  };
  return (
    <div className="flex gap-3">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={2}
        className="flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-100"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
      />
      <button
        onClick={onSend}
        disabled={disabled || !value.trim()}
        className="rounded-xl bg-blue-600 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300"
      >
        发送
      </button>
    </div>
  );
}

window.AppComponents = window.AppComponents || {};
window.AppComponents.ChatInputBox = ChatInputBox;
