# TASK.md

## 功能清单
- [x] 项目基础设施（AGENTS.md + PLANNING.md + TASK.md；CLAUDE.md 仅历史兼容）— 已完成
- [x] Codex-first 开发指导迁移 — 已完成（AGENTS.md 主入口 + CLAUDE.md 兼容转发 + PLANNING.md Harness 门禁）
- [x] Harness Engineering 项目宪法 — 已完成（AGENTS.md 中文短入口 + docs/specs/harness-engineering-governance.md 详细治理指南）
- [x] BaseSkill + SkillRegistry 重构 — 已完成，68 测试全过
- [x] 默认 LLM 模式切换（mock → gemini）— 已完成
- [x] 依赖版本锁定 — 已完成
- [x] 安全清理（.gitignore + 移除追踪数据 + .env.example 清理）— 已完成
- [x] P0: 清理 Legacy `app/agents/` 目录 — 已完成（2026-04-28，68 测试全过）
- [x] P0: LLM 端到端打通验证 — 已完成（2026-04-28，vertex 模式打通，gemini-3.1-pro-preview，amberstar-gemini/global）
- [x] P1: 拆分 Comprehensive 为六步管线 → 完成（2026-04-28，docs/plans/comprehensive-refactor-plan.md）
- [x] P1: 补全 Behavior/Credit Pydantic Schema → ✅ 完成（2026-04-30，docs/plans/behavior-credit-schema-plan.md，b5f165e，348 passed）
- [x] P2: 新增产品策略 Agent（stage=2）— 完成（2026-04-30，docs/plans/operation-skills-plan.md，六步管线 + S1-S6 规则 + LLM 增强 + e2e 测试）
- [x] P2: 新增运营策略 Agent（stage=2）— 完成（2026-04-30，docs/plans/operation-skills-plan.md，六步管线 + S1-S6 规则 + churn 升档 + LLM 增强 + e2e 测试）
- [x] P3: LangGraph 迁移 → 评估完成，暂不迁移（2026-04-30，docs/specs/langgraph-migration-design.md）
- [x] P4: UI 前端分离 → ✅ 完成（2026-04-30，docs/plans/ui-separation-plan.md） → docs/plans/ui-separation-plan.md（Step 2 Design 已确认 docs/specs/ui-separation-design.md，3e94dbe；Step 3 架构 Stub 已落地）
- [x] data_acquisition_agent V1 — Design Doc 已确认（[docs/specs/data_acquisition_agent.md](docs/specs/data_acquisition_agent.md)，2026-04-29）
- [X] data_acquisition_agent V1 — demo0 凭据脱敏 mini-task — 已完成（2026-04-29，764a647）
- [X] data_acquisition_agent V1 — Step 3 架构设计 — 已完成（2026-04-29，caed309）
- [x] data_acquisition_agent V1 — Step 4 实现 Plan — 已确认并 commit（[docs/plans/data-acquisition-v1-plan.md](docs/plans/data-acquisition-v1-plan.md)，4c854c6）
- [x] data_acquisition_agent V1 — Step 5 TDD 实现完成（2026-04-29，e686404..c8793e3，72 tests）
- [x] data_acquisition_agent V2 — Design Doc 已确认（docs/specs/data_acquisition_agent_v2.md，2026-04-29）
- [x] data_acquisition_agent V2 — Step 3 架构 Stub 已落地（2026-04-29）
- [x] data_acquisition_agent V2 — Step 4 实现 Plan 已确认（[docs/plans/data-acquisition-v2-plan.md](docs/plans/data-acquisition-v2-plan.md)，2026-04-29）
- [x] data_acquisition_agent V2 — Step 5 TDD 实现完成（2026-04-30，916a2dd..5ef1699，71 tests，全量 163 passed）
- [x] data_acquisition_agent V2 — Step 7 交付完成（2026-04-30）
- [x] 前端：product_advice + ops_advice 展示 tab — 完成（2026-04-30，dd7c65f）
- [x] 前端：standardized_labels 标签概览卡 — 完成（2026-04-30，dd7c65f）
- [x] 前端：批量分析 S1-S6 客群分布统计 — 完成（2026-04-30，dd7c65f）
- [x] data_acquisition_agent V1+V2 白盒审计 — 完成（2026-04-30，ca375fa，docs/reviews/data-acquisition-v1v2-audit.md）
- [x] 行为画像：Quincena 发薪日分析 — 完成（2026-04-30，999fcf7..7b71d13，10 tests）
- [x] 重构：APP 分类词典抽到 country_packs/mx/ — 完成（2026-04-30，2ccd4d4..2b6cc36，3 tests）
- [x] E1 单用户埋点深度解析 → docs/plans/trace-analyzer-plan.md（2026-05-01）

