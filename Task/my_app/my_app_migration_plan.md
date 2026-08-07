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
