# FineBI 看板迁移说明（my-finebi → my_app 原生页）

## 1. 结论

原 `http://192.168.100.19:7190/my-finebi/` 门户里**除两个示例页外**的全部看板，
已迁移为 my_app 的原生页面，**不依赖 my-finebi 进程**。

| 项 | 数量 |
| --- | --- |
| 迁移看板 | 17 |
| 迁移组件（图表） | 187 |
| 组件类型 | 5（line / bar / kpi / table / text） |
| 数据源库 | 8 个远端只读库 + 1 个本机库 |

未迁移（按需求排除）：`Sample · Embedded (link pending)`、`Sample · Open in new tab (fallback)`
——这两个是空链接的占位示例页，无数据内容。

## 2. 页面入口

URL 形如 `http://localhost/myapp/?page=finebi_<slug>`，侧栏新增分组「**FineBI 看板**」。

> ⚠ **侧栏结构是服务端持久化的**（`GET/PUT /api/ui/menu-layout`，见
> `frontend/src/App.tsx` 的 `normalizeMenuLayout`）。旧逻辑只会把代码里新增的
> **页面**并入最后一个目录，**新增的目录**不会出现 —— 于是这 16 个看板曾被全部
> 堆进「系统」（4 → 22 项），侧栏里根本看不到 FineBI。
>
> 已修正为：① 补回保存配置里缺失的内置目录（按默认位置插入）；
> ② 把被旧逻辑塞错位置的页面「收」回它默认所属的目录。
> 老配置**自愈**，用户无需手动重置菜单。

| slug | 页面 | 分类 | 组件 | 数据源 |
| --- | --- | --- | --- | --- |
| `metro_ring` | IP RAN Metro Ring KPI | IP RAN | 10 | ipran_ume_kpi.sqlite3 |
| `ipran_hq` | IP RAN HQ-ODC/Banjor-ELWA/OLT | IP RAN | 8 | ipran_ume_kpi.sqlite3 |
| `ipran_4region` | IP RAN 4 Region KPI | IP RAN | 10 | ipran_ume_kpi.sqlite3 |
| `fw_daily` | FW Daily KPI | FW | 4 | fw_db.sqlite + ipran_ume_kpi.sqlite3 |
| `cn_kpi` | CN KPI（CCN_Daily_KPI） | 示例 | 19 | db_ps_cs_cn.sqlite3 |
| `cn_kpi_monthly` | CN KPI 月度 | 核心网 | 16 | db_ps_cs_cn.sqlite3 |
| `daily_availability` | Daily Availability KPI | 可用率 | 11 | avail_recon.sqlite3 + db.sqlite3 |
| `availability_daily` | Availability Daily Dashboard | 可用率 | 14 | db.sqlite3 |
| `availability_tt` | Availability Dashboard (TT) | 可用率 | 8 | db.sqlite3 + avail_recon.sqlite3 |
| `kpi_4g` | 4G KPI | 无线KPI | 12 | db.sqlite3 |
| `kpi_3g` | 3G KPI | 无线KPI | 11 | db.sqlite3 |
| `kpi_2g` | 2G_Daily_KPI | 无线KPI | 11 | db.sqlite3 |
| `mttr` | MTTR 看板（日/周/月） | 运维工单 | 15 | mttr_tt.sqlite3 |
| `cm_dashboard` | Corrective Maintenance | 运维工单 | 13 | db.sqlite3 |
| `spare` | Spare Management | 备件 | 13 | **本机 app.db**（见 §4） |
| `progress` | Progress | 运维工单 | 7 | progress.sqlite3 |
| `progress_v3` | Progress V3 | 运维工单 | 9 | progress.sqlite3 |

> `page=cn_kpi`（上一轮会话的 `CnKpi.tsx` 独立实现）与 `page=finebi_cn_kpi`
> （本轮通用引擎）内容相同，按需求**两者并存**。

## 3. 架构

```
frontend/src/pages/NativeBoard.tsx     一套组件渲染全部 17 个看板
        │  GET /api/native-boards/{slug}?start=&end=&force=
        ▼
backend/routers/native_boards.py       3 个端点（数据 / 导出 / 健康）
        │
backend/services/dashboard_service.py  取数引擎：并发 + 缓存 + 时间窗口 + Excel
        │
backend/services/native_catalog.py     看板定义（187 组件，自动生成）
        │
        ├─ 远端只读 SQL API（.19:8765）── 8 个库
        └─ 本机 db/app.db ──────────── spare 看板
```

### 看板定义是自动生成的

