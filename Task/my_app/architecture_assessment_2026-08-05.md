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
