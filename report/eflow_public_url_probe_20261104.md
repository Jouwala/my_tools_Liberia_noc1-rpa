# eFlow 公网入口连通性测试记录（41.191.105.18:8165）

- **日期**：2026-11-04 14:01–14:09 GMT
- **目的**：核实 Orange 团队邮件中「分配给 eFlow 的公网 IP `41.191.105.18:8165`」对应的 URL 是否可用
- **测试机**：192.168.100.20（Windows）。T1–T5 用 Git Bash `curl`；对照组为如意本机 `curl.exe 8.21.0 / schannel`
- **通用参数**：`-k`（忽略自签证书）、`--connect-timeout 4~6`、`--max-time 6~10`
- **代理说明**：环境存在 `HTTP_PROXY / HTTPS_PROXY = http://127.0.0.1:59925`。走代理时 HTTPS 响应前会先出现一行 `HTTP/1.1 200 Connection Established`（代理的 CONNECT 隧道），**该行不是服务端响应**。所有结论性测试均加 `--noproxy '*'` 直连复核，结果与走代理一致。
- **脱敏**：环境变量中的内部配置项已省略；RAIS 返回的 RSA 公钥只保留首尾片段；全文不含任何账号、口令、Token。

---

## 一、对照组：如意本机 curl.exe（14:06–14:09）

| # | 命令 | 结果 |
| --- | --- | --- |
| C1 | `curl.exe -vk https://10.100.20.8:28001/uportal/framework/default.html` | **200 OK**，2735 B，eFlow Angular 门户 HTML |
| C2 | `curl.exe -vk https://41.191.105.18:8165/raisprod` | **404**，979 B 通用静态 404 页 |
| C3 | `curl.exe -vk https://41.191.105.18:8165/` | **404**，同 C2 页面 |

C1 关键响应头（eFlow 应用直出指纹）：

```
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
Content-Length: 2735
Cache-Control: no-cache, no-store
X-Frame-Options: sameorigin
Content-Security-Policy: frame-ancestors 'self'
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

正文特征：`<div id="ptl-page-loading">`、`<app-root></app-root>`、`iui/component/...`、
`assets/js/const.js?2606051048`、Angular `chunk-*.js` / `main-JJEWYRDF.js`。**无 `Server: nginx` 头。**

C2/C3 关键响应头（公网网关指纹，与 C1 明显不同）：

```
HTTP/1.1 404 Not Found
Server: nginx
Content-Type: text/html; charset=utf-8,gbk
Transfer-Encoding: chunked
X-Frame-Options: SAMEORIGIN
X-XSS-Protection: 1;mode=block
Strict-Transport-Security: max-age=31536000;includeSubDomains
```

404 正文标题 `404 - Page Not Found`，且含 **`<a href="/raisprod">home</a>`**
—— 网关预设的应用根路径是 `/raisprod`，这是整轮排查的转折点。

---

## 二、T1 基础连通性与协议判定（14:01）

```bash
curl -k -sS -D - -o /dev/null --connect-timeout 5 --max-time 8 http://41.191.105.18:8165/
curl -k -sS -D - -o /dev/null --connect-timeout 5 --max-time 8 https://41.191.105.18:8165/
```

| 请求 | 结果 |
| --- | --- |
| 明文 HTTP | **400 Bad Request**，`Server: nginx` |
| HTTPS | `HTTP/1.1 200 Connection Established`（代理隧道）→ **404 Not Found**，`Server: nginx` |

**判读**：TCP 可达、TLS 握手成功；明文 HTTP 被拒（典型的「明文请求发到 HTTPS 端口」），
故该端口**必须用 `https://`**。根路径返回 404。

---

## 三、T2 排除代理 + 已知 eFlow 路径（14:01）

