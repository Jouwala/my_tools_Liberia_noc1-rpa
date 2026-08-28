# 项目文档总汇（PROJECT_DOCS）

> 本文件由 11 个根目录 Markdown 文档合并而成，保留全部原文内容。

> 📌 **2026-08-27 起：「项目现状」以 `docs/manual/` 手册为准。**
> 本文件只保留**历史计划、评估、审计与复盘**（§2、§3、§4、§5、§6、§8、§10、§11）。
> §1 项目说明、§7 MS SLA 服务、§9 局域网访问属于说明性内容，已迁入手册并在原位留指针，
> 原文逐字备份在 `PROJECT_DOCS_ARCHIVE.md`。

## 目录

1. 项目说明 README ——【已迁移 → 手册，原文入归档】
2. 迁移计划
3. 架构评估（2026-08-05）
4. FastAPI 架构优化方案
5. 国际化（i18n）审计报告
6. 国际化检查（2026-08-10）
7. MS SLA 服务 ——【已迁移 → 手册，原文已过时】
8. IP Trace 与故障概览集成方案
9. 局域网访问（LAN Access）——【已迁移 → 手册，原文入归档】
10. 迁移失败复盘（Postmortem）
11. 优化建议：用户体验与加载效率


# 1. 项目说明 README —【已迁移到手册】

> 本节是"项目现状描述"，已由 `docs/manual/` 接管，请以手册为准：
>
> | 原内容 | 现位置 |
> | --- | --- |
> | 项目定位、功能模块 | `docs/manual/01-overview.md` |
> | 技术栈、项目结构 | `docs/manual/02-architecture.md` |
> | 快速启动 | `docs/manual/10-quickstart.md` |
> | 功能模块明细（原 9 节 → 现 23 个页面） | `docs/manual/11-feature-guide.md` |
> | 数据源 | `docs/manual/14-integrations.md` |
>
> **原文已过时的两处**：①「快速启动」写的是 `--port 8000 --reload` 与 `localhost:5173`，那只是开发模式，生产实走 7038 + 看门狗；②功能模块只覆盖 9 节，界面已有 23 个页面。
> 原文逐字备份见 `PROJECT_DOCS_ARCHIVE.md`（原第 20-170 行）。
# 2. 迁移计划

# my_app：SQLite → PostgreSQL 迁移 + 分散库归口 + 归档 — 定稿计划

> 状态：**规划定稿，未执行**。本文件为执行对照基线。
> 项目根：`D:\01_RPA\Task\my_app`
> 决策基线时间：2026-08-07

> **⚠️ 2026-08-07 修订（重要）**：初版计划称「报告/图片取数全部经 `get_raw_connection`，完全可控」。经**全量枚举**（非抽样）证伪：运行期存在 **4 处裸 `sqlite3.connect` 绕过 `get_raw_connection`**，其中 `ipran_chart_service.py:233`、`fw_kpi_services.py:488` 是图表数据源，迁移后会**静默坏图**。本计划已据全量枚举更正（见 Phase 1 双层拦截、Phase 3 改写项、风险 8/9、Phase 7 回归）。

> **⚠️ 2026-08-07 二次复核（全量枚举重跑，详见复盘报告 1.5 节）**：核心架构事实（F1-F6、4 处裸连、R7 未实现）复核全部成立；另发现 7 项增量差异（D1-D7）：① 本地 db_ps_cs_cn 副本已不存在（非 0 字节）；② email_recovery 实际读 app.db，原"不影响"分类有误；③ 任务队列三件套（worker/task_runner/task_stats）未列入影响矩阵，须纳入 Phase 3 + DB_MODE；④ ipran 本地库已 0 字节（API 优先写入所致），迁移须定图表读源而非搬空库；⑤ sqlite 方言耦合实测 sqlite_master 20/PRAGMA 53/INSERT OR REPLACE 19/rowid 7/to_sql 13 处，Phase 3 清单与墙钟低估；⑥ get_raw_connection 实测 76 处；⑦ ms_sla 库实际名 lbr_ms_sla_kpi.sqlite3。结论不变：功能影响可控可逆；回退保证以 R7+风险 10/11+R8+队列层覆盖四项落地为前提。

---

## 0. 已采纳的决策（Phase 0 主体已闭环；2026-08-07 11:23 范围扩大，见变更标记）

| 项 | 决策 |
|---|---|
| `data/eflow/eflow.sqlite3` | **迁移 → PG**（2026-08-07 11:23 改：原定保留，现要求本地库全迁） |
| `db_ps_cs_cn` | **不迁移**。代码考古确认：项目内本地 `db`/`data/cnn_ume` 下的 `db_ps_cs_cn.sqlite3` 均为 **0 字节占位、无代码按绝对路径引用**；真数据在**远端** `http://192.168.100.19:8765`（`E:\01_RPA\LBR_Tools\KPI\db_ps_cs_cn.sqlite3`），经 `RemoteDBReader`(HTTP) 读、经 `ccn_ume_kpi_service`(HTTP) 写。**远端库排除（FINEBI 在用）→ 本地无真副本可迁 → 整个 `db_ps_cs_cn` 移出迁移范围**，保持 remote HTTP 读取 |
| 归口拓扑 | 单 PG 实例 + 每域一个 schema（推荐） |
| 归档对象 | 纠正为 `lte_pl.packet_loss_data`（非 `eflow_tt`） |
| PG 部署 | 同机 Docker PG + 连接池 `pool_size=20 / max_overflow=10`，低峰切流 |
| `eflow.sqlite3` 与 `app.db` 关系 | 两者都在用且都含 `eflow_tt`（各 28,437 行）。现两者都迁 PG → `eflow_tt` 出现**双源**，需决策归一（见第 4 节风险 5 + 下方待决） |

> **Phase 0 待决（已逐项核实，2026-08-07 11:55 收口）**
> - 0.5 `eflow_tt` 写入归属（已查代码确认 ✅）：`sync_from_eflow_api`（即 eFlow Data Sync）**只写 `app.db.eflow_tt`**，文件头明确"不再依赖 eflow.sqlite3 中间文件"（`sync_from_eflow_api.py:3-4,20,531,364`，`result.target_db=app.db`）。eflow.sqlite3 的 `eflow_tt` 是**旧版流水线遗留快照**，当前同步不维护。→ 双源"实时写入分裂"风险对 `eflow_tt` 不成立；`app.db.eflow_tt` 作 PG 唯一活源，eflow.sqlite3.eflow_tt 按只读快照迁。**已闭环。**
> - 0.6 本地 `db_ps_cs_cn` 真数据确认（已查代码+文件确认 ✅）：项目内 `D:\01_RPA\Task\my_app\db\db_ps_cs_cn.sqlite3` 与 `D:\01_RPA\Task\my_app\data\cnn_ume\db_ps_cs_cn.sqlite3` **均为 0 字节、且无任何代码按绝对路径引用**（`RemoteDBReader`/`ccn_ume_kpi_service` 仅把 `"db_ps_cs_cn.sqlite3"` 当**逻辑名**发往远端 `192.168.100.19:8765`）。→ 本地无真副本可迁；远端库排除 → **`db_ps_cs_cn` 整体移出迁移范围**，保持 remote HTTP 读取。**已闭环。**
> - 0.7 告警表读取归属（已查代码确认 ✅，较原风险 7 降级）：页面（`alarm_dashboard.py:38`、`gis.py:29` 等）全部 `get_raw_connection()`（无参 → `database.py:98` 默认 `DB_PATH=app.db`）读取 `realtime_alarm`/`history_alarm`；`alarm_dashboard.py:31` 用 `sqlite_master` 印证读 sqlite app.db。`eflow_alarm_service.py` 确把两表**同时写** app.db 与 eflow.sqlite3，但**页面只读 app.db**，eflow.sqlite3 副本是报表副产品。→ 因 PG 按 schema 分离（`app_`/`eflow_`），两副本不撞名、不冲突；**无需"定归属 schema"合并决策，保持双 schema 分离即可**。**已闭环。**

---

## 1. 迁移范围

**纳入 → PG**（单实例，每域 schema）：
- `app.db`（主库 39 表，含 `eflow_tt`）
- `data/eflow/eflow.sqlite3`（含 `eflow_tt`，与 app.db 双源，需归一）
- `battery_kpi`、`lte_pl`(含 `packet_loss_data`)、`ms_sla`、`fw_db`、`ran_ume`、`ipran_ume`

**不纳入**：
- `db_ps_cs_cn`：**整体排除**。本地 `db`/`data/cnn_ume` 下的 `db_ps_cs_cn.sqlite3` 为 0 字节占位、无代码引用；真数据在远端 `http://192.168.100.19:8765`（FINEBI 在用），经 `RemoteDBReader`(HTTP) 读 / `ccn_ume_kpi_service`(HTTP) 写 → 保持 remote HTTP 读取，**不写入 PG**（见 0.6）。
- `credential_store` 独立 credentials sqlite（见风险 9，建议保留独立 sqlite 不迁）

---

## 2. 七阶段分工（执行顺序，依赖链）

**Phase 1 — 接入层收口**（Qoder 主导）
- 建中央 DB 注册表 / 连接管理器，接管所有硬编码 sqlite 路径
- `eflow.sqlite3` 走 PG 分支；`db_ps_cs_cn` 整体保持 remote HTTP 分支（不进 PG，本地无真副本）；`credential_store` 独立 sqlite 保留不进 PG
- 交付物：单一数据源的 DB 配置；所有 service/router 改为从注册表取连接
- **关键拦截点（必要但非充分！2026-08-07 全量枚举后修正）**：报告/图片取数**并非全部**经 `get_raw_connection`。全量枚举（`grep -rn "sqlite3.connect(" backend`）确认运行期存在 **4 处裸 `sqlite3.connect` 绕过 `get_raw_connection`**：
  - `ipran_chart_service.py:233` → 裸连 `data/ipran_ume/ipran_ume_kpi.sqlite3`，是 **ipran 图表(savefig:361)的数据源** → 迁 PG 后若不处理，**ipran 图表静默空图/报错**
  - `fw_kpi/fw_kpi_services.py:488 _open_db()` → 裸连 fw sqlite，是 **FW 图表(savefig:669)数据源**，且含 sqlite 专有「锁则追加 `_序号` 换新文件」旋转逻辑（`:496-505`，PG 无等价物）→ 必须重写
  - `credential_store.py:154` → 裸连 **credentials / 鉴权** sqlite（独立库，非业务数据）。**硬排除：必须保留独立 sqlite，绝不进 PG 分支**（一旦迁坏 → 全员鉴权失败锁死，且不在业务回退范围内）。注册表工厂对 `credential_store` 路径**强制返回原 sqlite 连接**，不作 PG 映射（见风险 9 / 回退保障审计）
  - `battery_kpi_service.py:268` → 仅「`get_raw_connection` 导入失败时的兜底」裸连，含 sqlite PRAGMA；正常（backend 模式）走 `:266` 的 `get_raw_connection`，低优先但需清理 PRAGMA
- **注册表必须同时拦截两层**：① `get_raw_connection`（主入口，覆盖 eflow/ran_ume/packet_loss/ms_sla/battery 主路径）；② **所有裸 `sqlite3.connect` 调用点**（ipran_chart / fw_kpi / credential_store / battery 兜底）统一改走注册表工厂。否则 ipran/fw 图表会在迁移后无声坏掉——这正是初版计划漏算的盲区。

**Phase 2 — app.db → PG**（Qoder + 我）
- `database.py`：`DATABASE_URL` 环境变量 + `psycopg2`，删 `check_same_thread` / `timeout` / PRAGMA hook
- `requirements` 加 `psycopg2[-binary]`；加连接池参数
- **⚠️ 独立 ORM 基类接线（2026-08-07 全量枚举后发现，原 Phase 2 漏算）**：除主 `Base`(`database.py:35`) 外，还存在 **`PlBase`(`models/packet_loss.py:10`)** 与 **`BatteryBase`(`models/battery.py:9`)** 两个独立 `declarative_base()`，且**全项目仅 `database.py` 一处 `create_engine`**（grep 确认），即 PlBase/BatteryBase **没有自己的引擎**，其物理连接走 service 内的 `get_raw_connection`/裸 `sqlite3.connect`。→ 仅靠"改 `database.py` 引擎"**绑不到** packet_loss / battery 的 PG 连接。Phase 2 必须：① 为这两个 Base 各自显式绑定 PG 引擎（或在 service 层用 PG 连接执行其 Core `Table`/ORM 映射）；② 确保 `models/eflow.py` 的 `automap_base()` 跟随主引擎切 PG（它 `from backend.database import engine`，已跟随，OK）。否则 packet_loss_data / battery 表在 PG 下无连接可用。
- **⚠️ 启动期建表双重管理（新增）**：`main.py:103` 启动时 `Base.metadata.create_all(bind=engine)` 会直接按主 Base 元数据建表，与 Alembic 形成**双 schema 管理源**。切 PG 后须用 `DB_MODE` 守卫该 `create_all`（sqlite 模式才跑；PG 模式由 Alembic 接管），否则会与 Alembic 抢建/冲突或启动报错（见风险 10/11）。

**Phase 3 — 写层 PG 化**（最硬，按模块并行；Codex 精确改写 / Qoder 骨架）
- 重写 `_upsert_df`（`sync_from_eflow_api.py:299-341`）：`INSERT OR REPLACE`→`ON CONFLICT DO UPDATE`；`rowid` 去重→唯一键/CTID；`PRAGMA table_info`→`information_schema`；`DROP+CREATE INDEX`→`CONCURRENTLY` 幂等
- 镜像改 `ipran_ume_kpi_service.py:739`、`ms_sla_sync.py:269`
- 全局：`sqlite_master`→`pg_catalog`、`datetime('now')`→`now()-interval`、`AUTOINCREMENT`→`IDENTITY`、`sqlite3.OperationalError`→PG 异常；`to_sql(replace)` 逐处改显式 DDL
- **报告/图片链路专属改写（最易被遗漏，漏改会静默坏报告）**：
  - `get_raw_connection` 内 `PRAGMA busy_timeout/synchronous`（`database.py:110-111`）→ PG 下删除（`psycopg2` 不支持 PRAGMA，否则连接即报错）
  - `ran_ume_service.py:900` `SELECT name FROM sqlite_master WHERE type='table'` → PG `information_schema.tables`；否则可用性报告读不到表、静默产出空 Excel
  - `eflow_data_mapper.py:475,513` 经 `get_raw_connection(DATA_DIR/eflow.sqlite3)` 读写报告数据 → 走注册表映射到 PG `eflow_` schema
  - `packet_loss_service.py:62,341` `EFLOW_DB_PATH` 硬编码绝对路径读 `site` 表 → 经注册表映射（仍走 `get_raw_connection`，已可拦截）
  - `eflow_alarm_service.py:401,451` 写 `realtime_alarm`/`history_alarm` 到 eflow.sqlite3 → 映射 PG（与风险 7 归属 schema 一致）
  - **`ipran_chart_service.py:233` 裸 `sqlite3.connect(ipran_ume_kpi.sqlite3)`** → 改走注册表 PG 工厂（ipran 图表数据源，否则图静默空）
  - **`fw_kpi/fw_kpi_services.py:488 _open_db()` 裸连 + `:496-505` 锁旋转逻辑** → 改走注册表 PG 工厂；删除 WAL/synchronous/cache_size PRAGMA 与「`_序号` 换新文件」逻辑（PG 连接池替代锁竞争）

**Phase 4 — Alembic 补全**（我）
- `env.py` 去硬编码 `sqlite:///`，改读 `DATABASE_URL`
- 反向工程 33 张无 migration 表（含 `eflow_tt`）生成初始 migration
- `alembic upgrade head` 实跑

**Phase 5 — 分散库归口**（并行，我写脚本）
- 5.1 建 schema（`battery_/lte_pl_/ms_sla_/fw_/ran_ume_/ipran_ume_`）
- 5.2 sqlite→pg 搬运（类型修正：全 NULL 列被推断 `REAL`、`ne_id/alarm_id` 为 `REAL`、`*_time` 混 `sla_time='2d0h0m'` 时长串）
- 5.3 跳过 `db_ps_cs_cn`（整体排除，无本地真副本）；`eflow.sqlite3` 按只读快照迁（见 0.5 / 风险 5），schema 命名 `eflow_`
- 5.4 每库迁移幂等可 `DELETE` 重导

**Phase 6 — 归档**（纠正为 `packet_loss_data`）
- `packet_loss_data` 按月原生分区（按 `Begin Time`）
- 旧月归档至冷表/导出 + 加 `VACUUM/ANALYZE` 周期（当前全项目 0 处）
- `eflow_tt` 仅软保留 `DELETE`

**Phase 7 — 审核回归**（Codex 审核）
- Codex review 全部 PG 代码；影子运行比对；切流
- **Phase 7 报告生成回归（新增，纳入 R2 gating）**：迁移后逐一实跑报告/图片任务——eFlow 小时报告+图片、ran_ume 可用性报告、packet_loss 报告、battery 报表+Dashboard 图、ccn/ipran/fw 图表邮件。**其中 ipran 图表（`ipran_chart_service.py`）、fw 图表（`fw_kpi_services.py`）此前裸连 sqlite，是最高危遗漏点，必须单独验证 PNG 非空且数据正确**（非仅邮件发出）。比对 Excel 行数 / PNG 尺寸与迁移前基线一致；任一报告空表/报错即阻断切流。

---

## 3. Phase R — 回退 / 应急方案（强制）

- **R0 前置备份（每段开工前必做）**：sqlite 文件级拷贝 `backup/<ts>/`（含 `-wal/-shm`）；PG 迁移前 `pg_dump` 基线、每段后增量 dump；配置开关 `DB_MODE=sqlite|pg`，默认 sqlite，回退=改回 sqlite
- **R1 影子/双写闸门（Phase 2-5）**：切 PG 前先「读 PG、写仍落 sqlite」影子跑，按表 rowcount + 时间窗抽样 checksum 对账，差异超阈值不切流；`eflow_tt`/`packet_loss_data` 做 rowcount + 抽样行 hash
- **R2 切流 gating（必须全绿）**：PG 连接池稳定 + Alembic head 一致 + 影子对账误差 <0.1% + API 冒烟通过 → 才切；任一红 → 不切，保持 sqlite
- **R3 即时回退触发**：PG 写入持续报错 / 连接池耗尽 / 数据偏差 / 上游异常 → `DATABASE_URL`/连接工厂切回 sqlite、停双写；PG 损坏用 `pg_restore` 基线
- **R4 分阶段可撤**：Phase1 注册表加开关；Phase3 写层加 `DB_MODE` 分支；Phase5 脚本幂等可重跑可 `DELETE` 重导
- **R5 一致性对账脚本**：自动比对 sqlite 源 vs PG 目标（表清单/行数/关键列聚合/抽样行 hash），输出差异报告
- **R6 决策与沟通**：回退决策人 = 用户；SOP 文档化；切流选低峰；**回退演练一次**（用备份库跑通切回）
- **R7 DB_MODE 通用熔断开关（回退的硬前提，当前未实现！）**：`DB_MODE=sqlite|pg` 不能只停留在计划——它必须是**代码级全局开关**，覆盖 `get_raw_connection` 工厂、独立 `PlBase`/`BatteryBase` 引擎、`main.py:103 create_all` 守卫、Alembic `env.py`。**切流前必须已实现并验证"切回 sqlite 即全量回到原 sqlite 运行态"**。在 R7 落实前，回退**不保证**（详见第 8 节回退保障审计）。
- **R8 鉴权库零迁移**：`credential_store` 硬排除（见 Phase 1 / 风险 9），无论 `DB_MODE` 为何值均走原 sqlite；回退时它本就未动，无需处理。

---

## 4. 主要风险 / 不确定项

