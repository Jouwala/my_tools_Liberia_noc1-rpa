# my_app 项目长期笔记

> 定位：**跨模块硬规则 + 索引**（主文件有注入上限，细节按需读子文件）。
> - `memory/MODULES.md` —— §4 各业务模块的实现细节 / 口径坑（WhatsApp、SP 报表、eFlow、UME、看板…）
> - `memory/OPS_RUNBOOK.md` —— 重启 7038 / worker 组、nginx、门户登录鉴权的完整 runbook
> - `memory/PLAYBOOK.md` —— 验证约定 + 排障套路
> - `memory/FRONTEND_PITFALLS.md` —— 前端 / Playwright / i18n 硬规则
> - `memory/YYYY-MM-DD.md` —— 单模块实现细节日志

## 1. 环境与部署
- 生产机 192.168.100.20；工作区 `D:\01_RPA\Task\my_app`；nginx 配置 `D:\01_RPA\nginx-1.28.0\nginx-1.28.0\conf\nginx.conf`。
- 前端产物必须出到 `D:\01_RPA\Task\_fe_dist`（nginx `/myapp/`）；用托管 Node 直接跑 vite，**别用 `npm run build`**（会先跑 tsc）。
- `_fe_dist/assets` 无限累积历史 chunk（`vite.config.ts` `emptyOutDir:false` 是刻意的：safe-delete 钩子会拦 Vite 清空目录）。清理 `TMP/t_dist_prune_apply.py --apply`（移到备份目录；回滚 `t_dist_restore.py`）。⚠️ 单次批量移动 >2000 文件会被 safe-delete 钩子 SIGTERM 掐断 → `--limit 300` 反复跑到「待清理 0」；**批量文件操作必须过 alive 白名单**（从 index.html 做 import 图 BFS），曾漏过滤搬走 18 个活 chunk → 404。
- 端口：后端 **7038**；**7138 = FineBI/my-finebi 独立应用**（不在本机/本仓库，nginx 转 `/my-finebi/`、`/api/dashboards`、`/api/data/sources`、`/api/finebi/` 给它）；它没监听属长期状态，别当自己改坏了。
- 映射盘 `Y:`/`/y` = 共享盘根；远程改文件 ≠ 能 reload 生产 nginx。
- 内网请求绕代理：curl `--noproxy '*'`，Python `trust_env=False`。
- 解释器：后端 = `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`（pandas/psycopg2/uvicorn/playwright/openpyxl/win32com）；工作区 venv `Scripts\python.exe` **无 pandas/pytest**（有 playwright）。pytest 不可用，单测靠 importlib 直接 exec。
- ⚠️ 生产 `DB_MODE = pg`：业务数据（SP 明细 / 看板 / 会话）都在 **PG**；`db/app.db`（1.58 GB）是**遗留 sqlite**，**别用它判断同步结果**。长任务（写 PG 12 万行）要用后台跑，前台会被 SIGTERM 掐断。

## 2. 进程与重启（详细 runbook → `memory/OPS_RUNBOOK.md`）
- 重启 7038 由 `backend/backend_watchdog.py` 托管，≈3s 拉起；`taskkill /PID <pid> /F` **不加 `/T`**（会连带杀实时代理 8787/8790）。改 `backend/services/**` 后**必须重启对应 worker 组**：`python restart_workers.py --groups <g> --reason "..."`（组见 `backend/worker_watchdog.py::GROUP_TASK_MAP`；邮件任务在 m，`ume_in_kpi_sync` 在 n）。
- ⚠️ **7038 常常杀不掉**（`Access is denied`，token/integrity 差异，非沙箱策略）→ **别硬来，让用户在本机双击 `fix_backend.bat`**。
- ⚠️ 新增任务只重启 worker 不够，必须 `restart_workers.py --mode watchdog --groups <g> --force` + `Start-ScheduledTask -TaskName MyApp_EnsureRunning`。
- ⚠️ **Windows nginx 不是守护进程**：沙箱里起的会随 shell 被杀，**唯一可行 = PowerShell 的 WMI 启动**；重启会真中断站点，**动手前必须告知用户**。

