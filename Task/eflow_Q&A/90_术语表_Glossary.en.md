---
标题: eFlow Glossary of Terms and Abbreviations
状态: 部分待验证
最后更新: 2026-09-01
作者: 如意
来源: Code reading + database reading
---

# eFlow Glossary of Terms and Abbreviations

> In two parts: **Confirmed** (backed by code/docs/data) and **Unconfirmed** (inferred only from field names, unverified).
> For unconfirmed terms, AI must prompt the user to verify before answering.

---

## I. Confirmed

| Abbrev. | Full Name | Meaning | Basis |
|---|---|---|---|
| **TT** | Trouble Ticket | Fault ticket. Created automatically or manually from an alarm; the core object of eFlow | `eFlow_API集成方案.md`; table `eflow_tt` |
| **WO** | Work Order | Work order, executed under a TT (table has a `TT NO.` link column) | `eFlow_API集成方案.md`; table `eflow_wo` |
| **CR** | Change Request | Change request form | `eFlow_API集成方案.md`; table `eflow_cr` |
| **PM** | Preventive Maintenance | Preventive maintenance, i.e. inspection tasks | `eFlow_API集成方案.md`; table `eflow_pm` |
| **P1–P4** | Ticket Severity | Ticket severity level, P1 most severe | `eflow_rules/README` → `Ticket Severity (P1-P4)` |
| **ttLevelRule** | — | TT severity-rule type, a rule category in the eFlow config center | `eflow_rules_README.md` |
| **autoCreateTT** | — | One of the rule trigger steps; an alarm auto-creates a TT | `eflow_rules_README.md` |
| **NOC** | Network Operations Center | Network operations center | General |
| **SLA** | Service Level Agreement | Service level agreement | General |
| **CSD** | Complete Site Down | **Complete site down**. Appears in alarm name `sub_alarm_name`, e.g. `Complete site down (CSD)` | 14,292 tickets in DB carry this tag |
| **PSD** | Partial Site Down | **Partial site down**. Same as above, appears in alarm name | 2,882 tickets in DB |
| **G:3rd_Power** | — | Third-party power processing group, one value of the dispatch (派单) owner field `last_processer_group` | 73.1% of POWER-root-cause tickets dispatched here |
| **G:ZTE_NOC_FO** | — | ZTE self-maintained frontline field group (FO = Field Operation?) | FO full name unconfirmed |
| **TRM** | Transmission? | One value of `alarm_reason_type` | ⚠️ Inferred, unconfirmed |
| **Assign Delay** | — | eFlow history-alarm field: built-in delay of the dispatch rule (seconds). SITEOUTAGE rules = **14400s = 4 hours**, i.e. wait 4h after alarm for self-recovery before auto-dispatch | `Assign Start Time = alarm_occur_time + Delay` matches to the second |
| **SITEOUTAGE_REGULAR_COOL** | — | Auto-dispatch rule name. SITEOUTAGE=site-down type, REGULAR=regular site (Site Attribute), COOL=cooling type of site power (site_type) | Full value set of each dimension unconfirmed |
| **Assign-Append** | — | Dispatch type: after an alarm occurs, **append** to an existing TT per the delay rule. Later alarms (e.g. 3G) get appended into the earlier TT, causing `impacted_service`/`sub_alarm_name` on the TT to differ from the real state at dispatch time | Verified by TT202608220047 |

> ⚠️ **CSD does NOT mean "all standards down"**: the DB does contain alarms marked CSD that only dropped 2G+4G (3G normal).
> CSD/PSD are judged by the **upstream NMS UFM** and sent along with the alarm name; eFlow only receives them, it does not judge them.

---

## II. Unconfirmed ⚠️

> The following terms are **inferred only from database field names; no authoritative definition found**. Verify with a colleague familiar with eFlow before use; once verified, move them up to Part I.

| Abbrev. / Field | Inferred Meaning | Appears In | Notes |
|---|---|---|---|
| **MOC** | Managed Object Class? | `eflow_wo` | Could also mean maintenance-object category, needs confirmation |
| **PMP No.** | PM Plan number? | `eflow_pm` | Relationship with `PMT NO.` unclear |
| **PMT NO.** | PM Task number? | `eflow_pm` | Guessed to be inspection task number |
| **fdn** | Full Distinguished Name | `site` | Common in NMS; the fully-qualified network-element identifier |
| **Commune** | Village/community | `site` | Site address hierarchy: Region > Province > District > Commune |
| **GS Type** | ? | `site` | Possibly GSM Site Type, unconfirmed |
| **TRM Type** | Transmission Type? | `site` | Whether synonymous with `Transmission Type` unconfirmed |
| **Vender** | Vendor | `eflow_wo` | ⚠️ Note: spelled **Vender** not Vendor in DB, don't misspell in SQL |
| **restypename** | Resource type name | `realtime_alarm` / `history_alarm` | |
| **MW Layer** | Microwave layer | `realtime_alarm` / `site` | MW = Microwave |
| **RAN Site Type** | Radio access network site type | `realtime_alarm` | |
| **MOC / MOP** | ? | — | If MOP (Method of Procedure) appears, it refers to the change-operation procedure document |

---

## III. An Easily-Confused Pair

| | TT | WO |
|---|---|---|
| What it is | Fault ticket (one fault) | Work order (one job) |
| Relationship | Parent | Child, linked via `WO.TT NO.` |
| Order of magnitude | ~28k rows | ~10k rows |
| Typical scenario | Base station down → create TT | TT dispatched to field → create WO |

> Data source: `D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3`, read on 2026-09-01.

---

## IV. Supplementary Terms

To add a term, append it to the relevant table and state the source in the "Basis" column.
Turning "Unconfirmed" into "Confirmed" is the highest-value contribution — **this costs you 2 minutes but saves everyone after you 20.**
