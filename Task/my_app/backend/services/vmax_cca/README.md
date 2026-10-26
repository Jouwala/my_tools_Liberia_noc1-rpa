# VMAX CCA 投诉「用户信息查询」客户端（vmax_cca）

对接 VMAX CCA 投诉页（`https://10.123.255.12:26180/rdk/app/vmax_s_data_cca/complaint/web/`）
的按号码查用户/终端能力，供 my_app「VMAX 用户查询」页（`/api/vmax-cca-query`）使用。

协议于 2026-10-24 从该页前端 JS（`main.js`、`awade-assets/js/vmax-s-rsa-encryptor.js`）
复刻并实测验证，方法与 `vmax_multi_data`（vReport 复刻）一致。

## 1. 加密信封（与 vReport / mars 同源）

前端 `vmax-s-rsa-encryptor.js` 给 XHR 打补丁：URL 命中 `/^\/vmax\/cca\/.+/` 的 GET 请求，
把查询参数对象 `JSON.stringify` 后用 **JSEncrypt encryptLong** 加密：

- 静态公钥与 vReport / mars 完全相同（复用
  `backend/services/vmax_multi_data/vmax_report_client.py` 的 `encrypt_long()`，勿再实现第二份）；
- 密文 base64 后 URL 编码，拼成 `?encryptedStr=<密文>`；
- 同时带请求头 `X-Content-Type: application/x-vmax-s-rsa-encrypted`。
  实测（2026-10-24）经 8790 代理不带该头也能正常解密，但浏览器行为总是带，客户端保持一致。

## 2. 接口（全部 GET，参数在 encryptedStr 里）

### userinfo/query_imsimdn —— 号码 → 用户/IMSI

明文参数：`{"msisdn": "<号码>"}`（前端原样透传，不做格式归一）。

⚠️ **号码必须用 `231` 开头的完整格式**（2026-10-24 真号 `231777777322` 实测：
12 位命中 `SUCCESS`，剥成 9 位 `777777322` 返回 `IMSI is not found`——
初版客户端曾剥 231 前缀导致查不到，已改回原样透传）。

实测响应（号码不存在）：

```json
{"msg": "IMSI is not found", "status": 3,
 "data": [{"msisdn": "777123456"}, {"imsi_arr": []}]}
```

- `status == 0` 才是命中；`status == 3` 表示查无此号；
- `data` 是数组：`data[0]` 为用户信息对象（除 msisdn 外的字段需真实号码实测补充），
  `data[1].imsi_arr` 为 IMSI 列表。

### userinfo/query_terminal —— IMSI → 终端

明文参数：`{"imsi_arr": "<IMSI1,IMSI2>", "starttime": "<窗口起点>"}`。

⚠️ **`starttime` 必填**（2026-10-24 真号 `618070109668163` 实测）：

- 缺键 → 上游直接 **HTTP 500**；
- 空串（CCA 前端在 URL 不带投诉单时间时的默认值）→ `status=1, msg="Terminal info not found", data=null`；
- 今天 / 昨天 / 7 天前 → 均返回同一份完整终端数据。

说明返回的是 IMSI 的终端属性记录，窗口起点只须落在最近使用区间内。
客户端固定回溯 **7 天**（覆盖最近换机场景；CCA 前端的 starttime 来自投诉单时间，
本查询页没有投诉单上下文，取固定窗口）。

实测响应（无命中时用 `--` 占位；`status=1 data=null` 也是未命中的一种形态）：

```json
{"msg": "Terminal info fetched", "status": 0,
 "data": {"country_name": "--", "network_arr": ["--"], "flag_arr": [["--", "--"]],
          "modelos_arr": ["--"], "imei_arr": ["--"], "msisdn": "--",
          "modelvendor_arr": ["--"], "operator": "--", "modelname_arr": ["--"]}}
```

`data` 是扁平对象，数组型字段（`*_arr`）直接渲染即可。

### getcause —— 窗口内投诉根因（2026-10-25 接入）

