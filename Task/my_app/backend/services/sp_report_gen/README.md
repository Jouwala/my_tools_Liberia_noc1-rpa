# SP 备件报表生成服务（sp_report_gen）

将远程 `\\192.168.100.19\e\01_RPA\LBR_Tools\SP\sp_report\gernarate_sp_report.py` 集成到 my_app，
由 Task Manager 统一调度，解决原远程生成端无稳定定时任务导致的报表数据长期不更新问题。

## 数据流

```
SFTP 10.100.20.11 /home/ubuntu/sp（备件原始数据，上游每小时产一份）
   │  sftp_download()（paramiko）—— 按「目录名 + 固定文件名」取**最新**一份：
   │    sp/inbound/<yyyymmdd>/<yyyymmddHHMMSSfff>/inbound.xlsx
   │                                        → data\inband_details.xlsx
   │    sp/outbound/.../outbound.xlsx        → data\outband_details.xlsx
   │    sp/inventory_management/.../inventory_management.xlsx
   │                                        → data\inventory_details.xlsx
   │    sp/wh_transfer/.../wh_transfer.xlsx  → data\transfer_details.xlsx
   │    sp/wh_transfer_return/.../wh_transfer_return.xlsx
   │                                        → data\transfer_return_details.xlsx
   │  （另有 ocrule：OCAuto/OCAutoOutput 递归找 csv → 转 excel）
   ▼
my_app\data\sp_email\data\          ← 原始数据（本地统一叫 *_details.xlsx）
   │  明细预处理（剔除单据 → 出库状态 → Canceled → Material Name/Type 同步，均写回同一批 xlsx）
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

> ⚠️ **2026-09-16 数据源变更**：上游把目录从 `sp/spinbound|spoutbound|spinventory|sp-wh_transfer`
> 迁到 `sp/inbound|outbound|inventory_management|wh_transfer`（+ 新增 `wh_transfer_return`），
> 文件名也从 `spinbound.xlsx` 之类改成与目录同名。**旧目录已于 2026-09-15 08:00 停更**，
> 继续用会静默取到过期快照（旧逻辑只取「最新 xlsx」、不校验文件名）。
> 同一变更同步应用于 `backend/services/get_sp_table.py`（仓库看板同步）与
> `task_configs_registry.py` 的 `sp_sftp_config.json` 默认目录。

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
| Step 2.3 | `apply_operation_result_filter()` | 入库/出库明细剔除 `Operation Result Status='Canceled'`（`OP_RESULT_DROP_STATUS`） | ✅ |
| Step 2.4 | `apply_operation_result_filter_to_file()` | 转仓明细（transfer / transfer_return）剔除 `Operation Result Status='Canceled'` | ✅ |
| Step 2.5 | `apply_inventory_fields()` | 覆盖明细的 **Material Name**（取数据库表 `sp_material`，回退 inventory）与 **Material Type**（取 inventory） | ✅ |
| Step 4 | `preprocess()` | 排除仓库 `Liberia Monrovia material warehouse` | ❌ 仅报表 |
| 生成时 | `generate_report()` | 仅保留 `Material Type='SpareParts'`（或 `Consumables`） | ❌ 仅报表 |

`Operation Result Status` 只有 inbound / outbound / wh_transfer 有；`inventory_management`
没有该列，不受影响。已作废单据（Canceled）在 SP Details Report 与报表里都不出现。

剔除匹配口径（命中任一即删）：
- `full` = (单据号, Material No., Serial No., Qty) 四字段全等
- `loose` = (单据号, Serial No.) 兜底（排除表物料号/数量与明细对不上时仍能删）

> 已停用：Step 3 `filter_data()`（去掉 `Inbound Type='Borrow Return Inbound'` / `Outbound Type='Repair Outbound'`）
> ——2026-09-08 起注释，函数保留便于恢复。

实现要点：
- 排除表**表头行不固定**（前有标题行 + 空行），扫描前 10 行找同时含 `单据号 / Serial No. / 物料号 / 数量` 的行。
- 物料号**前导零**：明细是文本 `033030100337`，排除表被 Excel 存成数字 `33030100337`，统一用 `_norm_excl_value()` 归一（纯数字串转最简 int 形式），否则大面积不命中。
- 写回统一走 `_save_detail_xlsx()`（tmp + `os.replace` 原子替换）；写回失败只告警，内存数据仍是处理过的，报表照常生成。

### Material Name / Domain 数据来源：数据库表 `sp_material`

`load_material_maps_from_db()`（经 `get_material_maps()` 进程内缓存，一次运行只读一次库）
按 materialNo 建 `{materialNo: materialName}` / `{materialNo: materialType}`，
并按 materialName 建 `{materialName: domain}`（2026-09-19 起，Summary-Current 的 Domain 列用）：

| 来源 | 说明 |
|------|------|
| **PG**（优先） | 连接串取环境变量 `DATABASE_URL`，缺失则读 `backend\.env`；表位置自动定位（优先 `app` schema），即 `app.sp_material` |
| sqlite（回退） | `db\app.db` 的 `sp_material` |
| inventory（再回退） | 上面都拿不到时，用 `inventory_details.xlsx` 的 Material No.→Material Name；Domain 同样回退 inventory 明细 |

- `sp_material` 由任务 `sp_material_sync`（每天 04:55）从 eFlow SP 接口拉全量写入，字段含 `materialNo / materialName / materialType / domain`，当前 922 行。
- 表里没有 `domain` 列时只丢 domain 映射（打印「无 domain 列」），不影响 Name/Type（2026-09-19 防旧表结构）。
- 覆盖率对比：用 `sp_material` 时明细**未命中 0 行**（inband/outband 全量命中）；只用 inventory（约 320 条）时分别有 339 / 406 行取不到名称。
- 表缺失 / 连不上只会打印 `[MatSync][WARN]` 并回退，**不会中断**报表生成。
- Material Type 目前仍取 inventory（同物料多值取首个）；`sp_material` 也有 `materialType`，如需切换可复用同一函数。

### 报表口径 vs SP Details Report

`sp_email_details` 合并 **5 份**明细（inventory / inband / outband / transfer / transfer_return），
**只经过 Step 2.x 的过滤**（不做「排除仓库」与「Material Type 过滤」）；
SpareParts/Comsumables 报表**额外**再做这两项。

`Transfer Return` 是**可选** sheet：源文件缺失时只告警并跳过（其余 4 份缺失仍报错，
避免静默发出残缺报表）。2026-09 上游的 `wh_transfer_return.xlsx` 一直是空表（0 行）。

以 2026-09-09 14-57-26 版（旧数据源时代）为例：

| 阶段 | Inbound | Outbound | Inventory |
|------|---------|----------|-----------|
| 下载原始 | 4015 | 2021 | 2094 |
| 剔除（in&out_exclude） | -299 → 3716 | -6 → 2015 | — |
| 剔除 WaitingForUpdate | — | -66 → 1949 | — |
| 排除仓库（仅报表） | -26 → 3690 | -26 → 1923 | -1 → 2093 |
| Material Type=SpareParts（仅报表） | -1628 → **2062** | -1058 → **865** | -896 → **1197** |

核对脚本：`TMP\verify_sp_report_filters.py "<报表时间戳>"`（如 `"2026-09-08 17-41-32"`），
逐条套用过滤条件并与报表各 sheet 实际行数比对，输出 PASS/FAIL。
（注意：报表 sheet 前 3 行是标题 / Generated / 表头，数据行 = 总行数 − 3。）

### Summary-Current 的列结构（2026-09-17 起，2026-09-19 更新）

`Summary-Current` 共 **11 列（A:K）**，前 6 列是主表原有列（其中 `Domain` 是 2026-09-18 新增、
固定在第 2 列；`Balance` 列 2026-09-19 删除），后 5 列是补库建议列（早期版本写成表身下方的独立区块，已废弃）：

| # | 列 | 口径 |
|---|----|------|
| 1 | Material Name | 主键，来自 Inventory / Inbound / Outbound 的并集 |
| 2 | **Domain** | **取自数据库表 `sp_material` 的 `domain` 列（按 materialName 映射，2026-09-19 起）**；库里取不到回退 Inventory 明细的 `Domain`；同一物料多行时取第一个非空；`Total` 行留空 |
| 3 | Inbound Qty | 入库数量合计 |
| 4 | Outbound Qty | 出库数量合计 |
| 5 | Inventory Qty | 库存数量合计 |
| 6 | Difference | Inventory Qty − (Inbound Qty − Outbound Qty)（原 Balance 列已删，口径不变） |
| 7 | Avg Monthly Consumption | 出库量合计（**先剔除 `SPOB202608160004` / `SPOB202609120014` 两张异常单据**）÷ 9.5，**保留 2 位小数，不取整**（2026-09-19 起） |
| 8 | Safety Stock | 月均消耗 > 0 → `ceil(6 × Avg Monthly Consumption)`（整数，按 2 位小数月均验算）；**月均消耗 = 0 → `ceil(20% × max(Inbound Qty, Outbound Qty, Inventory Qty))`**（整数） |
| 9 | **Remark** | 月均消耗 > 0 → `Actual Consumption`；**月均消耗 = 0 → `Failure Rate`**（`Total` 行留空） |
| 10 | Replenishment Qty | Safety Stock − Inventory Qty，**向上取整**；**≤ 0 留空**（不显示 0/负数，便于直接求和） |
| 11 | Alert Level | Inventory Qty / Safety Stock：< 50% `Urgent Replenish`；50%~100% `Replenish`；> 100% `Excess`（红/黄/绿三色；`Total` 行留空） |

- **Avg Monthly Consumption 保留 2 位小数**（2026-09-19 起，Excel 数字格式 `#,##0.00`）；
  **Safety Stock 保持向上取整**：`Safety = ceil(6 × Avg)`（整数，如月均 2.11 → 6×2.11=12.66 → 13）；
  `Replenishment Qty` 同样 `ceil`（如安全库存 13、库存 3.5 → 补库 10）。
  ceil 前先 `round(x, 6)` 防浮点误差误进位（如 `15 × 0.2 = 3.0000000000000004` 直接 ceil 会变 4）。
  常量：`REPLENISH_DEC_COLS` / `REPLENISH_INT_COLS`。
