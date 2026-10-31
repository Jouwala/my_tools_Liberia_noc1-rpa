# olib_soc_report —— OLIB SOC VMAX 例行报表（任务 42 `olib_soc_vmax_report`）

把用户 JupyterLab notebook **`OLIB SOC VMAX Routine Report`**（`/lab/tree/data1/notebook/development/Zeeshan/`）
里「按天循环 SQL → 拼 DataFrame → 写多 sheet Excel」的人工流程，搬成 my_app 里的定时任务。

* 数据通道：直连 VMAX 数仓 **GBase 8a**（`10.123.255.12:5258`，库 `zxvmax`，MySQL 协议 / pymysql）
  —— 客户端与全部实测证据见 [`../vmax_gbase/README.md`](../vmax_gbase/README.md)
* 9 段 SQL 从 notebook **原样移植**（只把分区表名做成参数），sheet 名与 notebook 完全一致
* 默认出**上一个自然月**（cron `30 7 1 * *`，每月 1 日 07:30，即月初出上月月报）
* 产物：`data/olib_soc_report/OLIB SOC VMAX <label>.xlsx` + 运行记录 sqlite + 摘要 JSON
* 顺带把**日粒度 KPI**写进同一个 sqlite 的 `daily_kpi` 表，供
  **90 天经营看板**（`?page=vmaxCxoDashboard_90Days`）取数（见 §11）
* 凭据：分组 **`vmax_gbase`**（设置 → 凭据管理；或 `VMAX_GBASE_PASS` 环境变量）

## 1. 报表块 ↔ sheet 对应（与 notebook 一致）

| 块 | sheet | 内容 | 表族（`_day_` 分区） | 关键指标 |
|---|---|---|---|---|
| `traffic` | `traffic` | 每日总流量 TB | `aggr_5gsa_flow_ciservice` | `SUM(ppb400401001+ppb400401002)/1024^4` |
| `active_user` | `Active_user` | 活跃用户数 | `aggr_ds_250024` | `count(distinct msisdn)` |
| `cache` | `cache` | 缓存 / 非缓存服务器 | `aggr_5gsa_flow_spservice` | 按 5 个缓存 IP 分两类 + 流量 + UL/DL RTT |
| `core` | `GUW` | 核心网元 | `aggr_5gsa_flow_ciservice` | `targetid` → SGW_HQ_122 / SGW_ODC_22 + RTT |
| `video` | `Video` | 视频业务 | `aggr_5gsa_video_spservice` | 3 组 APP 组合 + 有效下载速率 Mbps |
| `game` | `game` | 游戏业务 | `aggr_5gsa_game_spservice` | 3 组 APP 组合 + RTT |
| `tcp` | `TCP` | TCP 质量 | `aggr_5gsa_flow_ciservice` | 建链成功率、UL/DL 重传率/乱序率/丢包率、RTT |
| `top_service` | `df_TOP_Service` | TOP 业务流量 | `aggr_5gsa_flow_spservice` | join `dim_service`，每日 TOP 20 |
| `top_video` | `df_TOP_Video` | TOP 视频 APP | `aggr_5gsa_flow_spservice` | `service_id=5`，每日 TOP 10 |

> 与 notebook 的差异只有两处（都属于工程化，不改口径）：
> ① 未映射到两个 SGW 的 `targetid` 按配置 `core_fold_unmapped_to` 并入 `SGW_ODC_22`
> （等价于 notebook 的 `CASE ... ELSE 'SGW_ODC_22'`，把它留空则改为按 `target_<id>` 分开统计）；
> ② 结果按 `clttime` 升序稳定排序后落盘。

另外会自动追加一张 **`_数据质量`** sheet（见 §5），只在真有异常的日子出现。

## 2. 时间窗口

| `range_mode` | 含义 |
|---|---|
| `last_month`（默认） | 上一个自然月整月（月度任务用这个） |
| `this_month` | 本月 1 号 ~ 今天 |
| `last_n_days` | 最近 N 天（含今天），N = 配置 `days` |
| `weekly` | 上一个完整周（周一 ~ 周日） |
| `explicit` | 用 `--start/--end` 指定的窗口（给了 start/end 就优先） |

三条重要规则：

1. **窗口统一 `YYYYMMDD`**，`--start 2026-08-01` 这类带连字符的写法会自动归一。
2. **超长窗口按「保留最近」截断**：`max_days` 默认 92（数仓 `_day_` 只留约 90 天），
   截断会写进摘要 `warnings`。
