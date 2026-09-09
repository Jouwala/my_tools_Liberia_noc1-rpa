# SP 备件报表生成服务（sp_report_gen）

将远程 `\\192.168.100.19\e\01_RPA\LBR_Tools\SP\sp_report\gernarate_sp_report.py` 集成到 my_app，
由 Task Manager 统一调度，解决原远程生成端无稳定定时任务导致的报表数据长期不更新问题。

## 数据流

```
SFTP 10.100.20.11（备件原始数据，每日更新）
   │  sftp_download()（paramiko）
   ▼
my_app\data\sp_email\data\          ← 原始数据（inband/inventory/outbound/ocrule/transfer xlsx）
   │  明细预处理（剔除 → 状态过滤 → Material Name/Type 同步，均写回同一批 xlsx）
   ▼
my_app\data\sp_email\data\          ← 处理后明细（下游 sp_online / sp_email_details 同口径）
   │  generate_report()（再按仓库 / Material Type 过滤）
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
| `gernarate_sp_report.py` | 主脚本（源自远程 `gernarate_sp_report.py`，已按 my_app 大量改造）。配置：`DATA_DIR=my_app\data\sp_email\data`、`OUT_DIR=my_app\data\sp_email`；相对路径下载统一解析到 DATA_DIR（不依赖进程 cwd）。在 `load_data()` 之后新增明细预处理（剔除 / 状态过滤 / Material Name·Type 同步），详见下方「明细预处理流水线」 |
| `generate_sp_online_report.py` | 生成 SP 在线未关闭单表格（Inbound / Outbound 的 PNG + XLSX）到 `data\sp_email\sp_online`，图片复用本目录 `_render_summary_image` 渲染样式，Excel 复用 `style_excel` 样式 |
| `requirements.txt` | 依赖：pandas / numpy / paramiko / openpyxl / Pillow（系统 Python3.12 已具备） |

## 明细预处理流水线（gernarate_sp_report.py main）

下载 → 处理 → 生成报表。**前三步都会写回 `data\sp_email\data\` 下的明细 xlsx**，
因此 `sp_online_report_generate`（06:00）与 `sp_email_details`（07:00）复用的是同一份已处理数据。

| 步骤 | 函数 | 作用 | 写回 |
|------|------|------|------|
| Step 2.1 | `apply_exclude_to_details()` | 按 `data\sp_email\data\in&out_exclude.xlsx`（sheet `3_剔除单据Serial明细`）剔除指定单据行，分入库/出库两组 | ✅ |
| Step 2.2 | `apply_status_filters()` | 出库明细剔除 `Status='WaitingForUpdate'`（`OUTBOUND_DROP_STATUS`） | ✅ |
| Step 2.3 | `apply_inventory_fields()` | 用 `inventory_details.xlsx` 的 Material No. 覆盖明细的 **Material Name** 与 **Material Type** | ✅ |
| Step 4 | `preprocess()` | 排除仓库 `Liberia Monrovia material warehouse` | ❌ 仅报表 |
| 生成时 | `generate_report()` | 仅保留 `Material Type='SpareParts'`（或 `Consumables`） | ❌ 仅报表 |

剔除匹配口径（命中任一即删）：
- `full` = (单据号, Material No., Serial No., Qty) 四字段全等
- `loose` = (单据号, Serial No.) 兜底（排除表物料号/数量与明细对不上时仍能删）

> 已停用：Step 3 `filter_data()`（去掉 `Inbound Type='Borrow Return Inbound'` / `Outbound Type='Repair Outbound'`）
> ——2026-09-08 起注释，函数保留便于恢复。

实现要点：
- 排除表**表头行不固定**（前有标题行 + 空行），扫描前 10 行找同时含 `单据号 / Serial No. / 物料号 / 数量` 的行。
- 物料号**前导零**：明细是文本 `033030100337`，排除表被 Excel 存成数字 `33030100337`，统一用 `_norm_excl_value()` 归一（纯数字串转最简 int 形式），否则大面积不命中。
- 写回统一走 `_save_detail_xlsx()`（tmp + `os.replace` 原子替换）；写回失败只告警，内存数据仍是处理过的，报表照常生成。

### 报表口径 vs SP Details Report

`sp_email_details` 合并 4 份明细（inventory/inband/outband/transfer），**只经过前三步**；
SpareParts/Comsumables 报表**额外**再做「排除仓库」+「Material Type 过滤」。

以 2026-09-08 17-41-32 版为例：

| 阶段 | Inbound | Outbound | Inventory |
|------|---------|----------|-----------|
| 下载原始 | 4014 | 2017 | 2096 |
| 剔除（in&out_exclude） | -298 → 3716 | -6 → 2011 | — |
| 剔除 WaitingForUpdate | — | -65 → 1946 | — |
| 排除仓库（仅报表） | -26 → 3690 | -26 → 1920 | -1 → 2095 |
| Material Type=SpareParts（仅报表） | -1627 → **2063** | -1057 → **863** | -896 → **1199** |

核对脚本：`TMP\verify_sp_report_filters.py "<报表时间戳>"`（如 `"2026-09-08 17-41-32"`），
逐条套用过滤条件并与报表各 sheet 实际行数比对，输出 PASS/FAIL。
（注意：报表 sheet 前 3 行是标题 / Generated / 表头，数据行 = 总行数 − 3。）

## SP 在线未关闭单（generate_sp_online_report.py）

读取 `data\sp_email\data\` 最新 `inband_details.xlsx` / `outband_details.xlsx`，
**排除** `Status` 为 `WaitingForReturn` / `Draft` / `WaitingForUpdate` / `Closed` 的数据（这些状态不要），其余保留，
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
- ⚠️ **跑任务前不要打开 `data\sp_email\data\` 下的 xlsx**：文件被 Excel 占用时 `sftp_download()` 会
  `PermissionError` 直接中断（Windows 上 tmp+replace 也替换不了），任务报 `returncode=1`；
  系统有 `auto_retry` 会自动补跑，但最好先关闭文件。
- 改动脚本后无需重启 worker：报表脚本以子进程方式每次现读。
