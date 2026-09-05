# eFlow Knowledge Base

> A team Q&A knowledge base for eFlow (ZTE operations work-order system).
> Goal: explain each question only once; the answers live here so both humans and AI can find them.

- **Location**: `D:\01_RPA\Task\eflow_Q&A`
- **Form**: A Markdown document library; AI reads the directory directly to answer; you can also use `tools/search.py` for full-text search
- **Created**: 2026-09-01

---

## 1. How to Use This Knowledge Base

### Asking a question (human)

1. First check [INDEX.md](INDEX.md) for a matching entry
2. If none, register it in [99_待补充问题_BACKLOG.md](99_待补充问题_BACKLOG.md) — don't just ask verbally and leave
3. After getting an answer, write it as a proper entry per [CONTRIBUTING.md](CONTRIBUTING.md) and strike it off the BACKLOG

### Asking a question (AI / me / OpenClaw)

Just say "query the eflow knowledge base: \<question\>". The AI reads this directory following the lookup order in [AGENT_GUIDE.md](AGENT_GUIDE.md) and answers.
**The AI must cite the file path of its source.** If nothing is found, say so plainly — do not make things up from memory.

### Command-line full-text search

```bash
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "工单 挂起"     # spaces auto-split into two words, OR
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "工单 挂起" --all  # AND: both words must be present
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "sync" --dir 10_集成篇_Integration
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "P1" --context 3
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "派单 三方" --phrase  # search as a complete phrase
```

> Note: multiple words default to **OR** (any hit); `--all` is **AND**, matched at the **file level**
> (a file hits if it contains all the words, not necessarily on the same line). A single argument with spaces is auto-split.

### Checking the dispatch (派单) basis of a work order

```bash
python "D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py" TT202608220047
```

**Easier: analyze directly in the my_app page** — open
`http://localhost/myapp/?page=eflow_qa`, enter the ticket number in the "TT quick analysis" box on the left and click "Analyze",
and a graphical report appears (key conclusions / alarm→dispatch time gap / CSD-PSD mapping / root-cause attribution distribution / work-order fields).
The page calls `GET /api/eflow-qa/inspect-tt?tt=<ticket>`, sharing the same `analyze_tt()` logic inside `inspect_tt.py` with the CLI, so changes take effect on both sides.

---

## 2. Directory Structure

```
eflow_Q&A/
├── README.md              this file: what this is, how to use it
├── INDEX.md               full index (category → entry → one-line summary)
├── CONTRIBUTING.md        contribution guide: how to write an entry, naming, status markers
├── AGENT_GUIDE.md         retrieval guide for AI (follow first when answering)
│
├── _templates/            copy from here when writing a new entry
│   ├── TEMPLATE_faq.md              Q&A style (one specific question)
│   ├── TEMPLATE_howto.md            how-to style (steps to complete a task)
│   └── TEMPLATE_troubleshooting.md  troubleshooting style (symptom → cause → fix)
│
├── 00_操作篇_Operations/  ← for NOC front-line ops: how to operate in the eflow UI
│   ├── 01_工单管理_TT_WO_CR_PM/
│   ├── 02_告警与故障_Alarm/
│   ├── 03_站点与资产_Site/
│   ├── 04_账号与权限_Account/
│   └── 05_常见报错速查_Errors/
│
├── 10_集成篇_Integration/ ← for dev/integration: API, table schema, sync tasks
│   ├── 11_架构与数据流_Architecture/
│   ├── 12_API接口_API/
│   ├── 13_数据字典_DataDictionary/
│   ├── 14_同步任务_Sync/
│   └── 15_排障与运维_Troubleshooting/
│
├── 90_术语表_Glossary.md        abbreviations and business terms (TT/WO/CR/PM/MOC/PMP…)
├── 99_待补充问题_BACKLOG.md     pool of questions still without answers
│
└── tools/
    └── search.py                full-text search script
```

**Layering rule**: the same topic is written in two layers that do not replace each other —

| | Operations (ops) | Integration (dev) |
|---|---|---|
| Answer | where to click in the eflow UI | which API to call, which table to query |
| Language | steps + screenshots + plain words | code + SQL + field names |
| Example | "how to suspend a work order" | "what are the enum values of eflow_tt.Status" |

---

## 3. eFlow Business Objects at a Glance

eFlow manages the full lifecycle of operations work orders, with 7 core object types:

| Abbrev | Full name | One-liner | Volume (my_app side) |
|---|---|---|---|
| **TT** | Trouble Ticket | fault ticket, auto-created from alarms or manually | 161 cols / ~28k rows |
| **WO** | Work Order | job order, executed under a TT | 168 cols / ~10k rows |
| **CR** | Change Request | change request form | 57 cols / ~205 rows |
| **PM** | Preventive Maintenance | preventive inspection task | 47 cols / ~1632 rows |
| **Site** | site master data | site / area / lat-lng / maintainer | 44 cols / 808 rows |
| **Person** | personnel | handler, contact | 36 cols / 133 rows |
| **Alarm** | alarm | real-time + historical alarms | 36 cols |

> Volume source: `D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3`, read on 2026-09-01.
> For detailed fields, see [13_数据字典_DataDictionary](10_集成篇_Integration/13_数据字典_DataDictionary).

---

## 4. Related System Locations

| Purpose | Path |
|---|---|
| eFlow API client | `D:\01_RPA\Task\my_app\backend\services\eflow_api_client.py` |
| Sync service | `D:\01_RPA\Task\my_app\backend\services\sync_from_eflow_api.py` |
| Integration design doc | `D:\01_RPA\Task\my_app\backend\services\eFlow_API集成方案.md` |
| TT severity rule engine | `D:\01_RPA\Task\my_app\backend\services\eflow_rules\` |
| Alarm service | `D:\01_RPA\Task\my_app\backend\services\eflow_alarm_service.py` |
| eFlow raw DB | `D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3` |
| Early login script | `D:\01_RPA\Task\eflow_python\eflow_login.py.txt` |

---

## 5. Current Status

- [x] Directory skeleton + templates + search tools
- [ ] Content fill — see [99_待补充问题_BACKLOG.md](99_待补充问题_BACKLOG.md), claim by priority

**The value of this knowledge base depends on the number of entries, not on how pretty the directory looks. Write 20 entries first.**