3. **缺表自动跳过**：分区缺表（如实测缺失的 `20260907`）或未来空分区不会让报表失败，
   缺哪些天记录在摘要 `missing_days` 与警告里。
4. **当天是移动靶**：当天分区持续累积（实测 2026-09-16 16:50 门户快照 68.31 TB，
   19:50 门户与数仓同为 122.25 TB），窗口含当天时摘要给 `partial_days` + 警告。
   月度任务取上一个自然月，天然不含当天。

## 3. 产物

```
data/olib_soc_report/
├── OLIB SOC VMAX Monthly-Report2026-08.xlsx     # 9 个 sheet（名字同 notebook）
├── olib_soc_report.sqlite3                      # report_runs / block_runs / daily_kpi（看板数据源）
└── last_month_20260801_20260831.summary.json    # 该次运行的完整摘要（含每块行数/耗时/错误）
```

* Excel 先写临时文件再 `os.replace` 原子替换，不会留半截文件；空块写 `note` 占位。
* `persist.keep_csv=true` 时额外导出每 sheet 的 CSV（`<stem>_csv/`）。
* 运行记录表结构见 `_sqlite()`；`report_runs` 一行一次运行，`block_runs` 一行一个块。
* `--no-persist` / `persist=False`：Excel、sqlite、摘要 JSON 全部不写（只返回摘要）。

## 4. 用法

```bash
cd D:/01_RPA/Task/my_app

# 体检：连库 + 各表族分区数量/范围
python -m backend.services.olib_soc_report.olib_soc_report_service --check
python -m backend.services.olib_soc_report.olib_soc_report_service --list

# 默认：上一个自然月（月报）
python -m backend.services.olib_soc_report.olib_soc_report_service

# 指定窗口 / 最近 N 天 / 上一周
python -m backend.services.olib_soc_report.olib_soc_report_service --start 2026-08-01 --end 2026-08-31
python -m backend.services.olib_soc_report.olib_soc_report_service --mode last_n_days --days 7
python -m backend.services.olib_soc_report.olib_soc_report_service --mode weekly

# 只跑几个块 + 看明细（不打开 Excel 也能核对）
python -m backend.services.olib_soc_report.olib_soc_report_service --blocks traffic,GUW --full
python -m backend.services.olib_soc_report.olib_soc_report_service --workers 1 --progress
python -m backend.services.olib_soc_report.olib_soc_report_service --no-persist     # 只看摘要
python -m backend.services.olib_soc_report.olib_soc_report_service --mail           # 强制发信
```

退出码：`0` 正常（含 partial）/ `2` 全部块失败 / `3` 数仓不可用。

Python 侧：

```python
from backend.services.olib_soc_report import run_olib_soc_report
run_olib_soc_report()                                   # 任务入口（无参）
run_olib_soc_report(mode="weekly")
run_olib_soc_report(start="2026-08-01", end="2026-08-31", blocks=["traffic"])
```

## 5. 数据质量自检（人工 notebook 没有这一层）

每块都配了「当日主指标」（`DAILY_METRIC`）。窗口 ≥5 天时，某天主指标 **低于窗口中位数的 50%**
就被记为异常（`suspect_days`），并同时写进：

* 摘要 `suspect_days` 与 `warnings`，日志 warning；
* Excel 追加一张 **`_数据质量`** sheet（列：`block / sheet / day / metric / value / median / ratio`）——
  只在真有异常时追加，正常窗口的 sheet 集合仍与 notebook 完全一致；
* 邮件正文的「提示」区（发信开启时）。

**只提示、不改数据**（数仓里是什么就是什么，避免"自动清洗"掩盖问题）。阈值 0.5 的依据：
正常日流量波动 ±10%、活跃用户 ±15%，而实测异常日掉到中位数的 0.08%~0.3%。

> 首次跑 2026-08 月报就抓到一条上游数据问题：**8/11~8/14 活跃用户数从 ~47.4 万掉到
> 102,786 / 1,570 / 630 / 401**，而同期流量（287~292 TB）与 TCP 成功率（91% 左右）完全正常。
> 查数仓确认是 `aggr_ds_250024` 当天只有 1.3~5.3 万行（正常 2,049 万行）——**上游采集/ETL 缺数**，
> 不是网络事件。人工看 Excel 很容易把 401 当成一次全网故障，这层自检就是为了避免这种误读。