## 3. 门户登录与鉴权（详细 runbook → `memory/OPS_RUNBOOK.md`）
- `/api/` 全量强制会话（`main.py::require_session_middleware`），放行 `_PUBLIC_API`；本机回环 `client_is_local` 放行（本机 curl/Playwright 免登录）。生产会话存 **PG** 的 `portal_sessions`（`db/app.db` 同名表是遗留）。
- 前端鉴权引导必须在 React 渲染前完成（`api.ts::bootstrapAuth` + `main.tsx` 先 await 再 render；`App.tsx` 用 `bootDone` 卡页面）。**别在页面里抢跑数据请求初始化。**
- ⚠️ **门户反代 `location /api/` 靠 Referer 区分上游，对 WebSocket 天然失效** → 带 WS 的门户 API 必须按 URI 开 `^~` 专用 location，别指望 Referer。
- ⚠️ **独立端口门户反代 8081-8086/8088 是 HTTPS-only**（2026-11-09 起，`conf/portal_ports.conf` 的 `listen 808x ssl` 共用 443 自签证书）。主站 80→301→443 恒为 https，前端 `location.protocol` / 协议相对 `//{HOST}:808x` 都会拼出 `https://<host>:808x`；端口若说 HTTP 就回 `ERR_SSL_PROTOCOL_ERROR`（Chrome 显示「localhost sent an invalid response」）。**不能改回 http://** —— https 页嵌 http iframe 会被混合内容拦（仅 localhost/127.0.0.1 例外）。口径四处要同步：nginx 端口协议 + `proxy_redirect` 的 https、`ImonitorScreen.tsx::portalBase()`（固定 https）、`PortalLogin.tsx`（给 `//` 前缀补 https）、`PROXY_PREFIXES`。`http://host:808x` 的书签/脚本一律改成 https。排查用 Playwright 遍历 `page.frames` + `requestfailed`，别只看顶层 200。详见 `memory/2026-11-09.md`。
- 免登录总开关 `D:\01_RPA\auth-switch.json` 的 `authEnabled`；临时种会话用 `GET /api/auth/kiosk?key=<MYAPP_KIOSK_KEY>`（用完从 PG 删）。

## 4. 关键业务模块（细节 → `memory/MODULES.md`）
- **4.1 WhatsApp 发送**：剪贴板路径发送，只做最小改动。
- **4.2 SP 备件报表**：`sp_report_gen/gernarate_sp_report.py`，任务 05:15；明细预处理会写回 `data/sp_email/data`（`sp_email_details` 同口径）。**数据源 2026-09-16 迁到 `/home/ubuntu/sp/<目录名>/<日期>/<时间戳>/<同名文件>.xlsx`**（旧 `sp/spinbound` 等已停更，同变更也应用于 `get_sp_table.py` / `task_configs_registry.py`）。**每个 sheet 标题下第 3 行有过滤条件说明行**（含 `Operation Result Status ≠ 'Canceled'`）。
  - **Summary-Current 共 12 列（A:L）**（全英文，2026-09-17 定稿、2026-09-18 加列）：
    前 7 列 = `Material Name` / **`Domain`（2026-09-18 新增，固定第 2 列，取自 Inventory 明细，同一物料取第一个非空，Total 行留空）** / `Inbound Qty` / `Outbound Qty` / `Inventory Qty` / `Balance` / `Difference`；
    后 5 列 = `Avg Monthly Consumption`（= 出库量剔除 `SPOB202608160004`/`SPOB202609120014` 后 /9.5）、`Safety Stock`（=6×月均）、**`Remark`（月均>0 → `Actual Consumption`；月均=0 → `Failure Rate`）**、`Replenishment Qty`（=安全库存−Inventory Qty，≤0 留空）、`Alert Level`（<50% Urgent Replenish / 50~100% Replenish / >100% Excess）。**报表文案一律英文，不要中文**。
    - **3 个数值列一律向上取整为整数**，且**逐级取整**（先 `ceil(消耗/9.5)` 得月均，再 `6×月均` 得安全库存 → 表内可验算 `Safety = 6 × Avg`）。Excel 数字格式 `#,##0`。
    - **月均消耗 = 0 的物料按「故障率」备件处理**：`Safety Stock` 保底 **1**、`Remark = Failure Rate`；其 Alert 按 `库存/1` 判（库存 0 → Urgent、1 → Replenish、≥2 → Excess）。
    - **口径说明写在文件上方**：Summary-Current 第 4/5/6 行**三行**英文说明（`Replenishment basis: ...` / `Replenishment Qty = ...` / `Remark: ...`），**表头在第 7 行、数据从第 8 行起**（其余 sheet 仍是第 4 行表头）。
    - 生成结束由 `_cleanup_old_reports()` 按「前缀+仓库名」只留最新一份 xlsx/png。
  - ⚠️ 该脚本走 `kpi_email_report.run_sp_report_generate` 的 **subprocess** 执行 → 改完**不用重启 worker 组 m**，05:15 自动用新代码。本地验证可打桩 `sftp_download` / `_save_detail_xlsx`（不写回生产明细）/ `_cleanup_old_reports`，参考 `TMP/t_sp_replenish_verify.py`，配套 `t_sp_final_check.py` / `t_replenish_edge.py` / `t_style_compat.py`。