## 当前进行中的功能
- [x] ModelClient 重构 → [docs/plans/01-model-client-refactor-plan.md](docs/plans/01-model-client-refactor-plan.md)（[complete] a949830 2026-05-02）
- [x] explainer/trace 切 Claude → [docs/plans/02-explainer-trace-claude-migration-plan.md](docs/plans/02-explainer-trace-claude-migration-plan.md)（[complete] 874c305 2026-05-02）
- [x] Orchestrator Agent → [docs/plans/03-orchestrator-agent-plan.md](docs/plans/03-orchestrator-agent-plan.md)（[complete] 8fb3377 2026-05-03）
- [x] 前端对话 Tab → [docs/plans/04-nl-chat-tab-frontend-plan.md](docs/plans/04-nl-chat-tab-frontend-plan.md)（[complete] 92771ee 2026-05-04 + hotfix 路由 2026-05-04，349 tests + HTTP smoke 全绿）
- [x] Orchestrator Memory V1 → SQLite + FTS5 长期记忆、Memory 管理 API / Inspector、离线评估集与 runner（2026-05-25，baseline checkpoint `3c10d85`，contract: docs/specs/memory-behavior-contract.md）
- [x] Memory recovery audit → 确认 Memory 管理/评估功能仍在，恢复本地 `.env/key.json/data` 运行文件，并记录不可恢复的本地 SQLite runtime state（2026-05-25，docs/reviews/memory-recovery-audit-2026-05-25.md）
- [x] Orchestrator Chat progress + memory/session UI contract → 模块级 `tool_progress`、短期会话历史列表、长期记忆心智澄清（2026-05-26；docs/specs/orchestrator-chat-progress-memory-ui-contract.md；plan: docs/plans/orchestrator-chat-progress-memory-ui-plan.md）
- [x] NL Chat workspace snapshot + history restore split → 历史会话仅切右侧 transcript、显式恢复左侧 workspace、sessionStorage 同 tab 恢复、read-only 追问优先复用已有画像结果（2026-05-27；docs/plans/orchestrator-chat-workspace-snapshot-plan.md）

## 已完成（最近）
- [x] NL Chat 状态分层修复（2026-05-27）
  - workspace state / chat session / reusable workspace snapshot 三层显式分离
  - 历史会话点击不再整页跳转，不再清空左侧画像
  - 新增“恢复该次分析结果”，按历史 `tool_calls` 重建左侧 workspace
  - 只读追问命中已有画像结果时，agent loop 直接模板化回复，不再默认重跑 `run_profile`
- [x] 前端渐进加载迁移（参考项目融合）→ docs/plans/frontend-progressive-loading-plan.md（2026-05-02）
  - 后端：shared_orchestrator 单例 + 模块级缓存 + `/api/analyze-module` + `/api/ui-config`
  - 前端：SSE → 模块级渐进加载 + 假动画过渡 + ModuleStatusPanel 四态重试 + trace 独立加载
  - AppPanel 大模型分析报告卡片（已存在）
  - BehaviorPanel 中文乱码修复 + 大纲 LLM 摘要
  - 270 passed 0 failed
- [x] A1 Golden Test 评估框架（behavior 4 case + comprehensive 1 case smoke）— 完成（2026-05-01，docs/specs/golden-test-design.md + docs/plans/golden-test-plan.md）
- [x] Memory Eval V1（policy / recall@8 / no-leak / redaction / management gates）— 完成（2026-05-25，tests/golden/memory_eval.py + tests/fixtures/golden/memory/eval_set.json）
- [x] D2 SSE 进度推送 → docs/plans/sse-progress-plan.md（2026-05-01，[complete] sse-progress-plan，235 tests passed）
  - Step 2 Design Doc：docs/specs/sse-progress-design.md（Q1-Q6 全锁）
  - Step 3 架构 Stub
  - Step 4 Plan：8 Task TDD
  - Step 5+ 执行：Task 1-8 全部完成
    - Task 1: SkillRegistry.run_all 加 progress_callback
    - Task 2: Orchestrator 透传 callback + analysis_progress 事件
    - Task 3: SSE 端点骨架 (queue 桥接 + heartbeat)
    - Task 4: 总超时 watchdog + stream_error 兜底
    - Task 5: 前端 analyzeByUidStream SSE 解析
    - Task 6: 前端 ProgressView 组件
    - Task 7: app.jsx 集成 streaming view（删除假 LOADING_TEXTS 动画）
    - Task 8: 路由挂载 + LOAD_ORDER 注册

