---
标题: 如何核查一张 TT 工单的派单依据
分类: 10_集成篇_Integration/15_排障与运维_Troubleshooting
标签: [排障, 派单, SQL, eflow_tt, 工具]
状态: 已验证
适用对象: 开发
最后更新: 2026-09-01
作者: 如意
来源: 实际操作确认
---

# 如何核查一张 TT 工单的派单依据

## 一句话

有人投诉「XX 单派错了」时，用 `tools/inspect_tt.py` 一键出报告；要自己查就用下面的 SQL。

## 用工具（推荐）

```bash
python "D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py" TT202608220047
python "D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py" TT202608220047 --json   # 机器可读
```

输出包含：站点 / 时间轴 / 告警 / 制式掉站分布 / 根因 / 派单组 / 告警到派单的时间差 /
该根因在全库的派单分布 / CSD vs PSD 对照。

单号记不全时会做模糊兜底，列出相近单号。

---

## 数据源位置

| 项 | 值 |
|---|---|
| 库 | `D:\01_RPA\Task\my_app\db\app.db` |
| 表 | `eflow_tt` |
| 单号列 | **`tt_no`** |
| 列数 | 161 |

> ⚠️ **不是** `data\eflow\eflow.sqlite3`。那份原始导出库里没有 `tt_no` 列，
> 单号在那里叫 `WO No.`，且数据与 app.db 不同步。**查工单用 app.db。**

---

## 手查 SQL

### 1. 拉一张单的关键字段

```sql
SELECT tt_no, site_name, site_id, region_level1,
       alarm_occur_time, created_time, alarm_clear_time,
       root_cause, sub_root_cause, root_cause_description,
       sub_alarm_name, impacted_service,
       col_2g_down_site_count, col_3g_down_site_count, col_4g_down_site_count,
       last_processer_group, last_processer,
       status, ticket_severity, sla_status
FROM eflow_tt
WHERE tt_no = 'TT202608220047';
```

### 2. 算告警到派单的延迟

```sql
SELECT tt_no,
       alarm_occur_time,
       created_time,
       ROUND((julianday(created_time) - julianday(alarm_occur_time)) * 24, 2) AS lag_hours
FROM eflow_tt
WHERE tt_no = 'TT202608220047';
```

### 3. 某根因的派单归属分布（判断这次派单是否常规）

```sql
SELECT REPLACE(REPLACE(last_processer_group, char(10), ''), char(13), '') AS grp,
       COUNT(*) AS n
FROM eflow_tt
WHERE root_cause = 'POWER'
  AND last_processer_group IS NOT NULL
  AND TRIM(last_processer_group) <> ''
GROUP BY grp
ORDER BY n DESC;
```

### 4. CSD vs PSD 的派三方比例（证明掉站类型不决定归属）

```sql
SELECT SUM(sub_alarm_name LIKE '%CSD%')                                   AS csd_all,
       SUM(sub_alarm_name LIKE '%CSD%' AND last_processer_group LIKE '%3rd_Power%') AS csd_3rd,
       SUM(sub_alarm_name LIKE '%PSD%')                                   AS psd_all,
       SUM(sub_alarm_name LIKE '%PSD%' AND last_processer_group LIKE '%3rd_Power%') AS psd_3rd
FROM eflow_tt;
```

当前结果：`csd_3rd/csd_all = 57.4%`，`psd_3rd/psd_all = 57.3%` —— 几乎无差异。

### 5. 各根因的派单倾向

```sql
SELECT root_cause,
       COUNT(*) AS total,
       SUM(last_processer_group LIKE '%3rd_Power%') AS to_3rd_power,
       ROUND(SUM(last_processer_group LIKE '%3rd_Power%') * 100.0 / COUNT(*), 1) AS pct
FROM eflow_tt
WHERE root_cause IS NOT NULL AND TRIM(root_cause) <> ''
GROUP BY root_cause
ORDER BY total DESC;
```

---

## 字段说明

| 字段 | 用途 | 注意 |
|---|---|---|
| `tt_no` | TT 单号 | 主键式查询列 |
| `alarm_occur_time` | **告警发生时刻** | 派单判定基准 |
| `created_time` | TT 创建 / 派单时刻 | 可能比告警晚数小时 |
| `root_cause` | **根因** | 决定派单归属的主要因素 |
| `sub_root_cause` | 根因细分 | 如 `Power Solar` |
| `sub_alarm_name` | 告警名列表 | 其中含 `CSD` / `PSD` 标记 |
| `col_Ng_down_site_count` | 各制式掉站数 | ⚠️ **大量工单为空**，不能当判定依据 |
| `last_processer_group` | 派往的处理组 | 多值，分号分隔且**带换行符**，聚合前需 `REPLACE` 清理 |
| `impacted_service` | 受影响制式 | 如 `2G,3G` |