- **4.3 eFlow TT**：判定真相源 `eflow_rules_matcher.py`；AI 走 Open WebUI `agnes-2.5-flash`。
- **4.4 Alarm Management 看板**：`FMS_REAL` 是冻结快照，结构性常量不自愈。
- **4.5 incident-overview AI**：agnes 直连上游；不存在的模型返回 **503**。
- **4.6 UME PM-analysis 协议**：socket+TLS+RSA 登录 → history 查询 → ZIP 包裹 xlsx。
- **4.7 ume_in KPI 看板**：任务尚未被 worker 认领（暂缓）。
- **4.8 OSG Weekly QoS Report**：改 sheet XML 填数，保公式与图表。
- **4.9 前端 / Playwright / i18n** → `memory/FRONTEND_PITFALLS.md`。
- **4.10 身份与组织主数据（任何"按人/按部门"的功能都踩这里）**：门户会话只带 `username` + `role`(admin/viewer) + `allowedGroups/Cards`，**没有邮箱、没有部门、没有真名**（`portal_auth.py::create_session`）。身份桥（2026-10-30 实测）：门户 username 小写 == `app.flm_team_information."unnamed_5"`（eFlow Acount，仅 30 人）→ 同行取 `unnamed_3`姓名 / `unnamed_4`职位 / `unnamed_2`Base location / `unnamed_1`County → 姓名经 `services/person_name.py::normalize_person_name` 归一 → `app.person`（email 仅 50/137、`managed_regions`、`leavestatus`）。**`app.person` 的 `department`/`position`/`office`/各级 `*_leader` 列全为空（0 行非空），不要当部门主数据用**。办公室账号（admin/jouwala/6000056629 等）不在 FLM 花名册，需人工建档。`person_name.py` 是姓名跨表 JOIN 的唯一实现（`Name(FE_FE_111)` / `P:Name` 归一，实测 96% 命中率）。

- **4.11 AP 行动计划（`?page=ap_center`，2026-10-30 上线）**：整改任务闭环（DRAFT→ASSIGNED→ACKNOWLEDGED→IN_PROGRESS→PENDING_REVIEW→COMPLETED/REJECTED）。细节见 `docs/manual/11-feature-guide.md` §39 与 `backend/services/ap_manager/AP_Plan_Review.md`。四条硬规则：① 状态值一律下划线、转换白名单在 `ap_manager/store.py::TRANSITIONS`，并发用乐观锁 `UPDATE ... WHERE id=? AND status=?`（sqlite 无行锁）；② 组织架构 = Escalation Matrix（`ap_manager/org.py::ORG_SEED`，4 级 21 人），**不是部门表**；任务里存姓名、账号靠 `permissions.keys()` 的「账号+姓名+显示名」别名互认，否则按姓名派单本人看不到；③ WhatsApp 走 `wa_notify_service` 是**单槽作业文件**，必须批量 dispatch（`notify.py` 3 秒合并窗口），逐条发会互相覆盖；④ PG 上 `COALESCE(时间列,'9999')` 会报错、`datetime` 序列化带 `T` 会让逾期比较出错，统一用 `store.normalize_ts()`。