## 历史进行中
- 功能：data_acquisition_agent V1+V2 收尾
- V1 收尾：
  - prompt/security hardening → 已完成（5183809）
  - real LLM JSON 稳定性 → ✅ 已修复（2026-04-30，3/3 成功，commit 32d64e0）
  - Step 8 白盒审计 → 待做
  - Step 8 面试技术总结 → 待做
- V2 状态：Step 5 TDD 全量完成（2026-04-30，163 passed, 1 skipped, 0 failed）
  - 待做：Step 7 交付（push + PLANNING.md 更新）
  - 待做：Step 8 白盒审计 + 面试技术总结

## 待做
- [x] V1 follow-up: stabilize real LLM structured JSON output — 已修复（2026-04-30，32d64e0）
  - 修复：_parse_json_text 预转义裸换行 + schema required 5 key + NL→sql_kind 一致性检查
  - 结果：real LLM 3/3 成功（修复前 0/3），278 passed 0 failed
- [x] V2 Step 3：架构设计 — 已完成（2026-04-29）
- [x] V2 Step 4：Plan — 已确认（2026-04-29，docs/plans/data-acquisition-v2-plan.md）
- [x] V2 Step 5：TDD 实现 — 已完成（2026-04-30，71 tests，全量 163 passed）
- [x] V2 Step 7：交付 → ✅ 完成（2026-04-30）
- [ ] V2 Step 8：白盒审计 + 面试技术总结

## 已完成
- Phase 0 / Task 0.0 — 添加 pyyaml 依赖（1bfac61）
- Phase 0 / Task 0.1 — 填 mexico.yaml 真实知识库路径（4bb3d26）
- Phase 1 / Task 1.1 — schemas: 要求 sql 或 python 至少一非空（739b985）
- Phase 1 / Task 1.2 — schemas: sql_kind ↔ high_risk_ddl 联动 validator（02602d7）
- Phase 2 / Task 2.1 — manifest: CountryManifest YAML loader（b253add）
- Phase 3 / Task 3.1 — redactor: L1 凭据脱敏（11 family，15 tests）（06cdf41）
- Phase 4 / Task 4.1 — output_scanner: L2 凭据回扫（400d6c6）
- Phase 4 / Task 4.2 — output_scanner: Python 危险代码黑名单（d6c7bf1）
- Phase 4 / Task 4.3 — output_scanner: SQL DDL 二分策略（cf2af70）
- Phase 5 / Task 5.1 — prompt_assembler: CJK 加权 token 估算（740bfd2）
- Phase 5 / Task 5.2 — prompt_assembler: assemble_prompt + 800K 阈值护栏（b63dc6d）
- Phase 6 / Task 6.1 — orchestrator: 骨架 + request_id + happy path（3eaaf1d）
- Phase 6 / Task 6.2 — orchestrator: 输出策略三类分流（b7aa784）
- Phase 6 / Task 6.3 — orchestrator: response 异常兜底 → schema_validation_failed（dfc907b）
- Phase 7 / Task 7.1 — api: 接 orchestrator + ErrorType→HTTP 映射（ca3f708）
- Phase 7 / Task 7.2 — app/main.py 挂载 da-agent router（8163d73）
- Phase 8 / Task 8.1 — e2e mock LLM happy-path 集成测试 [complete]（c8793e3）
- V1 prompt/security hardening — prompt 注入 analyst_private_prefix + 默认 query_only + 禁止 Python DB client；ErrorResponse / OrchestratorError 改为固定安全短消息，避免泄漏 SQL / Python / LLM payload（5183809）
- V2 Phase 1 / Task 1.1 — ExecuteRequest validators（15c8c68）
- V2 Phase 2 / Task 2.1 — starrocks connection layer（b65b28d）
- V2 Phase 3 / Task 3.1 — pre-execution gates（18ccef1）
- V2 Phase 3 / Task 3.2 — count precheck（67339ab）
- V2 Phase 3 / Task 3.3 — execute_query（8cbaa4b）
- V2 Phase 4 / Task 4.1 — bucket schema validation（6485e5d）
- V2 Phase 4 / Task 4.2 — per-uid payload builder（1c02b38）
- V2 Phase 4 / Task 4.3 — atomic per-uid writer（142d592）
- V2 Phase 4 / Task 4.4 — resolve bucket dir（a891a87）
- V2 Phase 5 / Task 5.1 — execute pipeline（c59dfa9）
- V2 Phase 5 / Task 5.2 — wire api /execute to pipeline（178faff）
- V2 Phase 6 / Task 6.1 — T1 build_table_script no-connect（72c7a8f）
- V2 Phase 6 / Task 6.2 — T2 query_only DDL/DML reject（e02bd45）
- V2 Phase 6 / Task 6.3 — T3 connection no secret leak（6567230）
- V2 Phase 6 / Task 6.4 — T4 fixed error messages（b26dc08）
- V2 Phase 6 / Task 6.5 — e2e mock executor happy path [complete]（5ef1699）