`native_catalog.py` 由 `_gen_native_catalog.py` 从 my-finebi 的
`db/app.db → dashboards.native_config` 提取，数据源映射取自同库
`settings.data_sources`（连接名 → 逻辑库文件名）。

**新增/修改看板**：改 my-finebi 侧配置后重跑

```powershell
python backend/services/_gen_native_catalog.py      # 重新生成目录
python backend/services/_verify_native_catalog.py   # 逐条 SQL 预检
```

不需要改 `dashboard_service.py`。

## 4. `spare` 看板为什么读本机库

my-finebi 里 `spare` 指向 `LBR_SP → inventory.db`（远端
`C:\FineBI6.0\...\WareHouseDashBoard\inventory.db`）。该库**长期被占用**：
实测连 `SELECT 1` 都要 42.5s 才返回 `database is locked`；
my_app 的 `task_registry.py` 也已记录该库单次锁 1~9min、最坏 2h+ 的事故。

关键事实：`inventory.db` 是**镜像库**，由 my_app 的
`sp_data_sync` 任务写入；而它镜像的源头正是本机 `db/app.db` 的
`inband_details` / `outband_details` / `inventory_details` 三张表。

> **⚠ 2026-09-30 更正两处此前的错误论断。**
> 1. 本节原先写「唯一写入方就是 my_app」——**与实测不符**。独占打开探测显示
>    远端确有**其它活进程**持有该库的 `-shm` 字节范围锁
>    （`inventory.db` 与 `-wal` 可独占打开，`-shm` 被拒 `PermissionError`）。
> 2. 镜像写不进去的原因**不是**「WAL-over-SMB 天生不可用」。2026-09-30 实测：
>    在同一 SMB 目录新建库、甚至切成 WAL，只要没有远端持有者，本机读写都正常。
>    真正的症结是**远端那个持锁进程**，而 SMB 无法代理 WAL 的共享内存语义。
>
> 该问题已从 my_app 侧根治：镜像改为「本地构建 + 整文件推送」
> （`backend/services/sp_mirror_push.py`），整文件覆盖**不需要**字节锁。
> 详见 `docs/manual/04-task-system.md` 的 `sp_data_sync` 小节。

因此 `spare` 直接改读本机 `app.db`：绕开远端锁、少一跳网络，
且与既有 `sp_dashboard` 服务口径完全一致。实测 12 个组件全部通过。

## 4.1 三张派生宽表为什么也读本机库（2026-09-21 事故修复）

### 症状

`?page=finebi_daily_availability` 的数据从 **2026-09-13** 起不再更新
（`?page=finebi_availability_tt` / `finebi_mttr` / `finebi_progress(_v3)` 同理）。

### 根因

这 5 个看板共 **34 个组件**读的 `avail_recon` / `mttr_tt` / `progress` 三张库，
**不是任何业务系统的原生表**，而是 FineBI 时代在 my-finebi 项目 `data/` 下用
**手工脚本**跑出来的一次性快照（`TMP/etl_avail_recon_v2.py`、`TMP/etl_mttr_tt.py`、
`TMP/etl_progress.py`）。my-finebi 自己的 `PROJECT_DOCS.md` 把它们归类为
「ETL 快照刷新 …… 变更后**重跑**」——**没有调度，靠人记得**。

my-finebi 门户退役后没人再跑，三张表分别冻结在：

| 库 | 冻结于 | 受影响看板 |
| --- | --- | --- |
| `avail_recon.sqlite3` | **2026-09-13**（快照建于 09-14 18:08） | `daily_availability`(9/11 组件)、`availability_tt`(6/8) |
| `mttr_tt.sqlite3` | **2026-08-31 09:29** | `mttr`(10/11) |
| `progress.sqlite3` | **2026-08-31 15:37** | `progress`(6/7)、`progress_v3`(8/9) |

**为什么没人发现**：这三张表既不在 `db_freshness_check` 的远端库清单里
（它们是本机/自建库），也不在它的本地回退库判定里（那里只记录、不判新鲜度）。
页面本身也一切正常——11/11 组件、0 报错，只是**数据是两周前的**。
用户是先看页面才发现的那一方。这与 §5.3 之前 `olib_soc` 看板静默停摆两天是同一类问题。

### 修复

把这三个 ETL 收进 my_app，变成**有调度、有监控**的日常任务；
产物落到本机 `data/`，看板经别名直读本机文件（与 `spare` 同一思路）：

