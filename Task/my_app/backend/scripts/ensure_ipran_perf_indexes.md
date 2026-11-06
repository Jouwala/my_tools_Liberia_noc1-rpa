# ensure_ipran_perf_indexes —— 给 ipran_ume 补查询侧索引

一句话：给本机 PG `ipran_ume` 的 6 张 15 分钟 KPI 表建「以看板等值列打头」的索引，
把 IP RAN 四个看板的冷取从秒级/十几秒压回亚秒。幂等、可重跑、用
`CREATE INDEX CONCURRENTLY` 不阻塞采集写入。

```powershell
cd D:\01_RPA\Task\my_app
# 只看要执行什么 + 记录当前计时基线（不建索引）
python -m backend.scripts.ensure_ipran_perf_indexes --dry-run --measure
# 实建（建完自动 ANALYZE 并再计时一次做前后对比）
python -m backend.scripts.ensure_ipran_perf_indexes --measure
# 只补指定表
python -m backend.scripts.ensure_ipran_perf_indexes --tables Metro_ring_me_15mins
```

## 为什么原来慢

采集侧建的唯一索引是 `("Begin Time", "ME", "Measure Object"[, "Counter"])` ——
前导列是业务时间，这对 upsert 幂等正好，但看板 SQL 的谓词是
`WHERE "ME"=? AND "Measure Object"=? AND "Begin Time" 区间`，**等值条件用不上前导列**，
于是查一个端口要扫完整个时间区间（`Metro_ring_me_15mins` 31 天 ≈ 340 万条索引项 +
同样量级的回表取 `Counter Value`）再丢掉 99.9%。成本随窗口线性放大：
5 天 1.2s、31 天约 10s。`finebi_metro_ring` 默认窗口 2026-11-05 从 7 天放到 31 天后，
整页冷取因此到 9~21 秒。

## 建了什么，效果如何（2026-11-05 实测）

| 表 | 索引列 | 依据 | 建索引耗时/体积 | 计时：前 → 后 |
|---|---|---|---|---|
| `Metro_ring_me_15mins` | `("ME","Measure Object","Begin Time")` | metro_ring c1–c8 的 WHERE | 42.3s / 288 MB | 7714ms → **29ms** |
| `Gbarnga_Buchanna_RIA_Kakata_me_15mins` | `("ME","Begin Time")` | ipran_4region 8 个组件是**区域聚合**，只按 ME 过滤 | 1.7s / 3.9 MB | 152ms → 43ms |
| `Banjor_ELWA_me_15mins` | `("ME","Measure Object","Begin Time")` | ipran_hq c5/c6 | 2.4s / 26 MB | 126ms → 27ms |
| `IPCORE_HQ_ODC_bnctp_15mins` | `("ME","Measure Object","Begin Time")` | ipran_hq c1/c2（pivot 再按 Counter 分） | 0.4s / 1.8 MB | 205ms → 14ms |
| `OLT_bnctp_15mins` | `("ME","Measure Object","Begin Time")` | ipran_hq c3 | 0.7s / 6.5 MB | 620ms → 33ms |
| `HQ_M6K_FW_bnctp_15mins` | `("ME","Measure Object","Begin Time")` | ipran_hq c4 | 0.1s / 0.7 MB | 46ms → 23ms |

整页效果（`/api/native-boards/<slug>?force=1`，默认 31 天 + 小时聚合）：
`metro_ring` 9~21s → **0.32s**，`ipran_hq` 0.74s → 0.14s，`ipran_4region` 0.94s → 0.25s。
新增磁盘占用合计约 329 MB。

Gbarnga 那条**故意只有两列**：它的 8 个组件不指定 `Measure Object`，多给一列只是白付
索引体积与写放大 —— 不为「以后也许用得上」提前抽象。

## 规矩

1. **不进 Alembic**。这 6 张表由采集服务运行时 `CREATE TABLE IF NOT EXISTS` 建
   （`grep -rl ipran_ume alembic/versions/` 为空），索引同理走本脚本；
   新机器、或库被重建后跑一次即可。
2. **别删那个唯一索引**：`ipran_ume_kpi_service.mirror_rows_to_local` 的
   `ON CONFLICT` 依赖它，删了 upsert 直接报错并可能造出重复行。
3. **`CONCURRENTLY` 失败会留 INVALID 索引**（不用于查询，但重名会让下次建索引失败）。
   本脚本每次回查 `pg_index.indisvalid`，非空就退出码 1 并打出清理语句：
   `DROP INDEX CONCURRENTLY ipran_ume."<索引名>";` 然后重跑。
4. **给看板加下推表时索引要跟着配**（`PLAN` 里加一条 + 按真实谓词定列序），
   否则新表又退回全区间扫。表清单与 `dashboard_service.PUSH_DOWN_TABLES` 的对应关系
   由 `pg_schema_freshness.PG_SCHEMA_CHECKS` 那条守卫间接管着（加表先要配巡检）。
