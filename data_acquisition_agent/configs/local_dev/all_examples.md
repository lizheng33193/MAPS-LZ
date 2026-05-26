# 本地开发 — All Examples（local MySQL `user_profile`）

参考 [few.md](./few.md) 的 5 个示例。本地开发模式只覆盖最基础的查询场景：
- 抽样 N 个 UID
- 三方数据齐全 UID
- 按 App 类别筛选
- 按行为时间窗筛选
- 按征信风险筛选

不支持的场景（生产环境才有）：
- 多日数仓分区（`dt=...`）
- 用户画像产品中间层（`dwd_loan_user_*`）
- 关联资产/借贷/还款/催收宽表
