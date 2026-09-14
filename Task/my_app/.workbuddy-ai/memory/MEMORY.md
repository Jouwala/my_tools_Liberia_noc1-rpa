# my_app 项目长期笔记

## 1. 环境与部署
- 生产机为 192.168.100.20，本地工作区 `D:\01_RPA\Task\my_app`；nginx 实际配置：`D:\01_RPA\nginx-1.28.0\nginx-1.28.0\conf\nginx.conf`。
- 前端构建产物必须输出到 `D:\01_RPA\Task\_fe_dist`，nginx `/myapp/` 直接静态托管；使用托管 Node 的 Vite build，避免 `npm run build` 先跑 tsc。
- API 后端 7038；**7138 = FineBI / my-finebi 独立应用（不在本机，也不在本仓库）**，nginx 把 `/my-finebi/`、`/api/dashboards`、`/api/data/sources`、`/api/finebi/` 都转给它；它没在监听属长期状态，别当成自己改坏了；前端默认 API base `/api`。
- 映射盘：`Y:`/`/y` 对应共享盘根，生产目录通常是 `/y/01_RPA`；远程改文件不等于能 reload 生产 nginx。
- 内网请求绕过代理：curl 用 `--noproxy '*'`，Python httpx 用 `trust_env=False`。

## 2. nginx 与 502
- `/myapp/` 直接 alias `_fe_dist`，避免 vite preview 7090 重启空窗造成 502。
- `/api/` 兜底到 7038；`/api/dashboards`、`/api/data/sources`、`/api/finebi/` 到 7138。
- nginx 配置曾关闭 access/error 日志，排查 502 不能只依赖日志。
- 修改 nginx 后需在生产机执行 nginx reload；修改后端路由/服务需重启 7038。
- **重启 7038 的正确姿势**（与用户桌面 `restart_7038.bat` 一致）：uvicorn 由 `backend/backend_watchdog.py` 托管（pid 见 `log/heartbeat_backend_watchdog.json`），只杀 7038 那个 uvicorn pid（`taskkill /PID <pid> /F`，**不要加 `/T`** —— `/T` 会连带杀掉实时代理 8787/8790 及其子进程），看门狗约 3 秒内自动拉起新实例并 reuse 还活着的代理。Git Bash 里 `taskkill //PID` 会被路径转换破坏，改用 `python -c "import subprocess;subprocess.run(['taskkill','/PID','<pid>','/F'])"`。
- 后端解释器 = `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`（有 pandas/sqlalchemy/psycopg2/uvicorn）；工作区 venv `Scripts\python.exe` 只有少量包，**没装 pandas/pytest**。pytest 本机不可用，单测靠 importlib 直接 exec。

## 3. 门户登录
- `frontend/src/pages/PortalLogin.tsx` + `backend/services/portal_login_service.py` 实现 client/server 双模式。
- myapp 数据接口强制鉴权：中间件 `backend/main.py::require_session_middleware`，会话实现 `backend/services/portal_auth.py`；放行清单 `_PUBLIC_API`（`/api/auth/`、`/api/health`、`/api/ui/menu-layout`、`/api/portals/client-login/consume`），本机回环 `client_is_local` 放行。
- 会话存储由 `backend/.env` 的 `MY_APP_DB_MODE` 决定：**生产是 `pg`**（表 `portal_sessions` 在 PostgreSQL），`db/app.db` 里的同名表只是 sqlite 时期遗留。
- 免登录总开关 `D:\01_RPA\auth-switch.json` 的 `authEnabled`（myapp + 门户共用，默认 true 即要求登录）。
- 前端鉴权引导约定（2026-09-14 修复首屏 401）：换会话必须在 React 渲染前完成 —— `api.ts::bootstrapAuth/runAuthBootstrap` + `main.tsx` 先 await 再 `createRoot().render()`；`App.tsx` 用 `bootDone` 保证业务页面不在会话就绪前挂载。**新增页面无需处理鉴权时序，但不要再在页面里抢跑数据请求的初始化逻辑**。
- 门户 token：URL `?t=` 或同源 localStorage `liberia_noc_auth_v1`（门户 `resolveUrl()` 自动追加 `&t=`）。
- eFlow 与 RAIS 是 `direct=True` 门户：不能走 nginx 反代。反代实测会出现告警 0/0、`Failed to Query Active Alarm Columns and Default Templates`，根因包含 cometd WebSocket 403。
- 本机访问者通过 `/api/portals` 的 `client_is_local` 自动走服务器桌面直接鉴权；远程访问者当前 client 模式只能直开门户手工登录，server 模式可在服务器桌面一键登录。
- eFlow 直接鉴权：先等待 Chrome 页面落到门户源，再种 Cookie，并回读校验 `localStorage.csrftoken`；成功判定需正证据和连续两次，不能只看 URL/非空正文。
- Chrome CDP 不能启用 Debugger 域；访问本机 CDP 前清除 http/https proxy；自签上游先 `Security.setIgnoreCertificateErrors`。
- 已验证本机 eFlow 直接登录能得到真实告警（6767/6767）；RAIS 直接鉴权回归通过。
- 无头浏览器验证页面可用 `chrome.exe --headless=new --no-proxy-server --virtual-time-budget=N --dump-dom`；临时种会话可走 `GET /api/auth/kiosk?key=<backend/.env 的 MYAPP_KIOSK_KEY>&next=...`（记得验证后从 PG 删掉该 kiosk 会话）。