1. **运行时动态 DDL + `rowid` 去重** → 这是重构不是搜索替换（最大风险）
2. **`eflow_tt` 无主键** → PG 分区强制唯一约束含分区键，`u_eflow_tt(tt_no)` 会变 `(tt_no, created_time)`，削弱唯一性，需业务确认
3. **反向工程 schema 类型不可信**（全 NULL 列被推断 `REAL`、`*_time` 混时长字符串）→ 需人工定类型
4. 切流前必须影子比对（R1/R2）
5. `eflow_tt` 写入归属：经代码核实，`sync_from_eflow_api` 仅写 `app.db.eflow_tt`（`sync_from_eflow_api.py:3-4,20,531,364`），eflow.sqlite3 的 `eflow_tt` 为遗留快照、无活写。→ 无需"双源合并"，`app.db` 作 PG 唯一活源即可；eflow.sqlite3.eflow_tt 按只读快照迁
6. ~~本地 `db_ps_cs_cn` 迁移~~（已核实撤销）：本地 `db`/`data/cnn_ume` 下的 `db_ps_cs_cn.sqlite3` 为 0 字节占位、无代码引用；真数据在远端（排除）→ **`db_ps_cs_cn` 整体移出迁移范围**。
7. 告警表读取：**页面只读 `app.db`**（`alarm_dashboard.py` / `gis.py` 均 `get_raw_connection()`→app.db，`alarm_dashboard.py:31` 用 `sqlite_master` 印证）。`eflow_alarm_service` 虽双写 app.db 与 eflow.sqlite3，但 eflow.sqlite3 副本仅报表用；PG 按 `app_`/`eflow_` schema 分离后两副本不撞名、不冲突 → **无需"定归属 schema"合并决策**（较原风险降级）。待 Phase 3 报告链路核查时一并确认报表究竟读 app.db 还是 eflow.sqlite3 副本。
8. **报告/图片生成链路耦合（2026-08-07 全量枚举后修正，原"全部经 get_raw_connection"结论有误）**：渲染（openpyxl/matplotlib/PIL）对底层 DB 无关（都操作内存 DataFrame）。**取数则分两路**：① 主路径经 `get_raw_connection`（eflow/ran_ume/packet_loss/ms_sla/battery）— 可被注册表拦截；② **运行期存在裸 `sqlite3.connect` 绕过点**（ipran_chart:233、fw_kpi:488、credential_store:154、battery:268 兜底），其中 **ipran_chart 与 fw_kpi 是图表数据源**，若不单独处理，迁移后这两类图表会**静默空图/报错**。→ 必须 Phase 1 双层拦截（get_raw_connection + 所有裸 connect）+ Phase 3 改方言 + fw_kpi 删锁旋转逻辑；漏改则对应报告/图表静默坏。原结论"全部经 get_raw_connection、完全可控"**不实**，已据全量枚举更正。
9. **fw_kpi 文件锁旋转逻辑无 PG 等价物（新增）**：`fw_kpi_services.py:488 _open_db()` 在 sqlite 被锁时「追加 `_序号` 生成新文件」(`:496-505`)，是文件级锁竞争的产物，PG 用连接池解决、无此概念。迁移时该逻辑必须删除并重写成连接池重试，否则会生成一堆孤儿 fw sqlite 文件。
10. **独立 ORM 基类无引擎（2026-08-07 全量枚举后发现）**：`models/packet_loss.py:10 PlBase` 与 `models/battery.py:9 BatteryBase` 是独立 `declarative_base()`，且全项目仅 `database.py` 一处 `create_engine`（grep 确认）。即 PlBase/BatteryBase 物理连接走 service 内 `get_raw_connection`/裸 `sqlite3.connect`，**不随 `database.py` 引擎切换**。→ Phase 2 仅改 `database.py` 不够，必须为其显式绑定 PG 引擎，否则 `packet_loss_data`/battery 表在 PG 下无连接。已补进 Phase 2。
11. **启动期 `create_all` 与 Alembic 双重管理（新增）**：`main.py:103 Base.metadata.create_all(bind=engine)` 在启动即按主 Base 元数据建表，与 Alembic 形成双 schema 源。切 PG 后必须用 `DB_MODE` 守卫（sqlite 模式才跑 create_all；PG 模式由 Alembic 接管），否则会与 Alembic 抢建/冲突或启动报错。已补进 Phase 2。

---

## 5. 执行者分工与并行编排（谁在执行）

三种角色定位：
- **吉祥（我）** = 指挥 + 直接执行者：写需全局一致性的模块（注册表、Alembic、归档、对账），并负责派发 / 汇总 / 解冲突。
- **codex** = 车道 A worker：headless、干净，擅长精确代码改写 + 最终审核。
- **qoder** = 车道 B worker：擅长模块改写；有排队风险——`qmodel` 排队时 90s 后才 fallback codex（该子任务变串行）。

逐阶段执行者表：

| 阶段 | 子任务 | 执行者 | 并行方式 |
|---|---|---|---|
| P1 | 写中央 DB 注册表 / 连接管理器，接管所有硬编码路径 | 吉祥（主） | 单作者，无并行（需全局一致） |
| P2 | `database.py` 改 `DATABASE_URL`+psycopg2、删 sqlite 参数；`requirements` 加 psycopg2；加连接池 | 吉祥（主） | 无并行 |
| P3-预处理 | 全局方言批量替换（`sqlite_master`→`pg_catalog`、`datetime('now')`→`now()-interval`、`AUTOINCREMENT`→`IDENTITY`） | 吉祥 | 串行，先于两车道 |
| P3-车道A | 最难模块：`sync_from_eflow_api.py`（动态 DDL + `rowid` 去重 299-341）、`ipran_ume_kpi_service.py:739` | codex | 与车道 B **并发** |
| P3-车道B | `ms_sla_sync.py:269` + 其余同类 service（packet_loss / fw_db / ran_ume） | qoder | 与车道 A **并发**；排队则 90s 后 fallback codex |
| P4 | `env.py` 去硬编码 `sqlite:///` 改读 `DATABASE_URL`；`alembic autogenerate` 33 表 + upgrade head | 吉祥（主，需连库） | 无并行（依赖 P3 schema） |
| P5-车道A | `battery_kpi` / `ms_sla` / `ran_ume`：建 schema + 搬运 + 类型修正 | codex | 与车道 B **并发** |
| P5-车道B | `lte_pl`（含 `packet_loss_data`，最大）/ `fw_db` / `ipran_ume`：建 schema + 搬运 | qoder | 与车道 A **并发**；排队 fallback codex |
| P5-支撑 | 写公共搬运骨架 + 对账校验脚本 | 吉祥 | 串行支撑两车道 |
| P6 | `packet_loss_data` 按月分区 + 冷归档 + `VACUUM/ANALYZE` 周期；`eflow_tt` 软 DELETE | 吉祥（主） | 无并行 |
| P7-审 | 全量 PG 代码 review | codex | 与吉祥对账脚本 **并发** |
| P7-对账 | 影子比对脚本（sqlite 源 vs PG 目标 rowcount / 抽样 hash） | 吉祥 | 与 codex 审 **并发** |
| P7-gate | 切流拍板 | 你（人） | 人时间，不在模型墙钟内 |

> 真并发只在 **P3、P5** 两车道；其余阶段吉祥单干或顺序依赖。阶段间整体串行（P1→…→P7），并行只压阶段内部。

---

## 6. 大模型执行墙钟预估（非人日）

阶段间串行，两条 worker 通道（codex / qoder）只压缩阶段内并行子任务，不能把总墙钟除以 2。

| 阶段 | 大模型执行墙钟 | 并行情况 |
|---|---|---|
| P1 接入层注册表 | 15–30 min | 吉祥单写 |
| P2 app.db → PG | 10–20 min | 改 3 文件 |
| P3 写层 PG 化 | 60–100 min | codex + qoder 两车道并发；`sync_from_eflow_api` 动态 DDL 最重 |
| P4 Alembic 补全 | 20–40 min | env.py 改 + autogenerate 33 表 + upgrade |
| P5 分散库归口 | 60–100 min | 7 域（battery/ms_sla/ran_ume/lte_pl/fw_db/ipran_ume/eflow）/ 2 通道并发；含 sqlite→pg 搬运 + 类型修正 |
| P6 归档 | 30–60 min | 分区 + VACUUM 周期 |
| P7 审核+影子+切流 | 30–60 min | Codex 审 + 对账脚本 |
| 缓冲 / 回退演练 | 30 min | |
| **关键路径合计** | **≈ 4.5–7.5 小时** | 阶段串行，并行只压阶段内 |

非 AI 时间（不计入墙钟，但拉长日历）：
- **qoder 排队惩罚**：每次排队白等 90s 才 fallback codex，P3 / P5 高频派发会拖长。
- **影子比对 + 低峰切流窗口**：P7 等低流量时段，日历等待可能跨 1–2 天。
- **你的人 checkpoint**：切流 gating（R2）必须你拍板，是人时间。

→ 纯模型连续跑 ≈ **5–8 小时**，散在日历上大概率 **1–2 个工作日**完成。

> 注：2026-08-07 11:23 范围扩大（原拟纳入 `eflow.sqlite3` + 本地 `db_ps_cs_cn`），但 11:55 核实本地 `db_ps_cs_cn` 为 0 字节占位、无真数据 → **撤销 `db_ps_cs_cn` 纳入**，仅 `eflow.sqlite3` 新增。P5 实际由 6 域增至 7 域（+eflow）；墙钟维持 ≈ 4.5–7.5 小时、日历 1–2 工作日。

---

## 7. 功能影响面全量矩阵（2026-08-07 12:00 复核，证据驱动）

> 目的：回答"迁移后功能会不会有影响"。结论：**渲染无关、取数相关；取数经 `get_raw_connection` 的 100% 可被注册表拦截，裸 `sqlite3.connect` 的 4 处是盲区（已在 Phase 1 双层拦截处理）；另有 2 个 ORM 引擎接线缺口（风险 10/11）+ 鉴权库硬性排除（风险 9）**。

### 7.1 API 读取端点（9 个 router，均经 `get_raw_connection` → 中央拦截覆盖 ✅）

| 端点 | 文件:行 | 取数连接 | 迁移覆盖 |
|---|---|---|---|
| upload | `upload.py:67,146` | `get_raw_connection(DB_PATH)` / `()` | ✅ |
| battery_dashboard | `battery_dashboard.py:66` | `get_raw_connection(BATT_DB_PATH, timeout=30)` **无 `with`（长连接）** | ✅ 拦截；须确保 PG 连接兼容长连接/手动 close |
| alarm_dashboard | `alarm_dashboard.py:38,127,200,290,363` | `get_raw_connection()`→app.db（含 `sqlite_master` 查表） | ✅ 拦截 + 方言改 |
| packet_loss_dashboard | `packet_loss_dashboard.py:44` | `get_raw_connection(PL_DB_PATH, timeout=30)` **无 `with`** | ✅ 拦截；PlBase 引擎须接线（风险 10） |
| tt_wo_dashboard | `tt_wo_dashboard.py:19,122,347` | `get_raw_connection()`→app.db | ✅ |
| system | `system.py:40,83` | `get_raw_connection(DB_PATH)` | ✅ |
| gis | `gis.py:29,490,567,647,744,804,825,862` | `get_raw_connection()`→app.db | ✅ |
| analysis | `analysis.py:34,99,135,160` | `get_raw_connection(DB_PATH)` | ✅ |
| tables | `tables.py:24,59,111,138` | `get_raw_connection()` + `list_tables()` | ✅（`list_tables` 用 `inspect(engine)`，随引擎切 PG） |

### 7.2 定时任务（27 个，见 `task_registry.py`）

| 类别 | 任务 | DB 目标 / 数据源 | 迁移覆盖 |
|---|---|---|---|
| eflow | eflow_sync / eflow_sync_full / active_alarm / history_alarm | `sync_from_eflow_api` / `eflow_alarm_service` 经 `get_raw_connection`(app.db+eflow.sqlite3) | ✅（动态 DDL 改写见 P3） |
| ran_ume | ran_ume_daily / main_kpi_sync / network_kpi_sync | `ran_ume_service` 经 `get_raw_connection` | ✅ |
| site_outage | site_outage_screenshot | 浏览器截图，**无 DB** | — 不影响 |
| whatsapp | whatsapp_send | 发图，**无 DB** | — 不影响 |
| ms_sla | ms_sla_full | `ms_sla_service` 经 `get_raw_connection` | ✅ |
| cnn | cnn_kpi_sync | 写**远端** db_ps_cs_cn(HTTP)；图表读 RemoteDBReader(HTTP) | — **远端排除，不影响** |
| sp | sp_data_sync | SFTP→app.db 经 `get_raw_connection` | ✅ |
| ipran | ipran_kpi_sync | `ipran_ume_kpi_service` 经 `get_raw_connection`+`to_sql` | ✅ |
| ipran 图表 | ipran_m6k_chart_email | **`ipran_chart_service.py:233` 裸 `sqlite3.connect`** | ⚠️ 盲区，已在 P1 双层拦截 |
| email | liberia_email_1h/8h / kpi_ms_* | `liberia_email_report`/`kpi_email_report` 经 `get_raw_connection`(本地 ms_sla/app.db) | ✅ |
| email 远端 | kpi_sp_spareparts / consumables / ran_availability | **远端 FTP 数据/图片** | — 不影响 |
| email 恢复 | email_recovery | EWS 探测 | — 不影响 |
| packet_loss | packet_loss_sync | `packet_loss_service` 经 `get_raw_connection`(lte_pl) + `PlBase` | ✅（PlBase 须接线，风险 10） |
| cnn 图表 | ccn_free_rating_chart_email | 读 **RemoteDBReader(HTTP 远端)** | — **远端排除，不影响** |
| fw | fw_kpi_sync | **`fw_kpi_services.py:488` 裸 `sqlite3.connect` + 锁旋转** | ⚠️ 盲区，已在 P1 双层拦截 + 删锁逻辑 |
| battery | battery_kpi_sync / battery_email | `battery_kpi_service` 经 `get_raw_connection` + `BatteryBase` | ✅（BatteryBase 须接线，风险 10） |
| mailbox | mailbox_cleanup | Exchange，**无 DB** | — 不影响 |

### 7.3 关键结论
- **受影响的功能 = 所有"本地 sqlite 取数/写数"的端点与任务**；渲染（Excel/PNG）对底层 DB 无感。
- **不被迁移影响的功能**：site_outage 截图、whatsapp、远端 FTP 报表、cnn 图表（读远端）、email_recovery、mailbox_cleanup —— 它们根本不碰本地 sqlite。
- **可控盲区**：ipran 图表(:233)、fw 图表(:488) 此前裸连，已纳入 Phase 1 双层拦截 + Phase 3 改写。
- **新增缺口（本轮回查发现）**：PlBase/BatteryBase 独立引擎（风险 10）、`main.py:103 create_all` 双重管理（风险 11）、credential_store 硬排除（风险 9）——均已补进计划。

---

## 8. 回退保障审计（能否"保证正常回退"）

### 8.1 目前已设计、可保证的回退
| 机制 | 保证级别 | 说明 |
|---|---|---|
| sqlite 文件 **从不删除**直到稳定期结束 | ✅ 强 | 原数据始终可回；双写期 sqlite 反而领先，回退数据不丢 |
| `DB_MODE` 开关切回 sqlite | ✅ 强（**前提：已实现**，见 R7） | 代码/配置级，秒级回退 |
| `pg_dump` 每段基线 + 增量 dump | ✅ 强 | PG 损坏可 `pg_restore` |
| 影子/双写闸门（R1）+ 切流 gating（R2） | ✅ 强 | 未全绿不切，天然不破坏 sqlite |
| 分阶段幂等（R4）：P5 脚本 `DELETE` 重导 | ✅ 强 | 数据迁移可重跑 |
| credential_store 硬排除（R8） | ✅ 强 | 鉴权库本就不动 |

### 8.2 当前**不能保证**回退的点（必须在切流前闭环）
1. **`DB_MODE` 通用熔断开关尚未实现**（R7）。当前只是计划文字；若切流后发现问题、但开关没落地，回退需手动改代码+配置，存在窗口风险。**→ 切流前必须实现并演练"切回 sqlite = 全量回到原态"。**
2. **独立 `PlBase`/`BatteryBase` 引擎接线**（风险 10）。若 Phase 2 只为 `database.py` 引擎切 PG，packet_loss/battery 仍连 sqlite —— 这本身不是"回退失败"，但若有人误把这些 Base 也切 PG 又没接线，会出现"部分表在 PG、部分在 sqlite"的分裂态，回退须分别处理。**→ 接线须带 `DB_MODE` 分支。**
3. **`main.py:103 create_all` 守卫**（风险 11）。若 PG 模式下 `create_all` 仍跑，可能抢建/冲突致启动失败；回退到 sqlite 时需它恢复运行。**→ 必须 `DB_MODE` 守卫。**
4. **`credential_store` 误迁移**（风险 9）。一旦迁坏 → 全员锁死且不在业务回退范围。**→ 已硬排除（R8），注册表工厂强制返回原 sqlite 连接。**

### 8.3 诚实结论
- **"迁移后功能是否受影响"**：按修订后计划执行（含本轮回查补的 3 个缺口），功能影响**可控且可逆**；但**无法在不动手执行+回归的前提下 100% 保证零影响**——唯一真正确认的方式是 P7 影子比对 + 报告回归 + 回退演练。
- **"能否保证正常回退"**：在 **R7（`DB_MODE` 熔断开关实现）+ 风险 10/11 接线守卫 + R8 鉴权库硬排除** 三项落地前，**回退不保证**；三项落地且演练通过后，**回退强保证**（sqlite 文件不删 + 双写领先 + 秒级切回）。
- 复盘报告见同目录 `my_app_migration_failure_postmortem.md`。


# 3. 架构评估（2026-08-05）

# my_app 架构评估与 Django 迁移必要性论证

> 评估日期：2026-08-05
> 评估对象：`D:\01_RPA\Task\my_app`
> 数据来源：源码静态统计 + git 历史 + `db/app.db` 中 1623 条真实任务执行记录
> 结论摘要：**不建议迁移 Django。** 当前架构可支撑现有及 12 个月内可预期的扩展；真实瓶颈在调度层与数据层，与 Web 框架无关。建议以 20 人日的原地演进替代 55–75 人日的框架迁移。

---

## 一、架构现状评估

### 1.1 技术栈盘点

| 层次 | 选型 | 版本 | 备注 |
|------|------|------|------|
| Web 框架 | FastAPI + Uvicorn | 0.139.0 / 0.51.0 | 单进程，无 `--reload`，无 workers |
| ORM | SQLAlchemy | 2.0.51 | **形同虚设**，见 1.3 |
| 数据库 | SQLite | 内置 | 主库 `db/app.db` 147 MB / 36 张表 / 7.99 万行 |
| 调度 | APScheduler `BackgroundScheduler` | 3.11.3 | **默认配置**，与 API 同进程 |
| 数据处理 | pandas / numpy / scipy / matplotlib | 3.0.3 / 2.4.6 | ETL 主力 |
| 前端框架 | React + Vite | 19.2 / 8.1 | TypeScript 6.0 |
| UI / 图表 / 地图 | antd 6.5 / ECharts 6.1 / Leaflet 1.9 + turf | — | 构建产物 3.1 MB |
| 前端路由 | **无**（手写 `switch`） | — | 见 1.5 |
| 前端数据层 | axios + 自研 30 s TTL `Map` 缓存 | — | 无 TanStack Query / SWR |
| 状态管理 | **无**（167 个 `useState` / 49 个 `useEffect`） | — | 仅 2 个 Context（i18n、TaskStatus） |
| 国际化 | 自研 Context（zh 413 / en 412 键） | — | 已知 3 个未定义键、2 个页面未覆盖 |
| 鉴权 | 回环放行 + `X-API-Token` | — | **无用户体系、无 RBAC** |

### 1.2 规模与增长速率

