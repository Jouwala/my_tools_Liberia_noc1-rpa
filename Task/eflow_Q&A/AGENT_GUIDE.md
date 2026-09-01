# AI 检索指引

> 本文件给 AI（WorkBuddy / OpenClaw / 其他 Agent）看。
> 回答任何 eflow 相关问题前，先按本流程检索，**不许凭训练记忆作答**。

---

## 一、检索流程

```
1. 读 INDEX.md          → 判断是否有对应条目
2. 命中 → 读该条目全文  → 检查 front-matter 的 状态/来源
3. 未命中 → 用 tools/search.py 全文本检索关键词
4. 仍无 → 去源码/数据库核实（见第四节），并建议用户补进知识库
5. 回答时给出引用路径
```

### 快速命令

```bash
# 全库检索（默认显示命中行上下文）
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "关键词"

# 限定目录
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "工单 挂起" --dir 00_操作篇_Operations

# 只列文件名
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "P1" --name-only
```

---

## 二、回答时的硬性约束

### 1. 必须给引用

```markdown
根据 `00_操作篇_Operations/01_工单管理_TT_WO_CR_PM/TT工单_状态流转.md`：
TT 挂起期间不计入超时…
```

查不到就说查不到，并建议补充到 `99_待补充问题_BACKLOG.md`。**宁可说不知道，不可编。**

### 2. 按 `状态` 字段调整措辞

| front-matter 状态 | 你该怎么说 |
|---|---|
| `已验证` | 直接陈述 |
| `待验证` | 「知识库里有这条，但**标注为未验证**，建议核实：…」 |
| `已过时` | 「知识库里有一条**已过时**的记录（仅供参考，可能已不适用）：…」 |

### 3. 按 `来源` 标注可信度

`实际操作确认` > `代码读取` > `文档摘录` > `他人转述`。
「他人转述」的内容要提醒用户核实。

### 4. 区分读者

同一个问题，问的人不同，答案不同：

- 运维问「工单状态」→ 答界面操作和业务含义（操作篇）
- 开发问「工单状态」→ 答字段枚举值和 SQL 查法（集成篇）

不确定对方身份时，**先给操作篇答案，再附一句集成篇补充**。

---

## 三、回答模板

```markdown
## 结论
<一句话答案>

## 说明
<展开，引用知识库原文>

## 来源
- 知识库：`路径/文件.md`（状态：已验证，最后更新 2026-09-01）
- 如需进一步确认：<源码文件 或 数据库表>

---
💡 这条答案已沉淀 / 未沉淀到知识库，建议补充。
```

---

## 四、知识库没覆盖时，去哪核实

按顺序查，查到就写进知识库：

### 1. 业务字段含义、枚举值

```bash
# 直接读 eflow 原始库
python -c "
import sqlite3
c = sqlite3.connect(r'D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3')
print([r[1] for r in c.execute('PRAGMA table_info(\"eflow_tt\")')])
print(c.execute('SELECT Status, COUNT(*) FROM eflow_tt GROUP BY Status').fetchall())
"
```

### 2. 同步逻辑、字段映射

- `D:\01_RPA\Task\my_app\backend\services\sync_from_eflow_api.py`
- `D:\01_RPA\Task\my_app\backend\services\eflow_api_client.py`

### 3. 架构与数据流

- `D:\01_RPA\Task\my_app\backend\services\eFlow_API集成方案.md`

### 4. 严重级别规则

- `D:\01_RPA\Task\my_app\backend\services\eflow_rules\`
- 规则明细：`eflow_TT_rules.xlsx`

### 5. 告警

- `D:\01_RPA\Task\my_app\backend\services\eflow_alarm_service.py`
- 配置：`eflow_alarm_config.json`

---

## 五、⚠️ 核实铁律（本项目血泪教训）

写「某函数会 X」「某字段是 Y」这类声明前，**必须查真实调用点/真实数据**：

- ❌ 由常量定义推断行为（例：看到 `FTP_UPLOAD_REMOTE_DIR` 就写「同步函数会上传 FTP」——实际全程内存操作，从不上传）
- ❌ grep 到函数名就判定死代码（可能通过 `import_module` 动态注册被调用）
- ❌ 用 `py_compile` / 静态推断代替真实运行验证

**正确做法**：
1. 对每个被声明的函数，全仓 grep 其调用点
2. 对每个外部动作声明（上传/写库/发邮件），grep 真实调用（`storbinary`、`write_data`、`send_mail`）
3. 每个字段名/库名，grep `DB_NAME` / 实际连接串取真实值

**写进知识库的每条事实，都要能指出它在哪个文件的哪一行。**

---

## 六、回答后顺手做的事

如果这次问题的答案**不在**知识库里：

1. 告诉用户「这条值得沉淀」
2. 询问是否要你直接按模板生成条目
3. 用户同意 → 从 `_templates/` 选模板 → 写入对应目录 → 更新 `INDEX.md`

知识库靠每次问答长出来，不靠一次性写完。