### 两个坑

1. **`last_processer_group` 含换行符**：直接 `GROUP BY` 会分出很多看着一样却不同的组。
   聚合前先 `REPLACE(REPLACE(col, char(10), ''), char(13), '')`。
2. **`col_*_down_site_count` 是字符串类型**，且大量为空字符串或 0。
   做数值比较前要 `CAST` 或 `int(float(v))`，否则会报
   `TypeError: '>' not supported between str and int`。

---

## 判定归属的正确顺序

```
1. 看 root_cause        → POWER 类大概率三方，RAN/MW/Fiber 类不派三方
2. 看 alarm_occur_time  → 判定基准时刻（不是 created_time）
3. 看 sub_alarm_name 的 CSD/PSD → 仅作参考，不决定归属
4. 查各制式告警真实时间线 → tools/eflow_hisalarm_by_tt.py（见下节）
```

---

## 从 eFlow 系统查历史告警（本地没有时）

**为什么本地可能没有**：`app.db.history_alarm` 只滚动保留**最近 48 小时**
（`backend/services/eflow_alarm_config.json` 的 `his_alarm_hours: 48`），
且同步时会丢弃 TT ID 为空/`-` 的记录。查更早的告警必须直连 eFlow API。

```bash
# 需用系统 Python 3.12（有 pandas）；my_app 自带 venv 没有
"C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe" ^
  "D:\01_RPA\Task\eflow_Q&A\tools\eflow_hisalarm_by_tt.py" TT202608220047
```

原理：从单号推断日期 → POST `/api/fm-history/v1/hisalarms/pageinfo`，
`alarmraisedtime` 指定时间窗 → 本地按 `TT ID` 过滤。单号日期查不到会自动向前扩天。

输出四部分：
1. 该单名下命中的告警（含 `Assign RuleName` / `Assign Delay` / 派单时间）
2. **同站点全部告警**（判断「派单时刻各制式是否掉站」看这里，不要看 TT 上的
   `impacted_service` —— 那是后续 Assign-Append 追加的汇总，不代表告警时刻状态）
3. 翻页说明：服务端单页实际上限 2000 条（无视请求的 size），工具按 `totalcount` 自动翻页
4. 3G 告警恢复时间 vs 派单时点的自动对比

### 实测发现（TT202608220047，2026-09-01）

- `Assign Delay = 14400s` 是派单规则 `SITEOUTAGE_REGULAR_COOL` 的**内置延迟**（4 小时），
  `Assign Start Time = 告警发生 + 4h`，分秒吻合 —— 4 小时是设计行为，不是派单慢
- 该站 2G 掉了 6 天（02:27 → 8/28），3G 是派单**之后** 7 小时才掉（13:31）、次日 08:21 恢复
- 3G 告警走 `Assign-Append` 追加进已有 TT —— 这就是 TT 上 `impacted_service=2G,3G`
  和 `sub_alarm_name` 含 `3G SITE DOWN` 的来源

### 调 API 的注意点

- 服务端单页上限 **2000**（请求 `size=5000` 也只返回 2000），翻页 offset 按**实际返回数**递增
- 时间窗用毫秒时间戳（`alarmraisedtime.start/end`），站点时区 Atlantic/Reykjavik（UTC+0）
- 登录复用 `eflow_api_client.ensure_login()`；需要 `forgerydefense` token 头
- 单次请求偶发 `read timed out`，`_http_request` 内部会重试，无需额外处理

---

## 相关

- 业务规则：[掉站工单派单归属判定规则](../../../00_操作篇_Operations/02_告警与故障_Alarm/掉站工单派单归属判定规则.md)
- 工具源码：`tools/inspect_tt.py`
- 数据字典：[eflow_tt 字段字典](../13_数据字典_DataDictionary/eflow_tt_字段字典.md)
  ⚠️ 注意：那份字典基于 `eflow.sqlite3`（原始库，列名为 `WO No.` 等），
  与 app.db 的字段名（`tt_no`、`snake_case`）不同。

## 变更记录

- 2026-09-01 如意 初稿（基于 TT202608220047 实际核查）