## 6. 配置（`backend/services/olib_soc_report_config.json`，设置页可改）

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 是否启用 |
| `gbase` | 见文件 | 连接串（host/port/user/database/charset/超时）；**密码不写在这里** |
| `credential_key` | `vmax_gbase` | 凭据分组名 |
| `range_mode` / `days` | `last_month` / 30 | 窗口模式与 `last_n_days` 天数 |
| `max_days` | 92 | 窗口上限，超出按保留最近截断 |
| `granularity` | `day` | 分区粒度（`day`/`hour`；小时级要用 `_hour_` 表） |
| `workers` | 3 | 并发**连接**数（每线程一条连接，保持对生产 MPP 库温和） |
| `cache_server_ips` | 5 个 IP | 缓存服务器判定 |
| `core_target_names` | 50331658/50331660 | targetid → 网元名 |
| `core_fold_unmapped_to` | `SGW_ODC_22` | 未映射网元归档；留空则按 `target_<id>` 分开 |
| `video_apps` / `game_apps` | 3+3 组 | `(service_id, subservice_id)` 组合 |
| `top_service_limit` / `top_video_limit` | 20 / 10 | 每日 TOP 条数 |
| `blocks.*` | 全 true | 9 个块开关 |
| `persist.*` | write_excel/write_sqlite true | 落盘开关（`keep_csv` 默认 false；`write_kpi` 控制看板 KPI 入库） |
| `kpi_sync.days_back` / `only_missing` / `refresh_last_days` | 7 / true / 1 | 每日 KPI 增量的回看天数、「只补缺口」、以及「窗口内最新 N 天重取」（防数仓晚到/任务漏跑） |
| `mail.*` | `enabled=false` | 可选邮件投递（见 §8） |

环境变量：`OLIB_SOC_RANGE_MODE`、`OLIB_SOC_WORKERS` 可临时覆盖；`VMAX_GBASE_USER/PASS` 覆盖凭据。

## 7. 注册与调度

* `backend/task_registry.py`：
  * `task_id=olib_soc_vmax_report`，loader =
    `backend.services.olib_soc_report.olib_soc_report_service.run_olib_soc_report`（无参），
    默认 cron `30 7 1 * *`（月报）；
    **`recent_runs_provider` 指向本模块的 `recent_runs_for_task`**（见 §12）；
  * `task_id=olib_soc_kpi_daily_sync`，loader =
    `...run_olib_soc_kpi_sync`（无参），默认 cron `20 6 * * *`（每天补看板 KPI 缺口 + 重取最新 1 天）；
  * 两者 category 都是 `olib_soc` → `CATEGORY_GATEWAY["olib_soc"]="vmax_gbase"`。
* `backend/services/task_configs_registry.py`：注册 `ConfigResource`（设置页可视化编辑/导入导出）。
* ⚠️ 新增任务只在进程启动时注册（`backend/main.py`、`backend/worker.py`），
  需要重启后端/worker 后才出现在任务列表（重启命令：`python restart_workers.py --reason "..."`）。
* ⚠️ **两个任务必须同时登记进 `backend/worker_watchdog.py` 的 `GROUP_TASK_MAP`**（2026-09-18 补录：
  `olib_soc_kpi_daily_sync` / `olib_soc_vmax_report` → **m 组**，GBase 直连、只写本模块自己的 sqlite，
  与 m 组其它任务无会话/写库冲突；分组清单在 watchdog 进程内存里，改完必须
  `python restart_workers.py --mode watchdog --force` 才生效（**需管理员权限**，否则旧 watchdog
  进程杀不掉会静默失败，要回查 `log/worker_restart_marker.log` 确认 pids 真的变了）。上线时只写了 `TASK_SPECS` 的后果是
  **静默停摆**：无任何 worker 认领→队列 pending 常坐→占住 `enqueue_task` 的单飞名额→之后每次调度
  全部被挡；`task_execution_log` 一条记录都没有，而看板只是“数据没更新”，不报错不告警。
  现在三道防线兼得：`tests/test_worker_group_coverage.py`（5 个用例：任务覆盖/重复/幽灵 id、三处组集合一致、
  8790 任务同组、前端任务帮助与分组表一致；不依赖 pytest：`python tests\test_worker_group_coverage.py`）
  + `worker.py::_expire_orphan_pending`
  （pending 超 6h 无人认领则置 failed 并释放单飞名额）+ `services/task_health_alert.py`
  （每小时巡检后把“未归组 / 无执行记录 / 队列滞留 / 成功逾期”按翻转去重主动微信+邮件通知）。
