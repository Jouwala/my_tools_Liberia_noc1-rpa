# VMAX 多报表指标采集（vmax_multi_data）

按用户抓包的 VMAX vreport 请求（`url.txt`）从 VMAX 取两个 CIService 报表的指标。
方法沿用 RAN_UME 那一套：**配置化取数 → 解析 → 落盘/落库 → 定时任务**。

| 报表 | report_part | 数据表 | 说明 |
| --- | --- | --- | --- |
| 5GSA 流量 | `sys_5gsa_traffic_ciservice` | `aggr_5gsa_flow_ciservice` | Location&Service - Traffic Statistics（25 维度 / 45 指标） |
| 5GSA 视频 | `sys_5gsa_video_ciservice` | 联网后自动读 `metadata` | 视频业务 CIService 报表 |

## 协议（从 VMAX 前端 RDK 资源复刻，不是猜的）

```
POST {VMAX}/rdk/service/app/vreport/web/rpt_home/<report_part>/server/report_query
Headers: Content-Type: application/json
         X-Content-Type: application/x-vmax-s-rsa-encrypted      <-- 必须，服务端据此解密
Body  : {"param": {"encryptedStr": RSA_encryptLong(JSON(condition))}}
```

* `RSA_encryptLong` = 前端 `jsencrypt_ex.encryptData`：静态 RSA 公钥 + PKCS#1 v1.5 分块
  （**首段 114 字节，其后每段 117 字节**，按字符落刀以免劈开多字节字符），
  每段密文 128B → 256 位十六进制 → 拼起来转 base64。公钥与 mars 历史查询同款
  （见 `backend/services/vmax_cxo_daily_cache.py`）。
* 明文 `condition`（前端 `report.js` 的 `conditionTableProcessor()`）：
  `reportPart` / `condition.topN` / `condition.times{beginTime,endTime,granularity,multi_period,bh}`
  / `condition.filterList{filters,filter_type}` / `paging{currentPage,pageSize,totalRecord}`
  / `isDrill` / `show`（维度 id + 指标 id）/ `area` / `session`（`JSESSIONID=<vreport 会话>`）。
* 粒度编码：`quarter=3`、`hour=4`、`date=5`、`month=6`、`week=7`、`5min=8`。
* 会话：`GET /rdk/service/app/vreport/server/session`（返回裸 session id）。
* 导出：`server/export_data`（同一信封，条件上再加 `exportType/exportAll/maxExportRecord` 等），
  再 `GET /vReport/export/checkFile|getFile?param=encryptData({"file":name,"method":"1"})` 下载。

### 一个坑：`X-Content-Type` 必须传到上游

本机 8790 VMAX 代理原先只转发自己的固定头，把调用方的 `X-Content-Type` 丢掉，于是 RDK
服务端不解密，脚本拿到的是 `{"encryptedStr": "..."}` 外壳，读 `param.condition.times` 就报
`Cannot read property "times" from undefined`。已修：

* `Scripts/realtime_proxy_vmax.py`：`forwardable_headers()` 透传调用方 `X-*`（去掉 `x-forwarded-*`/`x-real-ip`）。
* `backend/routers/realtime_proxy.py`：同源代理跳转时也带上 `X-*`。

## 时间范围与行数上限（实测，很重要）

页面时间控件 `timeOption = ["hour","day","month","week"]`；能取多长由**上游滚动保留期**决定，
不是本地限制：

| 粒度 | 可回看 | 实测 |
| --- | --- | --- |
| `date`（天） | **90 天** | 请求 90 天 → 656 行（traffic）；请求 120/180/365 天，返回的最早日期都停在 `2026-06-18`（正好 90 天前）→ 页面上的「最多 90 天」就是这个保留期 |
| `hour`（小时） | ≥30 天（保留期内） | 30 天单请求 = 719 个小时点、1714 行、88s；**90 天单请求会跑到代理 120s 超时** |
| `week` / `month` | 报表自身聚合 | 直接用，同样受 90 天明细保留期限制 |

**单次请求的行数上限 = `topN`/`pageSize`（服务端按报表默认排序截断，翻页无效）**，这是最容易
踩的坑：`topN=200` 时 90 天只回 200 行、日期跨度看着"缺一段"（实测只覆盖 06-19~07-20）；
`topN=5000` 才回满 656 行。`paging.currentPage=2` 返回 0 行 —— 服务端不做翻页。

