# Contribution Guide

Spend 2 minutes reading this before writing a knowledge-base entry. The goal is that **anyone (including AI) who finds it can use it directly**.

---

## 1. What Is Worth Writing as an Entry

Before writing, ask: **will this question be asked a second time?**

✅ Should write:
- A question someone has asked more than once
- An operation with pitfalls or hidden prerequisites ("you must configure X first, otherwise Y won't take effect")
- An error message that isn't intuitive and takes long to guess
- A business rule known by only a few (e.g., "suspended orders don't count toward timeout")

❌ Don't write:
- Button descriptions you can see just by opening the eflow UI
- One-off temporary handling records (put those in the work-order notes)
- Unverified guesses (if you must write, mark `状态: 待验证`)

---

## 2. Writing Steps

1. Decide the type → copy the matching template from `_templates/`
2. Put it in the right category directory (wrong placement is worse than not writing — see the directory map below)
3. Fill in per the template, **deleting the template's hint text**
4. Add an index line in [INDEX.md](INDEX.md)
5. If it came from the BACKLOG, strike the matching item in [99_待补充问题_BACKLOG.md](99_待补充问题_BACKLOG.md) and link to the new entry

### Directory map

| Your content | Put it here |
|---|---|
| Create/modify/close a work order in the eflow UI, status transitions | `00_操作篇_Operations/01_工单管理_TT_WO_CR_PM/` |
| How to view/confirm/dispatch (派单) alarms | `00_操作篇_Operations/02_告警与故障_Alarm/` |
| Site info query, maintainer, attribution | `00_操作篇_Operations/03_站点与资产_Site/` |
| Login, permissions, account application, roles | `00_操作篇_Operations/04_账号与权限_Account/` |
| Quick reference for UI errors (one error per file) | `00_操作篇_Operations/05_常见报错速查_Errors/` |
| How the system is built, how data flows | `10_集成篇_Integration/11_架构与数据流_Architecture/` |
| How to call interfaces, params, returns | `10_集成篇_Integration/12_API接口_API/` |
| Table/field meaning, enum values | `10_集成篇_Integration/13_数据字典_DataDictionary/` |
| Scheduled sync, field mapping, task config | `10_集成篇_Integration/14_同步任务_Sync/` |
| Sync-failure, wrong-data troubleshooting | `10_集成篇_Integration/15_排障与运维_Troubleshooting/` |
| Abbreviations, term explanations | `90_术语表_Glossary.md` (append, don't create a new file) |

---

## 3. File Naming

```
<object>_<action or question>.md
```

- Use **Chinese + underscores**, no spaces (spaces are troublesome on the command line)
- The name should hint at the content; avoid "说明.md", "问题1.md"

✅ Good examples:
- `TT工单_状态流转与枚举值.md`
- `告警_实时告警不显示排查.md`
- `同步任务_eflow_tt字段映射.md`

❌ Bad examples:
- `新建 Microsoft Word 文档.md`
- `问题.md`
- `temp.md`

---

## 4. YAML front-matter Spec

Every entry must start with this block (already included in the templates):

```yaml
---
标题: What are the TT work order statuses and what do they mean
分类: 00_操作篇_Operations/01_工单管理_TT_WO_CR_PM
标签: [TT, work order status, enum value]
状态: 已验证          # 已验证 / 待验证 / 已过时
适用对象: 运维        # 运维 / 开发 / 全部
最后更新: 2026-09-01
作者: 如意
来源: 实际操作确认    # 实际操作确认 / 代码读取 / 文档摘录 / 他人转述
---
```

### The `状态` field is mandatory

| Value | Meaning | AI handling when answering |
|---|---|---|
| `已验证` | confirmed by personal operation / DB query | can be used directly as the answer |
| `待验证` | heard or inferred, not verified | **must warn the user "this entry is unverified"** |
| `已过时` | obsolete after a system redesign, kept for reference | **must not be used as the answer**, reference only |

### The `来源` field determines credibility

Priority: **实际操作确认 > 代码读取 > 文档摘录 > 他人转述**

> ⚠️ Iron law of this project: **do not write from memory**.
> A claim like "this function uploads to FTP" must have a real grep'd call site before you write it.
> Conclusions inferred from constant definitions have already backfired twice.

---

## 5. Body Writing Requirements

### 1. Conclusion first

Give the answer in the first sentence, no buildup. Ops colleagues come with a question in hand.

```markdown
❌ eFlow's TT work order system is a system for managing fault tickets, and its status
   transition mechanism is rather complex, involving multiple stages and roles. Let's
   introduce it in detail below…

✅ TT work orders have 6 statuses: Open / In Progress / Pending / Resolved / Closed / Cancelled.
   Among them, **Pending (suspended) does not count toward timeout assessment**.
```

### 2. Give copyable things

- Commands, SQL, params → use code blocks, ensure they run when copied directly
- UI operations → write clearly "which menu → which button", don't just say "configure in settings"
- Errors → quote verbatim, don't paraphrase

### 3. Mark uncertainty

Where unsure, write "to be confirmed" directly, don't gloss over it:

```markdown
> ⚠️ To be confirmed: whether Pending counts toward SLA, needs to check with XX.
```

### 4. Screenshots

Put images in the same directory, reference with a relative path:

```markdown
![TT status transition](./images/TT状态流转.png)
```

---

## 6. Updating an Existing Entry

When changing someone else's entry:
- Update `最后更新` and `作者`
- If the content changed a lot, add a "Change Log" at the end:

```markdown
## Change Log
- 2026-09-01 如意 initial draft
- 2026-09-15 张三 added the rule that Pending doesn't count toward timeout (confirmed by XX)
```

---

## 7. Minimum Viable Entry

No time to write a full one? **3 lines is better than nothing**:

```markdown
---
标题: What to do about XXX error
状态: 已验证
最后更新: 2026-09-01
作者: 如意
---

## Symptom
XXX

## Fix
Just restart the YYY service.

## Note
Root cause not investigated; record the fix first.
```

Someone will expand it with the root cause later. **An empty document is the knowledge base's worst enemy.**