| 任务 | 分组 | cron | 产出 | 依赖 |
| --- | --- | --- | --- | --- |
| `avail_recon_sync` | `u` | `10 6 * * *` | `data/avail_recon.sqlite3` | 远端 `2G/3G/4G_Main_Kpi_Site_Daily`（同组 `main_kpi_sync` 04:00 写） |
| `mttr_tt_sync` | `m` | `40 7 * * *` | `data/mttr_tt.sqlite3` | 远端 `Eflow_TT_FB` + 本机 `data/excel_ds.sqlite3` |
| `progress_sync` | `m` | `50 7 * * *` | `data/progress.sqlite3` | 远端 `Eflow_TT_FB` ⨝ `Eflow_WO_FB` |

映射登记在 `dashboard_service.py`：

```python
LOCAL_SQLITE_FILES = {"__local_avail_recon__": data/avail_recon.sqlite3, ...}
DB_ALIASES = {"avail_recon.sqlite3": "__local_avail_recon__", ...}
```

**为什么用别名而不是改 `native_catalog.py`**：目录是**自动生成**的（见 §3），
手改会被下一次生成覆盖。别名在取数引擎里生效，对生成器完全透明，
`_gen_native_catalog.py` 里也留了 `WIDGET_DB_OVERRIDES` 让生成器直接产出本机库名（幂等，两条路都通）。

**口径注意**（`avail_recon`）：原 FineBI 自助数据集的基表在 FineDB 内部，
区域维度要跨库 JOIN `Master_Site_Database`，而远端只读 API 一次只能查一个库，
因此是**近似重建**：`Cell_Availability = AVG(rate)`（不是"达标站点占比"——
v1 曾按后者算，值域 40~100%，是已知回归，勿回退）；
未匹配到主数据的站点 `FME_Region` 为 NULL，仍计入不带区域过滤的
Availability-NW 组件（与原版一致）。`mttr_tt` / `progress` 的计算列则是
逐行复刻 FineDB 数据集 `4bc5a679`，SWITCH 级联**逐字移植**，改动前请对照原脚本。

**监控**：`db_freshness_check` 新增 `DERIVED_CHECKS`（本机派生表新鲜度判定），
滞后/缺文件都会进 `stale` 并给出调用链；任务本身漏注册/漏分组则由既有的
「任务执行健康检查」覆盖。

### 次生缺陷：日期列里的字面量 `'NaT'`

排查时另发现远端 `Eflow_TT_FB` / `Eflow_WO_FB` 的日期列存在**字符串 `'NaT'`**
（pandas 的 `NaT` 经 `json.dumps(default=str)` 序列化而来）：
`"Alarm Occur Time"` 3 行、`"Alarm Clear Time"` 95 行（WO 表 1 / 180 行）。
文本排序下 `'NaT' > '2026-…'`，于是 `ORDER BY "Alarm Occur Time" DESC`
把脏行排到**最前面** → 看板 TT 明细顶部出现空白行，`MAX()` 也返回 `'NaT'`。

两侧都已处理：写入侧 `eflow_data_mapper._normalize_fb_nulls()` 统一归一为 NULL；
存量 97 + 181 行用 `TMP/_clean_nat_rows.py` 清理（带备份，可 `--restore` 回滚）。
**未清理** `"Actual Completion Time"` 等列（TT 34340 行）——没有任何看板组件引用它们，
清理等于把整张表重写一遍，收益为零；它们会随新数据自然收敛。

## 5. 新增能力（原 FineBI 版没有）

### 5.1 时间窗口

页面右上角 `RangePicker`，可选预设（近 7/31/90 天、今年）或任意起止日期。

实现方式：**不改写原 SQL**。187 条 SQL 形态各异（UNION / CTE / 多层聚合 /
HAVING），正则改写必然破坏原口径，因此把原查询整体包成子查询：

```sql
SELECT * FROM ( <原 SQL> ) WHERE substr("<日期列>",1,10) BETWEEN '...' AND '...'
```

- 日期列**自动识别**：优先第 1 列，要求 80% 以上样本是 ISO 日期；
  识别不到则 `window_supported=false`，前端自动禁用控件（而不是静默返回错数）。
- 支持**日粒度与月粒度**（月粒度取前 7 位比较，覆盖 CN KPI 月度看板的 `2026-04`）。
- **KPI 卡片不参与窗口**：其 SQL 多为 `MAX(...)` 聚合单值，套窗口会变 0 行。

### 5.2 Excel 导出

页面右上角「导出 Excel」，把整页数据导成一个 xlsx：

- 每个组件一个 sheet（图表类导出其绘图数据，表格类导出明细）
- 首个「说明」sheet 记录看板名/数据源/时间窗口/取数时间，便于对账
- 样式遵循 `docs/EXCEL_EXPORT_STANDARD.md`（UNIFIED_EXCEL_V1）

