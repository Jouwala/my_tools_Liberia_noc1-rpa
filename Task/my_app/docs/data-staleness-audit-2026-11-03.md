# 数据停更审计报告（2026-11-03）

> 触发问题：门户 CR 统计长期停在 86；修复过程中被问及「还有没有类似的数据没真正更新」。
> 本文档记录**全库审计方法、发现清单、已修项、以及判定为「正常/误判」的项**，
> 供后续排查时直接对照，不必重新扫一遍。

---

## 一、审计方法（可复用）

三层交叉，任何单层都会漏：

| 层 | 做法 | 覆盖什么 | 本层盲区 |
|---|---|---|---|
| 1. 全库时间列扫描 | 遍历 `information_schema` 全部 schema 的基表，按 `_sync_time / Begin Time / Last Modified Time …` 取 `max()`，与当前时间比对 | 「某张表最后一次写入是什么时候」 | 表停更但无人读 → 假警报；有读方但表本来就不该更新 → 看不出 |
| 2. 跨 schema 同名表比对 | `group by table_name having count(*)>1`，逐个比行数 + 新鲜度 | 「代码读的到底是哪一份」 | 不知道代码读哪份，需配合 3 |
| 3. 代码读方定位 | `grep` 表名 → 找出 SELECT / to_sql 的入口 | 把「停更」翻译成「用户可见」 | 动态拼接的表名可能漏 |

**为什么需要第 2 层**：PG 迁移后，同一张表在两个 schema 各有一份是常态。
`_pg_raw_connection` 的 search_path 是「目标 schema 置顶 + 其余」，
所以同一个裸表名在不同调用点会命中**不同的物理表** —— 这是本次三个真故障的共同成因。

现成巡检 `db_freshness_check`（每小时）覆盖 103 项，本次审计时报告 **0 项滞后**，
但它只检查自己清单里的表（远端库 + app 主库指定表），对第 2 层**完全无覆盖**。
这就是 7 周 CR 停更、3 个月 Excel 不产出、3 个月 FW 看板不更新都没被发现的原因。

复现脚本：`TMP/audit_all_freshness.py`（只读，扫全库时间列）。

---

## 二、发现清单

### 真故障（已修，3 项）

#### 1. Excel 报告自 PG 迁移起从未生成

| 项 | 内容 |
|---|---|
| 症状 | 每轮 `eflow_sync` 日志 `WARNING Excel 报告生成失败: 关系 "sqlite_master" 不存在`，任务仍 `success=True` |
| 根因 | pandas 3.0.3 对**非 SQLAlchemy 的 DBAPI2 连接**（psycopg2）退化为 `SQLiteDatabase` fallback，`to_sql(if_exists="replace")` 先执行 `SELECT ... FROM sqlite_master` 判存在性 → PG 无此表 |
| 波及时间 | 至少自 2026-11-01（`eflow_sync_full` 的 `result_json.excel_upload_error` 可见）；实际自 PG 迁移起 |
| 次生问题 | 该报告读的是 `eflow` schema（`data/eflow/eflow.sqlite3` 的映射），该 schema 数据停在 **2026-08-06**。即使不报错，产出的也是 3 个月前的快照 |
| 修复 | `write_excel_from_sqlite` 改为**直接使用入参数据**（不再「先写库再读回」）；`save_to_sqlite` 在 PG 模式显式跳过并说明原因；`sync_from_eflow_api` 调用点改 `save_sqlite=False, save_excel=True` |
| 验证 | 实跑：`40654 行 TT + 830 站点 → 16.2 MB / 69.6s`，两个 sheet 行数正确 |

#### 2. 丢包报告关联的是 8 月的站点快照