```bash
env | grep -i proxy                       # 确认代理存在，内部配置项已省略
curl -k -sS --noproxy '*' -D - -o /dev/null --connect-timeout 4 --max-time 6 https://41.191.105.18:8165/
curl -k -sS -D - -o /dev/null --connect-timeout 6 --max-time 10 \
  "https://41.191.105.18:8165/uportal/framework/default.html"
curl -k -sS -D - -o /dev/null --connect-timeout 6 --max-time 10 \
  "https://41.191.105.18:8165/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html"
```

| 路径 | 结果 |
| --- | --- |
| `/`（直连，无代理） | 404，响应头与走代理完全一致 → **404 来自目标服务器，不是代理** |
| `/uportal/framework/default.html`（eFlow 门户首页） | 404 |
| `/api/oauth2/v1/authorize?...`（eFlow OAuth2 入口） | 404 |

---

## 四、T3 404 页内容与 Host 头变体（14:01）

```bash
curl -k -sS --noproxy '*' https://41.191.105.18:8165/ | head -20
curl -k -sS --noproxy '*' -H 'Host: 10.100.20.8:28001' -D - -o /dev/null \
  https://41.191.105.18:8165/uportal/framework/default.html
curl -k -sS --noproxy '*' -D - -o /dev/null https://41.191.105.18:8165/iui/
curl -k -sS --noproxy '*' -D - -o /dev/null https://41.191.105.18:8165/uportal/
```

404 正文片段：

```html
<title>404 - Page Not Found</title>
<h1>404 - Page Not Found</h1>
<p>The page you are looking for might have been removed or is temporarily unavailable.</p>
<p>Go back to <a href="/raisprod">home</a>.</p>
```

| 变体 | 结果 |
| --- | --- |
| `Host: 10.100.20.8:28001` + eFlow 首页 | 404 |
| `/iui/` | 404 |
| `/uportal/` | 404 |

**判读**：换 Host 无效，排除虚拟主机 / SNI 匹配问题；404 是 nginx 自定义静态错误页（非 eFlow 应用应答）。

---

## 五、T4 `/raisprod` 前缀路径枚举（14:08）

```bash
for p in "/raisprod" "/raisprod/" "/raisprod/index.html" "/raisprod/login" \
         "/raisprod/uportal/framework/default.html" "/zzz-nonexistent-8472"; do
  curl -k -sS --noproxy '*' -o /dev/null \
    -w "%{http_code} size=%{size_download} redirect=%{redirect_url}" \
    --connect-timeout 4 --max-time 8 "https://41.191.105.18:8165$p"
done

for h in "41.191.105.18:8165" "10.100.20.8:28001" "raisprod"; do
  curl -k -sS --noproxy '*' -H "Host: $h" -o /dev/null -w "%{http_code}" \
    --connect-timeout 4 --max-time 8 "https://41.191.105.18:8165/raisprod/"
done
```

| 路径 | 状态码 | 大小 | 跳转 |
| --- | --- | --- | --- |
| `/raisprod` | 404 | 979 B | 无 |
| `/raisprod/` | 404 | 979 B | 无 |
| `/raisprod/index.html` | 404 | 979 B | 无 |
| `/raisprod/login` | 404 | 979 B | 无 |
| `/raisprod/uportal/framework/default.html` | 404 | 979 B | 无 |
| `/zzz-nonexistent-8472`（随机对照） | 404 | 979 B | 无 |
| `Host=41.191.105.18:8165` / `10.100.20.8:28001` / `raisprod` | 404 / 404 / 404 | — | — |

---

## 六、T5 RAIS 路径与决定性 API 验证（14:08）

