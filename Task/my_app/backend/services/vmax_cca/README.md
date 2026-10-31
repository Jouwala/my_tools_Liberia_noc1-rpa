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
- 页面：`vmax_user_query` 的「信令详单」页签
  （`frontend/src/components/VmaxXdrPanel.tsx`；2026-10-26 由独立页合并而来，
  旧链接 `?page=vmax_xdr_query` 作为历史别名仍可用）

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

---

# XDR Records —— 分表查询（2026-10-27 接入）

同一 Talon 框架的另一半：合并表看「一个号码所有接口的流水」，分表看**单张 XDR 表**
的完整列（`UEMR_XDR` 带 RSRP/SINR 等空口测量列，是无线排障的主力表）。

- 客户端：`vmax_xdr_client.py` 的 `tables()` / `query_table()`
- 路由：`routers/vmax_xdr_records.py` → `/api/vmax-xdr-records/*`
- 页面：`vmax_user_query` 的「XDR 记录」页签（`components/VmaxXdrRecordsPanel.tsx`）

## 表清单：get_tabinfo

```
POST /rdk/service/app/talon/xdr/server/scripts/service/get_tabinfo
body  {"param":{"encryptedStr":"<RSA({"xdrServiceId":"32","condition":[]})>"}}
resp  {"result":"{\"status\":0,\"data\":[{\"table_name\":\"fact_lte_uemr\",\"xdr_name\":\"UEMR_XDR\"},...]}"}
```

`xdr_name` 是界面上的页签名，`table_name` 才是 `XDRTable` 要填的值。实测：

| serviceType | 表 |
| --- | --- |
| 32 | `ods_lte_xdr_uu_cmcc`(UU_XDR) / `ods_lte_xdr_x2_cmcc`(X2_XDR) / **`fact_lte_uemr`(UEMR_XDR)** |
| 33 | `ods_nr_xdr_uu_cmcc` / `ods_nr_xdr_xn_cmcc` / `fact_nr_uemr` |
| 34 | `ods_umts_uu` / `ods_umts_ho` / `ods_umts_uemr` |
| 1100 | `fact_pscp_s1mme` / `_s11` / `_s6a` / `_sgs` / `_gn` |
| 1300 | `fact_5gsa_psup_flow` / `_http` / `_dns` / `_mms` / `_ftp` / `_email` / `_voip` / `_rtsp` / `_https`、`fact_5gsa_nbup_coap` |
| 1301 | `fact_5gsa_psup_video` / `_web` / `_app` / `_ott_nslice` / `_ott_slice` |

## 查询：exec_query

表模式与合并表模式的参数差异（照抄前端 `show_table_module.js::initCommonConditionProcessor`）：

| 项 | 合并表 | 分表 |
| --- | --- | --- |
| 接口 | `exec_merge_query` | `exec_query` |
| `XDRTable` | `""` | 表名，如 `fact_lte_uemr` |
| `serviceName` | `"xdr_query"` | **不传** |
| `colModel` | `[]` | 该表列名数组（先取列头） |
| 列头 | `queryType=2` + `condition` | `queryType=1` + `XDRTable` |

其余一致：`condition` 四元组（时间 / serviceType / dbType / 号码）、
毫秒边界时间、域配对（32 用 `ran_service` + `btime` + `User Number`）。

### 号码条件的 `type` 必须是 `"1"`，不能照抄页面的 `"6"`（2026-10-27 实测）

页面 `initcomponent` 返回的组件类型是 `6`（SELECT_INPUT 下拉+输入），但**组件类型
不等于线上过滤类型**：把 `6` 原样发给 `exec_query` / `exec_merge_query`，上游既不报错
也不按号码过滤。实测（serviceType 1301，`fact_5gsa_psup_video`，窗口内确有该号码记录）：

| condition | 结果 |
| --- | --- |
| `{"field":"msisdn","type":"6",...}` | `3100100202`（有数据却说无数据） |
| `{"field":"msisdn","type":"1",...}` | `status=0`，命中该号码的记录 |

合并查询上 `type=6` 更危险：**完全不按号码过滤**，会把整窗别的用户的详单当成
当前查询结果返回（1301 用伪造号码也返回了真实号码的记录）。因此 `_build_condition()`
统一用 `type="1"`，并由 `tests/test_vmax_xdr_records.py` 固化。

RAN 域（32/33/34）没有 `msisdn` 列，号码列是隐藏列 `$msisdn`（前端列头里以 `$` 标记）；
且 UEMR/UU 记录实测只带 IMSI、`$msisdn` 为空串，所以**RAN 按号码查会如实返回空**，
而不是像旧实现那样用不存在的 `msisdn` 字段、忽略条件把整窗数据吐出来。

⚠️ **表名要白名单校验**：`XDRTable` 会被上游拼进 FROM 子句，任意字符串有注入风险。
`query_table()` 先用 `tables(service_type)` 匹配 `table_name` 或 `xdr_name`，
不匹配直接报错，不接受调用方随意传表名。

