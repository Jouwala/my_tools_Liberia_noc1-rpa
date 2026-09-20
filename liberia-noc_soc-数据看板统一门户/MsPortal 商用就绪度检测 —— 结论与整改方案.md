# MsPortal 商用就绪度检测 —— 结论与整改方案

## Context

用户要求对 `http://localhost/MsPortal/` 做功能、bug、易用性、性能四方面检测，判断能否商用。
判定口径已确认：**交付利比里亚客户（OLR / NOC 本地值班工程师）正式使用** —— 最严档。

本轮为纯只读检测（浏览器结构快照 + 页面内脚本度量 + HTTP 实测 + 源码审读），未改动任何文件。

**结论：按现状不能商用交付。** 功能层完成度其实很高（13 个区块、51 个看板目录、搜索、QC 下钻导出、中英切换、主题、用户管理全部可用且控制台零报错），但有 **6 项上线阻塞**必须先清 —— 最严重的一条是**不登录就能从局域网读到凭据库**（`http://192.168.100.20:7090/api/credentials` → 200 / 5,494 字节），其次是"生产环境跑在 Vite dev server 上"。

> 用户已明确要求：**「回环地址即管理员」这条设计保留**，不改。本方案不动它，只堵"让远程请求伪装成回环"的代理入口（见 B4）与它依赖的两个前提（见「设计保留项」）。

---

## 一、实测通过的部分（不用重做）

| 项 | 实测数据 |
|---|---|
| 首屏速度 | DOMContentLoaded **267ms** / load **844ms** |
| 控制台 | **0 条报错** |
| 全局搜索 | 输 `battery` → 命中 2 条；乱码 → 0 条；清空 → 恢复 33 条卡片，均正确 |
| QC 六卡片 + 达标率 | 全部走 `/api/portal-qc/summary` 真实数据，无写死值 |
| QC 下钻明细 | 点 Alarm 卡片 → `#qcMask` 展开、`/api/portal-qc/detail?metric=alarm` 返回表格、带刷新 / 导出 CSV / **300ms 防抖** / Esc 关闭 |
| 区块布局 | 13 个 region 渲染正常，BO 子分组折叠 + "展开全部 +10" 可用 |
| 中/EN、深浅主题、用户管理弹窗、退出登录 | 均能触发 |
| 局部 a11y | 4 个 iframe **全部有 title**、图片**全部有 alt**、33 处 aria-label、1151px 宽**无横向溢出** |
| 凭据面 | `/uniplam/api/auth/users` 未登录 → 401；`auth-data/portal-auth.db`、`portal-default.json`、`server/auth.ts` 走 HTTP 探测均 404，**凭据文件未暴露在网络面上** |

> 两处自我更正（不计入缺陷）：① 我一度判定 QC 卡片点击无反应，复查是 `position:fixed` 导致 `offsetParent` 为 null 的可见性误判，功能正常；② 一度判定 `/api/portal-qc/summary` 有请求风暴，干净 20s 采样下未复现（只在工具反复激活标签页的窗口里出现），非缺陷。

---

## 二、P0：上线阻塞（6 项，商用前必修）

### B1 生产环境跑在 Vite dev server 上
`/uniplam/` 实测响应含 `@vite/client` + `react-refresh` —— 而**登录、用户管理、目录读写鉴权全在这个 dev server 的中间件里**。
- `vite.config.ts:93-105`（`portal-default` 中间件）、`:111-125`（POST 侧）
- `package.json:8` 的 `dev` 脚本；`start_hidden.ps1:159` 实际就是 `npm run dev`
- 另有第二个 vite 进程同时占着 9267（双监听，无单实例锁）

风险：无压缩 / 无 tree-shake、HMR 端点对外开着、源码映射可读、dev server 非为并发设计、崩溃即全站掉登录。

### B2 全站无 TLS
`https://localhost/` 与 `:8443` 实测连接直接失败（只有 80 和 8081-8088 明文）。登录口令与 Bearer token 明文穿越客户机房网络。