明文参数：`{imsi, rattype: 0, servicetype: 1, starttime, endtime, model_id: "1"}`。

⚠️ **`model_id` 必须传 `"1"`（默认分析模型）**：空串时上游恒返回
`{"msg": "cause info is null", "status": 1, "data": []}`（2026-10-25 实测）。
大窗口（7 天级）上游会读超时（60s），由 query() 记入 failures 不阻断其它分项。

实测响应（真号 2026-10-24 全天，59 条根因）：

```json
{"status": 0, "data": [{
  "rule_name": "Downlink weak coverage(cell) ",
  "object_type": "CELL(4G)", "object_name": "Thinker Village-X2",
  "objectinfo": "4559_42", "ne_id": "461807001167146",
  "confidence": "90%",                       // 客户端去 % 转 float，列表按其降序
  "description": "Poor Quality Period:2026-10-24 03:00,Cell Dlweakcover MRs Ratio:...",
  "solution": "1.Adjusting a tilt of the Serving Cell;2...",   // 处理建议，高价值
  "vendor": "ZTE", "province": "Montserrado", "city": "Montserrado",
  "poortime": "2026-10-24 03:00,...", "kqicode": "ppd6-2-1-1-2",
  "appInfo": [{"clttime": "...", "judgeInfo": "Cell Dlweakcover MRs Ratio:12.33%,..."}]
}]}
```

客户端归一为 `[{rule_name, object_*, confidence, description, solution, vendor,
province, city, poortime, kqicode, app_info: [{clttime, judge}]}]`。

### rule/node（未接）

定界规则树（CN/UPF/Video/Perception… 静态配置，14KB），非用户维度数据，不接。

### 已知扩展面板（未接）

`userinfo/query_speedlimit`（限速）、`userinfo/query_tethering`（热点共享）、
`vs/userinfo` 需要时按同一信封补充。url.txt 抓包里其余非静态请求（门户 notice/theme/
鉴权、talon XDR 框架的 get_config_info/decrypt_param、webgis 地图密钥）均为平台框架
基础设施调用，与用户数据无关，不接。

### flowinfo/query_flow —— 窗口内按应用流量

明文参数：`{imsi, starttime, endtime, rat: 0, rattype: 0, servicetype: 1}`
（0=全部，1=数据业务 2=语音，与 CCA 前端一致）。

实测响应（多数用户无 DPI 记录）：

```json
{"msg": "Traffic info not found", "status": 1,
 "data": [{"app_flux": "[]", "total_flux": "--"}]}
```

命中时 `app_flux` 是 **JSON 字符串**（按应用列表），客户端解析成列表后透传。

### usertrack/query_cell —— 窗口内驻留小区 + 每小区 KPI

明文参数：同 query_flow 再加 `complaintServiceSwitch: 1`。

实测响应（2026-10-23 全天真号，41 个小区）：

```json
{"status": 0, "data": {
  "userTrack": [{"cellname": "Thinker Village-X2", "vendor": "ZTE", "pci": 377,
                 "cell": 461807001167146, "celllat": 6.24, "celllon": -10.66,
                 "azimuth": 240, "height": 43, "cellkey": "4559_42", "rat": 6}],
  "cellKpi": {"461807001167146": {"ppc300103004_23": 100.0, "cellrat": "6_4257_32", ...}},
  "userGridKpi": {}, "nrEutratonr": {}, "cellGrids": [], "gridKpi": {...1197 条...}}}
```

- `cellKpi` 的键是 `ppc 码_后缀`，后缀与 rat/网格相关；**KPI 名用
  `global/kpi_popup/query_kpi?function_id=3` 的字典映射**（121 条，进程内缓存），
  取 `_` 前段查名，缺码回落原始码；
- `gridKpi`/`userGridKpi`/`cellGrids` 是栅格级大块数据（实测 1197 条），
  与「用户在哪些小区」无关，客户端**不透传**，避免响应膨胀。

### 时间窗约定（normalize_window）

