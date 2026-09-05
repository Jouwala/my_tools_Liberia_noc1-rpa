# Knowledge Base Index

> All entries are registered here by category. **You must add a line here after adding a new entry**, otherwise the AI will miss it during lookup.
> Format: `- [entry title](relative path) — one-line summary · status`

---

## 📊 Fill Progress

| Category | Entries so far | Target |
|---|---|---|
| Operations · Work Order Mgmt | 0 | 8 |
| Operations · Alarms & Faults | 1 | 6 |
| Operations · Sites & Assets | 0 | 3 |
| Operations · Accounts & Permissions | 0 | 3 |
| Operations · Error Quick Reference | 0 | 5 |
| Integration · Architecture & Data Flow | 0 | 2 |
| Integration · API Interfaces | 0 | 4 |
| Integration · Data Dictionary | 2 | 7 |
| Integration · Sync Tasks | 0 | 4 |
| Integration · Troubleshooting & Ops | 1 | 3 |
| **Total** | **4** | **45** |

> Suggest filling the 🔴-marked questions in [99_待补充问题_BACKLOG.md](99_待补充问题_BACKLOG.md) first.

---

## 00 Operations (for NOC front-line ops)

### 01 Work Order Mgmt TT / WO / CR / PM

- _(no entries yet)_

> Suggest writing first: TT status enum and transition rules, relationship between TT and WO, whether suspended orders count toward timeout, P1-P4 severity determination rules

### 02 Alarms & Faults

- [Dispatch (派单) attribution rules for site-down tickets](00_操作篇_Operations/02_告警与故障_Alarm/掉站工单派单归属判定规则.md) — **who it is dispatched to is decided by root cause, not by CSD/PSD**; the 4h delay is built into the rule; includes full timeline of TT202608220047 · verified

> Suggest continuing: how alarms auto-trigger TTs, mapping between alarm level and ticket severity, troubleshooting alarms not displaying

### 03 Sites & Assets

- _(no entries yet)_

> Suggest writing first: how sites relate to work orders, difference between Site ID and Site Name, site maintainer lookup

### 04 Accounts & Permissions

- _(no entries yet)_

> Suggest writing first: account application process, roles and operable scope, login-failure handling

### 05 Error Quick Reference

- _(no entries yet)_

> One error per file, title uses the verbatim error text

---

## 10 Integration (for dev / integration)

### 11 Architecture & Data Flow

- _(no entries yet)_

> Can be extracted from `my_app/backend/services/eFlow_API集成方案.md`

### 12 API Interfaces

- _(no entries yet)_

> Suggest writing first: login auth (OAuth2 + RSA), 7 data pipelines, rule query interface

### 13 Data Dictionary

- [00 Index (data dictionary master table)](10_集成篇_Integration/13_数据字典_DataDictionary/00_索引.md) — column/row overview of 8 tables · verified
- [eflow_tt field dictionary](10_集成篇_Integration/13_数据字典_DataDictionary/eflow_tt_字段字典.md) — 161-column field list + value distribution of 33 enum columns (Status/Severity/SLA, etc.) · verified
- [person field dictionary](10_集成篇_Integration/13_数据字典_DataDictionary/person_字段字典.md) — 36 columns, personal-info columns masked · verified

> The other 6 tables can be generated in one click: `python tools/gen_datadict.py`
> ⚠️ The "business meaning" column of generated entries is still empty and **needs manual completion**

### 14 Sync Tasks

- _(no entries yet)_

> Suggest writing first: scheduled sync trigger time, field mapping rules (Network Type → domain), write mode

### 15 Troubleshooting & Ops

- [How to verify the dispatch (派单) basis of a TT work order](10_集成篇_Integration/15_排障与运维_Troubleshooting/如何核查一张TT工单的派单依据.md) — SQL + `tools/inspect_tt.py`; queries use app.db, not eflow.sqlite3 · verified

> Suggest continuing: sync-failure troubleshooting, abnormal row-count troubleshooting, API timeout handling

---

## Others

- [90 Glossary](90_术语表_Glossary.md) — abbreviations and business terms, some to be confirmed
- [99 Backlog of Questions to Fill](99_待补充问题_BACKLOG.md) — pool of questions without answers yet

---

## Index Line Format Example

Copy the format below when adding a new entry:

```markdown
- [TT work order status transitions and enum values](00_操作篇_Operations/01_工单管理_TT_WO_CR_PM/TT工单_状态流转与枚举值.md) — meaning and transition rules of 6 statuses, Pending does not count toward timeout · verified
```

The `状态` comes from the entry's front-matter, so the user can see at a glance whether it is trustworthy.