### B3 匿名接口泄漏完整目录
`GET /uniplam/api/portal-default` **在任何 token 校验之前就 `readFileSync` 返回**（`vite.config.ts:93-105`）。
实测从局域网地址 `192.168.100.20` **零凭据** → 200 / 47,696 字节，内容含：
- **51 处内网 IP**：`192.168.100.20`×33、`.19`×17、`.27:3000`×1
- **30 条带同一枚 64 位十六进制 token 的看板 URL**（`?t=b8120a42…4bf072d5`，见 `assets/data.js:212` 等）

实测该 token 已换不到 API 访问（带它作 Bearer 打 `/api/tasks` 仍 401），所以当前定级是"信息泄漏 + 历史鉴权旁路面"，不是已可利用的越权 —— 但它同时出现在 iframe src、地址栏、浏览历史和 Referer 里，必须整体清除。

### B4 【最严重】7090 端口 = 一个匿名管理员出口，凭据库可直接读走
`vite preview` 起的 my_app 实例绑在 **`0.0.0.0:7090`**（`netstat` 实测），它自带一条到后端的代理，**而这一跳的对端地址是 `127.0.0.1`** —— 于是后端的"回环即管理员"信任被远程客户端复用了。实测（均零凭据、从 LAN 地址）：

| `http://192.168.100.20:7090/...` | 结果 |
|---|---|
| `/api/credentials` | **200 / 5,494 字节 JSON，凭据记录列表**（`zte_ume` 等条目键名与名称） |
| `/api/portal-catalog` | 200 / 40,747 字节，完整真实目录 |
| `/api/tasks` | 200 / 77,179 字节，34 个自动化任务全貌（含 cron 与数据源） |
| `/api/auth/me` | 200 → `{"user":{"username":"local","role":"admin"}}` **直接坐实管理员身份** |

对照组（说明这确实是 7090 独有的洞，不是全局失效）：
- `192.168.100.20:7038/api/portal-catalog` → **401** `{"detail":"未登录：请通过统一门户登录"}`
- `192.168.100.20:9267/api/credentials` → **401**；`:9268/api/credentials` → **401**
- 走 nginx 的 `http://192.168.100.20/myapp/api/credentials` → 200 但是 **1,745 字节 `text/html`**（SPA 兜底页，不是数据）；`/uniplam/../api/…` 同样是 HTML 兜底 —— 端口 80 这条路是干净的。

修复**不需要动回环授权**：把 preview 绑到 `127.0.0.1`（或商用实例干脆不跑 `vite preview`，改由 nginx 直出静态产物）即可闭合。

### 设计保留项：回环即管理员（按用户要求保留）
`backend/services/portal_auth.py:397-407` + `security.py:17-23`。本轮实测确认**这条信任本身是可靠的**：

| 伪装尝试（打 `192.168.100.20/api/portal-catalog`） | 结果 |
|---|---|
| 无头基线 | 401 |
| `X-Forwarded-For: 127.0.0.1` | 401 |
| `X-Forwarded-For: localhost` | 401 |
| `X-Real-IP: 127.0.0.1` | 401 |
| `X-Forwarded-For: 127.0.0.1, 192.168.100.20` | 401 |
| XFF + X-Real-IP 组合 | 401 |

即它判的是**真实 socket 对端**，不是客户端可自填的头 —— 设计成立。但要写进文档并加监控的**两个依赖前提**：
1. `7038` 必须只接受"对端确为本机"的连接。当前 `0.0.0.0:7038` 对外开着，任何新增的本机反向代理 / preview / SSRF 面（B4 就是实例）都会立刻变成远程管理员。建议 `--host 127.0.0.1` 收紧，或至少在 nginx 侧禁掉一切会把外部请求转成回环对端的 `/api` 代理前缀。
2. 计划任务、WhatsApp 服务等本机调用方依赖此信任 —— 保留后要在 `AGENTS.md`/部署文档里写明"不得为本机 API 新增任何对外监听的反代入口"。