| 项 | 内容 |
|---|---|
| 症状 | `fw`/站点维度关联信息缺新站、站点属性变更不生效 |
| 根因 | `packet_loss_service._load_site_info` 读 `data/eflow/eflow.sqlite3` → `eflow.site`（**808 行，2026-08-07 停更**），而实时站点主表是 `app.eflow_site`（**830 行，每小时刷新**） |
| 修复 | 改读 `app.eflow_site`，字段映射经 `SITE_COLUMN_MAP` 反查核对（`Province→province_county`、`Vendor→power_vendor`、`TRM Type→trm_type`、`Network Type→network_type`），输出列名保持不变 |
| 验证 | `_load_site_info()` 返回 830 行，字段与原结构一致 |

#### 3. `FW Daily KPI` 看板图表停在 2026-08-04

| 项 | 内容 |
|---|---|
| 症状 | 看板 `fw_out` / `fw_in`（Main FW Out / Main FW In）图表为 3 个月前的平线 |
| 根因 | 图表 SQL 读本地 `device_whole_throughput` → `fw` schema。而 `fw_kpi_services` 的逻辑是「远端 API 成功就**不写**本地（本地仅作降级备份）」→ 远端一直正常，本地自 2026-08-04 起再无写入 |
| 修复 | 远端成功后**同时镜像**一份到本地（`FW_KPI_WRITE_LOCAL`，默认开；镜像失败只告警不影响任务） |
| 验证 | `write_to_local_db` 在 PG 下实写实测通过（已清理测试行）。下一轮 `fw_kpi_sync`（每日 07:17）生效 |

### 同类隐患（已顺手加固）

**`ran_ume_main_kpi` 的 `to_sql` 与 Excel 故障同源**：两处 `df.to_sql(..., conn)` 传入 psycopg2 原生连接
（建表分支 + 临时表去重分支）。当前因远端 API 可用而没走到，但一旦远端不可用回退本地就会以同样方式崩。

修复：新增 `backend/dialect_helpers.df_to_sql()` —— 统一入口，sqlite 连接行为不变，PG 连接改走
SQLAlchemy engine + `current_schema()` 推断的 schema 限定。已实写实测（写入 `ran_ume` schema 成功）。

**全局排查结论**：项目内 `to_sql(..., conn)` 共 5 处，其余 3 处（`cm_data_export` 的本地回退）
用的是真 `sqlite3.connect()`，不受影响；`read_sql_query(..., conn)` 共 11 处不触发该路径，均可正常工作。

### 被排除的「看起来陈旧」（不要误判为故障）

| 表 / 项 | 陈旧程度 | 判定依据 |
|---|---|---|
| `ran_ume.2G/3G/FDD/TDD_OLIB_Network_KPIs` | 49~86 天 | 任务每天成功，但远端 API 可用时**只写远端**（`_write_dataset` API 优先）。本地表无任何读方 |
| `ran_ume_ro.*_OLIB_Network_KPIs` | 64 天 | 只读镜像库，同上 |
| `fw.device_whole_throughput` | 90 天 | **例外**：有读方（见真故障 3），已修 |
| `app.history_alarm` | 16 小时 | 任务每日 03:35 一次（非注释里写的 3 小时），16h 属正常周期 |
| `lte_pl.*`（丢包库） | 12 小时 | 每日一次 |
| `ms_sla.*_1day / 1month` | 1.8 / 2.8 天 | 日/月粒度，当天未结束不落库，正常 |
| `app.meta_data` | 41 天 | 人工导入的 Meta 基准（`Meta_20260923.xlsx`），静态数据 |
| `app.tt_exclude` / `kml_mw_links` / `flm_*` / `*_sites` | 29~98 天 | 人工维护清单，按需导入 |
| `app.cm_cell_data` / `cm_site_summary` | 无时间列 | `cm_data_sync` 每日全量重建（15524 行），快照表无时间戳属设计 |
| `fw` / `battery` / `ipran_ume` / `lte_pl` 实时表 | 0~3 小时 | 正常 |

### 遗留问题（需人工决定，本次未动）

