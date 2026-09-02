# SP 备件报表生成服务（sp_report_gen）

将远程 `\\192.168.100.19\e\01_RPA\LBR_Tools\SP\sp_report\gernarate_sp_report.py` 集成到 my_app，
由 Task Manager 统一调度，解决原远程生成端无稳定定时任务导致的报表数据长期不更新问题。

## 数据流

```
SFTP 10.100.20.11（备件原始数据，每日更新）
   │  sftp_download()（paramiko）
   ▼
my_app\data\sp_email\data\          ← 原始数据（inband/inventory/outbound/ocrule/transfer xlsx）
   │  generate_report()
   ▼
my_app\data\sp_email\               ← 产出 Comsumables / SpareParts Inbound&Outbound&Inventory
                                       总表（xlsx + Summary PNG）与 4 个仓库分表
   │  kpi_sp_spareparts / kpi_sp_consumables 邮件任务
   ▼
远程共享名单 \\192.168.100.19\e\01_RPA\LBR_Tools\SP\sp_report\email\ss_email.txt / cc_email.txt
   ▼
EWS 发送邮件（owa_mail_report.py）
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `gernarate_sp_report.py` | 生成脚本（自远程复制，MD5 与远程一致）。已改配置：`DATA_DIR=my_app\data\sp_email\data`、`OUT_DIR=my_app\data\sp_email`；相对路径下载统一解析到 DATA_DIR（不依赖进程 cwd） |
| `generate_sp_online_report.py` | 生成 SP 在线未关闭单表格（Inbound / Outbound 的 PNG + XLSX）到 `data\sp_email\sp_online`，图片复用本目录 `_render_summary_image` 渲染样式，Excel 复用 `style_excel` 样式 |
| `requirements.txt` | 依赖：pandas / numpy / paramiko / openpyxl / Pillow（系统 Python3.12 已具备） |

## SP 在线未关闭单（generate_sp_online_report.py）

读取 `data\sp_email\data\` 最新 `inband_details.xlsx` / `outband_details.xlsx`，过滤 `Status != 'Closed'`，
按单号去重（一单多物料行取首行），按 Create Time 倒序，各输出 PNG + XLSX（Inbound.png/.xlsx、Outbound.png/.xlsx）。

| 输出列 | 来源 |
|--------|------|
| Operation No. | Inbound No. / Outbound No. |
| Status / Operation Type / Warehouse Name / Create Time / Closed Time | 同名列原值 |
| Approved Time | Verify Detail 中最早的 `Operation:Verify. Operation Time:`（日志条目不保证时间序，按解析时间取最小） |
| Approval Duration | Approved Time − Create Time（<1 天显示 `x.xh`，否则 `xd xh`） |
| Close Duration | Closed Time − Approved Time（未关闭单为空） |
| Current Operation Owner | Verify Detail 中最近一次 Verify 的 Operator，经 `db\app.db` person 表按 objectid 转名字；查不到保留原 ID |

运行：`python generate_sp_online_report.py`（依赖同目录 `gernarate_sp_report`；输出文件被占用时自动加 `_1` 后缀）。
注意：当前 inband_details.xlsx 导出全部为 Closed，Inbound.png 仅含表头属预期；上游导出含未关闭单后会自动带出。

## 任务配置（backend/task_registry.py）

| 任务 ID | cron | 说明 |
|---------|------|------|
| `sp_report_generate` | `15 5 * * *` | 每天 05:15 从 SFTP 下载数据并生成报表到 data/sp_email |
| `sp_online_report_generate` | `0 6 * * *` | 每天 06:00 基于最新明细生成 sp_online 未关闭单报表（PNG+XLSX） |
| `sp_online_report_send` | `20 6 * * *` | 每天 06:20 发送 sp_online 未关闭单报表：邮件（PNG 内嵌 + XLSX 附件）+ WhatsApp 群 |
| `kpi_sp_spareparts` | `45 5 * * *` | 05:45 发送 SpareParts 报表邮件（附件取本地 sp_email 最新总表） |
| `kpi_sp_consumables` | `40 6 * * *` | 06:40 发送 Comsumables 报表邮件（附件取本地 sp_email 最新总表） |

邮件收件人/抄送名单实时读取远程共享路径 `\\192.168.100.19\e\01_RPA\LBR_Tools\SP\sp_report\email\`。

`sp_online_report_send` 说明：
- 邮件与 WhatsApp 在同一任务内先后执行，结果合并展示（Email=OK/FAIL, WhatsApp=OK/FAIL）。
- 邮件收件人 key `sp_online_report`，默认复用 SP 报表远程共享名单，可在 Settings → Email Recipient Settings 覆盖。
- WhatsApp 复用 `whatsapp_service.run_whatsapp_send`（已参数化 photos/captions/files/groups，缺省行为不变），群组固定为 `WH&SP Management`（`kpi_email_report._SP_ONLINE_WA_GROUPS`，独立于 `WHATSAPP_GROUPS`）。
- 两个新任务已加入 `worker_watchdog.py` GROUP_TASK_MAP 的 "m" 组（新任务漏分组会无人认领、队列 pending 卡死）。

## 要点

- 生成脚本需 pandas/paramiko 等，托管 venv 缺 paramiko，`run_sp_report_generate` 用后端系统 Python（`sys.executable`）以子进程执行，超时 600s。
- 生成成功后校验两类总表 xlsx 是否存在，缺失则任务标记失败，避免静默发出旧数据。
- 邮件任务附件选择：按 `SpareParts` / `Comsumables` 过滤后取「非分仓（不含 ` - Liberia`）」的最新总表。
- 旧报表自动清理：每次生成后仅保留各仓库/类型最新一份（脚本 `_cleanup_old_reports`）。
- 运行耗时：约 30~40 秒（SFTP 下载 + 10 份报表 + 清理），脚本自带总耗时打印。