```bash
# 6.1 RAIS 已知路径
for p in "/raisprod/uacliteweb" "/raisprod/uacliteweb/" \
         "/raisprod/uacliteweb/#/login" \
         "/raisprod/platform-service/web/config/getAesConfig" \
         "/raisprod/uaclite/web/api/captcha/generate"; do
  curl -k -sS --noproxy '*' -o /dev/null \
    -w "%{http_code} size=%{size_download} ctype=%{content_type}" \
    --connect-timeout 4 --max-time 8 "https://41.191.105.18:8165$p"
done

# 6.2 GET 取 body
curl -k -sS --noproxy '*' \
  "https://41.191.105.18:8165/raisprod/platform-service/web/config/getAesConfig"

# 6.3 POST（按 RAIS 接口约定，带同源 Referer）
curl -k -sS --noproxy '*' -X POST \
  -H 'Content-Type: application/json' \
  -H 'Referer: https://41.191.105.18:8165/raisprod/uacliteweb/' \
  -d '{}' -D - --connect-timeout 4 --max-time 8 \
  "https://41.191.105.18:8165/raisprod/platform-service/web/config/getAesConfig"

# 6.4 SPA 入口带同源 Referer
curl -k -sS --noproxy '*' \
  -H 'Referer: https://41.191.105.18:8165/raisprod/uacliteweb/' \
  -D - -o /dev/null --connect-timeout 4 --max-time 8 \
  "https://41.191.105.18:8165/raisprod/uacliteweb/"
```

**6.1 结果**：

| 路径 | 状态码 | 大小 | Content-Type |
| --- | --- | --- | --- |
| `/raisprod/uacliteweb` | 404 | 0 | — |
| `/raisprod/uacliteweb/` | 404 | 0 | — |
| `/raisprod/uacliteweb/#/login` | 404 | 0 | — |
| `/raisprod/platform-service/web/config/getAesConfig` | **500** | 68 B | `application/json` |
| `/raisprod/uaclite/web/api/captcha/generate` | **500** | 68 B | `application/json` |

与 T4 的 979 B 静态 404 不同 → 说明 `/raisprod/` 下的这些路径**已被转发到上游应用**，
只是 GET 方法/参数不对。

**6.2 GET body**：

```json
{"code":{"code":"0001","msg":"Server Error"},"bo":null,"other":null}
```

**6.3 POST → 200 OK（决定性证据）**：

```
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
Vary: Origin
Vary: Access-Control-Request-Method
Vary: Access-Control-Request-Headers
X-Frame-Options: SAMEORIGIN
Strict-Transport-Security: max-age=31536000;includeSubDomains
```

```json
{"code":{"code":"0000","msg":"Success"},
 "bo":{"publicKey":"MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC/…（已脱敏）…X4KVkwIDAQAB",
       "algorithm":"RSA","keySize":1024},
 "other":null}
```

`Vary: Origin / Access-Control-Request-*` 是 Spring 系网关特征；返回 RSA-1024 公钥，
与项目记录的 **RAIS / UAC-Lite 登录前置接口**逐字吻合。

**6.4 结果**：`/raisprod/uacliteweb/` 带同源 Referer 仍返回 404、`Content-Length: 0`
→ 该网关只转发了 `/raisprod/` 下的 API，SPA 静态内容未发布。

---

## 七、项目内查证（配置与文档出处）

| 查证 | 结果 | 出处 |
| --- | --- | --- |
| `8165` 全库搜索 | 无有效命中（仅 geojson 坐标、HTML 长行误匹配），说明这是新地址 | 全局 Grep |
| eFlow 内网地址 | `https://10.100.20.8:28001`，OAuth2 `/api/oauth2/v1/authorize`，门户 `/uportal/framework/default.html` | `ticket_export_rpa/yingdao_to_python_V2.py:57,81`、`Site_outage/screenshot_site_outage.py:57` |
| `41.191.x` 网段 | Orange 利比里亚公网段（项目记录 `41.191.107.211~228` 缓存集群） | `backend/services/olib_soc_report/olib_soc_report_service.py:89` |
| `raisprod` | RAIS 统一权限平台 / UAC-Lite SPA，内网 `10.100.20.9:8766`，入口 `/raisprod/uacliteweb/#/login` | `backend/services/portal_login_service.py:92-120`、`Task/whatsapp-kb-bot/knowledge/22_iMind升级操作指导书.md:389` |
| RAIS 接口约定 | `POST /raisprod/platform-service/web/config/getAesConfig → bo.publicKey`；`/raisprod/*` 强制同源 Referer | `backend/services/credential_tester.py:503-563`、`docs/manual/11-feature-guide.md:2633-2638` |
| eFlow 公网反代已知坑 | cookie `domain=10.100.20.8;secure`、内网/localhost 绝对 URL、HSTS、CSP；需 `proxy_cookie_domain` / `nosecure` / `proxy_redirect` / `sub_filter` / 摘 HSTS | `docs/nginx-reference/portal_eflow_common.conf.txt:15-59` |

