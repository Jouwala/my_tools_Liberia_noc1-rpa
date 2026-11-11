# UME 拓扑服务（四层共用，ipran_topo_service.py）

> 页面：`?page=ipranTopo`　|　路由：`GET /api/ipran-topo/graph`、`GET /api/ipran-topo/layers`
> 真相源：`layers.py`（层清单与每层口径）+ `ipran_topo_service.py` 模块 docstring（聚合口径）。
> 本文是给人看的使用与排障说明。

## 1. 它做什么

一次请求完成「调 UME 8 次 → 折叠平行链路 → 分层 → 匹配站点坐标 → 汇总告警」，
把结果作为一张图的 `nodes` / `edges` / `meta` 返回。前端只负责布局与绘制，不再逐条查。

四层（IP RAN 光纤 / IP Core / Metro Ring / DWDM）**共用同一份聚合实现**，差别只有
`layers.py` 里的 lid 与口径配置。下表的实测值**只针对 ipran 层**，其余三层待
`probe_layers.py` 实测后校准（见第 7 节）。

| 项 | ipran 层实测值（2026-11-10） |
| --- | --- |
| 层内网元 | 93 |
| 层外设备 | 7（89MW01/02 微波、HQ-RAN-SW5960-1/2、ODC-M6000-8S-DCW1、HQ-M6K-8S_Plus_PS01/02） |
| 原始链路 | 167 |
| 折叠后唯一边 | 141（一对机框最多 10 条物理链路，折叠掉 11 对） |
| 分层 | 核心 4 / 汇聚 11 / 接入 78 |
| 站点坐标命中 | 77 / 93（74 精确 + 3 近似） |
| 带 critical 告警网元 | 74 / 93（80%） |
| 一次聚合耗时 | 0.6~3.0s（会话热时 0.6s） |

## 2. 数据源与鉴权

- UME：`https://10.100.2.99:28001`（自签 TLS）。四层端点序列完全一致，只有 `lid` 不同：

| layer key | 层 | lid | 抓包留档 | 口径状态 |
| --- | --- | --- | --- | --- |
| `ipran` | IP RAN 光纤 | `1293626099480711168` | `url_ipran_fiber.txt` | 实测（第 1 节的数值） |
| `ipcore` | IP Core | `1306074142901587968` | `url_ipcore.txt` | 按抓包 moc 推断的默认 |
| `metro` | Metro Ring | `1377433011116101632` | `url_metro_ring.txt` | 按抓包 moc 推断的默认 |
| `dwdm` | DWDM | `1295386822405836800` | `url_dwdm.txt` | 按抓包 moc 推断的默认 |

  前端只传 layer key，**不接受任意 lid**，映射在 `layers.LAYERS` 白名单里；
  分层 / 站名清洗 / 带宽解析按层配置在 `layers.py`，聚合逻辑里不堆 if-else。
  除 ipran 外三层的口径都是合理默认，待探层校准（第 7 节）。
- 鉴权复用 `backend/services/ipran_ume_kpi_service.py::UmeSessionClient`，凭据组 `ipran_ume`。
- 站点坐标取 PG/SQLite 的 `kml_mw_links`（`kind='site'`）。它是
  `frontend/public/mw_ume_orange_links.geojson` 的源表，由
  `backend/services/mw_ume/mw_links_store.py` 从 KML 写入。

两个实测坑（改动前务必知道）：

1. `forgerydefense` 请求头**不带 `-28001` 后缀**，带后缀一律 403。
2. 共享会话探活**不能打 `LOGIN_PORTAL`**（那里恒 200，会得到假绿），必须打真实业务端点。

同目录的 `url_*.txt`（fiber / dwdm / ipcore / metro_ring）是取数方法的一手抓包留档，
**含有效会话 cookie，已由 `.gitignore` 挡在版本库外**（AGENTS.md 四.2）；修改取数逻辑时照着它核对接口与参数，不要把它复制进任何文档或代码。

## 3. 缓存与刷新

- 进程内缓存 `CACHE_TTL_SEC = 120` 秒，**按 layer 分槽**（切页签不会串数据）；
  四层共用一把 `_fetch_lock` 串行化，避免连切页签时 4×8 次调用同时打向 NMS。
- `GET /api/ipran-topo/graph?layer=ipcore&refresh=1` 只清该层图缓存并重载共用的
  站点坐标缓存；不带 layer 时默认 `ipran`，现有页面与旧调用方式行为不变。
- 上游取数失败时**回退上一版成功数据**，并在 `meta.stale = true` +
  `meta.warnings` 里显式标注 —— 界面必须把它显示出来，不能当新鲜数据看。
- KML 重新上传后站点坐标会变：`refresh=1` 即可，无需重启后端。

## 4. 返回结构

