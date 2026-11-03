# IPT Digital Platform（RMS 能源监控）站点电源信息

> 状态：✅ 已打通并实测（2026-11-03）。客户端：`ipt_energy_client.py`（纯 requests，无浏览器依赖）。
> 来源：同目录 `url.txt`（Chrome DevTools 抓包转储）逆向 + 实测验证。**本文件不记录任何口令**。

## 一、认证（OIDC 隐式流）

门户 `https://portal.iptdigitalplatform.com` 是 Angular SPA，OIDC 配置（前端 `env.js` + main bundle 确认）：

| 项 | 值 |
| --- | --- |
| authority | `https://login.iptdigitalplatform.com`（OpenIddict） |
| client_id | `rubix-web` |
| response_type | `id_token token`（**隐式流**，无 code / 无 PKCE） |
| redirect_uri | `https://portal.iptdigitalplatform.com/cb` |
| scope | `openid rubix-api email profile` |

纯 requests 登录流程（`IptEnergyClient._login`）：

1. `GET /connect/authorize?client_id=rubix-web&redirect_uri=...&response_type=id_token token&scope=...&nonce=...&state=...`
   → 未登录 302 到 `/account/login?returnUrl=...`
2. 登录页表单字段：`ReturnUrl`、`Username`、`Password`、`__RequestVerificationToken`（页内 hidden input）
3. `POST /account/login`（同 Session cookie）→ 302 `/connect/authorize/callback?...` → 302 `portal/cb#access_token=...&id_token=...`
4. 从回调 **fragment** 取 `access_token`（RS256 JWT，**TTL 1 小时**）

- `password` grant 实测被拒（`unauthorized_client`），`rubix-admin` 等其它 client 均 `invalid_client`，只有 `rubix-web` 有效但仅限授权流 → 走上面的表单模拟。
- token 缓存在 `auth_cache/ipt_token.json`（已被 `.gitignore` 的 `**/auth_cache/` 覆盖，不入库）；过期前 120s 或遇 401 自动重登。

## 二、业务接口（Bearer access_token，请求头带 portal 的 Origin/Referer）

Base：`https://backend.iptdigitalplatform.com/api/v0.1/assets/clients/<client_ref>/energy`

| 接口 | 用途 |
| --- | --- |
| `GET /sites?query=<站名>` | 站点模糊搜索，返回概要（id/name/参考号/cluster/坐标/优先级/连接状态） |
| `GET /sites/<site_id>/diagram` | **电源全景**：loads / batterySets / generators / grids / gridBackups / rectifiers / fuelTanks / fuelTankClusters / solarSets / environment |
| `GET /sites/<site_id>/with-events` | 站点+设备详情（网关、SIM、SNMP 等；含设备凭据字段，注意脱敏） |
| `GET /sites/<site_id>/devices/<device_id>/attributes/values` | 单设备属性（实测该站点返回 `[]`，数据主要在 diagram） |
| `POST /sites/filter-map` | 全站过滤地图（body 为空过滤器组合） |

`client_ref` 默认 `9eda5e46b0294eb589881ee74f8940da`（Orange Liberia 租户，抓包确认）。

## 三、用法

```bash
# 系统 Python 3.12（C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe）
cd backend/services/ipt_data
python ipt_energy_client.py "Jahtondo Town"        # 中文摘要
python ipt_energy_client.py "Jahtondo" --list      # 只列站点（id | 名称 | 参考号 | 区域）
python ipt_energy_client.py "Jahtondo Town" --json # 归一化 JSON
```

代码调用：`IptEnergyClient().get_site_power(站名)` → `(site, 归一化电源 dict)`。

凭据来源（优先级）：环境变量 `IPT_USERNAME` / `IPT_PASSWORD` > 同目录 `url.txt` 头部「用户名：…/密码：…」两行。

## 四、注意事项

- ✅ `url.txt` 含明文凭据，已被 `.gitignore` 的 `/backend/services/ipt_data/url*.txt` 覆盖（2026-11-03 确认），不会被误入库。
- `with-events` 响应含网关设备密码/SNMP community 等敏感字段，任何落库/日志输出前须脱敏。
- 外网 API 需直连（客户端已设 `trust_env=False`，规避本机 http_proxy 干扰）。
- 会话同源：`rubix-web` 单账号多端登录不互踢（隐式流无服务端会话绑定限制，实测多次登录均有效）。