```
后端    62 个 .py     31,102 行
  ├─ services/       21,795 行  (70.1%)   ← 重量所在
  ├─ routers/         3,746 行  (12.0%)   ← Django 迁移的主战场
  ├─ task_registry     ~1,700 行 (5.5%)
  ├─ main.py            432 行
  └─ models/             33 行  (0.1%)    ← ORM 实际体量
前端    32 个 .ts/.tsx  8,443 行
API 端点  53 个（51 个同步 def，1 个 async）
定时任务  29 个
```

**增长曲线（git 实测）**：

| 日期 | backend 文件数 | backend 行数 |
|------|----------------|--------------|
| 2026-07-21 | 17 | 2,826 |
| 2026-07-24 | 28 | 12,794 |
| 2026-07-27 | 36 | 18,003 |
| 2026-07-31 | 41 | 22,046 |
| 2026-08-04 | 52 | 26,320 |
| 2026-08-05 | 62 | 31,102 |

15 天内后端从 2.8K 增长到 31.1K 行，**日均约 1,900 行**。这是典型的 AI 辅助高速扩张形态：功能覆盖跑在架构收敛前面。

### 1.3 定性判断：这不是 Web 应用，是带 Web 前端的 ETL 平台

三条独立证据：

1. **代码重量**：services 层占 70%，routers 占 12%，ORM 模型仅 33 行 2 张表。36 张表里 34 张由 ETL 通过 `pandas.to_sql` 动态建表，不受 ORM 管理。
2. **调用方式**：`get_raw_connection` 在 25 个文件中被调用 71 次；`SessionLocal` / `Base.metadata` 只出现在 4 个文件。ORM 已被裸 SQL + pandas 完全架空。
3. **运行时负载**（1623 次执行采样，最具说服力）：

| 指标 | 实测值 |
|------|--------|
| 总执行次数 | 1,623 |
| 失败次数 / 失败率 | 159 / **9.8%** |
| 平均耗时 > 60 s 的任务 | **18 / 29** |
| 最长单次任务 | `eflow_history_alarm` **79 分钟**（平均 40.6 分钟） |
| 历史峰值并发任务数 | **8** |

Top 慢任务与高失败任务：

| 任务 | 执行次数 | 平均耗时 | 最长 | 失败数 | 失败率 |
|------|---------|---------|------|--------|--------|
| `eflow_history_alarm` | 4 | 2437 s | 4739 s | 0 | 0% |
| `main_kpi_sync` | 8 | 722 s | 851 s | 1 | 13% |
| `ms_sla_full` | 15 | 633 s | 842 s | 3 | 20% |
| `eflow_sync` | 97 | 393 s | 541 s | 4 | 4% |
| `eflow_active_alarm` | 1071 | 90 s | 93 s | 21 | 2% |
| `email_recovery` | 115 | 19 s | 45 s | 55 | **48%** |
| `liberia_email_1h` | 99 | 48 s | 248 s | 45 | **45%** |
| `liberia_email_8h` | 17 | 53 s | 247 s | 7 | **41%** |

**Web 请求服务是这个系统里最轻的部分。** 53 个端点、单用户内网、无并发压力——恰恰是 Django 最擅长解决的那类问题，在这里根本不存在。

### 1.4 后端架构问题清单（按严重度）

#### P0-1 调度器使用默认配置，与 40 分钟级任务严重不匹配 🔴

`task_runner.py:56` 为裸 `BackgroundScheduler()`，未传任何参数，因此继承 APScheduler 3.x 默认值：

| 参数 | 默认值 | 与实际负载的冲突 |
|------|--------|------------------|
| `ThreadPoolExecutor(max_workers=10)` | 10 | 峰值并发已达 8，池子用掉 80%；`eflow_history_alarm` 单个任务占用 worker 长达 79 分钟 |
| `misfire_grace_time=1`（秒） | 1 s | 调度器线程稍有阻塞，该次触发即被**静默丢弃**，无日志无告警 |
| `coalesce=True` | True | 积压的多次触发合并为 1 次，长任务后堆积的执行被吞掉 |
| `max_instances=1` | 1 | 上一轮未跑完时新触发直接丢弃，`eflow_sync`（393 s 平均）若配置为每小时尚可，但余量很薄 |

这几乎可以确定是 9.8% 失败率与部分"任务没跑"现象的结构性来源之一。修复成本极低（一行配置），但当前无人显式设置。

#### P0-2 ETL 与 API 同进程，运维耦合 🔴

29 个任务在 uvicorn 进程内的线程里跑。后果：

- 改任何 `backend/` 代码必须重启 → 重启窗口内所有在跑任务被腰斩（40 分钟的任务重跑成本极高）
- 任一任务内存暴涨或崩溃 → 整个看板不可用
- 无法独立扩缩容 ETL 与 Web
- pandas 大 DataFrame 操作持有 GIL，会拖慢同进程内的 API 响应

#### P0-3 SQLite 承压与配置漂移 🟠

- 单文件 147 MB，8 并发写；`page_count=37579 / freelist=7077` → **18.8% 空闲页碎片**，从未 VACUUM
- `app.db-wal` 已积到 12 MB，未做 checkpoint
- **配置漂移**：`database.py` **不设置** `journal_mode`；散落 7 处各自设置——`init_db.py`、`eflow_api_client.py`、`fw_kpi_services.py`、`ipran_ume_kpi_service.py`、`ms_sla_service.py`、`ran_ume_network_kpi.py`、`sync_from_eflow_api.py` 设 WAL，而 `battery_kpi_service.py:270` 设 DELETE。**实测当前库处于 WAL 模式**，与项目文档中记录的 "journal_mode=DELETE" 不符。谁最后连上库谁说了算，这是不可控状态。

#### P1-4 服务层复制粘贴式扩张 🟠

`ran_ume_main_kpi.py`(1160 行) 与 `ran_ume_network_kpi.py`(1268 行) 去空白后差异仅 1096 行 / 2428 行 → **约 55% 重复**。

4 个 UME 系服务中同名函数各存一份：

```
4×  create_history_query, build_filename, _runtime_credentials
3×  wait_history_ready, export_history, _run_single_kpi_query,
    _rsa_encrypt_pem, _http_request_with_retry, _http_request,
    _create_ssl_socket, _auth_headers, _decode_chunked, _get_thread_socket
2×  login, upload_to_ftp, read_xlsx, import_to_database, detect_key_cols
```

估算可消除重复约 2,500 行。**这是维护成本上升的真实来源**——改一处 UME 登录逻辑要同步改 4 份。

#### P1-5 业务逻辑滞留路由层 🟡

routers 目录 74 处直接写 SQL / pandas：`gis.py` 25 处（882 行单文件）、`tt_wo_dashboard.py` 13 处、`battery_dashboard.py` 9 处。router 应只做参数校验与序列化。

#### P1-6 密码硬编码残留 🟠

`credential_store` 已建立，但仍有 9 处硬编码密码未收口（`auth_manager.py`、`ccn_ume_kpi_service.py`、`ipran_ume_kpi_service.py`、`ms_sla_service.py`、`ran_ume_main_kpi.py`、`ran_ume_network_kpi.py`、`report/mail_126.py` 等）。

#### P2-7 已知未修 bug（2026-07-24 深度测试报告，至今未闭环）

F-1 `stats` 列名未校验 → 500 未处理异常；F-2 `sort_by` 未校验 → 排序静默失效；F-3 上传文件名未净化。

### 1.5 前端架构问题清单

| 问题 | 现状 | 影响 |
|------|------|------|
| 无路由库 | `App.tsx` 用 `useState<PageKey>` + `switch` 渲染 14 个页面 | 无深链接、无法分享看板 URL、刷新丢失当前页、浏览器前进后退失效 |
| 无数据层 | 每页手写 axios + loading/error/refetch；自研 41 行 TTL 缓存 | 167 个 `useState` / 49 个 `useEffect`，重复样板代码，缓存失效策略靠手工 `invalidateCache(prefix)` |
| 无状态管理 | 仅 2 个 Context | 跨页共享数据（如任务状态）只能靠 Context 或重复请求 |
| 构建体积 | dist 3.1 MB，antd 1.2 MB + echarts 1.1 MB | 已做 lazy 分包，但两个大 vendor chunk 仍在首屏 |
| i18n 债务 | 自研方案，66+32 处 `locale === 'zh' ? ...` 内联三元；3 个未定义键；TTWODashboard 0% 覆盖 | 详见 `i18n_audit_report.md` |
| UI 硬编码列表 | `DataSync.tsx` 的 `ROW_GROUPS` 写死 task_id | 新增后端任务需同步改 3 处，漏改则 UI 完全不显示（已踩坑一次） |

### 1.6 结论：架构是否还撑得住？

**撑得住，但撑得辛苦，且辛苦的原因不在 Web 框架。**

- FastAPI + React 这套组合本身对 53 个端点 / 14 个页面毫无压力，官方生态可支撑 10 倍于此的规模。
- 真正逼近上限的是：**APScheduler 默认线程池（8/10 已用）** 和 **SQLite 单写者模型（8 并发写）**。这两项是硬约束。
- 开发效率下降的真实原因是**代码重复**（55% 的 UME 服务重复、路由层 74 处裸 SQL）和**缺前端基础设施**（手写路由与数据层），而非框架选型。

---

## 二、迁移必要性结论

### 2.1 Django 能带来什么，以及对不对症

| Django 卖点 | 本项目现状 | 是否对症 |
|-------------|-----------|---------|
| ORM + migrations | 36 张表中 34 张由 ETL `to_sql` 动态建表，表结构随数据源变化 | ❌ **负资产**。`inspectdb` 逆向后，每次 ETL 改表都要手写 migration，反而增加摩擦 |
| Admin 后台 | 已有 Task Manager 页面（任务列表、手动触发、cron 编辑、执行历史、调用链标注） | ❌ 重做一遍，功能不如现有 |
| Auth / RBAC | 单用户内网工具，鉴权 = 回环放行 | ❌ 需求不存在。真需要时 FastAPI 加 `fastapi-users` 或 OIDC 约 2–3 人日 |
| App 目录约定 | 已有 routers / services / models / schemas 分层，只是执行不彻底 | ⚠️ 约定有价值，但**原地重构同样能达成**，不必换框架 |
| DRF 序列化 | Pydantic 已覆盖，且性能更好、类型更强 | ❌ 平级替换，无收益 |
| 同步 WSGI 模型 | 51/53 端点已是同步 `def`（跑在 starlette threadpool） | ⚠️ 平手，无优劣 |
| 生态成熟度 | — | ⚠️ 真实项目里 FastAPI 生态对 pandas/ETL 场景同样成熟 |

**迁移 Django 完全不解决的问题**（占痛点 88%）：
调度器并发与 misfire、ETL 与 Web 进程耦合、SQLite 写竞争与碎片、2500 行 UME 重复代码、9.8% 任务失败率、前端路由与数据层缺失。

### 2.2 明确结论

> **不迁移 Django。** 投入 55–75 人日改造只占代码总量 12% 的 Web 层，同时冻结新需求约 3 个月，而系统 88% 的痛点原封不动。这是典型的用框架迁移掩盖架构治理的反模式。

如果确实要"换点什么"，**值得换的不是 Web 框架，而是这两项**：

1. **SQLite → PostgreSQL**（当并发写 > 20 或库 > 5 GB 时）——解决真实的写竞争
2. **进程内 APScheduler → 独立调度进程**（独立 APScheduler 服务 / Celery beat / Windows 计划任务）——解决 ETL 与 Web 的运维耦合

这两项都**不需要**动 FastAPI。

### 2.3 什么时候该重新评估（量化触发条件）

| 触发条件 | 建议动作 |
|----------|---------|
| 需要多租户 + 细粒度权限 + 操作审计 | 评估 Django，或 FastAPI + Casbin（后者仍更省） |
| 数据库并发写 > 20 或主库 > 5 GB | 换 PostgreSQL，**不换 Web 框架** |
| 定时任务 > 60 个，或需要 DAG 依赖 / 复杂重试策略 | 换 Airflow / Prefect，**不换 Web 框架** |
| 团队规模 > 3 人且缺乏架构约定执行力 | Django 的强目录约定才开始产生正收益 |
| 需要对外提供公网多租户 SaaS | 届时重新做整体架构评审 |

以上任一条件均**尚未**触发。

---

## 三、工作量估算

### 方案 A：迁移至 Django / DRF（不推荐）

| 编号 | 工作项 | 说明 | 人日 |
|------|--------|------|------|
| A1 | 53 个端点重写为 DRF views/serializers | 平均 0.4 人日/端点，含单测 | 21 |
| A2 | services 层（21.8 K 行）搬迁与 DB 适配 | 纯 Python 可原样搬，但 71 处 `get_raw_connection` 需适配；若保留裸 sqlite3，则 Django ORM 名存实亡 | 10 |
| A3 | 调度体系重写（Celery / django-q） | 1145 行 `task_runner` + 550 行 `task_registry`：调度、执行日志、call_chain 静态分析、手动触发、cron 编辑全部要重做 | 8 |
| A4 | 36 张表 `inspectdb` + 手工修正 + 初始 migration | 动态表结构需要特殊处理 | 4 |
| A5 | 前端接口结构对齐 | 若严格保持 URL 与响应体不变可压到 2 人日；DRF 默认分页/错误结构不同，实际会有偏差 | 5 |
| A6 | 测试重写与回归补齐 | 现有 2474 行测试需重写 5 人日 + 补回归 5 人日 | 10 |
| A7 | 双跑验证与上线切换 | 29 个任务 × 外部系统（UME / eFlow / FTP / EWS / 远程写服务），至少跑满一个完整周期（1 周）+ 回滚预案 | 6 |
| | **合计** | | **64（区间 55–75）** |

**隐性成本**：
- 单人全职约 **3 个月**，期间新需求基本冻结
- 迁移期风险叠加：基线失败率本就 9.8%，新环境下逐个复验 29 个外部集成，问题定位将极其痛苦
- 数据迁移：若仅保留 SQLite 约 1 人日；若同时上 PostgreSQL 需 **+5 人日**（类型映射、`to_sql` 方言差异、7.99 万行导入、远程 `db_writer` 兼容）

### 方案 B：原地演进（推荐）

#### P0 — 止血（8 人日，建议 2 周内完成）

| 编号 | 工作项 | 人日 |
|------|--------|------|
| B1-1 | 调度器显式配置：`ThreadPoolExecutor(max_workers=20)`、`misfire_grace_time=3600`、`coalesce=True`、`max_instances=1` | 0.5 |
| B1-2 | 长任务隔离：`eflow_history_alarm`(40 min)、`main_kpi_sync`(12 min)、`ms_sla_full`(10 min) 等拆到独立调度器实例或独立进程，与短任务分池 | 2.5 |
| B2-1 | SQLite 治理：`journal_mode` 在 `database.py` 单点设定（选 WAL），删除散落 7 处 `PRAGMA`；加定期 `wal_checkpoint` + `VACUUM`；`task_execution_log` 等日志表迁到独立库 | 2 |
| B2-2 | 高失败任务根因：`email_recovery`(48%)、`liberia_email_1h`(45%)、`liberia_email_8h`(41%) | 2.5 |
| B2-3 | 修 F-1 / F-2 / F-3 已知 bug | 0.5 |
| | **小计** | **8** |

#### P1 — 降耦合（12 人日）

| 编号 | 工作项 | 人日 |
|------|--------|------|
| B3 | 抽 UME 公共客户端：`_rsa_encrypt_pem` / `_http_request_with_retry` / `_create_ssl_socket` / `create_history_query` / `login` / `export_history` 收敛为 1 份，4 个服务复用（可减约 2500 行） | 4 |
| B4-1 | 路由瘦身：74 处 SQL / pandas 下沉到 services，router 只留校验与序列化 | 3 |
| B4-2 | 9 处硬编码密码收口到 `credential_store` | 1 |
| B5 | 前端引入 `react-router` + TanStack Query，统一数据层，替换自研 cache 与手写 switch 路由 | 4 |
| | **小计** | **12** |

#### P2 — 条件触发（15 人日，仅在触发阈值时执行）

| 编号 | 工作项 | 触发条件 | 人日 |
|------|--------|---------|------|
| B6 | SQLite → PostgreSQL | 并发写 > 20 或库 > 5 GB | 8 |
| B7 | 调度独立成服务，FastAPI 只读展示 | 重启中断长任务成为常态痛点 | 5 |
| B8 | 多用户 / RBAC | 出现真实多用户需求 | 2 |

### 方案对比总表

| 维度 | 方案 A（迁 Django） | 方案 B（原地演进 P0+P1） |
|------|---------------------|--------------------------|
| 工作量 | 55–75 人日 | **20 人日** |
| 周期 | 单人约 3 个月 | 分批增量，2–5 周 |
| 需求冻结 | 是，全程 | 否 |
| 停机风险 | 高（一次性切换） | 低（可灰度、可回滚） |
| 触达痛点比例 | 约 12%（仅 Web 层 + ORM 层） | 约 80% |
| 解决调度并发 | ❌ | ✅ |
| 解决 SQLite 竞争 | ❌ | ✅（P0 缓解，P2 根治） |
| 消除 2500 行重复 | ❌（原样搬迁） | ✅ |
| 降低 9.8% 失败率 | ❌ | ✅ |
| 引入新风险 | 高（29 个外部集成需全量复验） | 低 |

---

## 四、行动建议

1. **立即执行 P0（8 人日）**：调度器配置是一行代码换来最大收益的改动，优先做。
2. **两周内启动 P1（12 人日）**：UME 公共层抽取是遏制维护成本继续恶化的关键，越晚做重复越多。
3. **不启动 Django 迁移**，把评估结论与量化触发条件写入项目文档，避免反复讨论。
4. **建立监控**：现在能算出 9.8% 失败率是因为有 `task_execution_log`，但没人看。建议给失败率 > 15% 或单任务连续失败 3 次配告警。
5. **纠正文档漂移**：`MEMORY.md` 中 "journal_mode=DELETE" 与实测 WAL 不符，已同步更正。


# 4. FastAPI 架构优化方案

# my_app FastAPI 架构优化计划（方案A）

> 评估时间：2026-08-05
> 目标：在保持 FastAPI 技术栈的前提下，通过 5 个阶段的渐进式重构，解决随功能增长积累的架构债务，使项目可持续扩展。

---

## 一、架构现状评估

### 1.1 项目规模

| 维度 | 数据 |
|---|---|
| 后端 Python 文件 | 62 个，约 **31,123 行** |
| 前端 TypeScript/TSX 文件 | 36 个，约 394 KB |
| 主数据库 app.db | **147 MB**（WAL 文件 11.78 MB） |
| 定时任务 | **27 个**（task_registry.py 声明式注册） |
| 前端页面 | **13 个**（计划集成 IP Trace / Incident Overview 至 15 个） |
| API Router | 9 个独立 router + main.py 内嵌若干端点 |
| Service 层 | **39 个文件**，最大单文件 118 KB |

### 1.2 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI (ASGI) + uvicorn |
| ORM/数据库 | SQLAlchemy 2.0 + 原生 sqlite3 混用 |
| 任务调度 | APScheduler BackgroundScheduler（进程内线程池） |
| 数据库 | SQLite（主库 app.db + 多个辅助库） |
| 前端框架 | React 19 + Vite 8 + TypeScript |
| UI 组件 | Ant Design 6 + ECharts 6 + Leaflet/react-leaflet |
| 鉴权 | IP 白名单 + 静态 X-API-Token（security.py） |

### 1.3 架构分层现状

