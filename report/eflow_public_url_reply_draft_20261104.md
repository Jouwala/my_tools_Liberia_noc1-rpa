# 给 Orange 的回复草稿与技术要求（eFlow 公网发布）

- **日期**：2026-11-04
- **背景**：Orange 邮件给出 `41.191.105.18:8165`，请我方确认 eFlow 的 URL。
  实测该网关当前指向的是 RAIS 统一权限平台（`/raisprod/*`），eFlow 无任何路由。
- **如意确认（14:24）**：本次要暴露的系统是 **eFlow**，不是 RAIS。
- **结论**：需 Orange 侧把 8165（或另开端口）改为 eFlow 的**根路径反向代理**，
  并补齐必要的头部/Cookie/URL 改写；验证通过前不能回复 "URL confirmed"。
- 配套测试记录：`report/eflow_public_url_probe_20261104.md`。

---

## 一、英文回信（可直接发送，未含内网地址与任何凭据）

> **Subject:** RE: eFlow public IP / URL confirmation
>
> Hi \<Name\>,
>
> Thanks for the clarification — the system to be exposed is **eFlow** (our trouble-ticket / alarm portal), not the RAIS permission platform.
>
> We have checked `41.191.105.18:8165` from our side. The port is reachable over HTTPS, but it currently serves the `/raisprod/*` context (RAIS). All eFlow entry paths, such as `/uportal/framework/default.html` and `/api/oauth2/v1/authorize`, return the gateway's generic 404 page; changing the Host header does not help either. So there is no route to eFlow on this port yet.
>
> To publish eFlow, could you please confirm / arrange the following:
>
> 1. **Entry point.** Should 8165 be dedicated to eFlow (with RAIS moved to another port/address), or will eFlow get a separate public port/IP? Our eFlow portal must be served at the **root path with its native URLs** — it cannot be published under a sub-path prefix such as `/eflow/`. A prefix changes the client-side session keys and causes all post-login API calls to be rejected.
> 2. **Reverse proxy, not plain NAT.** eFlow issues host-bound cookies and embeds absolute internal URLs in its pages, so a simple port-forward will not work. The gateway needs to rewrite cookie domains, redirects and absolute URLs, and strip the upstream HSTS / CSP / frame-related headers. We can share the exact, already-validated nginx rules we use for this.
> 3. **Connectivity.** Please confirm the gateway can reach the eFlow upstream. The RAIS backend on the same internal network responds through this gateway, so the path most likely already exists.
> 4. **Access control & TLS.** We suggest restricting access to the agreed Orange source IPs. Please also confirm whether a trusted TLS certificate will be used on the public side — our upstream certificate is self-signed.
>
> Once the mapping is in place, we will run an end-to-end browser login test from your network and then confirm the final URL.
>
> Best regards,
> Dong

---

## 二、内部技术要求清单（中文，不外发）

### 1. 两条硬约束（来自项目实测）

| 约束 | 原因 | 出处 |
| --- | --- | --- |
| **eFlow 必须根路径直出，禁止子路径前缀**（如 `/eflow/`） | 早期把登录页放在 `/portal/eflow/` 前缀下，门户前端按 URL 上下文拼 localStorage 键名（`/portal/eflow_csrftoken`），登录后主页按无前缀取 token 失败 → 所有接口 403 "cross-site access"。已改回原生路径 | `nginx-1.28.0/conf/nginx.conf:293-295, 302-305` |
| **必须反向代理，不能纯端口转发/NAT** | 上游下发 `domain=10.100.20.8;secure` cookie（域不匹配 + 浏览器丢弃）、页面含 `http://localhost` / 内网绝对 URL、HSTS、CSP/X-Frame-Options、非法 `Content-Encoding: utf-8`、跨站 Referer 校验 | `docs/nginx-reference/portal_eflow_common.conf.txt:15-59` |

### 2. 网关必须具备的改写项（我方可直接提供现成规则）