```jsonc
{
  "nodes": [{
    "id": "…", "name": "M6K_2S16_Chocolate_City_UPE99", "site": "Chocolate City",
    "tier": 1,            // 0 层外 / 1 核心 / 2 汇聚 / 3 接入
    "model": "M6000-2S16", "ip": "10.16.1.x",
    "up": 1,              // connectionState == 1
    "crit": 1, "major": 2, "minor": 1, "warn": 0,
    "sev": "crit",        // 最高级告警，仅用于徽标与排行，不做节点填色
    "lat": 6.31, "lon": -10.8,    // 未命中为 null
    "geo": "exact",       // exact / fuzzy / miss / ext
    "geoName": "…",       // 命中的库内站名（fuzzy 时用于人工核对）
    "deg": 4              // 端口级度数（折叠前）
  }],
  "edges": [{
    "s": "nodeId", "t": "nodeId",
    "n": 3,               // 该对机框折叠了几条物理链路
    "gb": 100,            // 组内最小端口速率（GB）；解析不出为 null
    "down": 0,            // 组内 down 的链路条数
    "crit": 0, "major": 0,// 组内链路告警合计
    "ports": ["…"]        // 最多 12 条链路名，供悬停明细
  }],
  "meta": {
    "layer": "ipran", "layerName": "IP RAN 光纤",
    "fetchedAt": "2026-11-10T02:11:00+00:00", "elapsedSec": 2.31, "cached": false,
    "ne": 93, "ext": 7, "rawLinks": 167, "foldedLinks": 141,
    "tierCounts": {"0": 7, "1": 4, "2": 11, "3": 78},
    "geo": {"exact": 74, "fuzzy": 3, "miss": 16, "ext": 7},
    "geoMissSites": ["…"], "geoFuzzyPairs": [{"site": "Goodride", "matched": "Goodridge"}],
    "critNe": 75,
    "warnings": ["alarm_saturated: …", "geo_miss: …", "geo_fuzzy: …"]
  }
}
```

`warnings` 的三种前缀：`alarm_saturated`（告警饱和，颜色失去区分度）、
`geo_miss`（站点无坐标）、`geo_fuzzy`（近似匹配需人工确认）、
`upstream_unreachable`（回退到上次成功数据）。

## 5. 口径要点（都有实测依据，勿凭直觉改）

> 以下是**通用聚合口径**（四层一致，数值来自 ipran 层实测）；分层 / 站名清洗 /
> 带宽解析的**按层差异**在 `layers.py`，不在本节。

- **折叠取最小端口速率**：一对机框之间有 9 条、10 条链路时，看的是「还剩多少条最窄的」，
  取最大值会虚报容量。
- **端口速率从链路名解析**，不用 UME 的 `rate` 字段 —— 那是枚举码，含义未获确认。
- **模糊匹配带数字守卫**：`12th Street` 与 `18th Street` 相似度 0.94，但这是两条街。
- **告警不做节点填色**：80% 的网元带 critical 告警，填色等于全红。
- **层外设备必须保留**：89MW02 的度达 10，丢了对端会让核心节点看起来孤立。
- **层外设备名从 UME 取**，不从链路名切分（设备名含下划线、板卡名也用 `-`，切分必错）。

## 6. 排障

| 症状 | 先看 |
| --- | --- |
| 页面全空 + 「上游取数失败」 | 后端日志 `[IPRAN-TOPO]` / `[LOGIN]`；凭据组 `ipran_ume` 是否有效（账号锁号 1440 分钟风险见 `05-security-and-credentials.md`） |
| 坐标大量为空（`geo_miss` 很多） | `kml_mw_links` 是否有 `kind='site'` 行；`refresh=1` 重载 |
| 结果一直是旧的 | `meta.fetchedAt` / `meta.cached`；改完代码要重启 7038 |
| 告警数全是 0 | `/api/fm-active/v1/north/statistic/me` 的 `maintainstatus=0` 参数是否被上游改动 |
| 新增三层节点全挤在同一条分带 | 当前 `tier_rules` 把整层判成同一级：跑第 7 节探层，按实测 moc 补规则 |
| 新增三层带宽全是 null / 站点坐标大量 miss | 链路名与设备命名跟 IP RAN 不同：按探层报告补 `speed_res` / `site_strip` |
| `/graph` 返回 400「未知拓扑层」 | `layer` 必须是 `layers.LAYERS` 的 key；先调 `/layers` 拿清单 |

## 7. 探层校准（新增三层上线前必做）

`layers.py` 除 ipran 外的口径是按抓包 moc 推断的默认，需在内网跑一次只读探层。
在 `Task/my_app` 下用**项目 Python 环境**（缺 requests / pandas 会明确报错）执行：

    python -m backend.services.ipran_topo.probe_layers --layer ipcore
    python -m backend.services.ipran_topo.probe_layers --out D:\tmp\topo_probe.json

脚本只读、不向 UME 写、不打印凭据、默认不落盘。报告给出每层真实 moc 分布、
网元/链路命名样例、当前口径下的 tier 分布与带宽解析命中率，并自动列出 `alerts`。
据此**只改 `layers.py`** 的 `tier_rules` / `site_strip` / `speed_res`，不要动聚合逻辑。
一次约 20~28 次上游调用，别频繁跑（UME 账号有锁号风险）；`--layer` 可只探一层。

改完后端代码**必须重启 7038**（uvicorn 无 reload 时不会热更；watchdog 会自动拉起）：
只杀 7038 的 uvicorn PID，不要用 `stop.bat`（会连 10 个 worker 一起停）。
