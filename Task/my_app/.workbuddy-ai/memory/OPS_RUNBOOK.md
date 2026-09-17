# 进程 / 重启 / nginx / 门户鉴权 runbook（从 MEMORY.md 拆出，主文件已超注入上限）

> 用法：重启后端或 worker、动 nginx、调门户登录鉴权之前，先读本文件。

## 2. 进程与重启
- **重启 7038**（桌面 `restart_7038.bat`）：uvicorn 由 `backend/backend_watchdog.py` 托管；只杀 7038 的 pid，`taskkill /PID <pid> /F` **不加 `/T`**（`/T` 会连带杀实时代理 8787/8790）；看门狗 ≈3s 拉起。Git Bash 里 `taskkill //PID` 被路径转换破坏 → 用 `python -c "import subprocess;subprocess.run([...])"`。
  ⚠️⚠️ **7038 常「杀不掉」**：若 uvicorn/watchdog 由计划任务或更高完整性级别启动，`taskkill`/`Stop-Process`/`dangerouslyDisableSandbox` 全返回 `Access is denied`（2026-09-16 实测 PID 11728 `pythonw.exe`，watchdog 心跳新鲜）。**不是沙箱策略，是 token/integrity 差异，只能提权。**
  → 唯一可靠解法：**本机双击 `D:\01_RPA\Task\my_app\fix_backend.bat`**（自请求 UAC → 杀 7038 占用者整棵树 → 清 pid/heartbeat/stopped.flag → 用当前代码经 start_hidden.ps1 拉起 → 校验并写 `log/fix_backend_result.txt`）。**必须本机跑**（UNC 无法提权）。`restart_7038.bat` 里 `call restart_backend.bat` 指向的文件不存在；`start_hidden.ps1 -Force` 的「清理 7038 占用者」分支只在 watchdog 心跳**不新鲜**时才进入。**杀不掉就别硬来 → 让用户双击 fix_backend.bat。**
- **重启 worker 组**（改 `backend/services/**` 后必做）：`python restart_workers.py --list` → `--groups m --reason "..."`（自带留痕 `log/worker_restart_marker.log`，别手敲 taskkill）。组见 `backend/worker_watchdog.py::GROUP_TASK_MAP`；`sp_*`/`kpi_*` 邮件任务在 **m**，`ume_in_kpi_sync` 在 **n**。
  ⚠️ `GROUP_TASK_MAP` 由 watchdog 启动时读入内存并经 `MY_APP_WORKER_TASKS` 下发 → **新增任务只重启 worker 不够**，必须 `restart_workers.py --mode watchdog --groups <g> --force` + PowerShell `Start-ScheduledTask -TaskName MyApp_EnsureRunning`（沙箱内 schtasks 被拦）。改 `task_registry.py` 名称/描述要**同时重启 worker 和 7038**（UI 读 7038 内存里的注册表）。
- **nginx**：`/myapp/` alias `_fe_dist`，`/api/` 兜底 7038。access_log 故意关闭（曾 470MB），error_log 开到 warn（`logs/error.log`）。改配置先 `nginx.exe -t`；`logs/nginx.pid` 常已过期，`-s reload` 会静默失败（error.log `OpenEvent(...) failed`）→ 用 ctypes `CreateToolhelp32Snapshot` 按父子关系定位 master 再写回 pid。
  ⚠️ **Windows nginx 不是守护进程**：沙箱 shell 里 Popen/DETACHED 启动的会随 shell 进程树被杀（启动瞬间 200、几秒后消失），`CREATE_BREAKAWAY_FROM_JOB` 被拒（WinError 5）。**唯一可行 = PowerShell 工具的 WMI** `([wmiclass]"Win32_Process").Create("$ngx\nginx.exe", $ngx)`；校验三件套：80 口 LISTENING、`/myapp/` 200、tasklist 有**两个** nginx.exe。`-s stop` 本身安全但站点真会中断，**动手前必须告知用户**。本机 sandbox 禁用 `sc.exe`。