* 与任务 41 `vmax_multi_data_sync`（门户接口，小时级）互补：41 管实时趋势，42 管业务维度月报/看板。
  41 与 `cxo_dashboard_cache_sync`、`vmax_cxo_daily_sync` 共用本机 8790 VMAX 单会话代理，
  2026-09-18 从 n 组拆出独立成 **v 组**（组内串行、不被 sp_data_sync 这类 1.5~2h 长任务堵住）。

## 8. 邮件投递（默认关闭）

`mail.enabled=true` + `mail.recipients=[...]` 后，每次运行会把 Excel 作为附件发出去
（正文带各 sheet 行数/状态小表 + 数据质量提示）。发信账号取凭据分组 `mail.credential_key`
（默认 `mail_126`，smtp.126.com:465 SSL）。**发信失败只记日志、不影响报表产出**
（`summary["mail"]` 里有结果）。投递用自带的 smtplib 实现，**没有**复用
`report/mail_126.py`（那个把收件人写死成 Liberia Orange TT Summary 报表的名单）。

## 9. 自测与验证

```bash
python tests/test_olib_soc_report.py            # 离线 109 项（不连库/不发信）
python tests/test_olib_soc_report.py --live     # 追加连库取数 + 与门户口径对账（共 121 项）
```

离线覆盖：日期/分区工具、只读校验、连接参数优先级、5 种窗口 + 截断、9 段 SQL 组装与
占位符替换、逐日分片与缺表/单日失败容错、数据量体检（含 2026-08-11~14 真实案例回归）、
Excel（openpyxl 回读 sheet 名与表头、`_数据质量` 表）与 sqlite 落盘、编排状态机
（ok/partial/failed/no_block/unavailable）、无参调用走默认月报、注册集成。

实测（2026-09-16）：

* 单日全 9 块：**6.7 s / 21 次 SQL / 41 行**（traffic 2.3s、cache 5.4s、其余 <1.5s）；
* **2026-08 全月月报**：`ok`，9 块全成功，**1,333 行**，291 次 SQL，墙钟 **236 s**
  （`workers=3`；cache 最慢 136~235 s，traffic 最快 5~23 s），产出
  `OLIB SOC VMAX Monthly-Report2026-08.xlsx`（37 KB，10 个 sheet 含 `_数据质量`）；
* 门户口径对账：2026-08 **全月 31 天逐日完全一致**（最大偏差 0.0000 TB；全月 8892.53 TB
  与门户 8892.54 TB 的 0.01 TB 差是逐日四舍五入累加），2026-09-11~09-15 同样逐日一致；
* 幂等：同窗口重跑覆盖同名 Excel，sqlite 里以同一 `run_id` 覆盖 `report_runs`，
  `block_runs` 按运行追加（用 `DELETE`+`INSERT` 的幂等写法，不依赖表约束）。

## 10. 已知边界

* 数仓只留约 90 天：更早的数据拿不到（门户一样），要长期归档需自行把月报 Excel 留存
  （notebook 里那套 2026-05 的窗口现在已经取不到了）。
* `aggr_5gsa_flow_spservice` 的 `server_ip` 维度很大（实测单日 245 万不同 IP），
  `cache` 块相对最慢；如嫌慢可只保留需要的缓存 IP 或降为抽样。
* 单位换算按 notebook 原样（`/1024^4` 记为 TB）；如需 TB(10^12) 口径需改 SQL。
* 小时/15 分钟级块未纳入（notebook 没有）；`granularity=hour` 时表名会换成 `_hour_`，
  但各块 SQL 的聚合口径（按天分组）仍需按需调整。
* 数据质量自检是「主指标相对中位数」的粗筛，只做提示；阈值可用 `SUSPECT_RATIO`/
  `SUSPECT_MIN_DAYS` 调整。
* 对外投递目前只有邮件；FTP/SFTP 需额外依赖 `paramiko`，未做。

## 11. 日粒度 KPI 库（90 天看板的数据源）

`olib_soc_kpi_store.py` 在同一个 sqlite 里维护 `daily_kpi` 表（一天一行，主键 `day`，ISO 日期），
供 `?page=vmaxCxoDashboard_90Days` 使用；接口 `/api/olib-soc-dashboard/*` 只读（`query_only=ON`）。

**两次写入时机**