因此本服务做了两件事，避免静默丢数据：

1. `top_n` / `page_size` 默认 **20000**（配置可改）；
2. **分片拉取**：`chunk_days` 按粒度给（hour=7 天/片、date=30 天/片、week=60、month=180），
   各片互不重叠、首尾相接，合并后按 `clttime` 排序并去重；
   返回/落盘里带 `slices`（片数）与 `truncated`（某片是否顶到 top_n），
   顶到上限会在摘要 errors 里给出告警，不会悄悄少行。

```bash
# 90 天全量（date 粒度，3 片）——实测 836 行 / 282s，落盘
python -m backend.services.vmax_multi_data.vmax_multi_data_service --report all --days 90 --granularity date --progress

# 小时粒度建议 ≤30 天（每小时明细较贵：7 天/片 ≈40s）
python -m backend.services.vmax_multi_data.vmax_multi_data_service --report traffic --days 14 --granularity hour --progress
```

> 注意：定时任务默认 `days_back=1`（每小时增量），90 天这类大范围用于**一次性补数/回溯**，
> 不要把任务的 days_back 直接改成 90 —— 那会让每小时任务重拉一遍 90 天。

## 用法

```bash
cd D:/01_RPA/Task/my_app

# 健康检查：代理/直连是否可用 + vreport 会话 + 两个报表的默认 show
python -m backend.services.vmax_multi_data.vmax_multi_data_service --check

# 列出配置中的报表
python -m backend.services.vmax_multi_data.vmax_multi_data_service --list

# 取最近 24 小时（小时粒度）并落盘
python -m backend.services.vmax_multi_data.vmax_multi_data_service --report traffic --days 1

# 指定窗口与粒度（Granularity 可选 hour/date/week/month/5min/quarter）
python -m backend.services.vmax_multi_data.vmax_multi_data_service --report all \
    --start "2026-09-16 00:00" --end "2026-09-16 23:00" --granularity hour

# 只打印不落盘 / 打印全部行
python -m backend.services.vmax_multi_data.vmax_multi_data_service --report traffic --no-persist --full
```

Python 里：

```python
from backend.services.vmax_multi_data import vmax_report_client as vrc

rows = vrc.fetch_report_kpis("sys_5gsa_traffic_ciservice", days_back=1, granularity="hour",
                             kpis=["ppb400401001"])         # 也可给 dims=[]
for r in rows["records"][:5]:
    print(r)
```

定时任务：`vmax_multi_data_sync`（每小时 :45，与 `vmax_cxo_daily_sync` 的 :15 错峰），
入口 `run_vmax_multi_data_sync()`，可在「任务管理」手动触发。

## 配置

`backend/services/vmax_multi_data_config.json`（「设置 → 任务配置 → VMAX 多报表指标采集」可改）：

| 字段 | 说明 |
| --- | --- |
| `enabled` | 总开关 |
| `transport` | `auto`（默认）/`proxy`（走 8790）/`direct`（自带门户登录） |
| `granularity` / `days_back` / `top_n` / `page_size` | 默认粒度、回看天数、单请求行数上限（**默认 20000**，小了会被服务端截断） |
| `chunk_days` | 分片跨度（int 或 {粒度: 天数}），默认 `{5min:1, hour:7, date:30, week:60, month:180, quarter:365}` |
| `reports[].report_part` | URL 里的 `rpt_home/<report_part>` |
| `reports[].dims` / `kpis` | 留空 = 用报表 `design.json` 里 `defaultSelected=1` 的维度/指标 |
| `reports[].filters` | 前端同构过滤条件：`{"fields":[{"name":"city_id","data":["1"],"operator":6}]}` |
| `persist.*` | 是否落 JSON/SQLite、是否写远程 DB（`db_writer_client`，默认关闭） |

凭据：`vmax_cxo`（「凭据管理」或 `VMAX_CXO_USER/VMAX_CXO_PASS` 环境变量）；
仅 `direct` 模式需要——`proxy` 模式复用 8790 代理持有的门户会话，
避免撑爆 VMAX 门户的并发会话上限。

## 实测验证（2026-09-16，经本机 8790 代理）

