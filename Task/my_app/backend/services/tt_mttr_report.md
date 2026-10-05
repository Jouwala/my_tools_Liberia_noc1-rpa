# TTs and MTTR 报表生成（tt_mttr_report_generate）

## 背景

网络运维要按**月**看各优先级工单的 MTTR 是否压得住 SLA 目标。此前这一步是人工的：
从 `data/eflow/tt_reports` 里挑最新一份 `Liberia Orange Site Down hourly Report_*.xlsx`，
在 Excel 里筛「有 WO」「告警发生→告警清除历时 < 48 小时」，再按月做 P1~P4 的 TTs / MTTR 统计并画图。
2026-10-04 与需求方逐条确认口径并用 WPS COM 重算对拍通过后，固化为定时任务，
产物直接在 **「邮件报告文件」页 → 「TTs and MTTR」页签** 自动生成并下载。

## 任务信息

| 项 | 值 |
|---|---|
| task_id | `tt_mttr_report_generate` |
| cron | `20 7 * * *`（排在 `eflow_sync`（每小时 :00）之后，读到当天最新一期 hourly Report；要更高频在任务管理页改排程即可，不必改代码） |
| 入口 | `backend/services/tt_mttr_report.py::run_tt_mttr_report`（零参，返回摘要 dict） |
| category / gateway | `eflow` / `eflow_api`（数据血缘是 eFlow TT；本任务**不调 eFlow API**，只读写本地文件） |
| worker 分组 | `m`（内务轻任务；与同读该目录的 `liberia_email_1h` 同组） |
| 实测耗时 | 9.4 秒（源表 37006 行 → 写出 3.14 MB） |

## 数据源与产物

| 方向 | 路径 |
|---|---|
| 输入 | `data/eflow/tt_reports/Liberia Orange Site Down hourly Report_*.xlsx` 的 **`Processed Data`** 页，按 mtime 取最新一份 |
| 输出 | 同目录 `TTs and MTTR (Hour)_YYYY-MM-DD_HH-MM-SS.xlsx`（文件名带时间戳，每次生成一份新文件） |
| 保留 | 同前缀只留最近 `KEEP_FILES = 10` 份 |

**为什么保留份数要本任务自己管**：`eflow_data_mapper.py::_cleanup_old_tt_reports` 的清理名单是**写死的 8 个 pattern**
（hourly/8h/TT Summary 三份 xlsx + 五份 png），不含本产物；漏了就会每天堆一份 3 MB 文件而无人回收。

## 三个 sheet 与过滤口径

建表顺序即 tab 顺序（xlsxwriter 按 `add_worksheet` 调用顺序排）：

| sheet | 内容 | 行范围 |
|---|---|---|
| `Summary` | 分月 `MONTH / TTs / MTTR / Target`，P1 / P2 / P3 / P4 / N/A 五块堆叠；P1~P4 各一张组合图 | 统计格全部是**公式** |
| `Raw Data` | 源表中 `WO No.` 非空的工单，保留源表全部列 | 不按月、不按历时裁剪 |
| `ZTE` | 在 Raw Data 基础上再过滤（下表），并追加 `MTTR (Hour)` / `Month` / `SLA Target (Hour)` 三列（插在 `Alarm Clear Time` 之后） | 报表统计口径 |

`ZTE` 页的四条过滤（与需求方确认的口径，改任何一条都要重新对拍）：

1. `WO No.` 非空；
2. **MTTR = 告警清除时间 − 告警发生时间**，且 `0 <= MTTR < 48` 小时
   —— 注意**不是**源表的 `SLA Time` 列，那一列存的是 SLA **目标**而不是耗时，用它统计会得到「全员达标」的假结果；
3. `Site Category` 非空（空值即源表没填站点类别，这类工单不归 ZTE 侧统计）；
4. 告警发生月份 >= `2026-01`（`MONTH_FROM`）。

## Summary 的公式写法

统计单元格用 `COUNTIFS` / `AVERAGEIFS` 引用 `ZTE` 页，用户改数据后 Excel 会自己重算：

```
=COUNTIFS('ZTE'!$<Lv>$2:$<Lv>$<N>, "P1", 'ZTE'!$<Mv>$2:$<Mv>$<N>, $A10)
=IF($B10=0, "", ROUND(AVERAGEIFS('ZTE'!$<Tv>$2:$<Tv>$<N>, ..., "P1", ...), 2))
```

两个坑：

- **`AVERAGEIFS` 在零命中时返回 `#DIV/0!`**，必须套 `IF($B10=0,"",...)`；
- **`Ticket Severity` 为空的工单**（源表确有若干条）用条件 `"="` 匹配空单元格，单列 `N/A` 块，
  Target 写 `—` 不出图。代码里 `assert 分块合计 == ZTE 行数`，漏掉任何一类会立刻抛错而不是静默少统计。
- 写公式时用 `write_formula(..., value=)` 同时存了**缓存值**，所以不打开 Excel 也能读到数；
  `Workbook(..., {"strings_to_formulas": False})` 是必须的，否则源表里以 `=` 开头的文本会被当公式解析。

组合图用 `bar.combine(line)`：柱=TTs（左轴），青线=MTTR、红线=Target（`y2_axis`，右轴）。
右轴**只设 `min: 0`、上限交给 Excel 自动缩放** —— 早先写死 `max = Target * 1.25` 时，
P1 2026-05 的 16.37 h 超标点被裁出图外，正好把最需要看见的异常裁掉了。

## 依赖

没有新增第三方依赖：`pandas` / `xlsxwriter` / `openpyxl` 均已在项目根 `requirements.txt`
（`pandas>=2.0.0`、`openpyxl>=3.1.0`、`xlsxwriter>=3.0.0`），本模块不需要单独的 requirements 文件。

## 联动的其他位置（改口径时五处都要看）

| 位置 | 作用 |
|---|---|
| `backend/services/tt_mttr_report.py` | 生成逻辑 |
| `backend/task_registry.py` `TASK_SPECS` | 任务登记（漏了不执行） |
| `backend/worker_watchdog.py` `GROUP_TASK_MAP` | 分组（漏了永远 pending，`tests/test_worker_group_coverage.py` 会拦） |
| `backend/routers/email_reports.py` `_SOURCES` | 下载白名单，`patterns` 必须与 `OUTPUT_PREFIX` 一致，否则「列得出、下不动」 |
| `frontend/src/pages/EmailReports.tsx` + `i18n.tsx` | 「TTs and MTTR」页签与中英文案 |

## 验证方式

改动后至少做两件事：

1. `python backend/services/tt_mttr_report.py` 直跑，核对返回摘要里的
   `tickets` / `dropped` 是否符合预期（2026-10-04 基线：原始 37006 / 有 WO 13873 / 入报告 13320，
   剔除 未清除 18、负值 1、>=48h 447、Site Category 空 71、2026-01 前 16）；
2. 用 Excel/WPS COM 打开产物 `CalculateFull()` 后回读 Summary，与 pandas 独立复算逐格对拍
   （一次性脚本见 `TMP/_verify_report.py`，注意 TMP 会被 `tmp_cleanup` 回收，长期需要就搬进正式位置）。