```
backend/
├── main.py (432行)          ← 直接定义 ~120 行业务端点 + 路由注册 + 启动逻辑
├── routers/ (9个文件)        ← 模块化路由
│   ├── gis.py (883行)
│   ├── alarm_dashboard.py (613行)
│   ├── tt_wo_dashboard.py (460行)
│   ├── battery_dashboard.py (457行)
│   ├── packet_loss_dashboard.py (252行)
│   ├── analysis.py (306行)
│   ├── tables.py (190行)
│   ├── upload.py (156行)
│   └── credentials.py (118行)
├── services/ (39个文件)      ← 业务逻辑层
│   ├── eflow_api_client.py (118KB)    ← 最大
│   ├── ms_sla_service.py (118KB)      ← 最大
│   ├── site_outage_service.py (50KB)
│   ├── ran_ume_network_kpi.py (50KB)
│   ├── ran_ume_main_kpi.py (48KB)
│   ├── task_runner.py (48KB)
│   ├── ipran_ume_kpi_service.py (53KB)
│   ├── ccn_ume_kpi_service.py (40KB)
│   ├── sp_dashboard.py (39KB)
│   ├── battary_kpi_fetch/battery_kpi_service.py (47KB)
│   └── ... (其余 29 个文件)
├── models/ (2个文件)         ← ORM 模型几乎缺失
│   └── analysis.py (32行)
├── database.py (124行)       ← 连接管理 + _ClosingConnection
├── security.py (27行)        ← IP白名单 + Token
└── task_registry.py (294行)  ← 声明式任务清单 TASK_SPECS
```

### 1.4 数据库表分布

| 表来源 | 表名 | 创建方式 |
|---|---|---|
| 代码 CREATE TABLE | task_schedule_config | task_runner.py |
| 代码 CREATE TABLE | task_execution_log | task_runner.py |
| 代码 CREATE TABLE | credentials | credential_store.py |
| 代码 CREATE TABLE | uploaded_files | main.py |
| 代码 CREATE TABLE | sp_sync_log | get_sp_table.py |
| 代码 CREATE TABLE | analysis_archive | scripts/init_db.py |
| 代码 CREATE TABLE | packet_loss_data / site_pl_summary / pl_meta | packet_loss_service.py |
| 代码 CREATE TABLE | battery_latest / battery_reading / battery_trend / battery_meta | battery_kpi_service.py |
| eFlow 同步动态创建 | eflow_tt / eflow_wo / eflow_cr / eflow_pm / eflow_site / eflow_person | sync_from_eflow_api.py |
| 外部导入 | master_site_db / topology | import_topology.py |

### 1.5 六大问题诊断

**问题1：ORM/Model 层几乎缺失（严重度：高）**

`models/` 目录仅有 `analysis.py`（32 行）。所有其他表通过 raw SQL `CREATE TABLE IF NOT EXISTS` 管理：
- 无 migration 管理，多机部署 schema 变更无法自动迁移
- 表结构不透明，调试/扩展需翻阅散落各处的 SQL 字符串
- 数据完整性无 ORM 层保障

**问题2：main.py 承载过多职责（严重度：中）**

main.py 432 行中约 120+ 行是直接定义的业务 API 端点：
- `/api/tasks*` 系列（约 10 个端点）
- `/api/sp-data/*`、`/api/data`、`/api/warehouses`、`/api/details`（SP 备件看板）
- `/api/health`、`/api/data-source/timestamps`、`/api/db/info`（系统信息）

修改任一业务功能都要动 main.py，路由注册与业务逻辑混杂。

**问题3：Service 单文件过大（严重度：中）**

| 文件 | 大小 | 混合职责 |
|---|---|---|
| eflow_api_client.py | 118 KB | HTTP客户端 + 数据映射 + 告警解析 + FTP |
| ms_sla_service.py | 118 KB | SLA计算 + 报表生成 + 邮件 + FTP |
| site_outage_service.py | 50 KB | 截图 + 数据处理 + 文件管理 |
| task_runner.py | 48 KB | 调度核心 + 统计查询 + 调用链分析 |
| report/mail_126.py | 48 KB | 邮件发送 + 附件处理 + 模板渲染 |

**问题4：SQLite + 进程内调度并发瓶颈（严重度：高）**

- 27 个定时任务 + Web 请求在**同一进程**内，APScheduler 线程池（默认 10 线程）
- SQLite 单写锁：多任务同时写 app.db 时串行等待（busy_timeout=30s）
- app.db 已达 147 MB，历史数据持续增长，查询性能将下降
- 多个辅助 SQLite 库分散管理（battery_kpi.sqlite3、lte_pl.sqlite3、db_ps_cs_cn.sqlite3）

**问题5：鉴权体系薄弱（严重度：低-中）**

- 仅 IP 白名单 + 静态 Token，无用户账户体系
- 无角色/权限控制，无操作审计日志
- 使用人数增加或需区分权限时将成为瓶颈

**问题6：前端无路由库 + 无全局状态管理（严重度：低）**

- 用 `useState` 管理当前页面，无 react-router，无法深链接
- 无 Zustand/Redux，跨页面数据共享困难

### 1.6 迁移 Django 对比结论

| 维度 | 继续 FastAPI + 架构优化 | 迁移 Django |
|---|---|---|
| 工作量 | 约 18-21 人天（3-4 周） | 约 26-32 人天（4-6 周） |
| 风险 | 低（增量改造，前端零改动） | 高（全量重写，回归风险大） |
| ORM/Migration | Alembic（完全等价） | 内置（更便利） |
| 任务调度解耦 | 独立 Worker 进程（等价） | Celery + Redis（等价） |
| 异步性能 | FastAPI 原生异步 优势保留 | Django 4.x async 仍不成熟 |
| 免费 Admin | 无（需 fastapi-admin 或自建） | Django Admin 内置 |
| 团队学习成本 | 低（已有 SQLAlchemy 基础） | 中（Django 约定多） |

**结论：不建议迁移 Django。** 当前痛点根源在架构组织而非框架选型，同样的组织问题在 Django 中也会出现。通过 5 阶段渐进优化可解决全部已知问题。

---

## 二、Phase 1 — main.py 端点拆分

**工时估算：2 天**

### 2.1 目标

main.py 仅保留：app 创建、CORS 配置、router 注册、startup 事件、静态文件挂载。
所有业务端点下沉到对应 router。

### 2.2 改动清单

| 操作 | 文件 | 说明 |
|---|---|---|
| 新建 | `routers/tasks.py` | 迁移 /api/tasks* 全部端点（list / history / failures / {task_id} / run / status / stats / schedule / toggle）+ /api/eflow/sync、/api/eflow/status |
| 新建 | `routers/sp_dashboard.py` | 迁移 /api/sp-data/*、/api/data、/api/warehouses、/api/details |
| 新建 | `routers/system.py` | 迁移 /api/health、/api/data-source/timestamps、/api/db/info |
| 修改 | `main.py` | 删除迁移出的端点代码，新增 `app.include_router()` 注册 3 个新 router |

### 2.3 预期效果

- main.py 从 432 行缩减至约 120 行
- 所有 API 路径与返回结构**完全不变**（前端零改动）
- 新增/修改业务端点时只需关注对应 router 文件

### 2.4 验证方式

1. 启动后端，`GET /api/health` 正常返回
2. `GET /api/tasks` 返回任务列表，结构与迁移前一致
3. `GET /api/sp-data/summary`、`GET /api/data`、`GET /api/db/info` 逐一验证
4. 现有前端页面（DataSync、WarehouseDashboard 等）功能回归无异常

---

## 三、Phase 2 — Model 补全 + Alembic Migration

**工时估算：4-5 天**

### 3.1 目标

- 所有表有 SQLAlchemy 模型定义（显式或反射）
- schema 变更通过 Alembic migration 管理
- 保留 `get_raw_connection` 供动态表查询，ORM 会话用于结构化读写

### 3.2 改动清单

#### 3.2.1 补建 ORM 模型

| 新建文件 | 对应表 |
|---|---|
| `models/task_schedule.py` | task_schedule_config |
| `models/task_execution.py` | task_execution_log |
| `models/credential.py` | credentials |
| `models/uploaded_file.py` | uploaded_files |
| `models/sp_sync.py` | sp_sync_log |
| `models/analysis.py`（扩展） | analysis_archive（已有模型则复用） |
| `models/packet_loss.py` | packet_loss_data / site_pl_summary / pl_meta |
| `models/battery.py` | battery_latest / battery_reading / battery_trend / battery_meta |
| `models/eflow.py` | eflow_tt / eflow_wo / eflow_cr / eflow_pm / eflow_site / eflow_person |
| `models/site.py` | master_site_db / topology |

#### 3.2.2 引入 Alembic

```bash
cd d:\01_RPA\Task\my_app
pip install alembic
alembic init alembic
```

- 修改 `alembic/env.py`：导入 `backend.database.Base.metadata`，配置 `target_metadata`
- 修改 `alembic.ini`：`sqlalchemy.url` 指向 `db/app.db`
- 生成初始 baseline：`alembic revision --autogenerate -m "baseline"`
- 对现有库标记：`alembic stamp head`（跳过已存在的表结构）

#### 3.2.3 逐步替换 raw SQL

- 新增/修改数据时优先使用 ORM 会话（`SessionLocal()`）
- 动态表查询（如 `PRAGMA table_info`、`SELECT name FROM sqlite_master`）保留 `get_raw_connection`
- 删除散落的 `CREATE TABLE IF NOT EXISTS`，改由 Alembic migration 管理

### 3.3 验证方式

1. `alembic upgrade head` 在空库上建出与现库一致的表结构
2. `alembic downgrade base` + `alembic upgrade head` 幂等可重复
3. 现有 API 回归：`GET /api/tasks`、`GET /api/db/info` 等正常
4. 新增一条 migration 验证流程：修改某模型字段 → `alembic revision --autogenerate` → `alembic upgrade head`

---

## 四、Phase 3 — 任务调度解耦

**工时估算：4 天**

### 4.1 目标

27 个定时任务不再与 Web 进程争抢线程/DB 锁。Web 进程专注 API 响应，任务执行在独立 Worker 进程。

### 4.2 方案选型

| 方案 | 优点 | 缺点 | 适用场景 |
|---|---|---|---|
| **独立 Worker 进程（推荐）** | 改动最小；不引入 Redis/RabbitMQ；符合"无外部依赖"约束 | 需自建进程间通信（SQLite 任务队列表） | 当前规模（27 任务、单机部署） |
| Celery + Redis | 成熟方案；支持分布式；任务重试/超时管理完善 | 引入 Redis 依赖；部署复杂度增加；学习曲线 | 未来多机扩展 |

**推荐方案：独立 Worker 进程**

### 4.3 改动清单

#### 4.3.1 task_runner 改造

- 新增 `worker` 模式：`task_runner.py` 支持 `--worker` 参数启动纯 Worker 进程
- Web 进程：仅运行 APScheduler 调度器，触发任务时写入 `task_queue` 表（新增）
- Worker 进程：轮询 `task_queue` 表，取出待执行任务，执行后更新 `task_execution_log`
- 重型任务（RAN UME、eFlow 同步、邮件类）标记为 `async_exec=True`，强制走 Worker

#### 4.3.2 新增 task_queue 表

```sql
CREATE TABLE IF NOT EXISTS task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / running / done / failed
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    result TEXT,
    error TEXT
);
```

#### 4.3.3 启停脚本更新

- `start.bat` 增加启动 worker 进程：`start /B python -m backend.worker`
- `stop.bat` 增加终止 worker 进程逻辑

### 4.4 验证方式

1. 仅启动 Web 进程（不启动 Worker），`GET /api/health` 响应时间 < 100ms
2. 启动 Worker，手动触发重型任务（如 eFlow 同步），Web 接口响应不受影响
3. `GET /api/tasks` 中任务执行历史正常落库
4. 停止 Worker，任务排队不丢失（pending 状态保留在 task_queue 表中）

---

## 五、Phase 4 — Service 大文件拆分

**工时估算：5-7 天**

### 5.1 目标

单文件 < 1500 行，职责单一。每个 service 文件聚焦一个明确的业务域。

### 5.2 拆分清单

#### 5.2.1 eflow_api_client.py (118 KB) → 3 个文件

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `eflow_api_client.py` | HTTP 客户端、认证、重试、连接池 | ~800 行 |
| `eflow_data_mapper.py` | 数据映射、字段转换、入库逻辑 | ~600 行 |
| `eflow_alarm_service.py` | 实时/历史告警解析与存储 | ~500 行 |

#### 5.2.2 ms_sla_service.py (118 KB) → 3 个文件

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `ms_sla_sync.py` | SLA 数据同步（API 拉取 + 入库） | ~700 行 |
| `ms_sla_report.py` | 报表生成（Excel/图表） | ~500 行 |
| `ms_sla_email.py` | 邮件发送（名单获取 + 发送逻辑） | ~400 行 |

#### 5.2.3 task_runner.py (48 KB) → 3 个文件

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `task_runner.py` | 调度核心（注册、调度、执行） | ~600 行 |
| `task_stats.py` | 统计查询（成功率、耗时、历史） | ~300 行 |
| `task_introspect.py` | 调用链静态分析、源码解析 | ~200 行 |

#### 5.2.4 邮件公共逻辑抽取

| 新文件 | 职责 |
|---|---|
| `services/email/__init__.py` | 邮件包入口 |
| `services/email/sender.py` | 通用邮件发送（SMTP/EWS） |
| `services/email/recipient.py` | 远程名单获取与解析 |
| `services/report/mail_126.py` | 保留，但调用 sender.py 公共接口 |

### 5.3 约束

- `task_registry.py` 中的 `loader` 入口函数名**不变**，保证任务注册零改动
- 拆分后的模块通过 `__init__.py` 暴露与原文件相同的公共接口，外部 import 路径不变
- 每个新文件同目录配 MD 文档（遵循 code_rules.md）

### 5.4 验证方式

1. 27 个任务逐一通过 `POST /api/tasks/{task_id}/run` 手动触发，确认执行成功
2. `pytest tests/` 全部通过
3. grep 扫描确认无残留的旧 import 路径
4. 各 service 文件行数 < 1500 行

---

## 六、Phase 5 — 数据库升级评估（可选触发）

**工时估算：3 天（仅评估+预案，不立即执行）**

### 6.1 触发条件

满足以下**任一**条件时启动本阶段：

| 指标 | 阈值 |
|---|---|
| app.db 文件大小 | > 500 MB |
| 并发操作用户数 | > 5 人 |
| "database is locked" 错误频率 | > 5 次/天 |
| 单次查询 P95 延迟 | > 2 秒 |

### 6.2 升级路径：SQLite → PostgreSQL

#### 6.2.1 SQLAlchemy 层切换

```python
# database.py 改造（DATABASE_URL 从环境变量读取）
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{DB_PATH}"  # 默认 SQLite，切换时设置 DATABASE_URL=postgresql://...
)
```

- SQLAlchemy ORM 层无需改动（已使用标准 API）
- Alembic migration 重跑：`alembic downgrade base` → 切换 DATABASE_URL → `alembic upgrade head`
- `get_raw_connection` 需适配 PostgreSQL（psycopg2 连接）

#### 6.2.2 数据迁移

```bash
# 使用 pgloader 或自定义脚本迁移数据
pgloader sqlite:///db/app.db postgresql://user:pass@host/dbname
```

#### 6.2.3 辅助库统一归口

| 当前分散库 | 归口策略 |
|---|---|
| battery_kpi.sqlite3 | 合并至主库（PostgreSQL schema: battery） |
| lte_pl.sqlite3 | 合并至主库（PostgreSQL schema: packet_loss） |
| db_ps_cs_cn.sqlite3 | 合并至主库（PostgreSQL schema: core_network） |
| ipran_ume_kpi.sqlite3 | 合并至主库（PostgreSQL schema: ipran） |
| fw_db.sqlite（远程） | 保持独立（跨设备，API 写入） |

### 6.3 历史数据归档策略

对 eflow_tt 等大表（随时间持续增长）：
- 按月分区：`eflow_tt_202601`、`eflow_tt_202602`...
- 超过 6 个月的数据归档至 `eflow_tt_archive` 表（只读）
- 前端查询默认走活跃分区，归档查询走专用 API

### 6.4 当前结论

app.db 147 MB 仍在 SQLite 舒适区（SQLite 理论上限 281 TB，实际推荐 < 1 GB）。Phase 5 暂列为**评估与预案**，不立即执行。当触发条件满足时再启动。

---

## 七、总览

### 7.1 五阶段依赖关系

```mermaid
graph LR
    P1[Phase 1: main.py 拆分] --> P3[Phase 3: 任务调度解耦]
    P2[Phase 2: Model + Alembic] --> P3
    P4[Phase 4: Service 拆分]
    P5[Phase 5: 数据库升级评估]
    P1 --> P2
    P3 -.->|按需| P5
```

- Phase 1 和 Phase 2 可部分并行（Phase 1 先完成 router 拆分，Phase 2 补建模型）
- Phase 3 依赖 Phase 1（需要 router 拆分完成后才能 cleanly 分离 Web/Worker 进程）
- Phase 4 独立，可随时启动
- Phase 5 按需触发

### 7.2 总工时估算

| 阶段 | 工时 | 优先级 |
|---|---|---|
| Phase 1: main.py 拆分 | 2 天 | 高（立即可做） |
| Phase 2: Model + Alembic | 4-5 天 | 高 |
| Phase 3: 任务调度解耦 | 4 天 | 中 |
| Phase 4: Service 拆分 | 5-7 天 | 中 |
| Phase 5: 数据库升级评估 | 3 天 | 低（按需触发） |
| **合计** | **18-21 人天（3-4 周）** | |

### 7.3 风险与回滚策略

| 风险 | 概率 | 影响 | 回滚策略 |
|---|---|---|---|
| Phase 1 router 拆分导致 API 路径变化 | 低 | 高 | Git 回退；API 路径不变是硬约束 |
| Phase 2 Alembic migration 与现有表冲突 | 中 | 中 | `alembic stamp head` 标记现有库；空库测试先行 |
| Phase 3 Worker 进程任务丢失 | 中 | 高 | task_queue 表持久化；Worker 重启后自动恢复 pending 任务 |
| Phase 4 拆分后 import 路径断裂 | 低 | 中 | `__init__.py` 暴露兼容接口；grep 扫描验证 |
| Phase 5 PostgreSQL 迁移数据丢失 | 低 | 极高 | 迁移前完整备份；迁移后逐表行数校验 |

### 7.4 各阶段验收标准

| 阶段 | 验收标准 |
|---|---|
| Phase 1 | main.py < 150 行；所有 API 端点 curl 验证通过；前端页面无回归 |
| Phase 2 | 所有表有 ORM 模型；`alembic upgrade head` 空库可建；现有 API 回归正常 |
| Phase 3 | Web 进程与 Worker 进程可独立启停；重型任务执行时 /api/health 响应 < 100ms |
| Phase 4 | 所有 service 文件 < 1500 行；27 个任务手动触发全部成功；pytest 通过 |
| Phase 5 | 完成 PostgreSQL 迁移方案文档；数据迁移脚本在测试环境验证通过 |

---

## 附录：文件改动总览

### Phase 1 新增/修改

```
backend/routers/tasks.py          (新建)
backend/routers/sp_dashboard.py   (新建)
backend/routers/system.py         (新建)
backend/main.py                   (修改：删除迁移端点，新增 include_router)
```

### Phase 2 新增/修改

```
backend/models/task_schedule.py   (新建)
backend/models/task_execution.py  (新建)
backend/models/credential.py      (新建)
backend/models/uploaded_file.py   (新建)
backend/models/sp_sync.py         (新建)
backend/models/packet_loss.py     (新建)
backend/models/battery.py         (新建)
backend/models/eflow.py           (新建)
backend/models/site.py            (新建)
alembic/                          (新建目录)
alembic.ini                       (新建)
backend/requirements.txt          (修改：新增 alembic)
```

### Phase 3 新增/修改

```
backend/worker.py                 (新建)
backend/services/task_runner.py   (修改：支持 worker 模式)
start.bat                         (修改：增加 worker 启动)
stop.bat                          (修改：增加 worker 终止)
```

### Phase 4 新增/修改

```
backend/services/eflow_data_mapper.py       (新建)
backend/services/eflow_alarm_service.py     (新建)
backend/services/ms_sla_sync.py             (新建)
backend/services/ms_sla_report.py           (新建)
backend/services/ms_sla_email.py            (新建)
backend/services/task_stats.py              (新建)
backend/services/task_introspect.py         (新建)
backend/services/email/__init__.py          (新建)
backend/services/email/sender.py            (新建)
backend/services/email/recipient.py         (新建)
backend/services/eflow_api_client.py        (修改：瘦身)
backend/services/ms_sla_service.py          (修改：瘦身或拆分)
backend/services/task_runner.py             (修改：瘦身)
backend/services/report/mail_126.py         (修改：调用公共接口)
```


# 5. 国际化（i18n）审计报告

# my_app 国际化（i18n）系统审计报告

- 审计对象：`D:\01_RPA\Task\my_app`
- 审计日期：2026-08-05
- 审计方式：静态全量扫描（`TMP/i18n_audit.py`、`i18n_audit_en.py`、`i18n_classify.py`、`i18n_backend_scan.py`）+ 后端实测（`curl -H "Accept-Language: en|zh-CN" /api/tasks`）
- 覆盖范围：前端 22 个 `.tsx/.ts`（7157 行）、后端 62 个 `.py`、`index.html`、`public/warehouse-dashboard.html`

---

## 1. 架构现状

| 项 | 现状 |
|---|---|
| 方案 | 自研 React Context（`frontend/src/i18n.tsx`），**无** react-i18next/FormatJS |
| 语言 | `zh` / `en`，单文件内联字典 |
| 键总量 | zh **413**，en **412** |
| 回退链 | `translations[locale][key]` → `translations['zh'][key]` → `key` |
| 持久化 | `localStorage['app-locale']`，缺省探测 `navigator.language` |
| 组件库 | antd `ConfigProvider locale` 已随语言切换（`zhCN`/`enUS`）✅ |
| 后端协商 | `Accept-Language` 头，仅 `/api/tasks`、`/api/tasks/{id}` 两个端点 |

**结论：机制本身可用且设计合理，问题全部出在「覆盖率」和「实现一致性」。**

---

## 2. 缺陷清单（按严重度）

### P0 — 界面直接暴露原始 key（3 处）

`t()` 调用了字典中不存在的键，回退链最终返回 key 字符串本身，中英文模式下都会把 `batt.count` 这类技术标识符渲染到界面上。

| 键 | 位置 | 渲染位置 |
|---|---|---|
| `batt.count` | `pages/BatteryDashboard.tsx:399` | ECharts 趋势图 **右侧 Y 轴名称** |
| `batt.samples` | `pages/BatteryDashboard.tsx:406` | ECharts 趋势图 **图例/series 名** |
| `gis.drilldown.colTTNo` | `pages/gismap/helpers.tsx:160` | WO 明细表 **列头** |

修复：在 `i18n.tsx` 的 zh/en 两侧各补 3 个键。

---

### P1 — 整页未国际化

#### 2.1 `pages/TTWODashboard.tsx`（687 行）— 覆盖率 0%
文件第 15 行 `import { useI18n }`、第 68 行 `const { t } = useI18n()`，**但全文 0 次 `t()` 调用**，`t` 变量被解构后从未使用。全部 37 处面向用户文案为英文硬编码：

- KPI 标签：`TT Total` / `WO Total` / `WO No. (Unique)`
- 卡片标题：`TT Statistics` / `MTTR Weekly Trend` / `Domain & Root Cause Analysis` / `Work Order Analytics` / `Site Information`
- 图表标题：`Ticket Severity` / `SLA Status` / `TT by Domain` / `Root Cause (Main)` / `Root Cause (Sub)` / `WO by Source` / `WO by Status`
- 时间筛选：`All Time` / `Last 7 days` / `Last 30 days` / `Last 3 months` / `Last 6 months` / `Custom`
- 状态文案：`Loading TT&WO data...` / `Failed to load TT&WO Dashboard data` / `No data returned`
- 占位符：`All Regions` / `Search across all fields...`
- 图表轴名：`TT Count` / `MTTR (min)`

字典中 **`ttwo.*` 命名空间条目数 = 0**，即从未为该页建过翻译。

#### 2.2 `pages/AlarmDashboard.tsx`（732 行）— 覆盖率约 10%
仅 4 处 `t()`（`alarm.drillHint`、`alarm.dispatchedWithTT`、`alarm.overdueDesc`、`alarm.recordCount`），其余 37 处英文硬编码：`Total Active Alarms`、`Affected Sites`、`Total Alarm Hours`、`Critical Alerts`、`History Alarm Dispatch Timeliness`、`Dispatch Delay (Eflow)`、`Alarm Fetch Delay`、`Dispatch Overdue Total`、`Alarm Breakdown`、`Technology Distribution`、`Severity Distribution`、`Network Type`、`Regional Alarm Profile` 等。

另有 **2 处中文硬编码**，且其中一处是死三元：
```tsx
// AlarmDashboard.tsx:88  —— 两个分支完全相同，判断无意义
{label !== 'Critical Alerts' ? '点击下钻' : '点击下钻'} <RightOutlined/>
// AlarmDashboard.tsx:582
点击下钻 <RightOutlined/>
```
字典里已有 `alarm.drillHint`（zh `点击下钻明细 →` / en `Click to drill down →`），第 118 行也正确用了它 —— 88、582 两处属遗漏。

#### 2.3 `pages/WarehouseDashboard.tsx` — 完全脱离 i18n 体系
该页是 `<iframe src="warehouse-dashboard.html">`，静态 HTML（116 KB）**不接收语言上下文**，语言恒定不变。且其中含中文 `alert()` 文案（`邮件发送成功！`、`请输入收件人邮箱地址：`、`邮件发送失败: ...`）混在英文界面里。

连带后果：字典中 **12 个 `sp.*` 键全部成为死键**（`sp.inbound`/`sp.outbound`/`sp.inventory`/`sp.ocRule`/`sp.transfer`/`sp.closed`/`sp.unclosed`/`sp.countByTable`/`sp.invTypeDist`/`sp.detailTables`/`sp.searchPlaceholder`/`sp.loadRowsError`/`sp.lastSync`），系早期 React 版遗留。

---

### P1 — Task Manager 模块：三套 i18n 机制并存

`pages/DataSync.tsx` + `pages/datasync/*` 同时使用三种方式，无统一规范：

| 机制 | 用量 | 说明 |
|---|---|---|
| `t('key')` | 16 处 | 标准方式 |
| `locale === 'zh' ? '中文' : 'EN'` 内联三元 | **66 处** | 能切换，但文案散落在 JSX 里，无法集中维护/复用 |
| `label_zh` / `label_en` 对象字段 | 32 组 | `helpers.tsx` 的 `CRON_PRESETS`、`CATEGORY_CONFIG`；`DataSync.tsx` 的 `ROW_GROUPS` |

连带后果：**8 个 `sync.*` 键成为死键**（`sync.title`/`sync.subtitle`/`sync.syncNow`/`sync.syncing`/`sync.syncSuccess`/`sync.syncFailed`/`sync.noHistory`）—— 页面重写时改用了三元，旧键未清理。

#### 该模块内的确定性 BUG

**① `DataSync.tsx:606` — 分类筛选下拉在英文模式下混排中文**
```tsx
options={[
  { value: 'all', label: locale === 'zh' ? '全部分类' : 'All Categories' },  // ✅ 会切换
  ...Object.keys(CATEGORY_CONFIG).map(c => ({ value: c, label: CATEGORY_CONFIG[c].label_zh })),  // ❌ 写死 label_zh
]}
```
英文模式下该下拉显示为：`All Categories` / `eFlow 数据` / `通用` / `SP 备件` / `邮件报告` / `电池 KPI` … 中英混排。
同文件 441 行、686 行的同类调用都正确写了 `locale === 'zh' ? label_zh : label_en`，仅此处漏判。

**② `DataSync.tsx:657` — 失败任务兜底文案硬编码**
```tsx
{firstLine(t.recent_runs?.[0]?.error || '未知错误')}
```
英文模式下失败任务卡片显示"未知错误"。

---

### P1 — 后端调用链标注全中文（28/28）

实测 `GET /api/tasks` 携带 `Accept-Language: en`：
- `name` / `description`：**28 个任务全部正确返回英文**，无一残留中文 ✅
- `call_chain`：**28/28 全部含中文**，且英文模式下原样透出到前端 Tooltip ❌

示例（EN 模式实际返回）：
```
sync_from_eflow_api (backend/services/sync_from_eflow_api.py:485)
  ⟵ [DB: app.db (db/app.db, 主) ; DB: eflow.sqlite3 (data/eflow/, 报告生成副产品) ;
     API: eFlow (10.100.20.8) ; 远程DB: db.sqlite3 (via db_writer API, ...) ;
     远程FTP: tt_reports 上传 (FTP_REMOTE_DIR, 默认 /Python)]
```
标注文本在 `backend/services/task_runner.py` 的 `TASK_IO` / `CALL_CHAIN_IO` 两张表里，目前是单语字符串。

---

### P2 — 后端错误文案全中文直传前端（43 处）

后端 `HTTPException.detail` 与响应字段中的中文，被前端**拼接在已翻译前缀之后**直接展示，产生"英文前缀 + 中文详情"的混合语言：

```tsx
// CredentialSettings.tsx:76
message.error(t('settings.saveFailed') + ': ' + e?.response?.data?.detail)
// EN 模式实际效果：Save failed: 未知凭据组: xxx

// DataUpload.tsx:58
message.error(t('upload.failed', { msg: err.response?.data?.detail }))
// EN 模式实际效果：Upload failed: 仅支持 .xlsx, .xls, .csv 文件
```

分布：`main.py` 5、`routers/tables.py` 6、`routers/credentials.py` 8、`routers/gis.py` 4、`routers/analysis.py` 4、`routers/upload.py` 3、`routers/battery_dashboard.py` 3、`services/task_runner.py` 10。

典型条目：`任务 {task_id} 未找到`、`表 {table_name} 不存在`、`表为空，无法分析`、`非法排序列名`、`仅支持 .xlsx, .xls, .csv 文件`、`未知凭据组`、`用户名和密码不能同时为空`、`无电池数据（请执行任务: battery_kpi_sync）`、`凭据已保存，最迟 30 秒后生效`、`任务正在运行中`。

同时 `main.py:170` 直接返回硬编码 `"schedule": "每小时第22分钟"`。

---

### P2 — 文档级 / 格式化问题

| 问题 | 位置 | 影响 |
|---|---|---|
| `<html lang="zh-CN">` 固定 | `frontend/index.html:2` | 英文模式下 lang 属性错误，影响屏幕阅读器发音、浏览器"翻译此页"判断、SEO |
| `<title>数据洞察 SaaS MVP</title>` 固定中文 | `frontend/index.html:6` | 浏览器标签页恒为中文；且与字典 `app.title`（数据洞察 MVP / Data Insight MVP）文案不一致 |
| `toLocaleString()` 未传 locale（**10 处**） | AlarmDashboard ×2、TTWODashboard ×4、PacketLossDashboard、Dashboard、DataUpload、TableBrowser | 千分位分隔符跟随**浏览器**语言而非**应用**语言。`DataSync.tsx:255` 是唯一正确写法（显式传 `zh-CN`/`en-US`），应作为范本 |
| dayjs locale 从未导入设置 | 全局 | 当前 4 种格式均为 `YYYY-MM-DD` 类固定模式，暂无可见问题；一旦使用 `.fromNow()` 或本地化格式将恒为英文 |

---

### P2 — Provider 时序（潜在，当前无可见症状）

```tsx
<I18nProvider>            {/* useEffect → setApiLocale(locale) */}
  <TaskStatusProvider>    {/* useEffect → api.get('/tasks')  */}