- **4.12 RAN 网元管理表同步（`ran_element_management_sync`，2026-11-07 上线，每天 23:00 → u 组）**：抓包 `backend/services/RANElementManagement/url.txt`（1080 行）里**只有第 852 行** `GET /api/res/v1/ranmes?queryDn=model:subnetwork&operation=operation.rem.rnm.tools&includeAttr=...` 是真取数接口，其余是静态资源/登录/WS；另有 10 个 `/api/rncmoaction/v1/rnc/<uuid>` 详情含 `ommFtpPasswd` **禁止采集或入库**。实现 `backend/services/RANElementManagement/ran_element_management_service.py`（`run_ran_element_management_sync`）。硬规则：① **不硬编码抓包 Cookie**（`Z-AUTH-CODE-28001` 等会过期），走 `auth_manager.get_auth(probe=...)` + `credential_store` 的 `zte_ume`，且 **probe 必须打本业务接口**（登录首页会返回误导性 200）；② 归 **u 组**因为与 `ran_ume_daily`/`cm_data_sync` 共用同一 UME/账号/`auth_cache` 会话，并发登录互踢；③ PG 三表 `app.ran_element_management`（当前全量，按 `ne_id` upsert，末尾按 `fetched_at` 清陈旧行）/ `app.ran_element_management_daily`（PK `snapshot_date+ne_id`，同日先删再插，幂等）/ `app.ran_element_management_sync_log`，DDL 服务内幂等建表**无需 Alembic**；④ `get_raw_connection()` 是 autocommit，必须显式 `BEGIN/COMMIT/ROLLBACK`（游标自动把 `?`→`%s`）；⑤ `RAN_EM_MIN_ROWS`（默认 100）行数下限拦上游残片，实测 934 行 / 15 字段（ITBBU 812 / SDR 111 / MRNC 10 / MEC 1）。验证脚本 `TMP/t_ran_em_final_verify.py`（系统 Python312 直跑，含注册表/cron/懒加载/分组/PG 全链检查）。

## 5. 验证与排障（详细 → `memory/PLAYBOOK.md`）
- 后端纯逻辑用系统 Python312 起 FastAPI TestClient（**只挂目标 router，不加载 main**，否则鉴权中间件 401）；前端真交互用工作区 venv 的 Playwright（`--no-proxy-server` + `locale="zh-CN"`）。**写/改代码要验证、或排查线上异常时先读 `memory/PLAYBOOK.md`**（含：前端改动是否真上线怎么查、帮助文档生成链路、Excel 导出约定、改 xlsx 模板保图表的三步校验、nginx→7038 瞬时 502 的判法、代理污染 vs 真网络不通、`/api/tasks/history` 参数格式、任务被禁用静默跳过、EWS 邮件网关故障与补发机制）。
- ⚠️ **提交时 `.githooks/pre-commit` 假失败**：本机 Node 的 `spawnSync` 创建 stdio 管道恒报 `EBUSY(-4082)`（Node 22/24、Bash/PowerShell、沙箱内外都复现；`stdio:'inherit'`／文件 fd／异步 `execFile` 正常），导致 `check-cleanliness.mjs`、`check-team-scope.mjs` 起不了子进程。**不要用 `--no-verify`**，改用 `NODE_OPTIONS='--require=D:/01_RPA/.git/spawnfd_shim.cjs' git commit -F <msgfile>`（shim 把管道换成临时文件 fd，只注入 env、不入库、不改仓库代码，守卫真实跑）。详见 `memory/2026-11-06.md`。
