# Local Dev (MySQL 3-table) Knowledge Base — INDEX

> DA_LOCAL_DEV=1 时使用；4 个本地 mysql 用 md（无空格文件名）+ 跨国共享 system_prompt.md

---

## system_prompt.md
- **path**: data_acquisition_agent/demo0/system_prompt.md
- **title**: 跨国共享 system prompt
- **keywords**: [system, prompt, role, task_orientation, json_format_rules]
- **usage_hint**: 必须始终注入
- **token_estimate**: 0
- **always_inject**: true

## scheme.md
- **path**: data_acquisition_agent/configs/local_dev/scheme.md
- **title**: 本地 mysql 3 表 schema
- **keywords**: [schema, table, mysql, 字段, 表结构]
- **usage_hint**: 涉及表名 / 字段问题
- **token_estimate**: 0
- **always_inject**: true

## business_logic.md
- **path**: data_acquisition_agent/configs/local_dev/business_logic.md
- **title**: 本地业务规则
- **keywords**: [活跃用户, 业务规则, 定义]
- **usage_hint**: 业务定义问题
- **token_estimate**: 0
- **always_inject**: false

## few.md
- **path**: data_acquisition_agent/configs/local_dev/few.md
- **title**: 本地 few-shot SQL 模板
- **keywords**: [example, few-shot, sql 示例]
- **usage_hint**: 默认 few-shot
- **token_estimate**: 0
- **always_inject**: true

## all_examples.md
- **path**: data_acquisition_agent/configs/local_dev/all_examples.md
- **title**: 本地完整示例库
- **keywords**: [完整示例, 历史 case]
- **usage_hint**: 复杂查询补充
- **token_estimate**: 0
- **always_inject**: false