## 4. WhatsApp 发图任务（whatsapp_send）
- 图片清单**必须每次执行时重新收集**（`_collect_photos_and_captions()`）：worker 长驻，模块级 `PHOTOS` 只是 import 快照，新产出的截图会漏发（2026-09-14 `COOL.png` 事故）。
- 当前 WhatsApp Web **没有附件按钮**（`SELECTORS["ATTACH"]` 全不命中），页面常驻隐藏 `input[type=file]`；**只有剪贴板路径能正确挂备注**，不要让 file-input 路径跑起来（`CAPTION_INPUT` 含 `data-tab="10"` = 聊天输入框，会把备注打进输入框）。
- 用户偏好：此类修复只做**最小改动**，不要顺手重构发送流程（大改被要求全部回退）。

## 4.5 eFlow 知识库页（eflow_qa）的 TT 能力
- 单票「TT 快速分析」：`#tt-quick-analysis` → `/api/eflow-qa/inspect-tt` + `/tt-ai` + `/tt-alarm` + `/tt-ume-suggestion`。
- **TT 批量级别核查**（2026-09-14 新增）：左栏 `#tt-batch-check` / `POST /api/eflow-qa/tt-batch-check`
  → `backend/services/eflow_rules/tt_batch_severity.py`。前端在浏览器侧解析 xlsx/xls/csv/txt 清单（SheetJS），
  后端只吃单号数组。判定三态 ok/adjust/unknown，导出走 `utils/excelReport.ts`（全部结果 / 需调整 两个 sheet）。
- **TT 级别判定口径的唯一真相源** = `backend/services/eflow_rules/eflow_rules_matcher.py`
  （读 `eflow_TT_rules.xlsx` 的 ACTIVE 规则；每天 04:20 `eflow_tt_rules_check` 定时任务同源）。
  它内部直连 sqlite `db/app.db`，而生产是 `MY_APP_DB_MODE=pg` → **Web 路径取数必须走
  `backend.database.get_raw_connection()` 双模连接，再把 DataFrame 交给 matcher**；复用 `load_rules()`
  时记得 `redirect_stdout` 静音它的 print。

## 5. 当前未决问题
- 远程电脑访问 `http://192.168.100.20/myapp/?page=portalLogin`，点击 eFlow 显示 `Page opened; please complete login manually`；UME 反代登录正常。
- 反代 eFlow 诊断：HTTP 失败请求 0，但 `/api/fm-active/v1/cometd` WebSocket 握手连续 403，`/meta/connect` 返回 `402::session_unknown`，页面告警 0/0。当前优先评估是否能安全修复 ws；若不能，必须保持 eFlow 不反代并给远程用户准确提示。
- 诊断脚本在 `TMP/t_proxy_diag*.py`，临时 Chrome profile 可能位于 TMP；不得删除 `.workbuddy-ai`。

## 6. 验证约定
- 用系统 Python312 做 FastAPI TestClient（不加载 main）；新端点可检查 `/openapi.json` 标记。
- **前端真实交互验证优先用 Playwright**：工作区 venv `./Scripts/python.exe`（playwright 1.62 + 自带 chromium），`p.chromium.launch(headless=True, args=["--no-proxy-server"])` + `locale="zh-CN"`。示例见 `TMP/t_ttbatch_e2e.py`、`TMP/t_ttbatch_upload.py`（含真实下载校验）。
- 无头 Chrome `--dump-dom` 默认语言是 en，grep 中文文案会全部落空；且 antd 空表格的空态占位也是 1 个 `tbody tr`，统计行数要排除 `.ant-table-placeholder`。
- 同一消息对同一文件的多个 Edit 必须串行。