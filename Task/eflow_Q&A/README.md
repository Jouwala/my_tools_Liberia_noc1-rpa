# eFlow 知识库

> eFlow（ZTE 运维工单系统）的团队问答知识库。
> 目标：同一个问题只解释一次，答案沉淀在这里，人和 AI 都能查到。

- **位置**：`D:\01_RPA\Task\eflow_Q&A`
- **形式**：Markdown 文档库，AI 直接读目录作答；也可用 `tools/search.py` 全文本检索
- **建立**：2026-09-01

---

## 一、怎么用这个知识库

### 想问问题（人）

1. 先看 [INDEX.md](INDEX.md) 有没有对应条目
2. 没有就在 [99_待补充问题_BACKLOG.md](99_待补充问题_BACKLOG.md) 登记，别口头问完就散了
3. 拿到答案后按 [CONTRIBUTING.md](CONTRIBUTING.md) 补成正条目，从 BACKLOG 划掉

### 想问问题（AI / 我 / OpenClaw）

直接说「查 eflow 知识库：\<问题\>」即可。AI 会按 [AGENT_GUIDE.md](AGENT_GUIDE.md) 的检索顺序读本目录后作答。
**AI 作答必须给出引用的文件路径**，没查到就明说没查到——不许凭印象编。

### 命令行全文本检索

```bash
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "工单 挂起"     # 空格自动拆成两个词，OR
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "工单 挂起" --all  # AND：须同时含两个词
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "sync" --dir 10_集成篇_Integration
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "P1" --context 3
python "D:\01_RPA\Task\eflow_Q&A\tools\search.py" "派单 三方" --phrase  # 当成一个完整短语搜
```

> 说明：多个词默认 **OR**（任一命中）；`--all` 是 **AND**，按**文件级**匹配
> （文件里同时含这些词即命中，不要求在同一行）。带空格的单个参数会自动拆词。

### 核查某张工单的派单依据

```bash
python "D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py" TT202608220047
```

**更方便：直接在 my_app 页面里分析** —— 打开
`http://localhost/myapp/?page=eflow_qa`，左侧「TT 快速分析」框输入单号点「分析」，
即出图形化报告（结论要点 / 告警→派单时间差 / CSD-PSD 对照 / 根因归属分布 / 工单字段）。
页面走 `GET /api/eflow-qa/inspect-tt?tt=<单号>`，与 CLI 共用 `inspect_tt.py` 里的
`analyze_tt()` 同一份逻辑，改工具即两边同时生效。

---

## 二、目录结构

```
eflow_Q&A/
├── README.md              本文件：这是什么、怎么用
├── INDEX.md               全量索引（分类 → 条目 → 一句话摘要）
├── CONTRIBUTING.md        贡献规范：怎么写一条、命名、状态标记
├── AGENT_GUIDE.md         给 AI 看的检索指引（回答时优先遵守）
│
├── _templates/            写新条目时从这里复制
│   ├── TEMPLATE_faq.md              问答式（一个具体疑问）
│   ├── TEMPLATE_howto.md            操作式（完成一件事的步骤）
│   └── TEMPLATE_troubleshooting.md  排障式（现象 → 原因 → 解法）
│
├── 00_操作篇_Operations/  ← 给 NOC 一线运维：eflow 界面里怎么操作
│   ├── 01_工单管理_TT_WO_CR_PM/
│   ├── 02_告警与故障_Alarm/
│   ├── 03_站点与资产_Site/
│   ├── 04_账号与权限_Account/
│   └── 05_常见报错速查_Errors/
│
├── 10_集成篇_Integration/ ← 给开发/集成：API、表结构、同步任务
│   ├── 11_架构与数据流_Architecture/
│   ├── 12_API接口_API/
│   ├── 13_数据字典_DataDictionary/
│   ├── 14_同步任务_Sync/
│   └── 15_排障与运维_Troubleshooting/
│
├── 90_术语表_Glossary.md        缩写与业务术语（TT/WO/CR/PM/MOC/PMP…）
├── 99_待补充问题_BACKLOG.md     还没答案的问题池
│
└── tools/
    └── search.py                全文本检索脚本
```

**分层规则**：同一件事写两层互不替代——

| | 操作篇（运维） | 集成篇（开发） |
|---|---|---|
| 回答 | 在 eflow 界面点哪里 | 调哪个 API、查哪张表 |
| 语言 | 步骤 + 截图 + 人话 | 代码 + SQL + 字段名 |
| 例 | 「怎么把工单挂起」 | 「eflow_tt.Status 枚举值有哪些」 |

---

## 三、eFlow 业务对象速览

eFlow 管的是运维工单全生命周期，核心对象 7 类：

| 缩写 | 全称 | 一句话 | 数据量（my_app 侧） |
|---|---|---|---|
| **TT** | Trouble Ticket | 故障工单，告警自动或人工创建 | 161 列 / 约 2.8 万行 |
| **WO** | Work Order | 作业工单，挂在 TT 下执行 | 168 列 / 约 1 万行 |
| **CR** | Change Request | 变更申请单 | 57 列 / 约 205 行 |
| **PM** | Preventive Maintenance | 预防性巡检任务 | 47 列 / 约 1632 行 |
| **Site** | 站点主数据 | 站点/区域/经纬度/维护方 | 44 列 / 808 行 |
| **Person** | 人员 | 处理人、联系人 | 36 列 / 133 行 |
| **Alarm** | 告警 | 实时 + 历史告警 | 36 列 |

> 数据量来源：`D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3`，2026-09-01 实际读取。
> 详细字段请查 [13_数据字典_DataDictionary](10_集成篇_Integration/13_数据字典_DataDictionary)。

---

## 四、相关系统位置

| 用途 | 路径 |
|---|---|
| eFlow API 客户端 | `D:\01_RPA\Task\my_app\backend\services\eflow_api_client.py` |
| 同步服务 | `D:\01_RPA\Task\my_app\backend\services\sync_from_eflow_api.py` |
| 集成方案文档 | `D:\01_RPA\Task\my_app\backend\services\eFlow_API集成方案.md` |
| TT 严重级别规则引擎 | `D:\01_RPA\Task\my_app\backend\services\eflow_rules\` |
| 告警服务 | `D:\01_RPA\Task\my_app\backend\services\eflow_alarm_service.py` |
| eFlow 原始库 | `D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3` |
| 早期登录脚本 | `D:\01_RPA\Task\eflow_python\eflow_login.py.txt` |

---

## 五、当前状态

- [x] 目录骨架 + 模板 + 检索工具
- [ ] 内容填充 —— 见 [99_待补充问题_BACKLOG.md](99_待补充问题_BACKLOG.md)，按优先级认领

**知识库的价值取决于条目数量，不取决于目录漂不漂亮。先写满 20 条再说。**