## 落库（合规审计 + 取证）

其余 VMAX 接口都只读透传；本功能落两张表（`routers/vmax_xdr_records.py`）：

- `vmax_xdr_saved_record`：用户存档的单条记录（`payload` 为 JSON），本人可见；
- `vmax_xdr_query_log`：每次查询留痕（号码打码、记录数、耗时、状态）。

理由：上游只保留 24~72 小时，过期无法回查；且信令属用户隐私数据，
需要能回答「谁在什么时候查了谁」。归档上限 500 条/人、200KB/条。

## ⚠️ 探测纪律（2026-10-27 再次踩到）

为了摸清 `get_tabinfo` / `exec_query`，我连开了 5 个探针进程各自登录，
直接把该账号的并发会话占满：之后**所有**新登录（包括后端重启后的首次登录）
都返回 `The maximum number of connections for the user is reached`，
CCA 页与 XDR 页一起不可用，只能等旧会话超时。

结论：**任何探测都必须在同一个进程里只登录一次**（或直接复用后端单例会话），
不要在多个脚本里各 `VmaxCcaClient()` 一次。

2026-10-30 再踩一次：为了摸清用户面表的可查性，我连开 8 个探针脚本各登录一次，
把该账号的并发会话占满，**所有**新登录都返回同样的限流错误，
连 CCA 页都一起不可用。绕法是**借用运行中后端的会话**（调
`/api/vmax-xdr-records`）去取数 —— 后端持有单例会话，不占新连接。

---

# 按分类流量 —— 由 XDR 用户面话单算出（2026-10-30 接入）

「VMAX 用户查询」页「流量信息」卡的两级页签
（`数据|语音` + `流量|视频|网页|游戏|OTT语音|OTT视频|TCP指标|控制面`）
**数据源的改道**。

## 为什么要改道

原先取自 CCA 的 `query_flow`（DPI 应用识别），但**实测绝大多数用户查不到**：
`total_flux="--"`、`app_flux="[]"`，CCA 网页同样为空。
这是**采集侧**的问题（上游没采到 DPI），换查询参数解决不了。

Talon XDR 的**用户面话单**是另一条链路，数据可用（2026-10-30 实测）：

| 表 | serviceType | 内容 | 实测 |
| --- | --- | --- | --- |
| `fact_5gsa_psup_flow` | 1300 | 全量用户面话单 | 1558 条 / 6 小时窗 |
| `fact_5gsa_psup_video` | 1301 | 视频会话（带 vmos） | 13~32 条 |

每条话单带 `service`（业务大类）、`subservice`、`app_content_name`、
`ul/dl_traffic`（KB）、`ul/dl_pkt`、`tcp_resp_delay`、`tcp_ack_delay`、
`ul/dl_avg_rtt`、`ul/dl_retrans_pkt`、`ul/dl_disorder_pkt`、
`ul/dl_throughput_max` —— 足以自己算出分类结果。

- 客户端：`vmax_flow_from_xdr.py`（归一 + 聚合）
- 路由：`routers/vmax_flow_xdr.py` → `GET /api/vmax-flow-xdr`
- 页面：`vmax_user_query` 的「用户概览」→「流量信息」卡

## 上游 `service` 取值域（实测 1558 条样本，10 类）

    Web Browse / Video / Social / IM / Shopping / eMail
    Network Storage / Public Traffic / Comm Traffic / Others

**与面板页签不是一一对应**：只有 `Video` / `Web Browse` / `VoIP` / `OTT*`
能直接对上；`Social` / `IM` / `Shopping` 是应用类业务，落到「流量」页签的
全量应用清单里（该页签本就不按类过滤）。**不为了凑满页签而臆造分类**，
所以「游戏」「OTT视频」在多数样本里为空 —— 那是上游没采到该业务。

## ⚠️ 时窗的坏分区边界（实测，最容易误判为「没数据」）

固定 `start=14:00`，扫 `end`：

| end | 17:00 | 17:30 | 17:44 | **17:45** | 17:46 | 18:00 |
| --- | --- | --- | --- | --- | --- | --- |
| records | 759 | 785 | 785 | **0** | 785 | 785 |

`end` 落在某些刻钟上会让**整个分区查不到**，且上游**不报错**（status=0，
records=0）。取数时把 `end` 往后挪 1 分钟避开边界（`vmax_flow_from_xdr`
内部已处理）。

排查时如果「同样参数有时有数据有时没有」，先怀疑这个边界，再怀疑会话。

## 单次查询的取数上限

单次查询最多拉 8 页 × 200 条 = 1600 条话单（`MAX_PAGES` / `PAGE_SIZE`）。
再往后的记录对「每应用总量」的贡献递减，而上游单次查询 1 万级记录要几十秒，
不能无限翻页。实测忙时号码 6 小时窗共 1558 条 —— 一次基本取完。