- **月均消耗 = 0 的物料**（无出库记录）按「故障率」备件处理：`Safety Stock = ceil(20% × 主表三列数量最大值)`、`Remark = Failure Rate`。
  常量：`REPLENISH_ZERO_CONSUMPTION_SAFETY_PCT` / `REMARK_FAILURE_RATE` / `REMARK_ACTUAL_CONSUMPTION`。
  三列数量全 0 时 Safety Stock 为 0，Alert Level 分母保护后落入 `Excess`（库存也是 0，补库列留空）。
- `Total` 行：Avg 列为**各行 2 位小数值的合计**（仍为 2 位小数），Safety / Replenishment Qty 为各行取整后的合计（整数），
  `Domain` / `Remark` / `Alert Level` 留空。
- 口径说明写在**文件上方**（2026-09-17 起，改前在表身下方）：Summary-Current 的第 4/5/6/7 行是**四行**英文说明
  （`Replenishment basis: ...` / `Zero-consumption materials ...` / `Replenishment Qty = ... / Alert Level = ...` /
  `Remark: Failure Rate = ... | Actual Consumption = ...`），
  由 `_insert_title(..., extra_notes=REPLENISH_NOTES)` 写入；PNG 侧对应 `_render_summary_image(..., notes=...)`，
  画在标题正下方。**Summary-Current 的表头因此落在第 8 行**（title / Generated / Filters / 说明 ×4 / 表头），
  数据从第 9 行开始。