| 时机 | 任务 | 行为 |
|---|---|---|
| 每月 1 日 | `olib_soc_vmax_report` | 月报跑完顺带把整月日 KPI 入库（`persist.write_kpi=true`） |
| 每天 06:20 | `olib_soc_kpi_daily_sync` | 只跑看板需要的 7 个块，**只补库里缺的日期 + 关键指标为 NULL 的残缺日 + 重取最新 1 天**（默认回看 7 天），不出 Excel |

> 为什么是 06:20（服务器 UTC）而不是 00:20：数仓「前一天」的分区不一定在零点后立刻完成
> （实测当天分区在日内持续累积），取到未完成的一天会把偏低的日值永久写进库。放在早班
> 批次（与 `ems_kpi_daily` 05:20 同批）留出余量，另有 `kpi_sync.refresh_last_days=1`
> 每次运行都把窗口内最新的一天重取一遍兜底。跑完即可在
> `?page=vmaxCxoDashboard_90Days` 看到「昨日」数据（当天不纳入：分区仍在累积）。

每日任务是**幂等自愈**的：某天数仓分区晚到/同步失败，第二天会自动补上；库里不缺就零查询直接返回
（实测 `refresh_last_days=0` 时第二次调用 `up_to_date`、0 次 SQL）。手动命令：

「缺口」有**三类**，只看前两类会漏事故（2026-09-24 加固，2026-10-11 再次加固）：

| 类型 | 判定 | 说明 |
|---|---|---|
| 整天没有行 | `gap_days()` | 任务被跳过 / 数仓分区晚到 |
| 有行但关键指标为 NULL（**窗口内**） | `incomplete_days()` | 单个块临时取数失败仍写入一行，那列为 NULL |
| 有行但关键指标为 NULL（**全表**） | `all_incomplete_days()` | 同上，但不限回看窗口 —— 补滑出窗口的历史残留 |

第三类为什么必须单独有：`incomplete_days()` 只看最近 N 天（默认 7），一旦某个残缺日
滑出窗口**就再也补不到**。真实遗留：2026-09-07 的 `traffic_tb` 因超出窗口而残留了整整一个月，
每天同步都"看不见"它。每日同步现在会把 `all_incomplete_days()` 捞出、且不在窗口内的天
**单独跑一次**（不并进主 `gaps`，否则 `gaps[0]~gaps[-1]` 张成的区间会暴涨、把中间几十天重查）。

前两类的真实事故：2026-09-18~23 的 `active_user` 连丢 6 天，看板「Active Users」停在 17 号；
当时 `blocks_ok` 已从 7 掉到 6 但**不报错**，`gap_days` 也认为这天不缺口，故 NULL 永久残留。
判定列见 `REQUIRED_COLUMNS`（**全部主数值列**：traffic/active_user/video/video_mbps/
cache/noncache/tcp 及三类 TCP 质量列/game —— 任一列为 NULL 都会让对应卡片「少一天」）。

**取数侧同步加固（2026-10-11）**：`run_block()` 新增 `days_empty` —— 把「该块本应有数却没拿到」
的天（**分区缺失**、或**分区在但查出 0 行**）如实上报，块降级为 `partial`（`BLOCKS_ALLOW_EMPTY_DAY`
里的 TOP 业务/游戏块除外，它们天然可能整天无产出）。旧逻辑只把「查询抛异常」记为 error，
"分区在但查出空"会让块仍是 `ok`，数据缺了一天却无人知晓。

**看板侧暴露（2026-10-11）**：`coverage` 新增 `incomplete_days`（行在但关键列为 NULL 的天），
`/api/olib-soc-dashboard/status` 暴露其计数；页面顶部在存在缺口日时显示「数据完整 x/y 天 · 缺 n 天」
提示条，明细表对应行标「数据残缺」。

**排查手法**：`SELECT day, blocks_ok FROM daily_kpi ORDER BY day DESC`，`blocks_ok` 小于 7 的那天就是残缺日；
接口 `curl /api/olib-soc-dashboard/status` 看 `incomplete_days` 计数。

```bash
python -m backend.services.olib_soc_report.olib_soc_report_service --sync-kpi              # 补最近 7 天缺口 + 全表历史残留
python -m backend.services.olib_soc_report.olib_soc_report_service --sync-kpi --days-back 30 --force
python -m backend.services.olib_soc_report.olib_soc_report_service --start 2026-08-11 --end 2026-08-14 --kpi-only
```

