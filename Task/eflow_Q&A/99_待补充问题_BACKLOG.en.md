# Backlog of Open Questions

> A pool of unanswered questions. **Anyone can add a question**, and you're welcome to claim one and flesh it out into an entry.
> After answering: ① cross it off this table ② add an index line in [INDEX.md](INDEX.md).

## Legend

- 🔴 High frequency / high impact — fill in first
- 🟡 Medium
- 🟢 Low frequency / nice-to-have
- 🤖 **Marked as draftable by AI from code/database** (just tell the AI "fill BACKLOG item X")

---

## Operations (Ops Perspective)

### Ticket Management

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 1 | What statuses does a TT ticket have? What does each mean? How do they transition? | 🔴 🤖 | | To fill |
| 2 | What is the relationship between TT and WO? When should a WO be created? | 🔴 | | To fill |
| 3 | How is ticket severity P1–P4 determined? | 🔴 🤖 | | To fill (rule engine already implemented) |
| 4 | After a ticket is suspended, does it still count as overtime (SLA breach)? | 🔴 | | **Awaiting business confirmation**, only humans know the definition |
| 5 | What is the full flow of dispatching (派单) to the field? | 🔴 | | To fill |
| 6 | Can a closed ticket be reopened? How? | 🟡 | | To fill |
| 7 | How to query all historical tickets under a given site? | 🟡 🤖 | | To fill |
| 8 | How to fill `Alarm Category` / `Alarm Sub Category` in a TT ticket? | 🟡 | | To fill |

### Alarms & Faults

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 9 | How does an alarm become a TT? Fully automatic or needs manual confirmation? | 🔴 | | To fill |
| 10 | How do alarm levels map to ticket severity? | 🔴 🤖 | | To fill |
| 11 | Real-time alarm page shows nothing / empty data — how to troubleshoot? | 🟡 | | To fill |
| 12 | Alarm cleared but ticket not auto-closed — is that normal? | 🟡 | | To fill |
| 42 | Who gets the site-down ticket — decided by CSD/PSD or by root cause? | 🔴 🤖 | 如意 | ✅ **Done** (see Operations 02, with TT202608220047 case) |
| 43 | **Where is the authoritative config of eFlow dispatch (派单) rules?** Plain-text basis for the reference time point (alarm time vs dispatch time) | 🔴 | 如意 | 🔶 Mostly solved: eFlow history-alarm field `Assign Delay=14400s` + `Assign RuleName=SITEOUTAGE_REGULAR_COOL` prove "alarm + 4h auto-dispatch"; the full definition in the rule config center is still to be found |
| 44 | Among `root_cause=POWER` tickets, what splits the other 27% that weren't sent to the third party? | 🟡 🤖 | | To fill (may relate to REGULAR/COOL/site-attribute dimensions) |

### Sites & Assets

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 13 | What is the difference between Site ID and Site Name? Which to use? | 🟡 🤖 | | To fill |
| 14 | How to look up site ownership (region / maintainer / outsourced maintenance)? | 🟡 | | To fill |
| 15 | Site info is wrong — who fixes it, and where? | 🟡 | | To fill |

### Accounts & Permissions

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 16 | How to apply for an eFlow account? Who approves? | 🔴 | | **To be filled by hand**, process questions must be asked of humans |
| 17 | What roles exist? What can each do? | 🟡 | | To fill |
| 18 | Login failed / account locked — what to do? | 🟡 | | To fill |

### Error Quick Reference

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 19 | Creating a ticket shows "template does not exist" | 🟢 | | To fill (note when encountered) |
| 20 | Cannot select a person when dispatching (派单) | 🟢 | | To fill (note when encountered) |

---

## Integration (Dev Perspective)

### Architecture & Data Flow

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 21 | What is the overall architecture? How does data flow from eFlow to app.db? | 🔴 🤖 | | To fill (`eFlow_API集成方案.md` has material) |
| 22 | What environment variables are configurable? What are the defaults? | 🟡 🤖 | | To fill |

### API Interfaces

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 23 | How is login/auth done? (OAuth2 + RSA flow) | 🔴 🤖 | | To fill |
| 24 | What are the 7 data pipelines? What is the return structure? | 🔴 🤖 | | To fill |
| 25 | How to call the rule query interface? (query / detail) | 🟡 🤖 | | To fill (`eflow_rules_README.md` exists) |
| 26 | What is the interface timeout / reconnect mechanism? | 🟡 🤖 | | To fill |

### Data Dictionary

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 27 | `eflow_tt` field dictionary (161 columns) | 🔴 🤖 | AI | ✅ Generated, business meaning to be filled |
| 28 | `eflow_wo` field dictionary (168 columns) | 🔴 🤖 | | To fill (auto-generatable) |
| 29 | `eflow_cr` field dictionary (57 columns) | 🟡 🤖 | | To fill (auto-generatable) |
| 30 | `eflow_pm` field dictionary (47 columns) | 🟡 🤖 | | To fill (auto-generatable) |
| 31 | `site` field dictionary (44 columns) | 🟡 🤖 | | To fill (auto-generatable) |
| 32 | `person` field dictionary (36 columns) | 🟢 🤖 | AI | ✅ Generated (anonymized), business meaning to be filled |
| 33 | Alarm-table field dictionary (36 columns) | 🟡 🤖 | | To fill (auto-generatable) |
| 34 | Enum values of key fields (Status / Ticket Severity / domain etc.) | 🔴 🤖 | | To fill (SQL statistics possible) |

> #27–34 can be auto-generated in one pass: see `tools/` instructions, or just let the AI run it.

### Sync Tasks

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 35 | When does the scheduled sync run? How to trigger manually? | 🔴 🤖 | | To fill |
| 36 | What are the field mapping rules? (e.g. `Network Type` → `domain`) | 🔴 🤖 | | To fill |
| 37 | Is the write mode incremental or full replace? | 🔴 🤖 | | To fill |
| 38 | How to add a new data pipeline? | 🟢 🤖 | | To fill |

### Troubleshooting

| # | Question | Priority | Claimant | Status |
|---|---|---|---|---|
| 39 | How to troubleshoot a failed sync task? | 🔴 | | To fill |
| 40 | After sync, row count is abnormal (sharp drop / no growth) — how to check? | 🔴 | | To fill |
| 41 | API returns 401 / auth expired — how to handle? | 🟡 | | To fill |

---

## How to Add a New Question

Simply append a row under the relevant table:

```markdown
| 42 | Your question? | 🟡 | Your name | To fill |
```

**Don't just ask in WeChat and leave it at that.** A question asked once deserves to be findable by the next person.
