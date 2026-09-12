# my_app 项目长期笔记

> 详细过程见 `.workbuddy-ai/memory/YYYY-MM-DD.md`；本文件只留跨会话必须的结论。

## 1. 环境 / 机器
- **本机 = MSNOC1 = 192.168.100.20**（nginx + my_app:7038 + 门户 vite:9267 + WA:9268 都在这台）。
  `D:\01_RPA` 是本地盘；`net share` 显示 **`01_RPA` → `D:\01_RPA`** ⇒ `D:\01_RPA\Task\_fe_dist` 就是
  本机 vite outDir ⇒ **本机构建即上线**。`Y:`/`Z:` 映射因机器而异（实测指向 192.168.100.19），动前先 `net use`。
- **前端构建**：`FE_DIST_OUT=<目标> <managed node> node_modules/vite/bin/vite.js build`
  （base `/myapp/`、emptyOutDir:false，回滚只还原 index.html）。**别用 `npm run build`**（先跑 tsc）。
- **Python**：managed `3.13.12` 只有 stdlib；端到端验证用**系统 Python312**
  `C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe`（sqlalchemy/fastapi/uvicorn/
  httpx/pandas/paramiko/psycopg2 全有）→ `from backend.routers import X; app.include_router(X.router);
  TestClient(app).get(...)`，不加载 main、无副作用。
  邮件脚本走托管 venv `C:\Users\ZTEEMS\.workbuddy\binaries\python\envs\default\Scripts\python.exe`（有 exchangelib）。
- 拼 sqlite 路径用 `os.path.abspath`，**别用 `Path.resolve()`**（网络盘→UNC→`mode=ro` 报 invalid uri authority）。
- 本工作区 `rm` 被 safe-delete 钩子拦（网络盘 genie-trash 失败）→ 改覆盖写或让用户手删。

## 2. 数据库：PostgreSQL 双模（关键）
- `backend/.env`：`MY_APP_DB_MODE=pg` + `DATABASE_URL=postgresql://…:5432/myapp`，**PG schema = `app`**。
- `db/app.db`（1.5GB sqlite）只是 `pg_to_sqlite_sync` 的离线快照，**排查运行时别只看它**（task_queue 是旧副本）。
- 硬规矩：列名一律 `backend/dialect_helpers.table_columns(conn, table)`（PRAGMA ↔ information_schema；
  直接写 `PRAGMA table_info` 在 PG 下语法报错）；日期列别写 `!= ''`（PG date 报错）用 `IS NOT NULL`；
  SQL 写 `?`（`_PsycopgRawCursor` 转 `%s` 并透传 rowcount）；`get_raw_connection(path)` 在 pg 模式按路径映射 schema，
  **不是写 SQLite 文件**。

## 3. 沙箱限制（别把沙箱的锅当代码 bug）
- **不能执行 `.bat`/`cmd.exe`/`schtasks`**；`.ps1` 可以。**PowerShell 工具不回显 stdout** → 输出写文件再 Read。
- **杀不掉 7038**（更高完整性级别，taskkill / Stop-Process 一律 Access denied）。**唯一通道 = 请用户双击
  `fix_backend.bat`**（UAC 提权 → taskkill → `start_hidden.ps1` 用当前代码重启 → 写 `log\fix_backend_result.txt`）。
  **改完 service/router/task_registry 必须重启才生效。**
- `node` 直调被 shim 拦：用 Bash 工具直接调 `<绝对路径 node.exe> script.js` 可以；`Start-Process` 派生的进程
  调用结束即被回收（沙箱拉不起长期服务）。偶尔 `LsSDK_CreateSandbox(ConPTY) 失败(5)`，重发即可。
- 查子进程用 `Get-CimInstance Win32_Process -Filter "ParentProcessId=<pid>"`（**别用 `foreach ($pid in …)`**，`$pid` 只读）。
- bash 与原生 exe 的 `/tmp` 不同（MSYS 改写）→ 一律写显式 Windows 路径。
- PowerShell 5.1：环境同时有 `http_proxy`/`HTTP_PROXY` 时 `Start-Process -RedirectStandardOutput` 抛
  `Item has already been added` → catch 后把 `http_proxy/https_proxy/no_proxy/all_proxy` 置空重试（已写入 start_hidden.ps1）。

## 4. 服务归属（已划清）
- **门户 liberia-noc_soc**：9267 = vite dev；9268 = WhatsApp 分析服务（`npm start` = `tsx server/index.ts`，
  **别用 `npm run dev`**——tsx watch 被 kill 后立刻重生）。`MyApp_EnsureRunning`/`Portal_EnsureRunning` 每 5 分钟自愈。