### B5 备份文件全部可被公网下载
nginx `location /MsPortal/ { alias …/MsPortal/; }` 直出目录，无扩展名白名单。实测 200 可取：
- `assets/portal.js.fixed` → 240,919 字节
- `assets/portal_bak_20260917_direct_login.js` → 135,804 字节
- `index_bak_20260917_direct_login.html` → 19,579 字节
- `tailwind.config.v3.js.archived` → 936 字节

规模：**MsPortal 下 71 个备份文件，仓库 166 个跟踪文件里 54 个是备份/归档**；`data.js_bak_*` 里同样带着 B3 那枚 token。另有两个设计说明 `.md`（21KB / 28KB）直接躺在发布目录内，含内网主机名与负责人信息。

### B6 `/api/tasks` 轮询风暴
`Central Liberia Regional Topology` 里嵌的 MW 实时看板子帧（`/myapp/mw_real_time.html`）：
- 单次页面停留 10 分钟内发出 **212 次** `GET /api/tasks`，最近 60s 内 22 次 ≈ **每 2.7 秒一次**
- 单次响应 **77,035 字节**，服务端耗时 **160–320ms**
- 累计传输 **16.3 MB / 10 分钟** ≈ **单标签页 100 MB/小时**

顶部拓扑区还是 **3 层嵌套同源 iframe**，多开几个大屏就是倍数放大。会话侧同时是**进程内存态**（`server/auth.ts:99,449-472`，12h 滑动），服务一重启全员掉线。

---

## 三、P1：商用体验缺口（面向本地工程师）

| # | 问题 | 证据 |
|---|---|---|
| U1 | **缓存策略反了**：静态资源 `Cache-Control: no-cache, no-store, must-revalidate`（nginx conf:314），每次进页面全量重下 **840KB / 51 个请求**；`mw_real_time.html?_=<epoch>` 又额外做了 cache-busting | 实测响应头 + `performance` 计数 |
| U2 | **EN 翻译不完整**：切 EN 后仍有 **11 个中文节点可见**（"本机"、"本机站点"、"筛选当前视图看板"、"完整目录"、"Source: 升级机制.xlsx"、"3 / 5 项"…），且 **51 条看板描述只有中文一种**（`data.js` 仅 19 个 `"en"` 键，全是分组名）。对利比里亚值班工程师是直接用不了 | 页面内枚举 |
| U3 | **搜索无空状态**：0 命中时 13 个区块壳子全部留在屏幕上、也没有"未找到"提示，用户看到的是"页面坏了" | 实测：垃圾词 → 可见卡片 0、可见 section 仍 13 |
| U4 | **主搜索无防抖**：每敲一次全量 `render()`，6 键 177ms ≈ 30ms/键。本机快，远程低配机会明显卡。（同文件 QC 弹窗搜索有 300ms 防抖 —— `portal.js:5645`，说明只是主搜索漏了，`portal.js:5205`） | 实测计时 |
| U5 | **a11y 缺口**：无 skip link；6 个模态框均无焦点陷阱；`portal.js:4352` 注入的字号按钮缺 `aria-label` 且 `data-i18n-title` 根本没被翻译器应用（只处理 `data-i18n`/`data-i18n-attr`，`portal.js:4623`） | 实测 + 源码 |
| U6 | **运维不成立**：保活是 5 分钟一次的计划任务且**只在交互登录用户下跑**（`install_ensure_task.bat:14,31`），注销即停；nginx 从 SMB 共享 `Y:` 运行；nginx 访问日志因一次 470MB 事件被整体关掉（conf:10-13），出事无法回溯 | 源码 + 进程实测 |
| U7 | **管理员初始密码 seed 时 `print` 到控制台并落进日志**（`server/auth.ts:210-222` → `log/portal_dev.log`）；`auth-switch.json` 可全局关掉鉴权（当前 `authEnabled:true`，但错误日志显示被反复切过）；`DEV_TOKEN='dev-bypass'`（`auth.ts:191`） | 源码 + 日志 |

---