| 改写 | 作用 | 现成配置 |
| --- | --- | --- |
| `proxy_ssl_verify off` + `proxy_set_header Host 10.100.20.8:28001` | 上游自签证书；Host 保持上游期望值 | `portal_eflow_common.conf.txt:24,27` |
| `proxy_set_header Referer / Origin` | 伪装成上游同源，否则带会话请求被判 403 cross-site | 同上 :34-36 |
| `proxy_cookie_domain 10.100.20.8 $host` + `proxy_cookie_flags ~ nosecure` | Cookie 域改到访问用主机；http 反代时去掉 secure | 同上 :38-39 |
| `proxy_redirect` 改写 `http(s)://10.100.20.8:28001/`、`http(s)://localhost/` → 公网入口 | 防止登录跳转回内网/访问者本机 | 同上 :48-51 |
| `sub_filter` 去掉 `http://localhost` / `127.0.0.1`，`sub_filter_once off` | 页面内绝对 URL | 同上 :54-59 |
| `proxy_hide_header` 摘掉 HSTS / CSP / X-Frame-Options / Content-Encoding | 避免整站强制 https、iframe 限制、浏览器解码失败 | 同上 :40-43 |
| `location` 用原生路径：`/uportal/`、`/iui/`、`/framework/`、`/help/`、`/api/oauth2/` | 与上一条硬约束一致 | `nginx.conf:291,298-300,306` |

> 我方 `192.168.100.20` 的 nginx 已在 80/443 上跑通这套 eFlow 反代（`nginx.conf:291-310`），
> 配置经过生产验证。可优先让 Orange 把流量原样转给我方 nginx，避免对方从零实现改写；
> 前提是确认 Orange 网关到我方 nginx 的网络可达，以及新 Host 下
> `$portal_origin_rewritten` 等变量取值正确。

### 3. 网络与证书前提

- Orange 网关需能到达 eFlow 上游或我方 nginx。RAIS 后端（`10.100.20.x` 同网段）通过
  8165 能正常应答，说明该网段路径大概率已存在，但需对方正式确认。
- 公网侧建议受信任证书；上游自签由反代侧 `proxy_ssl_verify off` 处理。
- 建议源 IP 白名单（仅 Orange 约定网段），公网暴露网管系统不做全开放。
- 对外邮件/配置交付**不写内网 IP、账号、口令、Token**；上游地址由双方网络团队线下对齐。

### 4. 端到端验收清单（全部通过才发最终确认）

1. `https://<公网入口>/uportal/framework/default.html` 返回 **200** 且正文是 eFlow 门户 HTML
   （含 `app-root` / `ptl-page-loading`），不再是 979B 静态 404 页；
2. 浏览器打开入口能看到登录页，且**没有**证书告警阻断 / 混合内容报错；
3. 用真实账号登录成功并跳到主页，Cookie 域正确、刷新不掉会话；
4. 打开工单/告警等子页面无 **403 cross-site access**、无接口打到 `localhost` 或内网地址；
5. 从 **Orange 网络**（而非我方内网）复测 1–4，并确认源 IP 白名单生效。

---

## 三、方案选择（待 Orange 回复第 1 点后定）

| 方案 | 做法 | 代价 / 风险 |
| --- | --- | --- |
| **A（推荐，若 8165 专用于本次）** | Orange 把 8165 的默认站点/根路径改为 eFlow 反代，RAIS 迁到其他端口或地址 | URL 最干净、避开前缀坑；需确认 RAIS 是否仍需公网入口 |
| **B（若 RAIS 继续占用 8165）** | 给 eFlow 另分配一个公网端口/IP，根路径直出 | 不影响 RAIS；需对方新开端口 + 防火墙策略 |
| **C（不推荐）** | 同端口用 `/eflow/` 子路径区分 | 触发 localStorage 键名问题，登录后全接口 403；除非做完整 URL 重写透传，否则不可用 |
| **D（不可用）** | 纯 NAT 8165 → eFlow 上游端口 | Cookie / 绝对 URL / HSTS / 跨站校验任一都会让登录链路断开 |