- **my_app 不再管 9268**；stop.bat 端口列表去掉 9268，扫描的裸 `vite` 收紧为 `my_app.*vite`（否则误杀门户）。
- 门户日志写在门户根目录 `log\`（= vite root）会触发 HMR，已在门户 `vite.config.ts` 设 `server.watch.ignored: ['**/log/**']`。

## 5. 新增页面 / 任务落点
新增看板页（缺一不可）：`services/<name>_service.py`（口径写顶部 docstring）→ `routers/<name>.py`
（`APIRouter(prefix="/api/<name>")`）→ `main.py` import + `include_router` → `frontend/src/api.ts`
→ `pages/<Name>.tsx`（`useI18n()` + `WH`/`useTheme()` 令牌，禁硬编码颜色）→ `App.tsx`
（`PageKey`/`VALID_PAGES`/`PAGE_META`/`DEFAULT_GROUPS`/lazy import/renderPage）→ `i18n.tsx`（zh+en 两处）
→ `backend/data/ui_menu_layout.json`（改完菜单立刻生效，**不用重启**；但新 chunk/新端点仍需 build+重启）。
看板 GET 端点**直接平铺返回业务对象**，**不要**包 `{status,data}`（前端按 `r.data.rows` 取，包一层整页 No data）。

**新增定时任务三件套（缺一 → 队列 pending 卡死）**：
① `worker_watchdog.GROUP_TASK_MAP` 必须显式分组（邮件/内务→`m`，eFlow/网管→`n`，UME→`u`，CN EMS→`c`）；
② `task_registry.TASK_SPECS` 追加 dict，`default_cron` 在调度表缺行时兜底（缺行≠不跑）；`category` 决定 gateway；
③ `helpTaskDocs.ts` 补一条。邮件任务还需在 `email_recipient_store.EMAIL_RECIPIENT_GROUPS` 加 key（=task_id）。

## 6. 数据口径
- 可用率达标值 `0.9965`（site_availability_service / ran_cells_kpi_service）。库名/列名 `avalability` 是历史拼写，别改。
- 4G FDD 表列名含不换行空格 `\xa0`，双引号写错会退化成字符串常量 → 先 `table_columns` 拿真实列名
  （2G 表 `Managed Element`，3G `RNC Managed NE`）。2G 必须用「全信道」公式（静态 TCH/F + TCH/H + 动态）。
- **SP 物料 `inventory_details`（PG）**：每日全量快照，保留 **180 天**（`get_sp_table.py` 的
  `INVENTORY_RETENTION_DAYS`；cutoff = 表内最新**合法** `update_date` −(N−1)，非系统当天）。
  口径见 `sp_material_summary_service.py`（标记 `RCK_MATERIAL_SUMMARY_V1/V2`），页面
  `pages/SpMaterialSummary.tsx`（`page=sp_material`），端点 `/api/sp-material/summary|detail`。
- legacy iframe `frontend/public/alarm-management.html`（2.26MB）：**改 DOM 会影响 `site_outage_screenshot`
  自动截图** → 新 CSS 必须用 `#<区块id>` 限定；纯 public/ 静态资源直接 `cp` 到 `_fe_dist` 即上线。

## 7. 判定后端是否加载新代码
- 端点 docstring 写 ASCII 标记（如 `RCK_MATERIAL_SUMMARY_V2`）→ 进 openapi description →
  `grep <标记> /openapi.json` 匿名可确认。`/openapi.json` 是**单行 JSON**（数出现次数而非行数）。
- `/api/*` 未登录一律 401（不存在的路径也 401）；`/myapp/*` 被 SPA 回退成 index.html（任何路径 200，看内容）。
- 新版 FastAPI `include_router()` 产生 `_IncludedRouter`（`.path` 为 None）→ 别用 `app.routes` 过滤验证路由，用 TestClient。
- **同一条消息里对同一文件发多个 Edit 会互相覆盖** → 必须串行。

## 8. 守护链与自愈
- 三层：`MyApp_EnsureRunning`（5 分钟，`start_ensure.bat` → `start_hidden.ps1 -Quiet -Force`）→
  `backend_watchdog`(7038)/`worker_watchdog`(u/x/n/m/c) → 各 worker。
- `backend/stopped.flag`（stop.bat 写、start.bat 删，只影响是否启动）；心跳 `log/heartbeat_*_watchdog.json`
  （15s）**pid ≠ PID 文件内容 = 多个 watchdog 并存**。
- `stop.bat` 的命令行扫描是**唯一**能清「无 PID 文件的僵尸 watchdog / 孤儿 uvicorn」的机制。
- **巡检报 OK ≠ 7038 是新代码，仍须 `/openapi.json` 复核。** `restart_workers.py` 是 worker/watchdog 规范化重启入口。

