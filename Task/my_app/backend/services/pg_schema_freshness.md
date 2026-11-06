# 本机 PG schema 新鲜度巡检（pg_schema_freshness）

> 2026-11-05 新增，由 `db_freshness_check`（每小时 15 分）调用，也可单独跑。
> 入口：`backend/services/pg_schema_freshness.py::check_all`

## 背景：一次「页面看起来正常、数却是断的」事故

2026-11-04 把 IP RAN 四个看板（`finebi_metro_ring` / `finebi_ipran_hq` /
`finebi_ipran_4region` / `finebi_fw_daily`）的数据源从远端 SQLite 切到**本机 PG 的
`ipran_ume` schema**（远端单表全历史查询常 90s 超时，本机聚合 0.4s）。
2026-11-05 把默认时间窗口从 7 天改成 31 天时实测发现：

| 侧 | 近 31 天覆盖 | 说明 |
|---|---|---|
| 远端权威库 `ipran_ume_kpi.sqlite3` | **32/32 天齐全**（`HQ_M6K_FW` 每天 192 行、`IPCORE_HQ_ODC` 每天 768 行） | 采集一直没断：`ipran_kpi_sync` 有效 cron 是每小时 `0 * * * *` |
| 本机 PG `ipran_ume` | **只有 10~12 天**（`Metro_ring` 从 2026-10-27 起才有） | 中间断的日子永远不会自己长回来 |

原因是采集侧的 `mirror_rows_to_local` 是**只追头部水位**的增量镜像：只写
`本机 MAX("Begin Time") - 2h` 之后的行。所以 11-04 之前那 20 天的洞是永久性的，
除非有人显式回填。

而这件事**当时没有任何巡检能查到**：

| 既有检查 | 查的是谁 | 为什么查不到 |
|---|---|---|
| `db_freshness_check.REMOTE_CHECKS` | 远端库的水位 | 远端一直是新的 → 永远绿 |
| `db_freshness_check.LOCAL_CHECKS` 的「ipran 本地回退库」 | `data/ipran_ume/ipran_ume_kpi.sqlite3` | `MY_APP_DB_MODE=pg` 下这个文件早就不写了 |
| 判据本身 | 「最新 Begin Time 够不够新」 | 天生看不见「中间少了 20 天」 |

本模块补的就是这两点：**查看板真正读的那个库**，并且**按天判覆盖**。

## 判据

对清单里每张表：

1. **水位**：`MAX("Begin Time")` 距 now 是否超过 `max_age_hours`（IP RAN 每小时采集，容忍 6h）。
2. **逐日覆盖**：近 `lookback_days` 天（31 = 与看板默认窗口同档）逐日是否有行；
   判定只到**昨天**为止 —— 今天还没过完，按天判必然「缺」。
3. **偏薄日**：当日行数 < 窗口内峰值 × `thin_ratio`（0.5），多为采集只跑了一半。
4. **缺失日分类**（关键，否则运维不知道该往哪边使劲）：拿远端权威库逐日
   `LIMIT 1` 对照一次，拆成
   - **远端有、本机没有** → 镜像洞，可以补；reason 里直接给出补齐命令；
   - **远端也没有** → 采集断档，回填补不了，要查那几天 `ipran_kpi_sync` 的执行记录；
   - **远端对照未取到**（API 不可达/超时）→ 标记待复核，不硬下结论。

单次成本实测：大表 `Metro_ring_me_15mins`（回看 100 天、含 12 次远端对照）6.2s。
按 31 天窗口跑更省。每表一次 `GROUP BY 日` 全区间扫描，不加逐日 31 次探测。

## 与其它约定的关系

- **只读**：只发 SELECT；连不上 / 报错一律记 `read_error`，**不把巡检置失败**
  （沿用 `db_freshness_check` 的「数据滞后 ≠ 巡检失败」，避免 auto_retry 空转）。
  本机 PG 属 my_app 自有库，可以写；**VMAX 数仓（`zxvmax`）仍是只读红线**，
  本模块与那条链路无关。
- **补洞的命令**：回填脚本 `backend/scripts/backfill_ipran_pg.py` 有两种模式
  （不传 `--since` = 追水位；传 `--since` = 补历史洞、不按水位裁行）。
- **守卫**：`tests/test_doc_consistency.py::test_pg_freshness_covers_pushdown_tables`
  要求 `dashboard_service.PUSH_DOWN_TABLES` 里每张表都必须出现在本模块
  `PG_SCHEMA_CHECKS[].tables` 里 —— **给看板加下推表却忘了配巡检，提交会被拦下**。
  清单只用字面量（不含 lambda），守卫才能 `ast.literal_eval` 静态解析。
- **页面侧**：本机库缺日子时看板会**常驻**显示告警（数据来自
  `dashboard_service._coverage_from_widgets` 写入的 `meta.coverage`），
  按仓库 UI 硬要求：解释怎么算的可以收起，算错了/算不全必须常驻可见。

## 清单（当前）

| schema | 表 | 窗口 | 水位容忍 | 产出任务 |
|---|---|---|---|---|
| `ipran_ume` | `Metro_ring_me_15mins`、`Gbarnga_Buchanna_RIA_Kakata_me_15mins`、`Banjor_ELWA_me_15mins`、`IPCORE_HQ_ODC_bnctp_15mins`、`OLT_bnctp_15mins`、`HQ_M6K_FW_bnctp_15mins` | 近 31 天 | 6h | `ipran_kpi_sync`（`0 * * * *`） |

## 运行

```powershell
cd D:\01_RPA\Task\my_app
# 单独跑一次（结果直接打印，便于人工核对）
python -m backend.services.pg_schema_freshness
# 随小时巡检一起跑：无需额外操作，db_freshness_check 已调用
```

输出：`results` 里每张表一条 `ok / STALE / read_error`；发现项进 `stale`
（进任务执行历史与巡检日志，`GET /api/tasks/db_freshness_check/history` 可查）。

> ⚠ **发现项目前不会主动推送**。`db_freshness_check.py:1206-1218` 的
> `task_health_alert.evaluate_and_notify()` **只吃 `task_health_findings`**
> （分组缺失 / 静默停摆 / 队列滞留 / 成功逾期），数据滞后类（含本模块的缺档）
> 只进 `result["stale"]`，没人看历史就等于没报。
> 现在能被人看到的地方是**看板页顶部的常驻告警条**（`meta.coverage` →
> `NativeBoard` 的 `nb.coverageTitle`），也就是「用户打开那一页时会被提醒」。
> 要做到「断了不打开页面也通知」，得把本模块的缺档项也送进推送通路 ——
> 那是产品决定（数据滞后类一旦全推容易刷屏），需要单独定范围与去重口径。


## 依赖

见 `requirements_pg_schema_freshness.txt`。核心判定只用标准库；
取数经 `backend.database`（PG）与 `backend.services.remote_readonly`（远端只读 API）。