**本次未改动任何生产配置、未代发邮件**，仅提供草稿与技术清单。

---

## 四、14:44 补充：防火墙 VIP 截图实证与回信更新

如意贴出 Orange 防火墙 VIP 配置（组 `ZTE-Eflow` / 成员 `MS-eflow-ZTE`）：

| 字段 | 值 |
| --- | --- |
| External IP / External Service Port | `41.191.105.18` / `TCP 8165` |
| **Mapped IP / Map to Port** | **`10.100.20.9` / `8765`** |
| Members | `MS-eflow-ZTE`、`MS-eflow-ZTE-BACKUP`（主备，**两个都要改**） |
| References | `1`（被 1 条防火墙策略引用，改 VIP 后确认策略仍放行 TCP 8165） |

实测闭环：公网 8165 与内网 `10.100.20.9:8765` 响应头逐字一致，
`POST /raisprod/platform-service/web/config/getAesConfig` 返回的 RSA-1024 公钥字符串完全相同
→ 该 VIP 是**纯四层 DNAT**，不存在七层 location 分流。详见测试记录第九节。

**最终根因**：VIP 映射目标写成 RAIS 服务器 `10.100.20.9:8765`，而 eFlow 在
`10.100.20.8:28001`。名字叫 eflow、目标不是 eflow，应为配置时沿用旧地址或混淆了两台服务器。

### 更新版英文回信（替代第一节）

> **Subject:** RE: eFlow public IP / URL mapping correction
>
> Hi \<Name\>,
>
> We have identified the cause. On the VIP `MS-eflow-ZTE` (group `ZTE-Eflow`), the mapping is currently:
>
> - External: `41.191.105.18 : TCP 8165`
> - Mapped to: `10.100.20.9 : TCP 8765`
>
> We verified from our side that `10.100.20.9:8765` is the RAIS / UAC-Lite platform — its `/raisprod/*` API returns the same RSA key as the public address, and the response headers match exactly. eFlow runs on a different server and port, which is why all eFlow paths return that server's 404 page.
>
> Could you please:
>
> 1. Correct the Mapped IP / Map to Port on **both** VIP members (`MS-eflow-ZTE` and `MS-eflow-ZTE-BACKUP`), so a failover does not restore the wrong target;
> 2. Confirm the firewall policy referencing this VIP (References: 1) still permits TCP 8165;
> 3. Confirm the intended mapped destination with our network team — eFlow needs a reverse proxy with cookie / URL rewriting rather than a plain port-forward. We can provide the validated nginx rules and the exact upstream address separately.
>
> Once the mapping is updated, we will run an end-to-end browser login test and confirm the final URL.
>
> Best regards,
> Dong

### 方案（选一个再把目标值填进第 3 点）

| 方案 | VIP 的 Mapped IP / Port 改为 | 评价 |
| --- | --- | --- |
| A 快速验证 | `10.100.20.8 : 28001`（eFlow 上游） | 改动最小、能立刻看到登录页；但纯 NAT 下上游 `Set-Cookie domain=10.100.20.8;secure` 会被浏览器按 `41.191.105.18` 判为域不匹配而丢弃，页面内 `http://localhost` 绝对 URL 会打到访问者本机 → 登录态/资源大概率坏，**不能当成完成** |
| **B 推荐** | 我方 nginx 反代入口（`192.168.100.20` 的专用端口） | 复用 `nginx.conf:291-310` + `portal_eflow_common.conf` 已验证的改写规则，一次到位；前提是 Orange 防火墙能路由到 `192.168.100.x`，且需核对新 Host 下 `$portal_origin_rewritten` 取值 |
| C | 由 Orange 侧做七层反代改写 | 对方实现成本高、易漏项，不推荐 |