```
React 副作用**自子向父**执行，`TaskStatusProvider` 的首个 `/tasks` 请求先于 `setApiLocale` 完成，该请求不带应用层 `Accept-Language`（退化为浏览器头）。

当前无可见影响：`TaskStatusContext` 只读取 `t.running` 布尔字段，不消费 `name`/`description`。但该竞态是隐患 —— 若后续在此 Provider 中使用文案字段即会出现首屏语言错误。

建议：把 `setApiLocale(detectLocale())` 提到模块初始化（`api.ts` 或 `main.tsx`）同步执行，而非依赖 effect。

---

### P3 — 字典卫生

| 项 | 数量 | 明细 |
|---|---|---|
| 重复键 | **0** | zh / en 均无重复定义 ✅ |
| 占位符不一致 | **0** | 385 个共有键的 `{n}`/`{col}`/`{msg}` 全部对齐 ✅ |
| en 缺失键 | 1 | `gis.exportSuccess`（zh 有 en 无）。该键当前未被使用，无实际影响，但会静默回退中文 |
| en 值仍为中文 | 1 | `lang.switch: '中文'` —— **属正确设计**（切换按钮显示目标语言），非缺陷 |
| en 空串 | 3 | `overview.tableSuffix` / `overview.rowSuffix` / `table.scoreUnit` —— **属正确设计**（中文量词"表/行/分"英文不需要），非缺陷 |
| 死键（定义未使用） | **28** | `sp.*` ×13、`sync.*` ×8、`common.*` ×4（`items`/`noData`/`seconds`/`total`）、`overview.tableSuffix`/`rowSuffix`、`gis.exportSuccess`、`lang.current` |
| 动态 `t(变量)` 调用 | **0** | 所有 `t()` 均为字面量键，静态可分析性良好 ✅ |

---

## 3. 量化总览

```
字典键          zh 413 / en 412        重复 0    占位符不一致 0
实际使用         388 键                 未定义 3   死键 28
硬编码中文       112 命中 → 真缺陷 21    （其余为注释 47 / locale 三元 44）
硬编码英文        88 命中 → 真缺陷 74    （其余为 aria-label / 数据值 / 属性名等误报 14）
后端中文外泄      43 处 + call_chain 28 条
```

**按页面覆盖率（`t()` 调用数）**

| 页面 | t() 次数 | 评价 |
|---|---|---|
| BatteryDashboard | 113 | ✅ 优 |
| PacketLossDashboard / GISMap / gismap.helpers | 50 / 50 / 50 | ✅ 优 |
| SiteDrilldownDrawer | 31 | ✅ 良 |
| ArchiveList / TableBrowser / Dashboard | 28 / 26 / 26 | ✅ 良 |
| CredentialSettings / DataUpload / App | 23 / 21 / 18 | ✅ 良 |
| Overview | 11 | ✅ 良 |
| **DataSync** | 15（+66 三元） | ⚠️ 机制混乱 |
| **AlarmDashboard** | **4** | ❌ 差 |
| **TTWODashboard** | **0** | ❌ 无 |
| **WarehouseDashboard** | **0** | ❌ 体系外（iframe） |
| datasync/TaskHistoryModal、helpers | 0 | ⚠️ 全部走三元 / label_zh |

---

## 4. 修复建议（按投入产出排序）

| # | 动作 | 工作量 | 收益 |
|---|---|---|---|
| 1 | 补 3 个未定义键（`batt.count`/`batt.samples`/`gis.drilldown.colTTNo`） | 5 分钟 | **消除界面暴露技术 key** |
| 2 | 修 `DataSync.tsx:606` 改 `locale === 'zh' ? label_zh : label_en`；`:657` 兜底文案改 `t()` | 10 分钟 | 消除下拉中英混排 |
| 3 | `AlarmDashboard.tsx:88/582` 改用已有 `t('alarm.drillHint')`，删除死三元 | 5 分钟 | 消除中文泄漏 |
| 4 | `index.html`：`lang` 由 JS 按 locale 写入 `document.documentElement.lang`，`title` 用 `t('app.title')` 动态设置 | 15 分钟 | 无障碍 / 浏览器行为正确 |
| 5 | 10 处 `toLocaleString()` 统一改为 `toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US')`（参照 `DataSync.tsx:255`） | 30 分钟 | 数字格式与应用语言一致 |
| 6 | `setApiLocale` 移出 effect，改模块初始化同步调用 | 10 分钟 | 消除首屏语言竞态 |
| 7 | 后端错误改为**错误码 + 参数**（如 `{"code":"TASK_NOT_FOUND","params":{"id":...}}`），前端用 `err.<code>` 键渲染 | 半天 | 根除 43 处混合语言 |
| 8 | **TTWODashboard 全量国际化**：新建 `ttwo.*` 命名空间约 40 键 | 半天 | 补齐最大缺口 |
| 9 | **AlarmDashboard 全量国际化**：扩充 `alarm.*` 至约 45 键 | 半天 | 补齐第二大缺口 |
| 10 | Task Manager 三套机制统一到 `t()`；`CRON_PRESETS`/`CATEGORY_CONFIG`/`ROW_GROUPS` 的 `label_zh/label_en` 改为存 key，渲染时 `t(key)` | 1 天 | 可维护性 |
| 11 | 清理 28 个死键；或为 `sp.*` 找回落点（若计划把 Warehouse 从 iframe 迁回 React） | 1 小时 | 字典卫生 |
| 12 | `call_chain` 标注双语化：`TASK_IO`/`CALL_CHAIN_IO` 值改 `{"zh":..., "en":...}`，`_annotate_call_chain` 按 lang 取值 | 半天 | 英文模式完整可读 |
| 13 | 拆分 `i18n.tsx`（958 行）为 `locales/zh.ts` + `locales/en.ts`；加 CI 校验脚本（键对齐 / 未定义键 / 占位符）阻断回归 | 半天 | 防回归 |

**最小可行修复（#1–#6，约 1.5 小时）即可消除全部"界面显示原始 key / 中英混排 / 中文泄漏"类可见缺陷。**

---

## 5. 做得好的部分

- 键命名规范统一（`模块.子模块.语义`），无重复、无冲突
- 385 个共有键的插值占位符 **100% 对齐**，无 `{n}`/`{col}` 错配
- 所有 `t()` 均为字面量键，**零动态键**，静态分析与提取工具友好
- 三层回退（locale → zh → key）避免了白屏/undefined
- antd `ConfigProvider` 已正确联动，日期选择器、分页器、表格空状态等组件内建文案随语言切换
- 后端任务名/描述双语字段 **28/28 全覆盖**，`name_en`/`description_en` 无一遗漏，实测 EN 响应零中文残留
- `en` 侧刻意的空串（量词后缀）与 `lang.switch` 反向显示，说明作者对细节有考虑
- BatteryDashboard、PacketLoss、GISMap 三大模块国际化质量高，可作为其余页面的实现范本


# 6. 国际化检查（2026-08-10）

# my_app 国际化（i18n）复查 — 2026-08-10

> 复查方式：静态全量扫描（`TMP/i18n_scan.py`）+ 关键文件逐行核对 + 后端路由/数据核对。
> 对照基准：`i18n_audit_report.md`（2026-08-05）。本次确认 **Settings 页中文泄漏的根因在后端**，并复核了其余页面当前覆盖率（相比 8-5 已有部分修复落地）。

---

## 0. 用户报告的现象「Settings 页英文环境下显示中文」— 根因已定位 ✅

不是前端 `t()` 漏写，而是 **Settings 页直接渲染后端返回的字符串，后端不协商语言**。

`frontend/src/pages/CredentialSettings.tsx` 渲染了 3 个后端字段，且未做翻译：
- `g.name`（凭据组名称）、`g.username_label`、`g.secret_label`（输入框标签）

这些值来自 `backend/services/credential_store.py` 的 `CREDENTIAL_GROUPS`，**全部硬编码中文，无 `name_en` / `username_label_en` / `secret_label_en`**。`backend/routers/credentials.py` 的 `GET /api/credentials` **完全没有 Accept-Language 协商**。

后果（EN 模式下实际可见）：
- 凭据组名全是中文：`ZTE UME 网管 (RAN KPI / MS SLA)`、`iPRAN UME 网管`、`CCN UME 网管`、`eFlow 告警系统`、`FW 整机吞吐 KPI (UMC)`、`SFTP 备件报表服务器 (10.100.20.11)`、`126 邮箱（邮件报告）`、`Exchange/OWA 邮箱（运维报告 + 邮箱清理）`、`微信/即时消息通知`
- 字段标签中文：`用户名` / `密码` / `邮箱账号` / `SMTP 授权码` / `登录账号 (域账号)` / `Server酱 SendKey` / `PushPlus Token`