---

## 八、结论

1. `41.191.105.18:8165` **IP、端口、HTTPS 均可达**（明文 HTTP 返回 400）。
2. 该网关的实际应用上下文是 **`/raisprod`**，上游是 **RAIS 统一权限平台**（POST
   `getAesConfig` 返回 200 + RSA-1024 公钥，决定性证据），**不是 eFlow**。
3. eFlow 的全部已知路径（`/uportal/framework/default.html`、`/api/oauth2/v1/authorize`、
   `/iui/`）在这台网关上 **没有任何 location**，一律落到 979 B 静态 404；换 Host 头无效，
   排除虚拟主机/SNI 问题。
4. 附带发现：即便按 RAIS 用途，SPA 入口 `/raisprod/uacliteweb/` 也返回 404 空体，
   静态内容尚未发布。
5. 因此 **不能回复「URL confirmed」**。需请 Orange 确认：要暴露的是 eFlow 还是 RAIS；
   若是 eFlow，请给出映射到 eFlow 的公网地址/端口/路径（或计划新增的网关前缀）；
   不排除对方计划用 RAIS 做 SSO 再跳 eFlow，但当前无 302 跳转、只有静态 404，链路未接通。
6. 待对方补全映射后，需从 Orange 网络做一次真实浏览器端到端登录，通过后才发最终确认。

> 本记录仅含只读 GET/HEAD/一次幂等 POST 配置查询，未做登录、未写入任何数据、
> 未代发任何邮件。

---

## 九、T6 决定性对照：公网 8165 ≡ 内网 10.100.20.9:8765（14:41）

依据如意提供的防火墙 VIP 配置截图（组 `ZTE-Eflow` / 成员 `MS-eflow-ZTE`）：
`41.191.105.18 : TCP 8165` → `Mapped 10.100.20.9 : TCP 8765`（`Map to Port 8765`，References 1）。

```bash
curl -k -sS --noproxy '*' -D - -o /dev/null https://10.100.20.9:8765/
curl -k -sS --noproxy '*' -X POST -H 'Content-Type: application/json' \
  -H 'Referer: https://10.100.20.9:8765/raisprod/uacliteweb/' -d '{}' \
  "https://10.100.20.9:8765/raisprod/platform-service/web/config/getAesConfig"
curl -k -sS --noproxy '*' -D - -o /dev/null https://10.100.20.9:8766/
```

| 检查 | 结果 |
| --- | --- |
| `10.100.20.9:8765/` | 404，响应头与公网 8165 **逐字一致**（`Server: nginx`、`charset=utf-8,gbk`、`1;mode=block`、HSTS） |
| `10.100.20.9:8765` POST `getAesConfig` | 200 `code=0000`，**RSA-1024 publicKey 与公网 8165 返回的字符串完全相同**（`MIGfMA0G…X4KVkwIDAQAB`） |
| `10.100.20.9:8766/` | 404，但 `charset=utf-8`（无 gbk）→ 同机另一个 nginx 端口 |

**判读**：公网 8165 与内网 `10.100.20.9:8765` 是同一服务实例，即防火墙做的是
**四层 DNAT 端口映射**，不存在七层网关按 location 分流。据此修正第八节的表述：
404 来自 `10.100.20.9:8765` 上那套 RAIS 应用自身的 nginx，eFlow 从未进入这条链路。

**最终根因**：VIP `MS-eflow-ZTE` 名称含 eflow，但 Mapped IP/Port 指向 RAIS 服务器
`10.100.20.9:8765`；eFlow 实际在 `10.100.20.8:28001`。目标地址与端口都错。