**落库口径（原始值落库、派生值查询时现算）**

* 库里只存 SQL 直接查得到的量（TB / 用户数 / 百分比 / Mbps）；「视频占比」「缓存占比」在查询时
  用 `分子/分母` 现算 —— 这样**周汇总永远是 `sum(分子)/sum(分母)` 的精确加权**，而不是「每天占比再平均」。
* 视频下载速率按**视频流量加权**（`sum(速率×流量)/sum(流量)`，只是 `wavg:video_tb`）。
* 周粒度：流量类求和、用户数取均值、比率/速率/时延按流量加权；最后一周不满 7 天会在图上标注天数。
* 只统计**已完成日**（最新一天=昨天）：当天分区仍在累积，纳入会让"昨天"忽高忽低。
* 单位换算：TB→GB ×1024、Mbps→kbps ×1000、用户→K ×0.001。
* 写入用 `COALESCE(excluded.x,x)` 的补丁式 upsert：只跑部分块补数时不会把当天其它指标清成 NULL。
* 看板把 `suspect_json`（上游缺数标记，见 §5）显示成趋势图上的淡红竖带 + 明细表角标，
  避免把「数据缺失」误读成「业务暴跌」。

**分业务「本地 / 海外」服务器分流（看板下钻，2026-10-20 新增）**

* 独立一步 `persist_app_offload()`，**不进 `BLOCKS`/`SHEET_ORDER`**：那 9 个块是月报 Excel 的
  契约（与 notebook 逐日对账过），这份明细只服务看板的点击下钻，加第 10 个块等于改月报结构。
  挂在 `run_olib_soc_report` 里 KPI 落库之后，所以月报全量跑与每日增量跑都会顺带写入。
* 落库到同库的新表 `daily_app_offload(day, appname, total_tb, local_tb, abroad_tb, unknown_tb)`，
  主键 `(day, appname)`，重跑覆盖；实测规模：单日 3000~3800 个业务（绝大多数是长尾小流量），
  90 天约 **29 万行 / +30MB**，接口一次窗口聚合 0.2 秒（点一次才查一次）。
  **全量业务都落库、不按流量阈值截断** —— 截断会让下钻表格的合计比 `traffic` 卡片少
  0.3%（实测 0.46 TB），对不上账。TOP N 的取舍放在接口层（其余并进「其它」，合计仍按全量算）。
  对账实测：2026-10-19 下钻合计 140.605 TB vs `daily_kpi.traffic_tb` 140.69 TB，差 0.085 TB
  （0.06%，来自每行 `round(...,4)` 的累加），无业务被漏。
* **判定口径用 `sp_country_id`（服务器所在国家）而不是 IP 白名单**：`LOCAL_COUNTRY_ID = 32`
  （= Liberia，取自 `dim_comm_country_scr`）。三桶互斥且相加=当日全量：
  `local` = 国家命中 32；`abroad` = 有 server_ip 且国家不是 32；`unknown` = server_ip 或
  国家解析不出来。接口里「本地占」的分母是 `local + abroad`（**剔除 unknown**），
  因为 DPI 取不到服务器地址的那部分（HTTPS/QUIC/UDP，实测约占全天 9%）既没走本地也没走海外。
* 为什么不用 IP 清单：上面「缓存占比」那 5 个 IP **只是 Facebook 视频那几台**。
  2026-10-19 实测两套本地缓存集群：`41.191.107.0/24`（Meta：Facebook 视频 48.22 /
  Instagram 1.57 / **WhatsApp 3.21 在 `.227/.226/.224`，白名单一个没算**）与
  `196.49.16.0/24`（Google：**YouTube 7.84 / Play 1.10 / Ads 1.01，整段不在白名单**）。
  国家维度一次覆盖两套，且以后加缓存机器不用再改代码。
* join `dim_service` 前**先按 `(serviceid, appid)` 去重**：`dim_service` 同一个
  (appid, serviceid) 有多行（不同 `app_content`），直接左连会把流量按行数放大
  （实测同一天的 APP 合计会算成 185 TB / 真实 140 TB）。
* 只读接口 `GET /api/olib-soc-dashboard/app-offload?days=90&as_of=YYYY-MM-DD&top=40`，
  返回「最新一天」与「窗口累计」两套行 + 各自合计；`as_of` 不是真实日期直接 400（不静默回退）。
  看板 `?page=vmaxCxoDashboard_90Days` 点「缓存服务器流量占比」或「总流量」卡片/图表面板
  即弹出该表格（2026-10-30 起总流量卡也走这份数据，见下一节）。