此外该页还把**后端中文消息**拼在已翻译前缀之后展示（EN 模式下「英文前缀 + 中文详情」）：
- `routers/credentials.py:64` PUT 成功返回 `"凭据已保存，最迟 30 秒后生效"` → 保存成功 toast 中文
- `routers/credentials.py:92` 不支持测试 → `"该系统暂不支持自动连接测试…"`
- `routers/credentials.py:108/116` 测试结果 → `"登录成功"` / `"登录失败：未获取到 Cookie"` / `"登录失败: …"`
- `routers/credentials.py:56/58/72` 错误 `detail` → `"未知凭据组: …"` / `"用户名和密码不能同时为空"`（拼在 `t('settings.saveFailed') + ': '` 之后）

---

## 1. 缺陷清单（按严重度，均经本次逐行核对）

### P0 — 后端驱动的 Settings 中文泄漏（用户报告现象）
| 位置 | 问题 | 修复方向 |
|---|---|---|
| `credential_store.py` `CREDENTIAL_GROUPS` | 组名/标签硬编码中文，无 EN 变体 | 加 `name_en`/`username_label_en`/`secret_label_en` |
| `routers/credentials.py`（GET/PUT/POST test） | 不协商 `Accept-Language`；消息/错误全中文 | 按 `Accept-Language` 返回双语，或返回错误码由前端 `t()` 渲染 |
| `CredentialSettings.tsx` | `g.name`/`g.username_label`/`g.secret_label` 直渲 | 渲染时按 locale 取 `_en` 字段 |

### P1 — 前端硬编码中文（英文模式恒显中文）
| 位置 | 内容 |
|---|---|
| `pages/DataSync.tsx:735` | `label: CATEGORY_CONFIG[c].label_zh` —— 分类筛选下拉在 EN 模式混排中文（`All Categories` + `eFlow 数据`/`通用`/`SP 备件`…） |
| `pages/AlarmDashboard.tsx:90` | 死三元 `{label !== 'Critical Alerts' ? '点击下钻' : '点击下钻'}` —— 两分支皆中文，恒显中文 |
| `pages/AlarmDashboard.tsx:593` | `'点击下钻' <RightOutlined/>` 硬编码 —— 恒显中文（已有 `alarm.drillHint` 未复用） |

### P2 — 前端兜底/格式
| 位置 | 内容 |
|---|---|
| `pages/DataSync.tsx:786` | `firstLine(error || '未知错误')` —— 错误为空时 EN 模式显示「未知错误」 |
| `pages/DataSync.tsx:563` | `（{getNextRunEta(task)}）` 中文全角括号包裹英文，EN 模式 `（in ~2h）` |

### P1 — 后端 `call_chain` 中文标注泄漏（28 个任务）
- `backend/services/task_introspect.py` 的 `TASK_IO` / `CALL_CHAIN_IO` 全为中文单语字符串（如 `"DB: app.db (db/app.db, 主)"`、`"远程FTP: tt_reports 上传"`）。
- `GET /api/tasks` 仅对 `name`/`description` 做了双语（`name_en`/`description_en`），**`call_chain` 原样透传**；`Accept-Language: en` 下 tooltip 仍显中文。

### P2 — 文档/格式化（与 8-5 审计一致，仍待修）
- `frontend/index.html:2` `<html lang="zh-CN">` 固定，EN 模式 lang 属性错误
- `frontend/index.html:6` `<title>数据洞察 SaaS MVP</title>` 固定中文
- `toLocaleString()` 未传 locale —— 10 处（数字千分位跟随浏览器语言而非应用语言）

### P3 — 整页覆盖率缺口（反向：英文硬编码 → 中文模式显英文）
相比 8-5 已有修复落地（`t()` 计数当前值）：
| 页面 | 当前 `t()` 次数 | 评价 |
|---|---|---|
| TTWODashboard | **14**（8-5 为 0） | ⚠️ 仍约 37+ 处英文硬编码（KPI/图表标题/状态文案） |
| AlarmDashboard | **18**（8-5 为 4） | ⚠️ 仍有大量英文硬编码卡片/图表标题 |
| WarehouseDashboard / IpTrace / IncidentOverview | 0 | iframe 遗留 HTML（设计上脱离 React i18n，内嵌 HTML 本身固定中文/中英混排） |

---

## 2. 最小修复建议（优先消除「英文环境显中文」）

| # | 动作 | 工作量 |
|---|---|---|
| 1 | `CredentialSettings` 页：后端为 `CREDENTIAL_GROUPS` 加 `_en` 字段、`/api/credentials` 协商 `Accept-Language`；错误改为错误码由前端 `t()` 渲染 | 半天（根除 Settings 全部中文） |
| 2 | `DataSync.tsx:735` 改 `locale === 'zh' ? label_zh : label_en` | 5 分钟 |
| 3 | `AlarmDashboard.tsx:90/593` 改用已有 `t('alarm.drillHint')`，删死三元 | 5 分钟 |
| 4 | `DataSync.tsx:786` 兜底改 `t('common.unknownError')`；`index.html` lang/title 动态化；10 处 `toLocaleString(locale==='zh'?'zh-CN':'en-US')` | 1 小时 |
| 5 | `task_introspect.py` 的 `TASK_IO`/`CALL_CHAIN_IO` 双语化，按 lang 取值 | 半天 |

**#1–#3（约半天）即可消除用户实际遇到的「Settings/下拉/告警页中文泄漏」全部可见问题。**

---

## 4. 已修复（2026-08-10，本次实施 #1–#3）

### #1 Settings 页中文泄漏（后端驱动）— 已修
- `backend/services/credential_store.py`：9 个 `CREDENTIAL_GROUPS` 全部新增 `name_en` / `username_label_en` / `secret_label_en`；`list_credentials(lang)` 按 `lang` 返回 `*_en` 变体（缺失回退中文）。
- `backend/routers/credentials.py`：`GET/PUT/POST test/reveal` 均读取 `Accept-Language`（与前端 `setApiLocale` 一致），成功消息、测试消息、错误 `detail` 全部双语化。
- `frontend/src/pages/CredentialSettings.tsx`：**无需改动**（标签/消息/错误现在由后端按语言返回，前端原样渲染）。
- 验证：`TMP/verify_credentials_i18n.py` 断言 ZH/EN 名称与标签正确，ALL_ASSERTIONS_PASS。

### #2 DataSync 分类下拉混排中文 — 已修
- `frontend/src/pages/DataSync.tsx:735`：`CATEGORY_CONFIG[c].label_zh` → `locale === 'zh' ? label_zh : label_en`。

### #3 AlarmDashboard 中文泄漏 — 已修
- `frontend/src/pages/AlarmDashboard.tsx:90`：删死三元，改用 `t('alarm.drillHint')`（并给 `SummaryCard` 补 `const { t } = useI18n()`，原组件缺该声明会导致 ReferenceError）。
- `frontend/src/pages/AlarmDashboard.tsx:593`：硬编码「点击下钻」→ `t('alarm.drillHint')`。
- 验证：`tsc --noEmit` 对三个改动文件零报错。

### #4 前端兜底 / 格式 / 文档语言 — 已修
- **`common.unknownError`**：`i18n.tsx` 新增 zh「未知错误」/ en「Unknown error」。
- **`DataSync.tsx:786`**：`'未知错误'` → `t('common.unknownError')`。
  - 顺带修掉一个真陷阱：该处所在的 `failedTasks.map(t => ...)` **用 `t` 作循环变量遮蔽了 i18n 的 `t()`**，直接改会编译不过。循环变量已重命名为 `task`。
- **`DataSync.tsx:563`**：新发现的真泄漏——`（{getNextRunEta(task)}）` 把**全角括号**写死在 JSX 里，EN 模式渲染成 `（in ~2h 15m）`。已改为按 locale 选择全角/半角。
- **`index.html` + `I18nProvider`**：`lang` / `title` 改为在 `useEffect([locale])` 内同步（`document.documentElement.lang`、`document.title`），index.html 的静态值降级为首屏兜底；顺便修正静态 title 与 `app.title` 不一致（原为「数据洞察 SaaS MVP」）。
- **10 处 `toLocaleString()`**：新增 `export const numLocale = (l) => l === 'zh' ? 'zh-CN' : 'en-US'`，6 个页面全部改为 `toLocaleString(numLocale(locale))`。
  - 这不是纯装饰：裸调会跟随**机器区域设置**，例如 de-DE 环境下 `1234` 会渲染成 `1.234`。
  - 分布：AlarmDashboard 2、TTWODashboard 4、Dashboard / DataUpload / PacketLossDashboard / TableBrowser 各 1。

### #5 后端 `call_chain` 资源标注双语化 — 已修
- `backend/services/task_introspect.py`：新增 `translate_io()`，用「最长优先」术语替换 + 正则（处理「由 X 生成」句式）+ `_IO_EN_OVERRIDE` 意译整句。
  - 选术语替换而非整句词典的理由：94 条资源串里主体是路径/表名/主机等标识符，只有前缀与括号内说明是中文；后续新增条目复用既有术语即可自动英文化。
- `_annotate_call_chain(chain, task_id, lang='zh')` 新增 `lang`；去重仍按中文主键做，保证中英条目**一一对应**。
- `backend/services/task_runner.py`：`register_task` 注册期同时烘焙 `call_chain` 与 `call_chain_en`（同源 `_chain_raw`）；新增 `_localized_chain(task, lang)`，`list_tasks` / `get_task_detail` 按 `lang` 取用，EN 缺失回退中文、绝不返回 `None`。

### 本次验证证据（全部可复跑）
| 脚本 / 命令 | 结论 |
|---|---|
| `TMP/verify_call_chain_i18n.py` | **PASS** — 94 条资源串英文化后**零残留中文**；7 个真实任务的 annotate 中英条目数一致；空链/未知 task_id 健壮 |
| `TMP/verify_register_chain_en.py` | **PASS** — `register_task` 确实烘焙了 `call_chain_en`；`_localized_chain` 取用与回退均正确；zh 版仍含中文（证明未被误改） |
| `TMP/verify_credentials_i18n.py` | **PASS**（回归）— #1 的凭据双语化未被破坏 |
| `tsc --noEmit -p tsconfig.json` | **全项目零报错**（不是只查改动文件） |
| `py_compile`（4 个改动后端文件，运行时 3.12） | OK |
| `grep "toLocaleString()"` | src 下**零**裸调（仅剩 i18n.tsx 内的说明注释） |
| `TMP/i18n_scan.py` 复扫 | plain 命中 110 条已逐条核对：真泄漏仅 `DataSync.tsx:563`（已修），其余为 JSX 注释 / JSDoc / `label_zh`+`label_en` 成对数据定义（4 处消费点均已配 locale 分支） |

> 注意：托管 Python 3.13 没装 `apscheduler`，后端脚本必须用项目运行时
> `C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe` 跑。

### 仍未处理（本次范围外）
- **P3 整页覆盖率缺口**（反向问题：中文模式显英文）——BatteryDashboard / GISMap / IncidentOverview 等页仍有大量英文硬编码，属于「补字典」量级的工作，与本次「英文环境显中文」主线无关。


- 扫描：`TMP/i18n_scan.py` 对 `src` 全部 `.tsx/.ts`（排除 `i18n.tsx`）做 CJK 命中分类，纯文本（非注释/非 zh-三元）命中逐行核对。
- 后端：`grep` 确认 `routers/credentials.py` 无任何 `Accept-Language`/`locale` 处理；`credential_store.py` 无 `*_en` 字段；`task_introspect.py` `TASK_IO`/`CALL_CHAIN_IO` 全中文。
- 覆盖率：`grep -o "t('"` 统计各页 `t()` 调用数（见上表）。


# 7. MS SLA 服务 —【已迁移到手册，原文已过时】

> 看板用法 → `docs/manual/11-feature-guide.md` 第 5–6 节；数据流与凭据分组 → `docs/manual/14-integrations.md`；库文件位置 → `docs/manual/03-data-layer.md`。
>
> **原文三处过时（已逐条核对当前代码）**：
> 1. `ms_sla_sync`、`contract_kpis_report` 两个 task_id 在当前 `backend/task_registry.py` 中**已不存在**，现为 `ms_sla_full`、`kpi_ms_contract`、`kpi_ms_wo_sla`；
> 2. 库名 `lbr_ms_sla_kpi.sqlite3` 已被 `ms_sla_dashboard.sqlite3` 取代（旧文件仍在 `data/ms_sla/`，两者并存）；
> 3. NUR / SLA / WO 口径自 2026-08 起改为 `backend/services/nur_calc.py` 实时计算，不再以 SQLite 快照为准。
>
> 原文逐字备份见 `PROJECT_DOCS_ARCHIVE.md`（原第 1621-1682 行）。
# 8. IP Trace 与故障概览集成方案

# 集成计划：IP_Trace_Tool + incident_overview → my_app

> 目标：将 `D:\01_RPA\Task\Unified_Tools` 下的 `IP_Trace_Tool` 与 `incident_overview` 两个独立 Flask 工具
> 以 my_app 现有架构规范（FastAPI router/service + React/antd 页面）集成进 my_app，
> 做到风格统一、依赖不冗余、不影响现有功能。

---

## 一、现状分析

### 1.1 源模块分析（Unified_Tools）

#### IP_Trace_Tool（Flask 独立服务，端口 7090）

| 项目 | 说明 |
|---|---|
| 核心文件 | `ip_detect_tool.py`（1862 行）、`templates/index.html`（Tailwind 单页 UI） |
| 功能实现 | tracert 路由追踪 → 对每跳持续 ICMP + TCP 双协议 ping → 统计时延/抖动/丢包 → AI 智能分析 → Leaflet 链路地图 |
| 对外接口 | `POST /trace`、`POST /stop`、`GET /status`、`POST /analyze`、`POST /shutdown` |
| 数据存储 | 多会话内存态（session_id 隔离）+ JSON/CSV 落盘到 `data/` 目录 |
| 配置文件 | 代码内 AI API 配置（Gemini/OpenAI/通义/豆包默认 key、base_url、模型列表），优先级：用户输入 > 环境变量 > 默认配置 |
| 依赖项 | flask、requests、geoip2（可选，GeoLite2-City.mmdb 地理位置库） |

#### incident_overview（Flask 独立服务，端口 7038）

| 项目 | 说明 |
|---|---|
| 核心文件 | `app.py`（1726 行）、`index.html`（7059 行单页 UI） |
| 功能实现 | 读取 Excel 七个 sheet（Status / TT Quality / Owner1 / ZTE / 3rd / Details1 / Details）→ 状态卡片、严重度×状态矩阵、SLA 分布、明细表、工单日志分页表、利比里亚地图、AI 助手、虚拟助手（电话/短信/浏览器语音/桌面通知） |
| 对外接口 | `/api/all`、`/api/status`、`/api/tt-quality`、`/api/severity`、`/api/sla/<vendor>`、`/api/details`、`/api/incident_log`（mtime 缓存 + 分页）、`/api/debug`、`/api/ai/*`（openai/gemini/doubao/qianwen/glm/deepseek 六个端点）、`/api/assistant/call`、`/api/assistant/sms`、`/lr-all.geo.json` |
| 数据存储 | `data/incident_overview.xlsx`（按文件 mtime 缓存解析结果）；`lr-all.geo.json` 利比里亚地图边界 |
| 配置文件 | `.env`（python-dotenv 可选）；电话/短信服务商由环境变量 `PHONE_SERVICE_PROVIDER`、`SMS_SERVICE_PROVIDER` 控制（twilio/aliyun/tencent/none 模拟模式） |
| 依赖项 | flask、flask-cors、pandas、openpyxl、requests、python-dotenv、openai（仅 deepseek 端点） |

### 1.2 my_app 架构分析（集成目标规范）

| 维度 | 现状 |
|---|---|
| 整体架构 | FastAPI 后端（端口 8000，`backend/main.py`）+ React 前端（Vite dev 5173，生产由后端挂载 `frontend/dist`） |
| 目录组织 | `backend/routers/`（API 层）、`backend/services/`（业务逻辑层）、`backend/models`、`backend/schemas`、`frontend/src/pages`、`frontend/src/components` |
| 模块注册 | 路由：`backend/routers/*.py` 定义 `APIRouter(prefix="/api/<module>", tags=[...])`，在 `main.py` 中 `app.include_router()`；页面：`App.tsx` 中 `lazy()` 懒加载 + `menuItems` + `renderPage()` switch |
| 任务调度 | `backend/task_registry.py` 声明式 TASK_SPECS + `task_runner` 通用调度（本次集成为在线交互功能，无需注册定时任务） |
| UI 风格 | React 19 + antd 6 + echarts + leaflet/react-leaflet；深色主题（背景 `#0a1929`、主色 teal `#13c2c2`，`theme.ts` 的 `WH` 常量）；中英双语 `i18n.tsx` |
| 命名规范 | router 文件名 snake_case（如 `alarm_dashboard.py`），页面组件 PascalCase（如 `AlarmDashboard.tsx`），API 前缀 kebab-case（如 `/api/alarm-dashboard`） |
| 配置管理 | 环境变量 + `credentials` 表（凭据集中管理，`CredentialSettings` 页面）；CORS 由 `MY_APP_CORS_ORIGINS` 控制 |
| 公共能力 | `logging`（禁裸 print）、`get_raw_connection`（SQLite）、`backend/security.py`（受保护接口）、`api.ts` 统一 axios 实例（baseURL `/api`，timeout 120s） |
| 依赖管理 | 根 `requirements.txt` + `requirements.lock.txt`；前端 `package.json` |

---

## 二、集成方案（改写而非复制）

### 2.1 后端改动（my_app/backend）

| 类型 | 文件 | 说明 |
|---|---|---|
| 新增 | `services/ip_trace_service.py` | 追踪/双协议 ping/多会话管理/GeoIP/AI 分析核心逻辑。改造点：`print` → `logging`；数据落盘目录改为 `my_app/data/ip_trace/`；移除硬编码 OpenAI API key，改环境变量注入；显示加载耗时 |
| 新增 | `routers/ip_trace.py` | `APIRouter(prefix="/api/ip-trace")`：`POST /trace`、`POST /stop`、`GET /status`、`POST /analyze`。去掉 `/shutdown`（服务生命周期由 my_app 统一管理） |
| 新增 | `services/incident_overview_service.py` | Excel 读取、向量化解析（pandas `to_dict('records')`）、mtime 缓存。数据文件路径改为 `my_app/data/incident_overview/incident_overview.xlsx` |
| 新增 | `routers/incident_overview.py` | `APIRouter(prefix="/api/incident-overview")`：`GET /all`、`/status`、`/tt-quality`、`/severity`、`/sla/{vendor}`、`/details`、`/incident_log`（分页）、`/geojson`；`POST /ai/analyze`（6 个提供商端点合并为统一分发，provider 参数选择，deepseek 亦改 requests 走 OpenAI 兼容接口）；`POST /assistant/call`、`POST /assistant/sms`（保留 twilio/aliyun/tencent/none 模拟模式） |
| 修改 | `main.py` | 导入并 `include_router` 两个新路由（约 +4 行） |
| 新增数据 | `data/incident_overview/` | 复制 `incident_overview.xlsx`、`lr-all.geo.json` |
| 新增文档 | `services/ip_trace_service.md`、`services/incident_overview_service.md` | 遵循项目规则：新 py 文件同目录配 MD 文档 |
| 修改 | `backend/requirements.txt` | 补充 `requests`（实际已被使用但未声明）、`geoip2`（注释标注可选） |

### 2.2 前端改动（my_app/frontend）

