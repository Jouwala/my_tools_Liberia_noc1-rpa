# 06 user-guide.md —— 面向使用者的功能说明

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\user-guide.md`

> **本文只是入口。** 完整的使用者文档在这里：
> - **`docs\manual\15-user-help.md`** —— 面向使用者的**一站式帮助**（平台简介、44 个任务的工作流与维护、25 个页面指南、运维排障与 FAQ）。英文版 `15-user-help-en.md`
> - **`docs\manual\11-feature-guide.md`** —— 23+ 个功能页按**导航顺序**逐个说明
>
> 两者与**站内「使用帮助」页面同源生成**。改内容改 TS 源文件后重新生成，**不要手改 MD**（见下节）。

## 一、怎么打开

| 方式 | 地址 |
| --- | --- |
| 从统一门户进入（推荐） | 门户里搜索或从分类中选，直接点开 |
| 直接访问 | `http://192.168.100.19/myapp/?page=<PageKey>` |

> **页面直链是查询参数格式**（`?page=xxx`），**不是** hash 路由（`#/xxx`）。写错会停在默认页。

常用页面 key：`sync`、`alarm`、`realtime_alarm`、`ttwo`、`nur`、`ms_sla`、`cxoDashboard`、`gis`、`packet_loss`、`battery`、`ip_trace`、`incident_overview`、`warehouse`、`overview`、`tables`、`upload`、`archive`、`dashboard`、`settings`。

## 二、站内「使用帮助」

系统内置**使用帮助页**，内容与 `docs\manual\15-user-help.md` **同源**：

- 平台简介与能力概览
- **44 个定时任务**的工作流与维护说明
- **25 个页面**的操作指南
- 运维排障与 FAQ

> **改帮助内容的方式**：改 `frontend\src\pages\helpContent.ts` 与 `helpTaskDocs.ts`（TS 源），然后跑
> ```
> cd frontend && node scripts\generate-help-doc.mjs
> ```
> 重新生成 MD。站内帮助页、导出按钮、MD 文档**三处同源**。**直接改 MD 会被下次生成覆盖。**

## 三、功能模块速览

> 逐页说明见 `docs\manual\11-feature-guide.md`。

| 业务域 | 你会在这里做什么 |
| --- | --- |
| 数据同步与任务 | 看任务跑没跑、手动触发、看执行历史、浏览/上传/归档数据表 |
| 告警与故障 | 看实时告警、历史告警、告警管理、故障概览 |
| 工单流程 | TT/WO 工单看板、NUR（网络不可用率） |
| 网络性能 | 丢包、性能 KPI、IP Trace、GIS 地图 |
| MS SLA / 合同 | MS SLA 看板、SP 系列报表、FME 工程师排名 |
| 资源与供应链 | 仓库看板 |
| 电源 | 电池看板 |
| 管理 | 系统设置、系统概览、CXO 看板、凭据设置、收件人设置、远程主机设置 |
| 知识问答 | eFlow Q&A |
| 分发 | 邮件报表、WhatsApp 通知 |

## 四、常用操作

### 配置在哪改（界面能改的，改完即生效）

| 想改什么 | 去哪 | 要不要重启 |
| --- | --- | --- |
| 凭据（各上游系统账号） | 「系统设置」→ 凭据设置 | **否**（缓存 30 秒） |
| 邮件收件人 | 「系统设置」→ 收件人设置 | 否 |
| 远程主机地址 | 「系统设置」→ 远程主机设置 | 否 |
| 任务定时（cron） | 「任务管理」 | 否 |
| 任务参数 | 「任务管理」 | 一般否 |

> 界面上改不了的（数据库模式、端口等）要改 `backend\.env`，**需要重启**。详见 `docs\manual\12-configuration.md`。

### 手动跑一个任务

「任务管理」里找到任务 → 手动触发。任务会进队列，由 worker 串行执行；同一任务**不会重复排队**（有单飞保护）。

### 看任务执行历史

任务执行日志写在 `task_execution_log` 表（跨进程可见），界面上的任务状态就是读它。

## 五、看到这些现象怎么办

| 现象 | 含义 / 怎么办 |
| --- | --- |
| 任务一直显示 **pending** 不动 | worker 没在跑，或该任务**没有归入任何 worker 分组**（这是已知坑）。查 `docs\manual\13-operations.md` |
| 任务卡在 **running** 很久 | 可能 worker 异常退出留下僵尸记录。后端会按 `WORKER_STALE_RUNNING_SECONDS`（默认 30 分钟）回收 |
| 页面**数据不更新** | 先看任务是否在跑；再看是不是取了空的占位库（见下条） |
| 某个报表**一直是空的但不报错** | 可能是读到了 **0 字节占位库**（`db_ps_cs_cn` 的真数据在远端）。这是最容易误判为"数据为零"的坑 |
| 图表空白但页面正常 | 图表的取数链路可能有问题（存在绕过统一数据访问层的连接点） |
| 页面白屏 | 前端产物目录可能不是 `_fe_dist` |
| 改了帮助内容但站内没变 | 需要重跑 `generate-help-doc.mjs` 重新生成 |

> 完整排障 FAQ 见 `docs\manual\13-operations.md`。

## 六、给你的三条约定

1. **界面能改的优先在界面改。** 改 `.env` 要重启，影响正在看数据的人。
2. **`db_ps_cs_cn` 别当本地库用。** 本地那个文件是空的，真数据在远端——查到空的不是"没有数据"。
3. **任务 pending 不动不是"在排队"，是没人接。** 优先查 worker 分组。

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| **使用者一站式帮助（最全）** | `docs\manual\15-user-help.md` / `15-user-help-en.md` |
| 逐页功能说明 | `docs\manual\11-feature-guide.md` |
| 配置项与开关 | `docs\manual\12-configuration.md` |
| 运维手册与 FAQ | `docs\manual\13-operations.md` |
| 接口与任务速查 | `docs\manual\90-appendix.md` |
| 快速上手（含环境搭建） | `docs\manual\10-quickstart.md` |
| 项目整体说明 | `project-overview.md` |
| 统一门户使用说明 | `..\..\liberia-noc_soc-数据看板统一门户\docs\user-guide.md` |

> **工具负责整理，人与 AI 负责协作执行。**