* **历史回补**：这张表是新增的，库里已有的天数不会自动长出来，数仓只留约 90 天，越早跑越全。
  两条路：
  * 正式入口 `python -m backend.services.olib_soc_report.olib_soc_report_service --sync-kpi --days-back 90 --force`
    —— 会把 7 个块 × 90 天整体重取（约 630 条 SQL，月报 30 天实测 236 秒，这里十几分钟），
    并按 COALESCE 重写 `daily_kpi` 的既有日值（结果应当一致，但确实动了看板现有数字）。
  * **只补这张表**（2026-10-20 首次回补用的就是这个，对生产 MPP 温和得多）：逐日调
    `fetch_app_offload(client, cfg, [day], run_id)` + `upsert_app_offload(rows)`，跳过
    `daily_kpi` 已覆盖之外没有分区的天。实测 90 天 **343 秒 / 181 条 SQL / 29 万行**，
    完全不碰 `daily_kpi`。幂等，中断后重跑只补没落库的天。
  此后每日增量任务 `olib_soc_kpi_daily_sync` 会自动带上（挂在 KPI 落库之后）。
* 注意 `GBase` 的 `decimal(65,0)` 经 pymysql 回来是 `Decimal`，**直接绑给 sqlite 会
  `ProgrammingError`**，落库前一律 `_to_float()` 转 float（`§13c` 离线用例专门盯这条）。

**视频 / 游戏逐 APP 明细（看板下钻，2026-10-30 新增）**

* 明细层整体在 **`olib_soc_app_detail.py`**（2026-10-30 从 `olib_soc_kpi_store` 迁出并扩成
  三个 builder 共用一份载荷契约：`day` + `window_agg` 两套行 + TOP-N 之外的并进「其它」+
  合计行，前端弹窗按列配置渲染 —— 再加一张下钻卡 = 一张明细表 + 一个 builder + 一份列集）。
  `daily_app_offload` 的建表/写入/builder 也随迁到该模块，行为契约不变。
* 取数路径与 offload 不同：`video` / `game` 块的 SQL **本来就按 appname 分组**，结果帧里
  现成带着逐 APP 行，`persist_app_detail()` 直接从帧提取落库，**不增加任何数仓查询**；
  只处理这次真正跑过的块（帧缺列/空帧不炸，pandas 的 NaN 落库前归一成 NULL）。
* 两张新表：`daily_video_app(day, appname, traffic_tb, thr_mbps)` 与
  `daily_game_app(day, appname, traffic_tb, ul_rtt_ms, dl_rtt_ms)`，主键 `(day, appname)`，
  重跑覆盖。规模：每天各 3 个 APP（配置 `video_apps` / `game_apps` 清单），90 天各 270 行。
* 只读接口 `GET /api/olib-soc-dashboard/video-apps` / `/game-apps`（与 app-offload 同构，
  `as_of` 非法日期同样 400）。窗口视图口径与卡片周汇总一致：流量求和、速率/RTT 按流量加权；
  video 的 `share_pct` 分母取 `daily_kpi.traffic_tb`（当日全网总流量），
  三家合计 ≈「视频流量占比」卡片。
* 前端下钻入口在 `vmax_cxo_dashboard_90days.html` 的 `DRILLS` 配置表（一处登记六张卡）：
  总流量 + 缓存占比 → `/app-offload`；视频流量 / 视频速率 / 视频占比 → `/video-apps`；
  游戏流量 → `/game-apps`。弹窗标题/口径说明/列集随卡走。
* **续写（2026-10-31 修正，务必留意）**：每日任务 `olib_soc_kpi_daily_sync` 原先调用
  `run_olib_soc_report(..., kpi_only=True)`，那条路径**只写 `daily_kpi`**，明细表永远不会
  增长（只能靠 `--details-only` 手工补）。现在改成 `kpi_only=False` 走完整落库路径，
  并按 `olib_soc_app_detail.gap_days()` 单独算一套「明细缺口」：窗口内 video/game
  两张表**任一张**缺的天 + 最新 `kpi_sync.refresh_last_days` 天重取。语义与卡片层
  严格对齐 —— `refresh_last=0` 时明细也不重取（保证「无缺口 = 零查询」）。
  任务摘要新增 `detail_requested_days` / `app_detail` 两个字段，明细续写失败要能在
  任务历史里看见。
