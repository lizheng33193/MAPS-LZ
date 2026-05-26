# 本地开发 — 墨西哥数据库 Schema（local MySQL `user_profile`）

> **重要**：你正在为本地开发模式生成 SQL，目标是本地 MySQL 数据库（database = `user_profile`）。
> 此环境只有 3 张表，所有表都包含 `uid` 字段（VARCHAR(20)）作为用户标识。
> SQL 方言：MySQL 5.7+ 兼容（不要用 StarRocks/Hive 专有语法）。
> **只读查询**：禁用 DELETE/DROP/TRUNCATE/UPDATE/INSERT。

---

## 表 1：`app_install_list` — 用户已安装 App 清单

| 字段 | 类型 | 含义 |
|---|---|---|
| `uid` | varchar(20) | 用户 ID（主索引） |
| `app_name` | varchar(255) | App 显示名（如 "Ualá"、"Mercado Pago"） |
| `app_package` | varchar(255) | Android 包名 |
| `first_install_time` | double | 首次安装时间（毫秒时间戳） |
| `last_update_time` | double | 最近更新时间（毫秒时间戳） |
| `gp_category` | varchar(255) | Google Play 一级分类（如 "金融"、"社交"） |
| `ai_category_level_2_CN` | varchar(255) | AI 标注的二级中文分类（如 "移动银行"、"借贷"） |

行数级别：~272 行（小数据集）

---

## 表 2：`behavior_events` — 用户埋点行为事件

| 字段 | 类型 | 含义 |
|---|---|---|
| `uid` | varchar(20) | 用户 ID（主索引） |
| `servertimestamp` | varchar(30) | 服务端时间戳（字符串型毫秒数） |
| `timestamp_` | varchar(30) | 客户端时间戳（字符串型毫秒数） |
| `scenetype` | varchar(255) | 场景类型（如 "WebViewActivity"） |
| `processtype` | varchar(255) | 进程类型（如 "Native"） |
| `eventname` | varchar(255) | 事件名（如 "page_onPause"、"click_apply"） |
| `extend` | text | 扩展字段（JSON 字符串） |
| `clientmodel` | varchar(255) | 客户端机型 |
| `clientosversion` | varchar(255) | 客户端 OS 版本 |
| `url` | text | 当前 URL |
| `refer` | text | 来源 URL |
| `ip` | varchar(50) | IP 地址 |

行数级别：~4096 行

---

## 表 3：`credit_report` — 用户征信报告（每用户 1 条）

| 字段 | 类型 | 含义 |
|---|---|---|
| `uid` | varchar(20) | 用户 ID（主键） |
| `report_json` | longtext | 完整征信 JSON 字符串，结构示例：`{"uid": "...", "credit_score_band": "D", "repayment_status": "normal", "risk_level": "high"}` |

行数级别：~9 行

---

## 输出约束（重要）

- **必须** 在 SELECT 列表中包含 `uid` 字段（agent pipeline 按 uid 切分输出）。
- **建议** 默认带 `LIMIT N`（5 ≤ N ≤ 100），用户未指定时取 5。
- **不要** 使用 `hive.dwd.xxx`、`dwd_w_user`、`dwb_*` 等生产数仓表名 —— 那些表本地不存在。
- **不要** 使用 `WHERE country='mexico'` 或 `dt='YYYYMMDD'` 这类生产分区字段 —— 本地表无分区。
- **MySQL 方言**：用 `LIMIT 5`；用 `FROM_UNIXTIME(col/1000)` 处理毫秒时间戳；用 `JSON_EXTRACT` 解析 JSON。