## 9. 统一 Excel 导出格式（UNIFIED_EXCEL_V1，2026-09-11 定）
- **规范文档** `docs/EXCEL_EXPORT_STANDARD.md`；**前端模块** `frontend/src/utils/excelReport.ts`。
- 样式源头 = 后端邮件报表 `backend/services/sp_report_gen/gernarate_sp_report.py` 的
  `style_excel()` / `style_summary_changed()`（常量在 97–133 行）→ Web 导出与邮件附件**同源**。
  参考样例：`data/sp_email/SpareParts Inbound&Outbound&Inventory <ts>.xlsx`。
- 依赖 **exceljs 4.4.0**（社区版 `xlsx` 写不了样式）。registry = npmmirror，可联网装。
- API：`exportReport(sheets, filename)` / `exportAoaReport({filename,header,rows,...})`（裸 `aoa_to_sheet` 直替）
  / `buildReportWorkbook` / `downloadBlob` / `safeFileName` / `SHEET_TAB_COLORS`。
- 关键样式：标题 Calibri14 bold `1F3864`；副标题 Calibri9 `808080`；表头 Calibri11 bold 白字 + 底纹 `2F5496`
  + 细框 `B4C6E7` + 底边中粗 `4472C4`；分组表头橙 `FF8C00`；数据 Calibri10 隔行 `F2F2F2`↔`FFFFFF` + `#,##0`；
  合计行 `D6DCE4` + bold `1F3864`；数值 0→`C0C0C0`、>0→bold `006100`、<0→bold `9C0006`；
  列宽 `min(max(len+2,10),42)` 扫前 200 行；**隔行底纹按工作表绝对行号奇偶**（非数据序号）。
- **ExcelJS 坑（必记）**：`ws.getCell(r,c)` 对已被合并覆盖的格子**返回主格** → 写多行表头必须用占用位图
  跳过上方 rowSpan 占用的列，否则整行左移且主格值被覆盖；合并放在写值之前即可
  （`Cell.merge` 默认 `this.style = master.style`，覆盖格自动继承样式）。
- 纯前端改动**不需要重启后端**，`vite build` 即上线。
- 已迁移：`SpMaterialSummary`（汇总 + 下钻明细）。**待迁移 9 处**仍用裸 xlsx 的页面见规范文档第 4 节。

## 10. ⚠️ PG 模式下 SQL 字面量里的 `%` 不会被转义（会 IndexError）
`backend/database.py::_qmark_to_pyformat` 转换 `?`→`%s` 时**整段跳过字符串字面量**（含 `''` 转义），
所以 `LIKE '%spare%'` 里的 `%s` 会被 psycopg2 当占位符 → `IndexError: tuple index out of range`。
**规矩：通配符放参数值，写 `LIKE ?` + `f"%{token}%"`**；列名里的 `%`（如 `"Packet Loss Rate(%)"`）
在**带参数**路径才会被转义，无参数路径 psycopg2 不格式化所以也安全。

## 11. outband_details 表事实（SP 出库）
- **全量刷新表**（每次同步整表覆盖，所有行 `update_date` 相同）→ 不能按 update_date 取快照，
  要按 `Outbound Time` 过滤。
- **只有 `Warehouse Name`，没有 `Warehouse Id`** → 归组只能 `_match_group("", name)`。
- `Outbound Type`：Install / Borrow / Inventory Lost / Others / **Repair Outbound**。
  一行 = 一个物料序列号，`Outbound Qty` 恒为 1；`Outbound Time` 是 `'YYYY-MM-DD HH:MM:SS'` 文本
  （字典序即时间序，跨库统一 `CAST(... AS TEXT)` 更稳），空值表示 WaitingForUpdate 未出库。

## 12. 7038 无法重启时的端到端验证套路（临时后端 + CDP 请求改写）
1. `TMP/tmp_sp_app.py`：只挂目标路由的最小 FastAPI + `allow_origins=["*"]`；
   起法 `<系统Python312> -m uvicorn tmp_sp_app:app --app-dir TMP --port 7039`（**必须 `--app-dir TMP`**）。
2. `TMP/cdp_verify_v2.mjs <outPng> <cellText|-> <table|drill> <url>`：CDP
   `Fetch.enable({patterns:[{urlPattern:'*://*/api/sp-material/*'}]})` → `Fetch.requestPaused` 里
   `Fetch.continueRequest({requestId, url: 7039+path})`，其余原样放行。
   **必须先 enable 再 `Page.navigate`**，否则首屏请求漏过（`intercepted=0`）。
3. 浏览器仍走真 nginx（`http://127.0.0.1/myapp/`，回环免登录），前端就是线上 `_fe_dist` →
   「新前端+新后端」真实组合可验证，无需改 nginx。
4. 同一 bash 调用连开两次 Chrome 要用**不同 `--user-data-dir`**（唯一名带 `$$`；该目录会被
   safe-delete 钩子挡住删不掉）。
