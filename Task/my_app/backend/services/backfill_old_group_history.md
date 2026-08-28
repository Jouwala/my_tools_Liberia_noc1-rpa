# backfill_old_group_history — 回补远程库旧命名（ZTE-OLR）Group 历史

## 背景

- 远程 `ran_kpi_daily.sqlite3` 中旧命名 Group（`G_NW`、`*_ZTE-OLR-MS-Network`、
  `*_ZTE-OLR-Region`）由部署机手工导出流水线写入，起点仅 2026-05-08，07-28 起停更。
- 部署机 `/01_RPA/LBR_Tools/KPI/RAN/ran_kpi_daily_2.sqlite3`（已下载至
  `d:\01_RPA\TMP\ran_kpi_daily_2.sqlite3`）存有 **2025-07-26 ~ 2026-07-27**
  一整年新旧两套命名完整历史，列结构与远程完全一致。
- 本脚本直接读该历史库 upsert 到远程库，**无需重新查询 UME**。

## 回补规则

| 组类型 | 判定 | 回补日期范围 |
|---|---|---|
| 旧命名 | `Group == "G_NW"` 或含 `ZTE-OLR` | ≤ 2026-07-27（全部净增量） |
| 新命名 | 其余 | < 2025-12-01（向前延伸，不覆盖已有数据） |

## 使用方法

```powershell
cd D:\01_RPA\Task\my_app
python backend\services\backfill_old_group_history.py --dry-run   # 先只统计不写入
python backend\services\backfill_old_group_history.py             # 正式回补
```

## 写入方式

- 目标库：`ran_kpi_daily.sqlite3`（db_writer `/api/write`），4 张
  `{2G,3G,FDD,TDD}_OLIB_Network_KPIs` 表
- 模式：`upsert`，主键 `[Begin Time, Group]`，可重复执行（幂等）
- 批次：1000 行/批，单批失败不影响其他批次
- 时间归一化：源库 `2025-07-26T00:00:00+00:00` → `2025-07-26 00:00:00`

## 已知限制

- `_2` 历史库最大日期为 2026-07-27，因此旧命名 **07-28 之后的数据无法从本地恢复**
  （需在 UME 上用旧收藏夹 `GSM/UMTS/FDD_KPIs_ZTE_OLR_FB` + `*_Dispatch_Rules_*`
  小区组重新查询导出，或改造 network_kpi_sync 增加旧 uilocations 查询任务）。

## 验证

```sql
SELECT date("Begin Time") d FROM "2G_OLIB_Network_KPIs"
WHERE "Group" = '2G_Regular_ZTE-OLR-MS-Network' GROUP BY d ORDER BY d;
-- 期望：2025-07-26 起连续至 2026-07-27（与远程已有 05-08 起数据合并后无缺口）
```
