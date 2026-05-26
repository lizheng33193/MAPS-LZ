# 本地开发 — Few-shot 示例（local MySQL `user_profile`）

## 示例 1：随机抽 5 个有 App 数据的用户

**自然语言**：帮我查 5 个墨西哥用户

```sql
SELECT DISTINCT uid
FROM app_install_list
LIMIT 5;
```

---

## 示例 2：抽 N 个有完整三方数据（app + behavior + credit）的用户

**自然语言**：找 3 个数据齐全的墨西哥用户

```sql
SELECT DISTINCT a.uid
FROM app_install_list AS a
INNER JOIN behavior_events AS b ON a.uid = b.uid
INNER JOIN credit_report  AS c ON a.uid = c.uid
LIMIT 3;
```

---

## 示例 3：找安装了金融类 App 的用户

**自然语言**：查装了金融 App 的墨西哥用户

```sql
SELECT DISTINCT uid
FROM app_install_list
WHERE gp_category = '金融'
LIMIT 10;
```

---

## 示例 4：找最近一周有行为埋点的用户

**自然语言**：查最近 7 天活跃用户

```sql
SELECT DISTINCT uid
FROM behavior_events
WHERE FROM_UNIXTIME(CAST(servertimestamp AS DOUBLE) / 1000)
      >= DATE_SUB(NOW(), INTERVAL 7 DAY)
LIMIT 10;
```

---

## 示例 5：找高风险征信用户

**自然语言**：查高风险征信用户

```sql
SELECT uid
FROM credit_report
WHERE JSON_EXTRACT(report_json, '$.risk_level') = '"high"'
LIMIT 5;
```

---

## 重要提示

- 所有示例必须 `SELECT uid`（pipeline 按 uid 切分输出文件）
- 默认带 `LIMIT`，避免全表扫描
- 不要用生产数仓表名（dwd_w_user、dwb_*、hive.* 等）