## 四、P2：代码健康（不阻塞上线，但决定能不能长期维护）

- `assets/portal.js` 单文件 **311KB / 5,908 行未压缩**、`portal.css` 98KB、`data.js` 74KB
- 34 处 `innerHTML` 字符串拼接；`esc()` 用得很一致，**但** `portal.js:1661` 与 `:5062` 的 `data-no="' + item.no` 未转义 —— 目录是服务端可写的（`PUT /api/portal-catalog`），存在属性断裂注入面
- 无 CSP、无任何安全响应头；目录 PUT 是**整份替换 + Cookie 鉴权 + 无 CSRF token**（`portal.js:1187`）
- `data.js` 头部注释写着"不要手工编辑"，却就是实际发布物；目录真源有三份并存（服务端 `portal-catalog` 35KB + `/uniplam/api/portal-default` 47KB + 本地 `data.js` 74KB）
- 仓库卫生：`TMP/` 下几十个一次性探针（含 Chrome profile、截图）、`ref.html` 60KB、`enterprise-bi-dashboards-*.json`×2、根目录多份同名 xlsx

---

## 五、整改方案

### 交付物 1（本轮唯一确定要做的）：检测报告文件
新增 `MsPortal_商用就绪检测报告_20260920.md`，落在仓库根目录，内容 = 上面二~四节的分级问题清单 + 每条的实测证据（URL / 状态码 / 字节数 / `file:line`）+ 判定结论。给客户方和内部评审直接看，可当验收单。

### 交付物 2：P0 修复（建议紧随其后的单独排期）
按依赖顺序：

1. **闭合 B4（最高优先，且不需要改回环授权）**：`vite preview` 绑定改 `--host 127.0.0.1`，或商用实例直接停掉 preview、由 nginx 静态直出；`uvicorn` 同步收为 `--host 127.0.0.1`；上线清单里加一条"对外监听端口不得存在任何把外部请求转成回环对端的 `/api` 代理"。
2. **切生产构建**：`vite.config.ts` 的鉴权中间件从 dev server 迁到独立 Express/`server.js`，`npm start` 跑构建产物；补单实例锁，杀掉 9267 双监听；`start_hidden.ps1:159` 的 `npm run dev` 改掉。
3. **加 TLS**：nginx 443 + 自签或企业内 CA，80 端口 301 跳 https。
4. **堵 B3**：`vite.config.ts:93-105` 的 `portal-default` GET 挪到鉴权之后；从 `data.js` 与 `portal-default.json` 里**移除全部 30 处 `&t=` token** 并作废该 token。
5. **清 B5**：nginx 加 `location ~* _bak_|\.archived$|\.fixed$ { deny all; }` 或把备份移出 Web 根；仓库侧 71 个 `MsPortal/*_bak_*` 与根目录归档件迁出/删除，`.gitignore` 补规则；两个设计说明 `.md` 移出发布目录。
6. **降 B6**：`/api/tasks` 改增量 / `If-None-Match`，或前端退到 ≥30s 且只在可见时轮询；会话改落盘（SQLite/文件），使重启不掉登录线。
7. **文档化保留项**：把"回环即管理员"及其两个依赖前提写进部署文档与 `AGENTS.md`，并给 `/api/credentials`、`/api/portal-catalog` 的回环命中加一条异常来源告警。

### 交付物 3：P1 修复（客户验收前）
- 缓存倒置纠正：HTML `no-cache`，带指纹的 JS/CSS `max-age=31536000, immutable`；去掉 `?_=<epoch>` cache-busting
- 补齐 EN 文案：11 个漏网节点 + 51 条看板描述的双语字段（`data.js` 结构要扩，同步 `viewer.js`）
- 主搜索加 300ms 防抖（复用 `portal.js:5645` 那套 `qcTimer` 写法）+ 加"未找到"空状态与零命中时隐藏空区块
- 模态框焦点陷阱、skip link、字号按钮补 `aria-label`，并让翻译器支持 `data-i18n-title`
- 保活改 Windows 服务（NSSM）+ 计划任务改"不论用户是否登录"；nginx 移回本地盘；访问日志按大小轮转重新打开
- 初始密码不再 `print`，`log/portal_dev.log` 里的历史值要清并轮换

