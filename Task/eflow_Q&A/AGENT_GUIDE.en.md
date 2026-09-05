# AI Retrieval Guide

> This file is for the AI (WorkBuddy / OpenClaw / other agents).
> Before answering any eflow-related question, follow this flow first — **do not answer from training memory**.

---

## 1. Retrieval Flow

```
1. Read INDEX.md          → judge whether there is a matching entry
2. Hit → read the full entry → check the 状态/来源 in front-matter
3. Miss → full-text search keywords with tools/search.py
4. Still nothing → verify against source code / database (see section 4), and suggest the user add it to the knowledge base
5. Cite the reference path when answering
```

### Quick commands

```bash
# Search the whole library (shows hit-line context by default)
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "keyword"

# Limit to a directory
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "工单 挂起" --dir 00_操作篇_Operations

# List file names only
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "P1" --name-only
```

---

## 2. Hard Constraints When Answering

### 1. Must cite sources

```markdown
Per `00_操作篇_Operations/01_工单管理_TT_WO_CR_PM/TT工单_状态流转.md`:
TT suspension does not count toward timeout…
```

If you can't find it, say so and suggest adding it to `99_待补充问题_BACKLOG.md`. **Better to say you don't know than to make things up.**

### 2. Adjust wording by the `状态` field

| front-matter status | How you should say it |
|---|---|
| `已验证` | State it directly |
| `待验证` | "This is in the knowledge base, but **marked unverified**; suggest verifying: …" |
| `已过时` | "There is an **outdated** record in the knowledge base (for reference only, may no longer apply): …" |

### 3. Mark credibility by `来源`

`实际操作确认` > `代码读取` > `文档摘录` > `他人转述`.
For content marked `他人转述`, remind the user to verify.

### 4. Distinguish the reader

For the same question, the answer differs by who asks:

- Ops asks "work order status" → answer UI operations and business meaning (Operations)
- Dev asks "work order status" → answer field enum values and SQL query method (Integration)

When unsure of the person's role, **give the Operations answer first, then add one Integration note**.

---

## 3. Answer Template

```markdown
## Conclusion
<one-line answer>

## Explanation
<expand, quoting the knowledge base verbatim>

## Source
- Knowledge base: `path/file.md` (status: verified, last updated 2026-09-01)
- For further confirmation: <source file or database table>

---
💡 This answer is / is not yet captured in the knowledge base; suggest adding it.
```

---

## 4. Where to Verify When the Knowledge Base Has No Coverage

Check in order; once found, write it into the knowledge base:

### 1. Business field meaning, enum values

```bash
# Read the eflow raw DB directly
python -c "
import sqlite3
c = sqlite3.connect(r'D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3')
print([r[1] for r in c.execute('PRAGMA table_info(\"eflow_tt\")')])
print(c.execute('SELECT Status, COUNT(*) FROM eflow_tt GROUP BY Status').fetchall())
"
```

### 2. Sync logic, field mapping

- `D:\01_RPA\Task\my_app\backend\services\sync_from_eflow_api.py`
- `D:\01_RPA\Task\my_app\backend\services\eflow_api_client.py`

### 3. Architecture & data flow

- `D:\01_RPA\Task\my_app\backend\services\eFlow_API集成方案.md`

### 4. Severity rules

- `D:\01_RPA\Task\my_app\backend\services\eflow_rules\`
- Rule details: `eflow_TT_rules.xlsx`

### 5. Alarms

- `D:\01_RPA\Task\my_app\backend\services\eflow_alarm_service.py`
- Config: `eflow_alarm_config.json`

---

## 5. ⚠️ Iron Law of Verification (hard lessons from this project)

Before writing a statement like "function X does Y" or "field Y is Z", **you must check the real call site / real data**:

- ❌ Inferring behavior from a constant definition (e.g., seeing `FTP_UPLOAD_REMOTE_DIR` and writing "the sync function uploads to FTP" — in reality it operates fully in memory and never uploads)
- ❌ Judging a function as dead code just because grep found its name (it may be called via dynamic registration through `import_module`)
- ❌ Using `py_compile` / static inference instead of real runtime verification

**Correct approach**:
1. For each declared function, grep the whole repo for its call sites
2. For each external-action claim (upload / write DB / send email), grep the real calls (`storbinary`, `write_data`, `send_mail`)
3. For each field name / DB name, grep `DB_NAME` / the actual connection string for the real value

**Every fact written into the knowledge base must point to the exact file and line where it lives.**

---

## 6. Things to Do After Answering

If this question's answer is **not** in the knowledge base:

1. Tell the user "this one is worth capturing"
2. Ask whether you should generate the entry directly from a template
3. User agrees → pick a template from `_templates/` → write into the right directory → update `INDEX.md`

The knowledge base grows from each Q&A, not from being written all at once.