CCA 投诉页按天查询：`starttime="YYYY-MM-DD 00:00:00"`、`endtime="YYYY-MM-DD 23:59:00"`。
本页时间选择器**精确到分钟**（5 分钟步进），带时分的时间原样透传；
只给日期时自动补 CCA 日界 00:00:00 / 23:59:59。
`query_terminal` 的 starttime 用窗口起点（今天/昨天/7 天前实测返回同一份终端数据）。
窗口跨度上限 31 天（`MAX_WINDOW_DAYS`，大窗口上游明显变慢且无意义）。

## 3. 登录与会话

- 与 vReport 直连同一条门户登录链路：`GET /rdk/service/app/portal/server/loginAuthenticate`
  取动态 RSA 公钥 → PKCS#1 v1.5 加密口令 → `POST /web/res/web-common/login`
  → `result == 1` 成功，JSESSIONID 由 CookieJar 持有；无网页验证码，可全自动。
- 凭据组 **`vmax_cca`**（`credential_store.CREDENTIAL_GROUPS`），优先级
  环境变量 `VMAX_CCA_USER` / `VMAX_CCA_PASS` > 凭据库。未配置密码时登录明确失败，
  由 router 返回「请先在 设置→凭据管理 配置」的指引。
- 实测 2026-10-24：`vmax_cxo` 组的账号（ZTE_NOC01）具备 CCA 接口调用权限；
  仍用独立凭据组，避免与 8790 看板代理（同账号持会话）互踢。
- HTTP 401/403/404/407 视为会话失效：自动重登并重试一次。
- 门户会话宝贵：客户端全程持锁串行，进程内单例复用会话，不做查询后 logout。

## 4. 使用

```python
from backend.services.vmax_cca.vmax_cca_client import get_client

client = get_client()
result = client.query("231777777322", "2026-10-23", "2026-10-23")
# {"msisdn": ..., "found": bool, "user": {...}, "terminal": {...}|None,
#  "window": {starttime, endtime}, "flow": {total_flux, apps}|None,
#  "cells": {cells: [...], cell_kpi: {cell: [{code,name,value}...]}}|None,
#  "failures": [...], "msg": ...}
```

号码归一化（客户端内做，`normalize_msisdn`）：只剔除空格/横线/括号/`+`
等分隔符，**前缀原样透传**（服务端只认 `231` 开头完整号码，见第 2 节实测）。

---

# VMAX 信令详单（vmax_xdr_client）

与上面 CCA 用户查询**同主机、同门户会话、同 RSA 公钥**，但接口属于 Talon XDR
框架（`/rdk/service/app/talon/xdr/...`），是另一套业务。2026-10-26 接入。

- 客户端：`vmax_xdr_client.py`（头注释有完整协议与踩坑清单）
- 路由：`routers/vmax_xdr_query.py` → `GET /api/vmax-xdr-query`
- 页面：`vmax_xdr_query`（`frontend/src/pages/VmaxXdrQuery.tsx`）

**与 CCA 的三处关键差异**（都在 `vmax_xdr_client.py` 头注释里详述）：

1. 查询走**合并表** `exec_merge_query`，不是 `exec_query` 分表；
2. `XDRTable` 必须**空串**、`serviceName` 固定 `"xdr_query"` —— 填表名恒返回
   `3100100303 Query no data`；
3. 时间参数是**毫秒边界** `YYYY-MM-DD HH:MM:SS.000`，CCA 是秒级。

**已接入的 serviceType**：`1100`（5G 会话）、`1300`（信令面）、
`1301`（用户面业务）。`32/33/34`（数据面）用另一套字段
（`btime` + `User Number`），实测 `3100100314`，**未接**。

**会话纪律**：`VmaxXdrClient` 内部持 `VmaxCcaClient` 的锁与 session，**不自行登录**。
2026-10-26 排查时反复登录触发过
`The maximum number of connections for the user is reached`，会短时影响 CCA 页——
上游按用户限并发，任何新增查询都必须复用同一会话。