### 5.3 缓存与加载速度（2026-09-21 追加）

**问题**：`?page=finebi_metro_ring` 等页面加载很慢（首屏要等 4~6 秒）。

**诊断**（先量再改，避免瞎优化）：

| 测量 | 结果 | 结论 |
| --- | --- | --- |
| 同一条 SQL，`LIMIT 10` vs `LIMIT 5500` | 28ms vs 1365ms | **成本几乎全在行数**（约 0.25ms/行），SQL 本身免费 |
| metro_ring 单页 | 8 个组件 × ~1.2s，共 **4.4 万行 / 1.27MB** | 冷取数 ≈ 4.4s |
| 数据形态 | 15 分钟粒度 × 57 天（5481 点/序列） | 行数是数据本身决定的，不是 bug |

真正的放大器是**旧的缓存策略**：TTL 只有 60 秒、且只在内存里 ——
意味着用户几乎每次访问都在等冷取数，而且后端每次被看门狗重启缓存就全丢。

**改法**（`dashboard_service.py`，源数据天粒度更新 → 缓存就该按小时算）：

1. **TTL 60s → 6h**（`NATIVE_BOARD_CACHE_TTL` 可调）。数据一天最多变一次，
   60 秒的 TTL 纯属浪费。要立刻看最新数据走 `?force=1`（页面「刷新」按钮）。
2. **磁盘缓存**（`backend/data/native_board_cache/`，已加 .gitignore）：
   看门狗重启后内存缓存必然为空，磁盘缓存让重启后依然秒开。
3. **stale-while-revalidate**：缓存过期时**先把旧数据返回**，再后台回源。
   实测过期后首次请求 **69ms** 返回（`stale=true`），10 秒内后台已刷新完毕 ——
   用户不再为「过期」买单。
4. **启动预热**：`main.py` startup 后台串行预热缺失/过期的看板，
   全部命中时不做任何事（重启后属此列）。
5. **浏览器端缓存**（`NativeBoard.tsx`，10 分钟）：切走再切回**不发请求**、
   不重复解析上兆 JSON；点「刷新」会先失效本地缓存。

**效果**：

| 场景 | 改造前 | 改造后 |
| --- | --- | --- |
| 看板 API（metro_ring） | ~4400ms | **124ms** |
| 看板 API（过期时） | 阻塞 4400ms | **69ms** 返回旧值 + 后台刷新 |
| 页面到出图（metro_ring） | ~6.2s（1s 外壳 + 4.4s 取数 + 0.8s 渲染） | **1.8s** |
| 切走再切回同一看板 | 重新取数 | **0 请求**（~1.0s，纯渲染） |
| 首次/强制刷新 | 4~6s | 4~6s（不变，属正常冷路径） |

> **两个诊断陷阱（别再踩）**
> 1. **`localhost` 的 IPv6 回退会凭空多 2 秒**：`localhost` 在 Windows 上先解析到
>    `::1`，而 nginx 只监听 `0.0.0.0:80`（IPv4），Python `urllib` 会先撞一次
>    `::1` 被拒再回退。实测 `http://localhost` 2070ms vs `http://127.0.0.1`
>    **19ms**。本机脚本一律用 `127.0.0.1`，否则会把「客户端 2 秒」误判成
>    「nginx 慢 2 秒」。
> 2. **不要给后端加 GZipMiddleware**：nginx 的 `/api/` 段有
>    `proxy_hide_header Content-Encoding`（nginx.conf:261），会把上游的
>    `Content-Encoding` 头摘掉 —— 后端一旦 gzip，浏览器拿到的就是没有声明
>    的压缩字节 = 乱码。要 gzip 只能在 nginx 层开。

## 6. 验证记录（2026-09-21）

| 检查项 | 结果 |
| --- | --- |
| 187 条 SQL 远端预检 | 175 通过 / 12 失败（仅 inventory.db 锁，已改本机库解决）→ **187/187** |
| `/api/native-boards/{slug}` × 17（经 nginx） | 200，**187/187 组件有数据，0 失败** |
| 浏览器渲染（Playwright，17 页） | **105/105 canvas 已绘制，0 空白，0 pageerror** |
| 时间窗口（浏览器实测） | 选中「近 7 天」→ 请求带 `start/end`，kpi_4g 872→30 行 |
| Excel 导出（浏览器实测） | 触发下载，`4G_KPI_2026-09-14_2026-09-21.xlsx`，12 sheet，含窗口信息 |
| 既有页面回归 | 24 个 `?page=` 全部 200，6 个核心 API 全部 200 |
| **my-finebi 后端（7138）未运行** | **全部页面照常工作** ✅ |
| `tsc --noEmit` | 0 错误 |

