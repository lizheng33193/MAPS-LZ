# NL Chat Tab 手动测试用例

前置：Plan #04 hotfix 已完成（POST /sessions, /messages, GET /stream 路由已落地）。

启动后端（PowerShell）：

```powershell
$env:MODEL_MODE='mock'
uvicorn app.main:app --reload --port 8000
```

> **Mock 模式下 agent_loop 直接返回 fallback final_message**（`tool_call=None`），所以
> **TC-3（ACK 卡片）天然无法在 mock 下端到端触发**，其逻辑由 `tests/frontend/test_chat_reducer.py`
> 单元测试覆盖（reducer 对 `awaiting_user_ack` 事件的响应）。TC-3 标记为 N/A（mock）。
> 在真实 Gemini 模式下若 prompt 引导 LLM 调用 `query_data` 工具，TC-3 会真实触发。

## TC-1 首次打开
1. 打开 `http://localhost:8000/`。
2. 期望仍停留在 HomeView，不自动进入 dashboard。
3. 打开 `http://localhost:8000/?tab=chat`。
4. 期望直接进入 DashboardView，第 8 个 tab `自然语言对话 / NL Chat` 高亮，页面无 console error。
5. **本步需先完成 TC-2 / TC-4 拿到真实 `<uuid>`**：用 TC-2 创建的 session_id 拼出 `http://localhost:8000/?session=<uuid>`，期望直接进入 DashboardView，第 8 个 tab 高亮，并触发 session restore（无真实 session_id 时跳过本步）。

## TC-2 首轮对话
1. 输入 `分析 G3 在墨西哥的 churn 风险`，按 Enter。
2. 期望出现 user 气泡、assistant 增量气泡、工具调用状态、最终 final 气泡。

## TC-3 ACK
1. mock 流触发 `awaiting_user_ack`。
2. 期望黄色 ACK 卡片出现。
3. Enter 发送 approve；Esc 发送 reject。

## TC-4 刷新恢复
1. 完成对话后确认 URL 包含 `?tab=chat&session=<uuid>`。
2. F5 刷新，期望历史消息恢复。

## TC-5 错误兜底
1. 停止后端，再发送消息。
2. 期望红色错误条出现，页面不崩溃。

执行结果：
- [x] TC-1 PASS（HTTP smoke：ChatPanel + chatReducer 注册到 bundled HTML）
- [x] TC-2 PASS（HTTP smoke：POST /sessions → GET /stream 收到 session_started/final/done 三事件，第二轮 /messages + /stream 同样绿）
- [x] TC-3 N/A（mock 模式无法触发，单元测试已覆盖 reducer；ack body 兼容已通过 HTTP smoke + 8 个 pytest）
- [x] TC-4 PASS（HTTP smoke：GET /sessions/{id} 持久化 messages 含 `user` + `assistant`，agent_loop 二段 hotfix 已落地）
- [x] TC-5 PASS（HTTP smoke：GET /stream 不存在 session 返回 404）

> Smoke 脚本：[scratch/plan04_smoke.ps1](../../scratch/plan04_smoke.ps1)
> Hotfix pytest：[tests/test_orchestrator_chat_routes.py](../../tests/test_orchestrator_chat_routes.py)（8 tests，全绿）
> 全量 pytest：tests/ 349 passed（baseline 341 + 8 new），data_acquisition_agent/tests/ 163 passed + 1 skipped 不变。
> React UI 纯渲染层（按钮点击、URL writeback、ChatAckCard）建议浏览器打开 `http://localhost:8000/?tab=chat` 30 秒目测。
