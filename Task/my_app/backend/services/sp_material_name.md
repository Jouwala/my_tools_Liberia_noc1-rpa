# SP 物料名字解析（sp_material_name）

## 背景

上游 SFTP 导出的入库 / 出库 / 库存 / 转仓明细里，`Material Name` 是**单据导出那一刻**的快照名。
物料在 eFlow 改名后，历史单据不回写新名，于是同一个物料会以两种写法同时出现在一张报表里。
`Summary-Current` 以 Material Name 为主键，结果是**一个物料裂成两行**，入库 / 出库 / 库存被拆开，
`Avg Monthly Consumption`、`Safety Stock`、`Replenishment Qty`、`Alert Level` 全按半截数量算。

2026-11-06 实测：主数据当天 08:20~08:37 把 `Chassis (NR9000TR)|`、`Fan unit A(High anti-corrosion)|`、
`Modem Unit D2 (High anti-corrosion)|` 三个物料改名去掉结尾 `|`，当天 SpareParts 总表受影响
86 行明细，`Summary-Current` 242 行里裂出 4 组重复物料。

## 口径

按 `Material No.` 取物料主数据 `sp_material.materialName`：

| 环节 | 说明 |
|---|---|
| 表来源 | `sp_material`（`backend/services/sp_material_sync.py` 从 eFlow `eflow-sp-material/base/list` 全量拉取，`materialNo` 唯一，重复时保留 `woId` 最大的一行 = 最新记录） |
| 读库 | `backend.database.get_raw_connection()`，双模：`MY_APP_DB_MODE=pg` → `app.sp_material`；`sqlite` → `db/app.db` |
| 命中 | 覆盖明细的 Material Name |
| 未命中 | **保留原值**，不清空、不写 `Unknown`：主数据缺档时宁可留着上游的名字 |
| 缓存 | 进程内 300 秒 TTL（`load_material_maps(force_refresh=True)` 可强制作废，报表生成器 Step 0 刷新主数据后必须调用） |
| 物料号归一 | `norm_key()`：去空格 + 纯数字转最简形式（`033030100337` 与 `33030100337` 视为同一个号），明细文本 / Excel 数字两侧统一 |

**`|` 不是脏字符**：979 条主数据里 510 条名字本身含 `|`（如 `DTB_B|Digital Trunk Board|`、
`SRAN65W_18_18_18(Band10)|ZRME|BS8912R2803E`）。所以只能整串取主数据的值，
**禁止**写「去掉结尾 `|`」「按 `|` 切第一段」这类字符清洗——那会把 510 个合法名字改坏。

## 接口

| 函数 | 用途 |
|---|---|
| `load_material_maps(force_refresh=False)` | `(name_lut, type_lut, domain_lut)`；domain 按 materialName 建（Summary-Current 的 Domain 列用） |
| `material_name_lut()` / `canonical_name(no)` | 只要名字映射时的简写 |
| `normalize_dataframe(df, ...)` | pandas 明细就地覆盖，返回 `{rows, changed, missing, type_changed, skipped?}` |
| `normalize_rows(columns, rows)` | `sp_details_service` 那种 list[list] 结构的同款覆盖 |

覆盖 `Material Type` 需显式传 `type_col` + `type_lut`：默认**不动 Type**。
两张总表按 Material Type 拆分 SpareParts / Consumables，换源会移动行数，
所以报表生成器仍传 inventory 派生的 Type 映射（实现克制，不改口径）。

## 调用方

| 调用方 | 位置 | 作用 |
|---|---|---|
| `sp_report_gen/gernarate_sp_report.py` | Step 2.5 `apply_material_master_fields()` | 五份明细 + 五份 `*_source.xlsx` 快照归一后写回 → 总表、分仓表、`Summary-Current`、PNG、周报、明细落库全部同口径 |
| `get_sp_table.py::_write_table` | 每小时 `sp_data_sync` 落库前 | `inband_details` / `outband_details` / `inventory_details` / `transfer_details` 四表入库前归一 → 仓库看板 iframe、原生看板、`page=sp_material`、MsPortal QC 面板 |
| `sp_details_service.py::_read_sheet` | `page=sp_details` 每次读表时 | 合并工作簿是 07:05 生成的快照，物料在那之后改名时页面要立刻跟上；本页**没有按 Material Name 聚合的汇总**（物料数是 Material No. 去重），所以实时解析不会造成同页两套名字 |

> **其余页面不在读取侧改名**（2026-11-06 与用户确认的取舍）：`sp_report` / `com_report` /
> `warehouse_summary` 的 `Summary-Current` 是**按名字聚合**出来的，若明细行实时改名而汇总行
> 还是生成时的名字，同一页会出现两套写法。所以那一族走「生产者侧归一 + 生成前刷新主数据」，
> 代价是 05:15 之后的改名次日进报表。

## 失败语义

主数据表缺失 / 连不上库 / 没有 `materialNo` 列时返回空映射并打
`[MatName][WARN]`，调用方按「保留明细原名」处理，**不抛异常、不中断报表**。