* **缓存占比口径（别混用）**：卡片 `cache_ratio_pct` = 缓存在 `cache_server_ips`
  （默认 5 台 Facebook 缓存 IP）上的流量 / 总流量；offload 下钻里的 `local_pct` =
  服务器所在国家为利比里亚（`sp_country_id=32`）的流量 /（本地+海外），覆盖两套缓存
  集群，数值天然更高（实测 90 天窗口 44.95% vs 卡片 36.56%）。两者**不是同一个指标**，
  弹窗里已写进口径提醒，不要拿它们互相对账。
* **「最新一天」一律夹到昨天**（`_window_bounds`，与卡片层 `end = today - 1` 同一约定）：
  当天分区仍在累积，白天点开不能看到半天数据，「数据截至」也不能跑到卡片前面。
* **历史回填**：CLI 新增 `--details-only`（默认块 video,game）——只把结果帧落明细表，
  不写 `daily_kpi` / `app_offload` / Excel / 邮件（部分块的结果若照常走 persist_daily_kpi，
  会把 `blocks_ok` 从 7 覆盖成 2）。2026-10-30 首次回补 90 天：video/game 各 270 行，
  对账 video 流量/速率误差 0.000%、share 0.061%、game 0.000%（见 `§13d` 离线用例）。
  配置的 APP 清单（`video_apps`/`game_apps`）变更后重跑一次即可补齐新 APP 的历史：

  ```bash
  python backend/services/olib_soc_report/olib_soc_report_service.py \
      --details-only --mode last_n_days --days 90
  ```

指标字典在 `olib_soc_kpi_store.METRICS`（10 个：4 个 CEO 主卡片 +
3 个业务结构 + 3 个网络质量），字段含中英标题/单位/小数位/越大越好/周汇总方式，
后端接口、前端卡片、周趋势、明细表全部引用这一份定义。

## 12. 任务列表「最近运行」兜底（2026-10-15）

**现象**：任务管理页里 `OLIB SOC VMAX Routine Report` 显示 **No Record / 未记录**。

**原因**：任务列表的最新执行记录来自主库 `task_execution_log`，该表按
`TASK_LOG_RETENTION_DAYS`（默认 **7 天**）定期清理（`backend/services/task_runner.py`）。
月报任务 cron 是 `30 7 1 * *`，**每月只跑一次** —— 月中查看时它的记录早已被清掉，
前端 `classifyTaskStatus()` 见不到任何记录，遂判为 `unknown` → No Record。
**报表本身一直是正常的**：`OLIB SOC VMAX Monthly-Report*.xlsx` 与 `report_runs` 都在。

**修法**（不是给保留期开口子，而是让任务自报产物库里的运行）：

* 通用机制在 **`backend/services/task_stats.py`**：
  `register_recent_runs_provider(task_id, provider)` 登记「最近运行」提供者；
  `_fetch_latest_runs()` **只在日志表里该任务一条记录都没有时**才调用它 ——
  日志表仍是唯一主源，已有记录的任务完全不受影响。
* 本模块提供 `recent_runs_for_task(task_id)`：从 `report_runs` 读该任务的最近若干次运行，
  字段与前端 `RunRecord` 对齐（`started_at/completed_at` 转 ISO `T` 分隔）。
* 归属判定靠 `report_runs.invoked_by`（本次运行由哪个任务发起）：每日 KPI 同步会借道
  `run_olib_soc_report(kpi_only=True)` 往 `report_runs` 写 `explicit_*` 行，**必须排除**，
  否则月报任务的列表会显示一堆同步记录。存量旧行 `invoked_by` 为 NULL，
  按 `mode='last_month'` 兜底认定为月报。
* 注册走 `backend/task_registry.py` 的 `TASK_SPECS` 字段
  `recent_runs_provider=(模块路径, 函数名)`，由 `register_all_tasks()` 懒加载注入
  （只在首次查询到该任务且日志无记录时才 import 本模块）。

**自测**：`python tests/test_olib_soc_report.py` 第 9 节（13 项）覆盖：
`invoked_by` 补列、排除同步行、倒序、成败判定、字段对齐、库缺失/提供者异常降级。

**⚠ 扩展新低频任务时**：同样在 `TASK_SPECS` 加 `recent_runs_provider`，
并让提供者只返回**本任务自己发起**的运行；不要改日志表保留期 —— 那会让所有任务的
历史一起变长，也会让主库膨胀。
