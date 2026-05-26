function ChatMessageList({ messages }) {
  if (!messages || messages.length === 0) {
    return <div className="text-sm text-slate-400 italic">开始你的第一条消息...</div>;
  }
  return (
    <div className="flex flex-col gap-3">
      {messages.map((m, index) => (
        <div key={index} className={`max-w-[82%] rounded-xl px-4 py-3 text-sm ${m.role === 'user' ? 'self-end bg-blue-600 text-white' : 'self-start bg-white text-slate-700 border border-slate-200'}`}>
          <div className="text-xs opacity-70 mb-1">{m.role}</div>
          <div className="whitespace-pre-wrap">{m.content}</div>
        </div>
      ))}
    </div>
  );
}

window.AppComponents = window.AppComponents || {};
window.AppComponents.ChatMessageList = ChatMessageList;
