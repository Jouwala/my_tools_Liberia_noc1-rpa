# backfill_new_group_history.py — 新区域 Group 历史数据回补

## 背景

远程库 `ran_kpi_daily.sqlite3`（db_writer_api @ 192.168.100.19:8765）中新命名
Group（`2G_NW`、`*_FME_Region-Regular/Cooli/ERA` 等，由 `network_kpi_sync`
2026-07-28 起写入）仅有 14 天数据，FineBI 曲线只显示几天；旧命名 Group
（`G_NW`、`*_ZTE-OLR-*`，旧导入路径 05-08~07-27）与新命名是**相互独立的
两套区域口径，无映射关系**，两套都需要完整历史。

本地旧采集库 `d:\01_RPA\Task\RAN\ran_kpi_daily.sqlite3` 存有同套新命名
2025-12-01 ~ 2026-07-23 共 235 天历史，列结构与远程库完全一致（12/18/16/16 列），
因此无需重查 UME，直接 upsert 回补即可。

## 处理逻辑

| 步骤 | 说明 |
|---|---|
| 1 | 只读（`mode=ro`）打开源库，读取 4 张 OLIB 表全部行 |
| 2 | 归一化 `Begin Time` / `End Time`：去 `T`、去 `+00:00`/`Z`/`±HH:MM` 时区后缀 → `YYYY-MM-DD HH:MM:SS`（源库混有 ISO 格式） |
| 3 | 过滤窗口：日期 ≤ `CUTOFF_DATE`（默认 2026-07-27，远程 07-28 起已有数据） |
| 4 | `DbWriterClient.write_data` upsert（pk=`[Begin Time, Group]`），按 1000 行/批，单批失败不影响其他批次 |

## 用法

```powershell
# 只统计不写入
python backfill_new_group_history.py --dry-run
# 正式回补
python backfill_new_group_history.py
```

## 执行记录

- 2026-08-11：回补 6928 行（2G 2437 / 3G 1732 / FDD 1732 / TDD 1027），耗时 0.3s，
  新命名组覆盖扩至 2025-12-01 ~ 2026-07-23；随后用 `NW_KPI_DAYS_BACK=19`
  重跑 `network_kpi_sync` 补齐 07-24 ~ 07-27 缺口。

## 设计约定

- upsert 可重复执行，不会产生重复行（主键 Begin Time + Group 格式已统一）。
- 时间格式必须与远程库统一为空格格式，否则 upsert 主键失配会写入重复数据
  （参见 fix_begin_time_format.py 修复过的双格式混存问题）。
- 旧命名组（ZTE-OLR 系列）历史由旧导入路径产生，本脚本不涉及；
  其 07-28 起无数据属旧路径停用，非数据丢失。

## 依赖

仅标准库 + 项目内 `db_writer_client.py`，见 `requirements_backfill_new_group_history.txt`。