1. **`eflow` schema 的 6 张旧表**（`eflow_tt/wo/cr/pm/site/person`）停更 88~90 天。
   唯一实际读方是丢包服务的 `site`（已切走）。建议：确认无其他用途后归档或删除，
   否则后来者仍可能误读到 8 月的旧数据。
   ⚠️ 注意 `eflow.realtime_alarm`（仍在双写）和 `eflow.history_alarm`（每日快照，145 行）
   与 `app` 侧同名表口径不同，不能一起清。
2. **`eflow.history_alarm` 与 `app.history_alarm` 口径不一致**：前者是「最新一次快照」（145 行），
   后者是「累积」（18680 行）。目前读方都读 `app` 侧，但同表名并存容易踩坑。
3. **远端 `db_writer` 无查询能力**：`DbWriterClient` 只有 write / upload / list_tables，
   所以「让看板直接读远端」这条路走不通，只能靠本地镜像（本次修法）。

---

## 三、本次会话新增的守卫

| 守卫 | 位置 | 挡什么 |
|---|---|---|
| 停更守卫扩表 | `sync_from_eflow_api._STALE_GUARD_TABLES`：4 → 6（补 `eflow_site`、`person`） | 站点/人员停更不再静默 |
| Excel 产物年龄检查 | `db_freshness_check.FILE_CHECKS` 新增 `eflow_*.xlsx`（阈值 6h） | 「任务成功但报告没生成」变成巡检可见 |
| 通用安全写入 | `dialect_helpers.df_to_sql` | pandas 原生连接在 PG 下查 sqlite_master |

---

## 四、验证清单

- [x] `write_excel_from_sqlite` 实跑产出 16.2 MB / 2 sheet
- [x] `_load_site_info` 返回 830 行（含 22 个此前缺失的新站）；下游 `_build_site_summary` 实跑通过
      （715 站点 × 72 小时 pivot → 87 列 summary，`gateway/region/province_county/latitude` 均正常）
- [x] `df_to_sql` 在 PG（`ran_ume` schema）实写实读通过
- [x] `write_to_local_db` 在 PG（`fw` schema）实写通过，测试行已清理
- [x] **真实定时任务确认**：`eflow_sync` 20:00 那轮产出
      `D:\01_RPA\Task\my_app\data\eflow\eflow_20261103_200047.xlsx`（17 MB）
      ```
      20:00:01 CR 直查完成: 323 条（上游 total=323）
      20:00:41/42 eflow_tt 406 / eflow_wo 220 / eflow_cr 323 / eflow_pm 37 同步完成
      20:00:42 eflow_site 830 同步完成(upsert+重建)
      20:00:43 person 137 同步完成
      20:02:09 Excel 报告已生成: ...\eflow_20261103_200047.xlsx
      ```
      同轮**无**「停更守卫」告警、**无** `excel_upload_error`。
      该轮 `result_json`：`success=true, errors=[], excel_path="...eflow_20261103_200047.xlsx"`
      —— 此前每轮都是 `excel_path: null` + `excel_upload_error: '关系 "sqlite_master" 不存在'`。
- [ ] **待真实定时任务确认**：`fw_kpi_sync`（每日 07:17）后 `fw` 表 `max(time_full)` 推进到今天

### 验证时的一个观察：本轮耗时 819s（历史 163s）

| 阶段 | 耗时 | 说明 |
|---|---|---|
| 数据抓取 + 落库 | 20:00:01 → 20:00:43 | 与历史一致 |
| **Excel 报告生成（新增）** | 20:00:47 → 20:02:09（约 70s） | 本次改动带来的正常成本，17 MB / 2 sheet |
| 小时报告 + 图片 + FTP 上传 | 20:02:09 → 20:03:11 | 与历史一致 |
| **远端 FB 写入** | 20:03:11 → 20:13:40（约 **590s**） | 历史同一步骤仅 43s；本轮异常变慢 |

远端 `db_writer /health` 正常、两个 worker 与 8765 一直保持 ESTABLISHED（在等响应，非卡死），
最终未触发 900s 超时、任务 success=True。**与本次改动无关**（Excel 生成在远端写入之前已结束），
但会把任务整体从 ~3 分钟拉到 ~14 分钟，值得后续单独观察：若持续变慢，
优先查远端 `db.sqlite3` 里 `Eflow_TT_FB` / `Eflow_WO_FB` 的行数膨胀与索引。