- **文案一律英文，报表内不出现中文**（2026-09-17 起：Inbound / Outbound 说明行原先引用的中文 sheet 名
  `3_剔除单据Serial明细` 也改写成 `[sheet 3: excluded order serial details]`；
  `EXCLUDE_SHEET` 常量本身仍是中文，那是读剔除名单用的真实 sheet 名，**不能改**）。
- ⚠️ 口径差异：SpareParts 的 `Outbound Qty` **仍含**那两张单据（保持原有输出），
  因此同一行 `Outbound Qty ≠ Avg Monthly Consumption × 9.5`；Consumables 明细里没有这两单，无此差异。
- 实现：常量 `REPLENISH_*` / `ALERT_*` / `REMARK_*`；
  `build_summary()` 负责前 6 列（Domain 优先取 `sp_material` 的 materialName→domain 映射），
  `build_replenishment(outb_df, inv_df, base_index=, summary_qty=)`
  按主表物料逐行对齐后 5 列（`summary_qty` 提供主表三列数量，供 0 消耗物料算 20% 安全库存）；
  Excel 收尾 `_style_replenish_columns()`（Alert 三色 + 列宽），说明行由 `style_excel(..., extra_notes=)` 透传；
  数字格式 `_num_fmt_for_col()`（小数列 `#,##0.00`，其余 `#,##0`）；
  PNG 侧由 `_fmt_summary_cell()` 统一小数 / 整数 / 留白格式。
  `_style_replenish_note()` / `_style_replenishment()` 均已停用，保留供回退。