| 类型 | 文件 | 说明 |
|---|---|---|
| 新增 | `src/pages/IpTrace.tsx` | React 重写：目标输入/启停按钮、跳数表格（ICMP/TCP 实时统计，轮询 `/api/ip-trace/status`）、echarts 时延趋势图、leaflet 链路地图（跳点坐标连线）、AI 分析面板（提供商选择，默认本地规则免 API） |
| 新增 | `src/pages/IncidentOverview.tsx` | React 重写：状态卡片（antd Statistic）、TT Quality、严重度×状态矩阵表、ZTE/3rd SLA 柱状图（echarts）、Details 表、Incident Log 服务端分页表、利比里亚地图（leaflet + `/api/incident-overview/geojson`）、AI 助手弹窗、虚拟助手（浏览器语音播报 + 桌面通知，纯前端实现） |
| 修改 | `src/App.tsx` | 懒加载两个新页面；`PageKey` 增加 `ip_trace`、`incident_overview`；`menuItems` 增加两项（图标：`AimOutlined`、`FileSearchOutlined`）；`renderPage()` 增加两个 case |
| 修改 | `src/i18n.tsx` | 新增 `nav.ipTrace`、`nav.incidentOverview` 及页面内中英词条 |

### 2.3 依赖合并策略

| 依赖 | 处理 |
|---|---|
| flask / flask-cors | **不引入**，全部改写为 FastAPI router |
| python-dotenv | **不引入**，沿用 my_app 环境变量方式 |
| openai SDK | **不引入**，deepseek 端点改为 requests 直调 ModelScope OpenAI 兼容接口 |
| requests | 环境已安装，补声明到 requirements |
| pandas / openpyxl / numpy | my_app 已有，直接复用 |
| geoip2 | 可选依赖（mmdb 文件缺失时地理位置降级为"未知"） |
| 前端 | antd / echarts / leaflet / react-leaflet / axios / dayjs 全部已有，**零新增 npm 依赖** |

---

## 三、关键风险与对策

| 风险 | 对策 |
|---|---|
| 源码硬编码 OpenAI API key 泄露 | 不迁移明文 key，改为环境变量 `OPENAI_API_KEY` 等注入 |
| 路径引用遗漏导致无法运行 | 遵守 my_app 自包含约束，所有文件与数据均在 `my_app/` 目录内 |
| 影响现有功能 | 仅新增 router/页面，不修改任何现有路由与组件 |
| API 路径冲突 | 现有 `/api/details` 已被 SP 看板占用，新模块统一使用 `/api/incident-overview/*` 前缀隔离 |
| GeoIP mmdb 文件不存在 | 与原逻辑一致：降级为"位置未知"，功能可用 |
| 大 Excel 解析性能 | 保留 mtime 缓存 + pandas 向量化，与原优化一致 |

---

## 四、集成后文件改动清单（预期）

### 新增
```
my_app/
├── backend/
│   ├── routers/ip_trace.py
│   ├── routers/incident_overview.py
│   ├── services/ip_trace_service.py
│   ├── services/ip_trace_service.md
│   ├── services/incident_overview_service.py
│   └── services/incident_overview_service.md
├── data/incident_overview/
│   ├── incident_overview.xlsx          （复制自源项目）
│   └── lr-all.geo.json                 （复制自源项目）
└── frontend/src/pages/
    ├── IpTrace.tsx
    └── IncidentOverview.tsx
```

### 修改
```
my_app/backend/main.py                    （注册 2 个新 router）
my_app/backend/requirements.txt           （补 requests、geoip2 可选）
my_app/requirements.txt                   （补 requests）
my_app/frontend/src/App.tsx               （菜单 + 路由注册）
my_app/frontend/src/i18n.tsx              （新增词条）
```

### 新增入口位置
- 前端左侧导航栏新增两个菜单项：**IP Trace**（IP 链路探测）、**Incident Overview**（事件总览），位于现有功能菜单中
- 后端 API 前缀：`/api/ip-trace/*`、`/api/incident-overview/*`

---

## 五、验证方式

### 5.1 后端验证
1. 启动后端（8000 端口），确认启动日志无异常、注册任务数不变之外无回归
2. `GET /api/health` 正常
3. `GET /api/incident-overview/all` 返回 status / tt_quality / severity / sla_zte / sla_3rd / details 六段数据
4. `GET /api/incident-overview/incident_log?page=1&limit=20` 分页正常，二次请求命中缓存（日志显示 from cache）
5. `POST /api/ip-trace/trace`（target=127.0.0.1 或公网域名）→ `GET /api/ip-trace/status` 持续返回 ping 数据 → `POST /api/ip-trace/stop` 停止
6. `POST /api/ip-trace/analyze`（provider=local）返回本地规则分析报告

### 5.2 现有功能回归
- `GET /api/tasks`、`GET /api/data`、`GET /api/sp-data/summary`、`GET /api/db/info` 抽查正常
- 现有页面（DataSync、AlarmDashboard 等）菜单与功能不受影响

### 5.3 前端验证
1. `npm run build`（tsc + vite）编译通过
2. 启动 dev server，打开 IP Trace 页面：输入目标 → 开始 → 表格实时刷新 / 地图渲染 / 停止
3. 打开 Incident Overview 页面：卡片、矩阵、SLA 图表、分页表、地图、AI 助手弹窗逐项验证
4. 切换中英文，词条无缺失


# 9. 局域网访问（LAN Access）—【已迁移到手册】

> 端口清单、放行步骤、CORS 与实测结论 → `docs/manual/13-operations.md`「局域网访问」。
>
> **精简原因（原文指示的步骤无法执行）**：`firewall_setup.bat` 在本项目内**不存在**（同机 `D:\01_RPA\Task\MTN_Comsal\my_app\` 下有同名文件，但端口与路径按那个项目写的，不可直接套用）；`setup_pg_lan_access.bat`、`install_ensure_task.bat` 在 `D:\01_RPA` 全树**均未找到**。即 PG 的 `pg_hba.conf` 改动与防火墙规则必须手工完成。
>
> 原文仍然有效的部分：与 MTN_Comsal 共用 7038/7090、两套不可同时运行。
> 原文逐字备份见 `PROJECT_DOCS_ARCHIVE.md`（原第 1842-1939 行）。
# 10. 迁移失败复盘（Postmortem）

# my_app 迁移失败复盘报告（Failure Post-Mortem）

> 文档性质：**预防性复盘**。迁移尚未执行（状态=规划定稿）。本报告基于 `D:\01_RPA\Task\my_app` 的**代码级全量枚举**（非抽样），记录"若迁移失败，会怎么失败、能否回退、根因是什么"，并把规划阶段已暴露的方法论失误一并归档。
> 配套基线：`my_app_migration_plan.md`（含 Phase R 回退方案 + 第 7/8 节）。
> 生成时间：2026-08-07；**2026-08-07 二次复核（本轮，全量枚举重跑，见 1.5 节）**

---

## 0. 一句话结论

- **功能是否会受影响**：按修订后计划（含本轮回查补的 3 个缺口 + 二次复核补的 4 个缺口）执行，**影响可控且可逆**；但**不亲手执行+回归就无法 100% 保证零影响**。
- **能否保证回退**：在 **R7（`DB_MODE` 熔断开关落地）+ 风险 10/11 引擎接线守卫 + R8 鉴权库硬排除 + 任务队列基础设施（task_runner/task_stats/worker）纳入 DB_MODE 分支** 四项闭环前，**回退不保证**；全部落地并演练后，**回退强保证**。
- **当前最大的"保证缺口"不是技术，是 `DB_MODE` 开关还没写**——它只是计划文字，不是代码（二次复核 grep 确认 backend 下 `DB_MODE` 零命中）。

---

## 1. 已验证事实（硬证据，非推测）

| # | 事实 | 证据 |
|---|---|---|
| F1 | 全项目**唯一** `create_engine` 在 `database.py:12`，模块加载即绑定 sqlite；`DATABASE_URL=f"sqlite:///{DB_PATH}"` 硬编码 | `database.py:9-17` |
| F2 | 主连接入口 `get_raw_connection(db_path)`（`database.py:88`）被 **9 个 router + 多数 service** 使用；`main.py:103` 启动期 `Base.metadata.create_all(bind=engine)` | grep `get_raw_connection` 计数 + `main.py:103` |
| F3 | 运行期存在 **4 处裸 `sqlite3.connect` 绕过 `get_raw_connection`**：`ipran_chart_service.py:233`、`fw_kpi/fw_kpi_services.py:488`、`credential_store.py:154`、`battery_kpi_service.py:268`(兜底) | `grep -rn "sqlite3.connect(" backend` |
| F4 | 独立 ORM 基类：`PlBase`(`models/packet_loss.py:10`)、`BatteryBase`(`models/battery.py:9`)，**无各自 `create_engine`**（全项目仅 F1 一处） | grep `create_engine` + 读两 model 文件 |
| F5 | `eflow_tt` 唯一活写源 = `app.db`（`sync_from_eflow_api.py:20,531,364` 明确"不再依赖 eflow.sqlite3"），eflow.sqlite3 那份是遗留快照 | 代码注释 + 行号 |
| F6 | `realtime_alarm`/`history_alarm` 页面只读 `app.db`（`alarm_dashboard.py:38` 等 `get_raw_connection()`→默认 app.db） | 路由代码 |
| F7 | 本地 `db_ps_cs_cn.sqlite3` **已不存在**（二次复核修正：非"0 字节占位"而是文件已缺失，`db/` 与 `data/cnn_ume/` 两处均 MISSING）；真数据在远端 `192.168.100.19:8765`（FINEBI 在用），代码仅以逻辑名 `"db_ps_cs_cn.sqlite3"` 经 HTTP 引用（`ccn_ume_kpi_service.py:92`、`remote_db_reader.py:101`） | `Test-Path` 双路径 MISSING + grep 仅逻辑名命中 |
| F8 | **28 个**定时任务（`task_registry.py`，二次复核修正：非 27），其中 site_outage/whatsapp/kpi_sp/kpi_ran/mailbox_cleanup/cnn 图表等**不碰本地 sqlite**；**⚠️ email_recovery 例外**（见 D2） | `task_registry.py` 全文正则计数 |

---

## 1.5 二次复核增量发现（2026-08-07，全量枚举重跑）

| # | 发现 | 证据 | 对计划的影响 |
|---|---|---|---|
| D1 | **F7 过时**：本地 `db_ps_cs_cn.sqlite3` 两处副本**文件已不存在**（非 0 字节）。结论不变（无本地真副本可迁、整体排除），但"0 字节占位"表述作废 | `Test-Path` 双路径 MISSING | 计划 0.6/第 1 节措辞修正 |
| D2 | **email_recovery 并非"不碰本地 sqlite"**：`email_recovery.py:231,310` 经 `get_raw_connection(DB_PATH)` 查询 `app.db.task_execution_log`（失败邮件扫描/成功记录比对）。F8/7.2 矩阵将其归入"不影响"**有误** | grep + 源码阅读 | 该任务实际**受 app.db 迁移影响**，纳入回归清单 |
| D3 | **任务队列基础设施未列入影响矩阵**：`worker.py`(3 处)、`task_runner.py`(7 处 get_raw_connection + `INSERT OR REPLACE INTO task_schedule_config` :199/204 + AUTOINCREMENT :90 + `PRAGMA table_info` :169)、`task_stats.py`(5 处 + AUTOINCREMENT :27 + PRAGMA :42)。这些是 FastAPI 优化 Phase 3 新增，全部走 app.db，sqlite 方言密集 | grep 全量枚举 | Phase 3 改写清单 + R7 的 `DB_MODE` 分支**必须覆盖队列三件套**，否则迁移后定时/手动任务调度即坏，且回退无开关 |
| D4 | **ipran 图表本地库已是 0 字节**：`data/ipran_ume/ipran_ume_kpi.sqlite3 = 0 bytes`。`ipran_ume_kpi_service` 写入为 **API 优先远程、本地 sqlite 仅兜底**（:706-722），故本地库长期为空；`ipran_chart_service.py:233` 裸连读的正是这个空库 → **图表取数空是既有现状，不是迁移引入**。迁移时需决策：ipran 图表改读远端 API/PG，否则迁一个空库只是把"空"搬到 PG | 文件大小 0 + `ipran_ume_kpi_service.py:706-722` | 风险 S4 改写："迁移后静默坏图" → "迁移前已空，迁移是修复机会而非新风险；但必须定读源，不能原样搬空库" |
| D5 | **sqlite 方言耦合面大于计划清单**：全量计数 sqlite_master **20 处**（计划仅点名 ~3 处，漏：`tt_wo_dashboard.py:21`、`get_sp_table.py:294`、`fw_kpi_services.py:523`、`sync_from_eflow_api.py:680/694`、`analysis.py:38`、`ms_sla_report.py:338/391`、`packet_loss_dashboard.py:50`、`ran_ume_network_kpi.py:813`、`eflow_alarm_service.py:535`、`ran_ume_main_kpi.py:898`、`battery_dashboard.py:73`、`gis.py:31`、`system.py:85`、`eflow_data_mapper.py:1144`、`battery_kpi_service.py:402`、`alarm_dashboard.py:32`、`scripts/init_db.py:222`）；PRAGMA **53 处**；INSERT OR REPLACE/IGNORE **19 处**；rowid **7 处**；to_sql **13 处** | backend 全量正则计数 | Phase 3 改写面被低估，**墙钟 60–100 min 乐观**，建议上调或以"全量清单驱动"而非"点名驱动"执行 |
| D6 | `get_raw_connection` 调用点实测 **76 处**（9 router + 17 service + worker + scripts + main.py），注册表必须全覆盖 | 全量 grep 行号清单 | Phase 1 验收标准 = 76 处全部经注册表 |
| D7 | ms_sla 库实际文件名 `data/ms_sla/lbr_ms_sla_kpi.sqlite3`（`ms_sla_service.py:78`），计划范围表写"ms_sla"未错但需防搬运脚本按错名找文件 | 源码确认 | P5 搬运脚本库名清单以本节为准 |

> 仍成立的硬事实：F1（唯一 `create_engine` at `database.py:12`）、F3（恰 4 处裸 connect）、F4（PlBase/BatteryBase 无引擎）、F5（eflow_tt 唯一活写源 app.db，`sync_from_eflow_api.py:364,496`）、F6（告警页面只读 app.db）、R7 未实现（`DB_MODE` backend 下零命中）、`main.py:103 create_all`（且 :108 另有一处 AUTOINCREMENT DDL 同样需 `DB_MODE` 守卫）。

---

## 2. 功能影响面全量（回答"迁移后功能会不会有影响"）

- **受影响的功能** = 所有"本地 sqlite 取数/写数"的端点与任务。渲染层（openpyxl / matplotlib / PIL）操作内存 DataFrame，对底层 DB 无感，**产出形态不受影响**。
- **不受影响的功能**：site_outage 截图、whatsapp 发送、远端 FTP 报表（kpi_sp/kpi_ran）、cnn 图表（读 RemoteDBReader 远端）、mailbox_cleanup —— 它们不碰本地 sqlite，迁移对其透明。
- **⚠️ email_recovery 受影响**（D2 修正）：读 `app.db.task_execution_log`，迁移后须回归验证补发扫描仍工作。
- **⚠️ 任务队列三件套受影响**（D3 新增）：worker/task_runner/task_stats 全走 app.db 且 sqlite 方言密集，是生产调度心脏，迁移优先级最高、回归必测。
- **可控盲区**：ipran 图表(:233)、fw 图表(:488) 此前裸连 sqlite，已在 Phase 1 双层拦截 + Phase 3 改写覆盖；其中 ipran 本地库已是 0 字节（D4），迁移是修复机会。
- **本轮回查新增缺口**（计划已补）：PlBase/BatteryBase 独立引擎（风险 10）、`main.py:103 create_all` 双管理（风险 11）、credential_store 硬排除（风险 9）。

详细端点/任务矩阵见 `my_app_migration_plan.md` 第 7 节。

---

## 3. 失败情景树（每种失败：触发 → 检测信号 → 回退动作 → 回退是否保证）

| 情景 | 触发条件 | 检测信号 | 回退动作 | 回退保证 |
|---|---|---|---|---|
| S1 引擎切换即崩 | `database.py` 改 PG 后 `psycopg2` 缺失 / DSN 错 | 启动即 `ImportError` / 连接拒 | `DB_MODE` 切回 sqlite（R7） | ⚠️ 取决于 R7 是否落地 |
| S2 动态 DDL 改写错 | `_upsert_df` 的 `ON CONFLICT`/唯一键推断错 → 写入丢列/报错 | 同步任务持续异常、`eflow_tt` 行数偏差 | 停双写 + `DB_MODE` 回 sqlite；PG 用 `pg_restore` 基线 | ✅（sqlite 未删、双写领先） |
| S3 方言漏改 | 某处 `sqlite_master`/`datetime('now')` 未改 → 报表读空 | 报告 Excel 行数=0 / PNG 尺寸异常 | R1 影子对账拦截切流 + 回 sqlite | ✅（切流前已拦） |
| S4 ipran/fw 图表裸连漏处理 | Phase 1 双层拦截漏掉 :233 / :488 | 图表 PNG 空/报错（邮件发出但图坏） | 代码补拦截 + 回 sqlite | ✅（已纳入 P7 回归强制校验） |
| S5 **PlBase/BatteryBase 未接线**（风险 10） | Phase 2 只改 `database.py`，packet_loss/battery 仍连 sqlite | 部分表在 sqlite、部分在 PG，状态分裂 | 分别接线 + `DB_MODE` 分支回退 | ⚠️ 须风险 10 闭环 |
| S6 **create_all 与 Alembic 冲突**（风险 11） | PG 模式下 `main.py:103 create_all` 仍跑 | 启动报错 / 表被抢建 | `DB_MODE` 守卫后回 sqlite | ⚠️ 须风险 11 闭环 |
| S7 **credential_store 误迁移**（风险 9） | 注册表工厂未硬排除 → 鉴权库也走 PG | **全员登录失败 / 锁死** | 鉴权库本就未动 → 不受影响 | ✅（R8 硬排除后） |
| S8 PG 连接池耗尽 | 高并发写 + 池参数不当 | API 5xx / 任务超时堆积 | `DB_MODE` 回 sqlite + 调池参数 | ✅（sqlite 未删） |
| S9 数据偏差超阈值 | 搬运类型推断错（全 NULL 列→REAL 等） | R5 对账差异 >0.1% | 不切流 + 重跑 P5（`DELETE` 重导） | ✅（幂等） |
| S10 FW 锁旋转残留 | :496-505 逻辑未删 → 仍生成孤儿 sqlite 文件 | 磁盘出现 `fw_*.sqlite3_序号` | 删残留文件 + 代码删锁逻辑 | ✅（文件级，可清理） |
| S11 **任务队列三件套漏改**（D3） | worker/task_runner/task_stats 的 AUTOINCREMENT/INSERT OR REPLACE/PRAGMA 未改 PG 方言 | 定时任务不触发、手动触发 500、执行日志不落库 | `DB_MODE` 切回 sqlite（队列三件套须纳入分支） | ⚠️ 取决于 R7 覆盖队列层 |
| S12 ipran 图表读源未定（D4） | 原样把 0 字节本地库搬 PG，图表继续读空 | ipran 图表邮件持续空图（既有问题延续） | 非回退问题：决策改读远端 API/PG 数据源 | ✅（现状无恶化风险） |

**结论**：所有情景的回退都依赖"sqlite 原文件不删 + `DB_MODE` 秒级切回"这一底座；**S1/S5/S6/S11 的回退保证取决于 R7（含队列层）/R10/R11 是否落地**，这是当前唯一的真缺口。

---

## 4. 回退保障审计（能否"保证正常回退"）

### 4.1 已强保证
- sqlite 文件从不删除直到稳定期结束（双写期 sqlite 领先，回退数据不丢）。
- `pg_dump` 每段基线 + 增量 dump（PG 损坏可恢复）。
- 影子/双写闸门（R1）+ 切流 gating（R2）：未全绿不切，天然不破坏 sqlite。
- 分阶段幂等（R4）：P5 脚本可 `DELETE` 重导。
- credential_store 硬排除（R8）：鉴权库本就不动。

### 4.2 当前不能保证（切流前必须闭环）
1. **R7 `DB_MODE` 熔断开关未实现**（二次复核确认 backend 下零命中）——只是计划文字。若切流后发现问题但开关没落地，回退需手动改代码+配置，存在窗口风险。**切流前必须实现并演练"切回 sqlite = 全量回到原态"**。
2. **风险 10 独立引擎接线**——PlBase/BatteryBase 须带 `DB_MODE` 分支，否则出现 sqlite/PG 分裂态。
3. **风险 11 create_all 守卫**——PG 模式下必须跳过启动期 `create_all`，否则启动失败。
4. **任务队列三件套的 `DB_MODE` 覆盖**（D3 新增）——worker/task_runner/task_stats 是调度心脏，其 sqlite 方言改写必须与 `DB_MODE` 分支同步落地，否则回退时调度层回不去。

### 4.3 唯一真正确认零影响的方式
P7 影子比对（R5）+ 报告生成回归（逐一实跑 eFlow/ran_ume/packet_loss/battery/ipran/fw 报告并比对 Excel 行数/PNG 尺寸）+ 回退演练（R6）。**这三件事之前，任何"无影响"的断言都是未证实的。**

---

## 5. 规划阶段已暴露的方法论失误（必须归档，防止重犯）

| 失误 | 发生轮次 | 后果 | 修正 |
|---|---|---|---|
| **抽样即 generalization** | 早期评估只查 3 条报告链路就下"全部经 `get_raw_connection`、完全可控"结论 | 漏掉 ipran/fw 图表裸连盲区，用户判断"方案风险很大"正确 | 全量 `grep` 枚举（F3），推翻原结论 |
| **单一拦截点假设** | 初版把"拦截 `get_raw_connection`"当唯一兜底 | 裸连绕过点会被静默漏改 | Phase 1 升级为**双层拦截** |
| **漏算独立 ORM 引擎** | 本轮回查前未注意 PlBase/BatteryBase | 仅靠改 `database.py` 绑不到 packet_loss/battery 的 PG 连接 | Phase 2 补显式接线（风险 10） |
| **漏算启动期 create_all** | 本轮回查前未注意 `main.py:103` | PG 模式下与 Alembic 抢建/启动失败 | Phase 2 补 `DB_MODE` 守卫（风险 11） |
| **回退方案缺失** | 初版计划无 Phase R | 用户指出"为什么没回退方案" | 补 Phase R（R0–R8） |
| **影响矩阵漏新增基础设施** | 二次复核发现任务队列三件套（worker/task_runner/task_stats）与 email_recovery 未列入/误分类 | 调度心脏与邮件补发在迁移后可能静默坏 | 影响矩阵补 D2/D3，回归清单补对应项 |
| **事实不复核即引用** | "0 字节占位""27 任务"在文件/代码已变化后仍被沿用 | 结论虽未错但证据失效，损害计划可信度 | 二次复核全量重跑（1.5 节），以 D1/D5 实测数为准 |

> 根因：规划阶段沿用了"前向线性拆活"思维，注意力全在"怎么迁过去"，把"失败怎么办/怎么回退"和"sqlite 方言耦合全貌"两条独立工作流漏掉。对一套**两个库在生产、旁边挂着 FINEBI** 的系统，这是不可接受的。本复盘即对此的纠正。

---

## 6. 切流前置条件清单（全部打勾后才允许切 PG）

- [ ] R7 `DB_MODE` 熔断开关已实现，且演练"切回 sqlite = 全量回到原态"通过
- [ ] **R7 覆盖任务队列三件套**（worker/task_runner/task_stats，D3）
- [ ] 风险 10：PlBase / BatteryBase 显式绑定 PG 引擎（带 `DB_MODE` 分支）
- [ ] 风险 11：`main.py:103 create_all` 已由 `DB_MODE` 守卫
- [ ] R8：credential_store 注册表工厂硬排除（强制返回原 sqlite）
- [ ] Phase 1 双层拦截覆盖 4 处裸连（ipran:233 / fw:488 / credential / battery 兜底）
- [ ] Phase 1 注册表覆盖全部 76 处 `get_raw_connection` 调用点（D6）
- [ ] Phase 3 按全量方言清单执行：sqlite_master 20 处 / PRAGMA 53 处 / INSERT OR REPLACE 19 处 / rowid 7 处 / to_sql 13 处（D5）
- [ ] ipran 图表读源决策：改读远端 API/PG，不搬 0 字节空库（D4）
- [ ] R1 影子双写跑通，R5 对账差异 <0.1%
- [ ] P7 报告回归全绿（含 ipran/fw PNG 非空校验 + email_recovery 补发扫描 + 任务队列触发→落库链路）
- [ ] R6 回退演练一次（用备份库跑通切回）
- [ ] 你（人）在 R2 gating 全绿后拍板切流

---

*本复盘随 `my_app_migration_plan.md` 同步更新。任何一条前置条件未闭合，切流即视为违规。*


# 11. 优化建议：用户体验与加载效率

# my_app 优化建议：用户体验 & 网页加载效率

> 分析对象：`D:\01_RPA\Task\my_app`（前端 React 19 + Vite 8 + Ant Design 6；后端 FastAPI + APScheduler）
> 分析日期：2026-07-26
> 结论先行：**三个问题里，"执行中"状态丢失是 P0（功能缺陷），国际化遗漏是 P1（一致性/质量），加载效率是 P1（首屏与重复请求）**。

---

## 一、P0 ｜ 任务"执行中"状态丢失（最严重）

### 现象（与你描述一致）
- 任务管理页点"立即执行"，任务**实际没真正跑完/跑失败**，但按钮上的"执行中…"一闪就没了。
- 切到别的页面再切回来，"执行中"也完全不显示。

### 根因（三层）

**1. 前端"运行中"只是本地乐观状态，后台真实状态没有回传**
`frontend/src/pages/DataSync.tsx` 的 `handleRun`：

```tsx
const [runningTasks, setRunningTasks] = useState<Set<string>>(new Set())  // 组件本地
const handleRun = async (taskId: string) => {
  setRunningTasks(prev => new Set(prev).add(taskId))   // 乐观置为 running
  try {
    const res = await api.post(`/tasks/${taskId}/run`) // 仅 HTTP 在途期间算"运行中"
    ...
    loadTasks()
  } catch { message.error(...) }
  finally {
    setRunningTasks(prev => { const s = new Set(prev); s.delete(taskId); return s }) // 请求一结束立刻清除
  }
}
```

`runningTasks` 只在"HTTP 请求在途"期间为 true，请求返回（成功/失败/超时）就立刻清除。**它并不反映任务是否真的还在跑**。

**2. 后端 `run_task` 是同步阻塞执行，且没有"运行中"字段**
- `backend/services/task_runner.py:153` 的 `run_task()` 直接 `func_result = task["func"]()` 同步执行，跑完才返回结果。
- `backend/main.py:289` 的 `POST /api/tasks/{id}/run` 调用的是同步 `run_task`，**HTTP 请求会一直阻塞到任务跑完**。
- `list_tasks()` / `get_task_detail()` **都不返回任何 `running`/`status` 字段**（`task_runner.py:326`、`get_task_detail` 只返回 `recent_runs`）。
- 前端 axios 超时是 120s（`api.ts:5`）。若某个同步任务跑超过 2 分钟，前端先超时 → `catch` 报"失败" → `finally` 抹掉 running；但后端那条线程可能还在跑。这正好解释了"实际没完成 + 不显示 running"。

**3. 切换页面会卸载组件，本地状态被清零**
`frontend/src/App.tsx:50` 用 `switch (currentPage)` 渲染页面——**切换页面 = 旧页面组件 unmount + 新页面 mount**。`DataSync` 的 `runningTasks` 是组件内 `useState`，卸载即销毁。所以"切走再切回不显示 running"是必然的。

### 推荐修复（彻底方案）

**后端**：改为后台线程执行 + 暴露真实状态
```python
# task_runner.py
import threading
_active = {}  # task_id -> {started_at}