## 开发中发现
- [ ] **behavior_profile fixture 中文乱码**：tests/fixtures/golden/behavior_profile/*.json 的 `evidence.behavior_profile_narrative.behavior_summary` 是乱码字节（GBK / latin-1 误解 UTF-8 字节流），影响 L3-d 跨 case quincena 关键词断言（当前 G1/G3 quincena_mentions 双 0，已 warning skip 严格大于）。根因推测在 ModelClient → Vertex SDK 的 protobuf decode 环节。修复后需重跑 `pytest tests/test_golden_behavior_comprehensive.py --refresh-fixtures` 重录 fixture（2026-05-01，A1 Golden Test 落地时发现）
- [x] `app/schemas/behavior_profile.py` 与 `app/schemas/credit_profile.py` 字段稀疏，大量字段藏在 `dict[str, Any]` 中（细节 Plan 阶段确认）— ✅ 已通过 P1 补全（2026-04-30，b5f165e）
- [x] 已发现：Pydantic v1 的 `@root_validator` 有 deprecation warning，迁移到 v2 的具体落点待 Plan 阶段确认
- [ ] `app/ui/live_frontend.py` 2256 行 HTML/JS 嵌入 Python 字符串，待前端分离（关联 P4：docs/specs/ui-separation-design.md / docs/plans/ui-separation-plan.md）
- [x] behavior_profile / credit_profile 的 `structured_result` 顶层未回传 `model_trace`，与 app_profile / comprehensive_profile 不一致 —— 影响 used_llm 可观测性（2026-04-28 P0-2 验证发现）
- [x] behavior_timeline_summary 在端到端运行中触发 1 次 json_parse retry（"Unterminated string"），retry 后仍 fallback 到 model_unavailable —— 需关注稳定性（2026-04-28 P0-2 验证发现）
- [x] data_acquisition_agent V2 — 连接 StarRocks 执行审核后 SQL + 数据落到 data/ per-uid 文件 — Step 5 TDD 完成（2026-04-30，71 tests）

## 阻塞项
（空）

## P0-2 验证结果（2026-04-28）
- 环境：执行 `pip install -r requirements.txt` 装入 google-genai-1.73.1（之前缺包）
- 配置：MODEL_MODE=vertex，model=gemini-3.1-pro-preview，project=amberstar-gemini，location=global，credentials=key.json
- ModelClient 探针：HTTP 200，JSON 解析成功（status=ok，reply=OK）
- 端到端 orchestrator.analyze(['824812551379353600'])：总耗时 ~163s，4 个 skill 全部 status=ok
  - app_profile：used_llm=True（model_trace 在 sr 顶层）
  - comprehensive_profile：used_llm=True（model_trace 在 sr 顶层）
  - behavior_profile：日志显示调用 LLM 成功（含 1 次 retry 因 json_parse），但 sr 顶层无 model_trace 字段
  - credit_profile：日志显示调用 LLM 成功，但 sr 顶层无 model_trace 字段
- 开发中发现新增条目见下