- 生成结束后由 `_cleanup_old_reports()`（`main()` Step 10）按「前缀 + 仓库名」分组，每组只留最新一份
  xlsx / png，其余删除。**它删的是 `OUT_DIR`（`data/sp_email`）下的正式产物**，不含仓库报表以外的文件。
- **改这个脚本不用重启 worker**：`sp_report_generate` 任务用 subprocess 调本脚本，每次都是新进程读最新代码。

### 报表内过滤条件说明行（2026-09-16 起）

每个 sheet 在标题下新增第 3 行蓝色小字（Calibri 9 `4472C4`），写明该 sheet 实际套用的过滤条件；
**第 4 行才是表头，数据从第 5 行开始**（改前表头在第 3 行）。

| sheet | 说明行内容 |
|-------|-----------|
| Inbound | `Material Type = <类型>` + `Warehouse Name ≠ 'Liberia Monrovia material warehouse'` + `Excluded orders: in&out_exclude.xlsx [sheet 3: excluded order serial details]` + `Operation Result Status ≠ 'Canceled'` |
| Outbound | 同 Inbound，末尾再加 `Status ≠ 'WaitingForUpdate'` |
| Inventory | `Material Type = <类型>` + `Warehouse Name ≠ 'Liberia Monrovia material warehouse'` |
| Summary-Current / Summary-Changed | `Material Type = <类型>` + 排除仓库 + `same exclusions as the Inbound / Outbound / Inventory sheets` |

分仓报表在说明行里额外带 `Warehouse Name = '<仓库名>'`。

⚠️ `Summary-Current` 因为额外带 4 行补库口径说明（见上一节），**表头在第 8 行、数据从第 9 行开始**；
其余 sheet 仍是「第 4 行表头、第 5 行起数据」。

实现：`_build_filter_note(kind, material_type, warehouse_name)` 生成文案 →
`_insert_title(ws, title, sheet_name, filter_note=)`（多插一行并**返回表头行号**）→
`style_excel(..., filter_note=)` / `style_summary_changed(..., filter_note=)` 据此计算 `header_row` / `data_start`。
**不传 `filter_note` 时行为与改动前完全一致**，因此 `generate_sp_online_report.py` 等复用方不受影响。

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
- 运行耗时：约 50 秒（下载 5 份 + 生成 10 份报表 + 清理），脚本自带总耗时打印。
- ⚠️ **跑任务前不要用 Excel/WPS 打开 `data\sp_email\data\` 下的 xlsx**：文件被占用时
  `sftp_download()` 会 `PermissionError` 直接中断（Windows 上 tmp+replace 也替换不了被
  独占锁定的文件），任务报 `returncode=1`。2026-09-16 就因 `outband_details.xlsx` 被 WPS
  打开而中断过一次；系统有 `auto_retry` 会自动补跑，但最好先关闭文件。
- 改动脚本后无需重启 worker：报表脚本以子进程方式每次现读。