def run_task_async(task_id, trigger="manual"):
    if _active.get(task_id):
        return {"accepted": False, "error": "already running"}
    def worker():
        _active[task_id] = {"started_at": datetime.now().isoformat()}
        try:
            run_task(task_id, trigger)        # 复用现有同步逻辑
        finally:
            _active.pop(task_id, None)
    threading.Thread(target=worker, daemon=True).start()
    return {"accepted": True, "running": True}

def is_running(task_id): return task_id in _active
```
`backend/main.py`：`POST /run` 改为调用 `run_task_async`（立即返回 `accepted`）；新增 `GET /api/tasks/{id}/status` 返回 `{running, started_at}`；`list_tasks` / `get_task_detail` 增加 `running` 字段。

**前端**：用 Context 托管运行状态 + 轮询，状态在页面切换间存活
- 新建 `TaskStatusContext`（挂在 `App` 顶层，高于页面切换），保存 `runningMap` 并每 3–5s 轮询 `GET /api/tasks` 或 `/status` 刷新。
- `DataSync` 的"Run Now"按钮改为：`onClick` 调 `run`，按钮 `loading` 读 `runningMap.get(taskId)`（来自 Context），不再用本地 `useState`。这样"运行中"由后端真实状态驱动，**切页面也不会丢**。

> 好处：同时修了"一闪就没""切走不显示""长任务超时误报失败"三个表现。

---

## 二、P1 ｜ 国际化（i18n）遗漏

### 现状：两套机制并存，不一致
- 大部分页面用集中式字典 `t('key')`（`i18n.tsx` 已定义 `zh/en` 两套）。
- `DataSync.tsx` 却大量用**内联三元** `locale === 'zh' ? '中文' : 'English'`，没有复用字典里已存在的 `sync.*` 键（如 `sync.runSuccess`、`sync.taskManager` 只在 toast 里用，可见 UI 文本仍硬编码三元）。维护成本高、易遗漏。

### 具体"未国际化"的硬编码中文（切英文仍显示中文）

| 文件 | 行 | 问题 |
|---|---|---|
| `pages/DataSync.tsx` | 237 | `placeholder="分 时 日 月 周"` —— **写死中文，未分支 locale** |
| `pages/AlarmDashboard.tsx` | 83 | `点击下钻明细 →` —— 卡片脚注可见中文，未国际化 |
| `pages/AlarmDashboard.tsx` | 442 | `sub={`已派单 ${...} 条 (with TT)`}` —— 可见中文 |
| `pages/AlarmDashboard.tsx` | 472 | `sub="Assigned - AlarmRaised > 5min 且超时限+10%"` —— 中英混杂，中文未国际化 |
| `pages/AlarmDashboard.tsx` | 614 | 弹窗标题 `共 {n} 条 · 展示最新 {m} 条` —— 可见中文 |

（其余页面 `TTWODashboard`、`GISMap`、`Dashboard`、`Overview` 等已基本用 `t()`，是干净的。）

### 推荐修复
1. 在 `i18n.tsx` 补齐键：`alarm.drillHint`、`alarm.dispatchedWithTT`、`alarm.overdueDesc`、`alarm.recordCount`、`sync.cronPlaceholder`。
2. 把上面 5 处硬编码替换为 `t('...')`。
3. （可选收尾）把 `DataSync.tsx` 的内联三元逐步改为复用 `sync.*` 字典键，统一为单一数据源。

---

## 三、P1 ｜ 网页加载效率

### 证据
- **整站只有一个 2.9 MB 的 JS 包**（`dist/assets/index-fU1bmyrE.js`），无代码分割。
- `App.tsx:19-27` **静态 `import` 全部 9 个页面**，其中包含重型库 ECharts 6 + react-leaflet + @turf/* + antd 6 —— 首屏一次性下载/解析全部，即使你只看"任务管理"。
- `vite.config.ts` **没有任何 `build` 配置**（无 `manualChunks`、无分包、无压缩），构建即单包。

### 具体问题与修复

**① 路由级代码分割（首屏最大优化）**
`App.tsx` 改为懒加载：
```tsx
import { lazy, Suspense } from 'react'
const DataSync = lazy(() => import('./pages/DataSync'))
// ... 其余页面同理
// renderPage 外包 <Suspense fallback={<Spin/>}>...</Suspense>
```
ECharts/Leaflet 只会在真正进入对应页面时才加载，首屏体积可下降 60%+。

**② 合并 N+1 接口（DataSync 当前最浪费的 API 调用）**
`DataSync.tsx:359` 的 `loadTasks`：`GET /api/tasks` 拿到列表后，再对**每个任务** `GET /api/tasks/{id}`（`Promise.all` 并发）。9 个任务 = 10 个请求，且每次 run/toggle 都全量重拉。
- 后端新增 `GET /api/tasks?with_details=1`，一次返回列表 + 最近执行记录。
- 或新增 `GET /api/tasks/status` 批量返回 `running` 状态，供轮询复用。

**③ 切页面重复拉取（与"running 丢失"同源）**
`AlarmDashboard.tsx:115`、`TTWODashboard.tsx:117` 都是 `useEffect(()=>{ fetch() },[])` 挂载即拉、无缓存。切走再切回又拉一次。
- 将任务列表/看板数据提升到**共享 Context 或轻量查询缓存**（如 `@tanstack/react-query`），页面切换不重新请求；配合①的懒加载，体验与性能双赢。

**④ 构建分包 + 静态压缩**
- `vite.config.ts` 加 `build.rollupOptions.output.manualChunks`，把 `echarts`、`leaflet`、`antd`、`react` 拆成独立 vendor chunk，利用浏览器长效缓存。
- 生产静态服务（`start.bat` 起的服务）开启 gzip/brotli，2.9 MB 可压到 ~700 KB–1 MB。

---

## 四、其他小问题（整洁度 / 健壮性）

- `handleRun` 的 `catch` 里没有日志，且失败仍调用 `loadTasks()`（非必要请求）。
- `DataSync.tsx` 的 `loadTasks` 在 `finally` 每次都 `setLoading(false)`，但多个并发触发时可能互相覆盖。
- 路由切换卸载组件，除状态丢失外，也意味着 ECharts/Leaflet 实例反复创建销毁，有轻微内存与卡顿风险（①用 lazy、③用缓存后缓解）。
- 建议对 `api.ts` 的 axios 增加统一错误拦截与超时分级（普通查询 10s，长任务走"已接受+轮询"模式，不再用 120s 大超时赌任务跑完）。

---

## 五、优先级与落地建议

| 优先级 | 项目 | 工作量 | 价值 |
|---|---|---|---|
| **P0** | 任务"执行中"状态（后端异步 + 状态接口 + Context 轮询） | 中 | 修复功能缺陷，最直接对应你的痛点 |
| **P1** | 国际化遗漏的 5 处硬编码中文 | 小 | 切英文不再露中文 |
| **P1** | 路由级代码分割（React.lazy） | 小 | 首屏体积骤降 |
| **P1** | 合并任务详情接口 / 消除 N+1 | 小 | 减少请求数，列表刷新更快 |
| **P2** | vendor 分包 + 静态压缩 | 小 | 二次访问更快 |
| **P2** | 共享数据缓存，避免切页重拉 | 中 | 彻底解决状态丢失 & 重复请求 |

> 说明：P0 的"running"修复与 P2 的"共享缓存"本质上共用同一套 Context 设计——**建议一起做**，一次解决"状态丢失 + 重复拉取"两个根因。

---

## ✅ 实施进度（2026-07-26）

已按"P0 + P1 国际化"范围完成落地：

**P0 执行中状态（彻底修复）**
- 后端 `task_runner.py`：新增 `_active_runs` 运行状态表 + 后台线程执行 `run_task_async`（立即返回 `accepted`）；`list_tasks`/`get_task_detail` 增加 `running` 字段；定时任务也经 `_scheduled_run` 包装以跟踪 running。
- 后端 `main.py`：`POST /run` 改异步；新增 `GET /tasks/{id}/status`。
- 前端新增 `TaskStatusContext.tsx`：应用顶层轮询 `/api/tasks`（运行时 2s / 空闲 8s），provider 位于路由 switch 之上 → **切页面不再丢失 running**。
- `DataSync.tsx`：按钮 loading 改读 `runningMap` + 本地乐观过渡；完成检测 effect 在任务结束（running true→false）时自动刷新卡片并按最新执行记录弹成功/失败提示。

**P1 国际化遗漏（5 处全部修复）**
- `i18n.tsx` 新增 `sync.runStarted`/`sync.cronPlaceholder`/`alarm.drillHint`/`alarm.dispatchedWithTT`/`alarm.overdueDesc`/`alarm.recordCount`（zh+en）。
- `DataSync.tsx:237` placeholder、`AlarmDashboard.tsx` 的 83/442/472/614 四处硬编码中文均已改为 `t()`（`HistoryMetricCard`、`ScheduleEditor` 子组件补 `useI18n()`）。

**验证**：`py_compile` 通过；系统 py312 import OK；`tsc --noEmit` 0 错误；`vite build` 成功。

## ✅ 实施进度（2026-07-26 续）

已按"P1 加载效率"范围完成落地（即用户说的"直到完全修改完成"）：

**① 路由级代码分割（首屏最大优化）**
- `App.tsx`：9 个页面由静态 import 改为 `React.lazy` + `<Suspense>`（loading 用 `Spin` 兜底）。构建后每个页面独立成 chunk（如 `AlarmDashboard` 19.75kB / `GISMap` 27.57kB / `DataSync` 13.7kB），首屏不再一次性下载全部页面与图表库。

**② 构建分包 + 长效缓存**
- `vite.config.ts`：新增 `build.rollupOptions.output.manualChunks`，把 `echarts`(1.13MB)、`antd`(1.18MB)、`leaflet`(153kB)、`antd-icons`、`react-vendor`、`date-lib`、其余 `vendor` 拆成独立 chunk。浏览器可并行下载并对 vendor 长缓存，二次访问只需拉变更的业务 chunk。

**③ 合并 N+1 接口（消除 DataSync 最浪费的请求）**
- `task_runner.py`：新增 `_fetch_latest_runs()`，用单条"子查询分组取 MAX(id)"SQL 一次性查出每个任务最新 1 条执行记录；`list_tasks(include_runs=True)` 将 `recent_runs` 随列表返回。
- `main.py`：`GET /api/tasks` 改为 `list_tasks(include_runs=True)`。
- `DataSync.tsx`：`loadTasks` 不再逐个 `/tasks/{id}` 发请求（原 N+1 → 1 次）；历史弹窗改为打开时按需拉 `/tasks/{id}` 完整 10 条记录。

**④ 切页数据缓存（与"running 丢失"同源问题一并解决）**
- 新增 `frontend/src/cache.ts`：`cachedGet(key, fetcher, ttl=30s)` + `invalidateCache(prefix)`。
- `DataSync`/`AlarmDashboard`/`TTWODashboard`/`GISMap` 的初次加载接入 `cachedGet`。切走再切回在 30s 内复用缓存数据，**无 spinner 闪烁、无重复请求**；手动刷新/执行完成/启停/改调度均 `invalidateCache('sync:')` + 强制重载。

**验证（全部通过）**
- 后端 `py_compile` OK；系统 py312 `import` OK，`list_tasks` 已支持 `include_runs` 参数。
- 前端 `tsc --noEmit` 0 错误。
- `vite build` 成功，产物为**多 chunk**（页面各自独立 + vendor 分包），彻底告别单 2.9MB 包。

**至此 P0（执行中状态）+ P1（国际化）+ P1（加载效率）三项全部完成。** 改动文件：
`backend/services/task_runner.py`、`backend/main.py`、`frontend/src/App.tsx`、`frontend/src/vite.config.ts`、`frontend/src/cache.ts`(新)、`frontend/src/pages/DataSync.tsx`、`frontend/src/pages/AlarmDashboard.tsx`、`frontend/src/pages/TTWODashboard.tsx`、`frontend/src/pages/GISMap.tsx`。

---

原报告中已落地的 P0/P1 国际化，连同本次 P1 加载效率，即为本次分析提出的**全部可落地优化项**。如需进一步压榨（如 ECharts 按需引入、路由预加载、图片/字体优化），可另开一轮。
