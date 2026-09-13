# my_app 项目长期笔记

## 1. 环境与部署
- 生产机为 192.168.100.20，本地工作区 `D:\01_RPA\Task\my_app`；nginx 实际配置：`D:\01_RPA\nginx-1.28.0\nginx-1.28.0\conf\nginx.conf`。
- 前端构建产物必须输出到 `D:\01_RPA\Task\_fe_dist`，nginx `/myapp/` 直接静态托管；使用托管 Node 的 Vite build，避免 `npm run build` 先跑 tsc。
- API 后端 7038；FineBI 专用 API 7138；前端默认 API base `/api`。
- 映射盘：`Y:`/`/y` 对应共享盘根，生产目录通常是 `/y/01_RPA`；远程改文件不等于能 reload 生产 nginx。
- 内网请求绕过代理：curl 用 `--noproxy '*'`，Python httpx 用 `trust_env=False`。

## 2. nginx 与 502
- `/myapp/` 直接 alias `_fe_dist`，避免 vite preview 7090 重启空窗造成 502。
- `/api/` 兜底到 7038；`/api/dashboards`、`/api/data/sources`、`/api/finebi/` 到 7138。
- nginx 配置曾关闭 access/error 日志，排查 502 不能只依赖日志。
- 修改 nginx 后需在生产机执行 nginx reload；修改后端路由/服务需重启 7038。

## 3. 门户登录
- `frontend/src/pages/PortalLogin.tsx` + `backend/services/portal_login_service.py` 实现 client/server 双模式。
- eFlow 与 RAIS 是 `direct=True` 门户：不能走 nginx 反代。反代实测会出现告警 0/0、`Failed to Query Active Alarm Columns and Default Templates`，根因包含 cometd WebSocket 403。
- 本机访问者通过 `/api/portals` 的 `client_is_local` 自动走服务器桌面直接鉴权；远程访问者当前 client 模式只能直开门户手工登录，server 模式可在服务器桌面一键登录。
- eFlow 直接鉴权：先等待 Chrome 页面落到门户源，再种 Cookie，并回读校验 `localStorage.csrftoken`；成功判定需正证据和连续两次，不能只看 URL/非空正文。
- Chrome CDP 不能启用 Debugger 域；访问本机 CDP 前清除 http/https proxy；自签上游先 `Security.setIgnoreCertificateErrors`。
- 已验证本机 eFlow 直接登录能得到真实告警（6767/6767）；RAIS 直接鉴权回归通过。

## 4. 当前未决问题
- 远程电脑访问 `http://192.168.100.20/myapp/?page=portalLogin`，点击 eFlow 显示 `Page opened; please complete login manually`；UME 反代登录正常。
- 反代 eFlow 诊断：HTTP 失败请求 0，但 `/api/fm-active/v1/cometd` WebSocket 握手连续 403，`/meta/connect` 返回 `402::session_unknown`，页面告警 0/0。当前优先评估是否能安全修复 ws；若不能，必须保持 eFlow 不反代并给远程用户准确提示。
- 诊断脚本在 `TMP/t_proxy_diag*.py`，临时 Chrome profile 可能位于 TMP；不得删除 `.workbuddy-ai`。

## 5. 验证约定
- 用系统 Python312 做 FastAPI TestClient（不加载 main）；新端点可检查 `/openapi.json` 标记。
- 前端真实点击验证需用 CDP `Input.dispatchMouseEvent`，纯 JS click 可能被浏览器拦截。
- 同一消息对同一文件的多个 Edit 必须串行。