```
$ python -m backend.services.vmax_multi_data.vmax_multi_data_service --check
transport : proxy ready = True      # {"status":"ok","proxy":"ready","auth":true,"user":"ZeeshanM"}
vreport session: u2u451ih13hh1hbp48s7v7z0p
配置 OK   : sys_5gsa_traffic_ciservice -> show = ['clttime','city_name','targetname','ppc400401001',...]
配置 OK   : sys_5gsa_video_ciservice   -> show = ['clttime','city_name','targetname','ambr_limit','ppc400464001',...]

$ python -m backend.services.vmax_multi_data.vmax_multi_data_service --report traffic --days 1
[vmax_multi_data] ok reports=1 rows=48 elapsed=6.22s
header: ["Statistical Time","City","Target NE Name","Total Traffic","Uplink Traffic",...]
{"clttime":"2026-09-15 16:00:00","city_name":"Monrovia","targetname":"SGW_HQ_122",
 "ppc400401001":"7836322800716","ppb400401001":"906622464924",...}
```

`run_vmax_multi_data_sync()` 一趟（两个报表）：`status=ok rows=92 elapsed≈3.4s`
（traffic 48 行 / `aggr_5gsa_flow_ciservice`，video 44 行 / `aggr_5gsa_video_ciservice`，
窗口 `2026-09-15 16:00 ~ 2026-09-16 15:59`，hour 粒度，均无错误），
JSON 快照 + SQLite 各 92 行已落盘。

90 天全量（date 粒度，3 片/报表）：`--report all --days 90 --granularity date`
→ traffic **656 行 / 89 天 / 2026-06-19~09-16**、video **180 行 / 90 天**，`truncated=False`；
小时粒度分片（14 天 = 2 片）：traffic **795 行 / 78.8s**，无超时。
同时回归了既有任务 40：`run_vmax_cxo_daily_sync()` 仍 `kpis=50/50 rows=400 errors=0`
（证明代理的 `X-*` 头透传没有影响看板链路）。

**注意**：上游返回的指标列名带 `#` 前缀（请求 `ppc400401001` → 响应 field `#ppc400401001`），
`parse_report_payload` 默认去掉前缀（原始列名保留在 `raw_fields`），所以落盘/落库的键
可直接当列名用。

## 落盘

```
data/vmax_multi_data/
  <key>_latest.json          最近一次全量快照（含 field/header/records/condition）
  vmax_multi_data.sqlite3    kpi_rows（明细行，按 报表+窗口+粒度 覆盖写）+ sync_runs
  _cache/<report_part>_{init_data,design,metadata}.json   报表静态配置缓存（默认 24h）
```

```sql
-- 明细
SELECT row_json FROM kpi_rows WHERE report_key='traffic' ORDER BY row_no LIMIT 5;
-- 每次采集的成功/失败记录（排查「某小时为什么没数据」）
SELECT report_key, window_begin, rows, status, error, finished_at FROM sync_runs ORDER BY id DESC;
```

## 排障

| 现象 | 原因 / 处理 |
| --- | --- |
| `Cannot read property "times" from undefined` | 少了 `X-Content-Type: application/x-vmax-s-rsa-encrypted`（见上文「一个坑」），或 body 少了 `param` 外壳 |
| `8790 VMAX 代理转发失败(502)` / `[WinError 10060]` | VMAX 10.123.255.12:26180 不可达（网络/门户会话）；先用 `--check` 确认，再 `POST /api/realtime-proxy/restart` |
| `session invalid` | vreport 会话过期，客户端会自动刷新一次 |
| 返回行数正好等于 `top_n` | 被服务端 TopN 截断了（`truncated=True` + 摘要 errors 有告警）：调大 `top_n` 或调小 `chunk_days` |
| 行数很少但日期跨度不对 | 同上，TopN 按报表默认排序截断（旧版本 top_n=500 就会这样） |
| 单请求跑到 120s 超时 | 范围太大（如 90 天 hour 粒度）：按 `chunk_days` 分片拉，或改用 date 粒度 |
| 返回 0 行 | 窗口内无数据，或超出上游保留期（date 只有 90 天）；粒度要与数据保留期匹配 |

## 测试

```bash
python tests/test_vmax_multi_data.py            # 离线单测（RSA 分块 / 条件 / 解析 / 配置 / 落盘 / 编排）
python tests/test_vmax_multi_data.py --live     # 追加一次真实取数（需能连 VMAX）
```