### 交付物 4：P2（可延后）
`portal.js` 按 区块渲染 / 目录同步 / 鉴权 / 弹窗 / 拖拽 拆模块；`data-no` 两处补 `esc()`；加 CSP 与 CSRF token；目录三源合一。

---

## 六、验证方式（整改后逐项复测）

安全（对照本轮实测基线，全部用同一条 curl 命令复跑）：
```
# ① B4 闭合 —— 期望全部从 200 → 连接失败/401；/api/credentials 是最硬的一条
curl -s -m 5 -o /dev/null -w "7090_creds=%{http_code} "    http://192.168.100.20:7090/api/credentials      # 基线 200/5494B，期望 000 或 401
curl -s -m 5 -o /dev/null -w "7090_catalog=%{http_code} "  http://192.168.100.20:7090/api/portal-catalog   # 基线 200/40747B
curl -s -m 5 -o /dev/null -w "7090_whoami=%{http_code}\n"  http://192.168.100.20:7090/api/auth/me          # 基线 200/role=admin
# ② 监听面收紧：期望只剩 127.0.0.1
netstat -ano | grep -E "TCP.*:(7038|7090|9267|9268)\b.*LISTEN"   # 基线：全部 0.0.0.0，且 9268 双进程
# ③ B3 堵住：期望 200 → 401
curl -s -o /dev/null -w "portal-default=%{http_code} " http://192.168.100.20/uniplam/api/portal-default   # 基线 200/47696B
curl -s http://192.168.100.20/uniplam/api/portal-default | grep -c "&t="                                   # 期望 0（基线 30）
# ④ B5 关闭：期望四条全部 403/404
curl -s -o /dev/null -w "%{http_code} " http://localhost/MsPortal/assets/portal.js.fixed
curl -s -o /dev/null -w "%{http_code} " http://localhost/MsPortal/index_bak_20260917_direct_login.html
# ⑤ dev 标记消失 + TLS 生效
curl -s http://localhost/uniplam/ | grep -c "@vite/client\|react-refresh"   # 基线 2，期望 0
curl -s -o /dev/null -w "https=%{http_code}\n" -k https://localhost/MsPortal/
curl -s -o /dev/null -w "redirect=%{redirect_url}\n" http://localhost/MsPortal/
```
**回环授权保留的正反两条断言（必须同时成立）**：
- 正向：`curl -s -o /dev/null -w "%{http_code}" http://localhost/api/portal-catalog` → **仍为 200**（改了就是回归，本机计划任务会挂）。
- 反向：上面 ① 与 ③ 全部非 200；并补测 `curl -H "X-Forwarded-For: 127.0.0.1" http://192.168.100.20/api/portal-catalog` → **仍 401**（本轮实测已 401，防止后续改动把 XFF 变成信任依据）。
性能：`document.querySelectorAll('iframe')` 逐帧读 `performance.getEntriesByType('resource')`，MW 帧的 `/api/tasks` 频率从 22 次/分钟降到 ≤2 次/分钟；单页 `transferSize` 总量（本轮 840KB）在二次访问时应 <50KB（缓存命中）。

功能回归（浏览器实测，与本轮同一套断言）：搜索 `battery` → 2 卡片、乱码词 → 出现"未找到"提示且空区块隐藏、清空 → 33 卡片；QC Alarm 卡片 → `#qcMask.hidden===false` 且表格有行、导出 CSV 落地；EN 模式下重新枚举中文叶子节点，期望从 11 → 0；深浅主题与拖拽排序后刷新页面保持；重启后端后用同一账号免重登（会话落盘验证）。

运维：注销交互用户后 `curl http://localhost/MsPortal/` 仍 200；`log/` 下访问日志按 50MB 轮转；`grep -i password log/portal_dev.log` 无明文口令。