---

## 六、`eflow` schema 旧表归档（2026-11-03 20:24 执行）

### 归档范围

`eflow` schema 原有 8 张表，本次只归档**已停更的 6 张**（88~90 天无更新）：

| 表 | 行数 | 体积 | 归档前最后数据 |
|---|---|---|---|
| `eflow_tt` | 28,455 | 56 MB | 2026-08-06 |
| `eflow_wo` | 10,000 | 17 MB | 2026-08-06 |
| `eflow_pm` | 1,632 | 2 MB | 2026-08-06 |
| `eflow_cr` | 205 | 424 kB | 2026-08-06 |
| `site` | 808 | 248 kB | 2026-08-06 |
| `person` | 133 | 72 kB | 2026-08-06 |

**保留不动**：`eflow.realtime_alarm`(59 行)、`eflow.history_alarm`(145 行) ——
经核实由 `eflow_alarm_service` 持续写入，最新记录为当天，属活跃表。

### 执行方式（可回滚）

1. `pg_dump -Fc` 备份 6 张表 → `backup/eflow_schema_archive_20261103.dump`（6.7 MB，
   已用 `pg_restore -l` 校验 6 个 TABLE DATA 段完整）。
2. 单事务内 `ALTER TABLE eflow.<t> SET SCHEMA eflow_archive`（不移动数据文件、不删数据）。
3. `COMMENT ON SCHEMA eflow_archive` 写明「禁止作为业务数据源」。
4. 回滚命令：`ALTER TABLE eflow_archive.<t> SET SCHEMA eflow;`

### 为什么这样安全

- `_SEARCH_PATH = "app,eflow,lte_pl,..."`，`eflow_archive` **不在** search_path 内，
  裸表名不可能再误命中。
- 全项目已无 `logical_name='eflow'` 调用；唯一按文件路径映射到 `eflow` schema 的
  是 `eflow_alarm_service`（写 alarm 两表）与 `eflow_data_mapper.save_to_sqlite`
  （PG 模式已直接 `return None`）。
- 巡检 `db_freshness_check` 的表清单全部指向 `app` schema，不涉及 `eflow`。

### 连带加固

`write_excel_from_sqlite` 原有一个「sheet 无数据时回退读 eflow 中间库」的分支，
归档后会查到不存在的表而抛错。已改为 `DB_MODE != "pg"` 才启用该分支
（PG 模式中间库本就不再写入，此分支已无意义）。
实测：含空 sheet 的报告生成正常，只打 `[SKIP] ...: no data`。

### 归档后验收

| 检查项 | 结果 |
|---|---|
| 归档表行数 | 205 / 1,632 / 28,455 / 10,000 / 808 / 133 —— 与归档前逐表一致 |
| `eflow` 剩余表 | `history_alarm`, `realtime_alarm` |
| 门户面板 `/api/portal-qc/summary` | `cr=80`，正常 |
| `packet_loss_service._load_site_info` | 830 行，走 `app.eflow_site` |
| 告警表可读 | `eflow.realtime_alarm=59`、`eflow.history_alarm=145` |
| Excel 报告 | 重建成功 17 MB / 40,657 行 TT + 830 站点 |
| 巡检 `db_freshness_check` | 104 项，0 滞后，6/6 库可达 |

> 过程中的一次失误：为验证空 sheet 分支，直接在 `data/eflow/` 生产目录调用
> `write_excel_from_sqlite`，该函数自带「只保留最新报告」的清理逻辑，
> 把 20:00 那份真实报告删掉了。已立即用 `load_report_data_from_db` +
> `generate_excel_report` 重建（`eflow_20261103_202412.xlsx`）。
> 后续同类测试应先改写模块级 `DATA_DIR` 指向临时目录再调用。