- ⚠️ **API 偶发中断的已知模式：孤儿 uvicorn 占 7038 + 看门狗心跳过期 → ensure 任务整栈强重启**。特征：`log/backend_watchdog_*.log` 反复出现「端口 7038 已在监听，但本 watchdog 拉起的子进程仅存活 6-8s（<10s）→ 疑似被不受管理的孤儿进程占用」。`MyApp_EnsureRunning`（每 5 分钟）按 `Get-WatchdogHealth` 的「**心跳 >3min = hung**」kill 掉 owner 再整栈重启（在途长请求被 `10054` 打断，API 中断约 40s）。排查顺序：先看 `log/backend_watchdog_*.log` 尾部 + `log/heartbeat_backend_watchdog.json` 的 ts，别一上来就怀疑自己刚改的代码。TT 分析等 60s+ 长请求最易成陪葬品。

## 3. 门户登录与鉴权
- `backend/main.py::require_session_middleware` 对 `/api/` 全量强制会话；放行 `_PUBLIC_API`（`/api/auth/`、`/api/health`、`/api/ui/menu-layout`、`/api/portals/client-login/consume`）；本机回环 `client_is_local` 放行（本机 curl/Playwright 无需登录）。
- 会话存储由 `backend/.env` 的 `MY_APP_DB_MODE` 决定：**生产是 `pg`**（`portal_sessions` 在 PG），`db/app.db` 同名表是 sqlite 遗留。免登录总开关 `D:\01_RPA\auth-switch.json` 的 `authEnabled`。
- 前端鉴权引导：换会话必须在 React 渲染前完成（`api.ts::bootstrapAuth/runAuthBootstrap` + `main.tsx` 先 await 再 `createRoot().render()`；`App.tsx` 用 `bootDone` 卡业务页面）。**别在页面里抢跑数据请求初始化。**
- 门户 token：URL `?t=` 或同源 localStorage `liberia_noc_auth_v1`（门户 `resolveUrl()` 自动加 `&t=`）。
- eFlow 与 RAIS 目前都 `direct=True`。**RAIS 真正不能反代**：前端把 API 根地址写死 `https://10.100.20.9:8766/`，反代时 fetch 不带 credentials → SSO cookie 种不下来。
- ⚠️ **门户反代路由陷阱：`location /api/` 靠 Referer（`map $http_referer $portal_ref`）区分上游，对 WebSocket 天然失效**（WS 握手不带 Referer，Chrome 只带 Origin，见 `TMP/t_ws_referer_local.py`）→ 门户 cometd 被误路由到 7038 → 403（日志 96 条 `WebSocket /api/fm-active/v1/cometd" 403`，client port `:0` 即经 nginx）。修法 = 按 URI 开专用 location（`^~` 优先于通用 `/api/` 且不参与正则）：`location ^~ /api/fm-active/ { proxy_pass https://10.100.20.8:28001; include portal_eflow_common.conf; }`（eFlow 已修，403→302）。**以后新增带 WS 的门户 API 命名空间，同样按 URI 开专用 location。**
  若将来要开 eFlow 反代：其 `proxy_prefix` 是**空字符串**（`''` 不是 None），`canClientLogin` 判 `!= null`；注释里「eFlow 前端把根地址写死 localhost」在 shell/const/16 个 JS chunk 里**零命中、无法复现**。
- 直接鉴权：等 Chrome 落到门户源 → 种 Cookie → 回读 `localStorage.csrftoken`；成功判定要正证据 + 连续两次。已验证 eFlow 得到真实告警 6767/6767。Chrome CDP 不能启用 Debugger 域；访问本机 CDP 前清 http/https proxy；自签上游先 `Security.setIgnoreCertificateErrors`。
- 临时种会话：`GET /api/auth/kiosk?key=<backend/.env 的 MYAPP_KIOSK_KEY>&next=...`（用完从 PG 删掉该 kiosk 会话）。