### 6.1 缓存改造后的回归（2026-09-21）

| 检查项 | 结果 |
| --- | --- |
| 17 个看板走缓存后完整性 | **187/187 组件有数据，0 失败** |
| 时间窗口缓存隔离 | 全量 44000 行 → 窗口 5657 行；窗口再取一次 **14ms** |
| Excel 导出（绕缓存取全量） | 200，18.0KB，`PK` 魔数正确，313ms |
| 过期缓存（SWR） | 69ms 返回旧值 + 后台 10s 内刷新完毕 |
| 浏览器切换看板 | 切回时 **0 请求**；点「刷新」+1 请求 |
| 启动预热 | 17 个看板落盘 13.3MB，重启后全部命中 |

### 6.2 派生宽表改本机库后的回归（2026-09-21）

| 检查项 | 结果 |
| --- | --- |
| 三张表重建（手工跑 `__main__`） | avail_recon 7964 行 / 281 天 → **2026-09-20**（2.9s）；mttr_tt 35478 行（1.8s）；progress 35478 行（3.1s） |
| 5 个看板经 nginx（`?force=1`） | **46/46 组件有数据，0 失败**；组件 `db` 全部解析为 `__local_*__` |
| 新任务走队列实跑（`POST /api/tasks/{id}/run`） | 三个任务 **success=1**（3.7s / 6.0s / 5.2s），证明「注册 → 分组 → worker 认领 → 执行」全链路通 |
| worker 分组清单 | `worker[u]` 11 项含 `avail_recon_sync`；`worker[m]` 32 项含 `mttr_tt_sync`/`progress_sync` |
| `tests/test_worker_group_coverage.py` | **PASS=5 FAIL=0**（65 个任务全部归组，帮助文档同步） |
| `db_freshness_check` | 新增 3 条 `scope=derived` 判定全部 `ok`；唯一 `stale` 是既有的 `olib_soc_vmax_report`（从未执行，与本次无关） |
| `'NaT'` 清理 | 4 个日期列 TT 97 行 / WO 181 行 → 剩余 **0**；`MAX("Alarm Occur Time")` 由 `'NaT'` 变回 `2026-09-21 08:21:06` |
| 数据备份 | `.19` 上 `avail_recon/mttr_tt/progress.sqlite3.bak_20260921`；`NaT` 清理另有 JSON 备份可 `--restore` |

## 7. 依赖与运维

- **数据依赖**：远端 `.19:8765` 只读 API 需可达（`.19` 开机且 `db_writer_api` 在跑）。
  地址可在「系统设置 → 远程主机」热改，无需改代码。
- **不依赖**：my-finebi（7190 门户、7138 后端）可完全停掉。
- **缓存**：整页 60s TTL，按 `slug|start|end` 维度缓存；`?force=1` 跳过。
- **单组件失败隔离**：某组件报错只标记该组件，不白屏。

## 8. 相关文件

| 文件 | 说明 |
| --- | --- |
| `frontend/src/pages/NativeBoard.tsx` | 通用看板页（5 种组件类型） |
| `backend/routers/native_boards.py` | API 路由 |
| `backend/services/dashboard_service.py` | 取数引擎 + 时间窗口 + Excel |
| `backend/services/native_catalog.py` | 看板定义（**自动生成，勿手改**） |
| `backend/services/_gen_native_catalog.py` | 目录生成器 |
| `backend/services/_verify_native_catalog.py` | SQL 预检工具 |
| `backend/services/_native_catalog_raw.json` | 生成器的中间产物 |
| `backend/services/avail_recon_sync.py` | 可用率核对宽表重建（§4.1，任务 `avail_recon_sync`） |
| `backend/services/mttr_tt_sync.py` | MTTR/TT 宽表重建（§4.1，任务 `mttr_tt_sync`） |
| `backend/services/progress_sync.py` | Progress 宽表重建（§4.1，任务 `progress_sync`） |
| `backend/services/remote_readonly.py` | 远端只读 SQL API 客户端（上面三个 ETL 共用） |
| `data/excel_ds.sqlite3` | 从 my-finebi 固化的静态参考库（`OLR_CELLS` / `Site_Maintainer_Category`） |
| `TMP/_clean_nat_rows.py` | 一次性 `'NaT'` 清理工具（可回滚） |
