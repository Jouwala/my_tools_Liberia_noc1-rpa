---
标题: How to Verify the Dispatch Basis of a TT Ticket
分类: 10_集成篇_Integration/15_排障与运维_Troubleshooting
标签: [排障, 派单, SQL, eflow_tt, 工具]
状态: 已验证
适用对象: 开发
最后更新: 2026-09-01
作者: 如意
来源: Verified by actual operation
---

# How to Verify the Dispatch Basis of a TT Ticket

## One-liner

When someone complains "ticket XX was mis-dispatched", use `tools/inspect_tt.py` for a one-click report; to check manually, use the SQL below.

## Using the Tool (recommended)

```bash
python "D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py" TT202608220047
python "D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py" TT202608220047 --json   # machine-readable
```

Output includes: site / timeline / alarms / per-standard site-down distribution / root cause / dispatch group / alarm-to-dispatch time gap /
whole-DB dispatch distribution for that root cause / CSD vs PSD comparison.

If the ticket number is incomplete, a fuzzy fallback lists similar numbers.

---

## Data Source Location

| Item | Value |
|---|---|
| DB | `D:\01_RPA\Task\my_app\db\app.db` |
| Table | `eflow_tt` |
| Ticket-no. column | **`tt_no`** |
| Column count | 161 |

> ⚠️ **NOT** `data\eflow\eflow.sqlite3`. That raw export has no `tt_no` column,
> the ticket number there is called `WO No.`, and its data is not synced with app.db. **Use app.db for tickets.**

---

## Manual SQL

### 1. Pull key fields of one ticket

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

### 2. Compute the alarm-to-dispatch delay

```sql
SELECT tt_no,
       alarm_occur_time,
       created_time,
       ROUND((julianday(created_time) - julianday(alarm_occur_time)) * 24, 2) AS lag_hours
FROM eflow_tt
WHERE tt_no = 'TT202608220047';
```

### 3. Dispatch-ownership distribution for a root cause (judge if this dispatch is normal)

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

### 4. CSD vs PSD third-party share (prove site-down type doesn't decide ownership)

```sql
SELECT SUM(sub_alarm_name LIKE '%CSD%')                                   AS csd_all,
       SUM(sub_alarm_name LIKE '%CSD%' AND last_processer_group LIKE '%3rd_Power%') AS csd_3rd,
       SUM(sub_alarm_name LIKE '%PSD%')                                   AS psd_all,
       SUM(sub_alarm_name LIKE '%PSD%' AND last_processer_group LIKE '%3rd_Power%') AS psd_3rd
FROM eflow_tt;
```

Current result: `csd_3rd/csd_all = 57.4%`, `psd_3rd/psd_all = 57.3%` — essentially no difference.

### 5. Dispatch tendency per root cause

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

## Field Notes

| Field | Purpose | Note |
|---|---|---|
| `tt_no` | TT ticket number | Primary-key-style query column |
| `alarm_occur_time` | **Alarm occurrence time** | Dispatch decision reference point |
| `created_time` | TT creation / dispatch time | May be hours later than the alarm |
| `root_cause` | **Root cause** | Main factor deciding dispatch ownership |
| `sub_root_cause` | Root-cause subcategory | e.g. `Power Solar` |
| `sub_alarm_name` | Alarm-name list | Contains `CSD` / `PSD` tags |
| `col_Ng_down_site_count` | Per-standard down-site count | ⚠️ **Empty for many tickets**, cannot be used as decision basis |
| `last_processer_group` | Dispatched processing group | Multi-value, semicolon-separated and **with newlines**; clean with `REPLACE` before aggregating |
| `impacted_service` | Affected standards | e.g. `2G,3G` |

### Two Pitfalls

1. **`last_processer_group` contains newlines**: a direct `GROUP BY` splits many groups that look the same but differ.
   Clean first with `REPLACE(REPLACE(col, char(10), ''), char(13), '')`.
2. **`col_*_down_site_count` is a string type**, and many are empty string or 0.
   `CAST` or `int(float(v))` before numeric comparison, otherwise you'll get
   `TypeError: '>' not supported between str and int`.

---

## Correct Order for Judging Ownership

```
1. Look at root_cause        → POWER-class likely third party; RAN/MW/Fiber-class not third party
2. Look at alarm_occur_time  → reference time point (not created_time)
3. Look at CSD/PSD in sub_alarm_name → reference only, does not decide ownership
4. Query each standard's real alarm timeline → tools/eflow_hisalarm_by_tt.py (see next section)
```

---

## Querying History Alarms from eFlow (when local has none)

**Why local may lack them**: `app.db.history_alarm` only keeps the **most recent 48 hours** rolling
(`backend/services/eflow_alarm_config.json`'s `his_alarm_hours: 48`),
and sync discards records with empty/`-` TT ID. For earlier alarms you must connect directly to the eFlow API.

```bash
# Use system Python 3.12 (has pandas); the my_app venv does not
"C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe" ^
  "D:\01_RPA\Task\eflow_Q&A\tools\eflow_hisalarm_by_tt.py" TT202608220047
```

Principle: infer date from ticket number → POST `/api/fm-history/v1/hisalarms/pageinfo`,
`alarmraisedtime` specifies the time window → filter locally by `TT ID`. If the date can't be found, it auto-extends days forward.

Output in four parts:
1. Alarms hit under that ticket (incl. `Assign RuleName` / `Assign Delay` / dispatch time)
2. **All alarms of the same site** (to judge "were each standard down at dispatch time" — look here, not at the TT's
   `impacted_service`, which is a post-hoc Assign-Append summary, not the alarm-time state)
3. Pagination note: server's real per-page cap is 2000 (ignores requested size); tool auto-paginates by `totalcount`
4. Auto comparison of 3G alarm recovery time vs dispatch time point

### Field findings (TT202608220047, 2026-09-01)

- `Assign Delay = 14400s` is the **built-in delay** (4 hours) of dispatch rule `SITEOUTAGE_REGULAR_COOL`,
  `Assign Start Time = alarm_occur_time + 4h`, matching to the second — 4 hours is by design, not slow dispatch
- The site's 2G was down 6 days (02:27 → 8/28); 3G dropped **7 hours after** dispatch (13:31) and recovered next day 08:21
- The 3G alarm was appended into the existing TT via `Assign-Append` — that's the source of the TT's `impacted_service=2G,3G`
  and the `3G SITE DOWN` in `sub_alarm_name`

### Notes on Calling the API

- Server per-page cap is **2000** (even `size=5000` returns only 2000); pagination offset increments by **actual returned count**
- Time window uses millisecond timestamps (`alarmraisedtime.start/end`); site timezone Atlantic/Reykjavik (UTC+0)
- Login reuses `eflow_api_client.ensure_login()`; needs `forgerydefense` token header
- Occasional `read timed out` per request; `_http_request` retries internally, no extra handling needed

---

## Related

- Business rule: [Rules for Determining Site-Down Ticket Dispatch Ownership](../../../00_操作篇_Operations/02_告警与故障_Alarm/掉站工单派单归属判定规则.md)
- Tool source: `tools/inspect_tt.py`
- Data dictionary: [eflow_tt field dictionary](../13_数据字典_DataDictionary/eflow_tt_字段字典.md)
  ⚠️ Note: that dictionary is based on `eflow.sqlite3` (raw DB, column names like `WO No.`),
  and differs from app.db's field names (`tt_no`, `snake_case`).

## Change Log

- 2026-09-01 如意 Draft (based on actual verification of TT202608220047)
