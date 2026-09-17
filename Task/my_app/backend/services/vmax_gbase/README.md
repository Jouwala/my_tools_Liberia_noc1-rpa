# vmax_gbase —— VMAX 数仓 GBase 8a 只读客户端

用户 JupyterLab notebook（`OLIB SOC VMAX Routine Report`）里的 `VmaxTool.GetDBConn("GBASE")` 就是
**直连 VMAX 数仓 GBase 8a**（MySQL 协议）取数。本包把这个数据通道抽成可复用的只读客户端，
供 `backend/services/olib_soc_report` 等任务使用；所有实测证据都记在下面，便于日后换环境时复现。

## 1. 为什么直连数仓（而不是走门户 vreport 接口）

| | 门户 vreport 接口（任务 41 `vmax_multi_data`） | 数仓 GBase 直连（本包 / 任务 42） |
|---|---|---|
| 粒度 | 只有报表预定义的 5min/hour/day/week/month | 任意聚合 / group by |
| 维度 | 报表 design.json 里选中的维度 | 任何字段：`targetid`、`service_id`、`subservice_id`、`server_ip`、`msisdn`… |
| 行数 | **TopN 截断且翻页无效**（实测 topN=200 只回 2000 行） | 无限制 |
| 业务拆分 | 拿不到 | 业务 / APP / 缓存服务器 / 网元全都能拆 |
| 口径 | 基准 | **逐字节一致**（见 §4） |

> 结论：门户数据用来做「实时看板/趋势」；要出 notebook 那种「业务+APP+网元+TCP 质量」的表，
> 必须直连数仓。两者口径实测相同，所以数仓结果可以直接替代人工 notebook。

## 2. 连接事实（2026-09-16 实测）

| 项 | 值 |
|---|---|
| 地址 | `10.123.255.12:5258`（TLS 不需要；TCP 直连可达） |
| 协议 | **MySQL 协议**，服务端版本 `8.6.2.43-R35.5_patch.1674d63d6` |
| 握手 | 旧式握手：不宣告 `CLIENT_PLUGIN_AUTH`，能力位 `0xf7ff` |
| 客户端 | **pymysql**（`requirements.txt` 已加 `pymysql>=1.1.0`）；psycopg2/postgres 不可用 |
| 库 | `zxvmax`；`CURRENT_USER()='gbase@%'`（通配授权，无网段限制）；本机 NAT 源地址被识别为 `gbase@10.16.151.254` |
| 账号 | 凭据分组 `vmax_gbase`（`gbase` / 密码在「设置 → 凭据管理」或 `VMAX_GBASE_PASS` 环境变量；代码默认值见 `credential_store.CREDENTIAL_GROUPS`） |
| 同理 | Spark Thrift `10.123.255.10:18000`（用户 `zxvmax`）也能连，但本包只用 GBase |

### 只读纪律

```python
from backend.services.vmax_gbase import VmaxGbaseClient
with VmaxGbaseClient() as c:                     # 自动 connect/close
    print(c.scalar("select count(*) from dim_service"))
```

* `_assert_readonly()` 只放行 `SELECT / SHOW / DESC / DESCRIBE / EXPLAIN / WITH`，
  其它语句一律抛 `VmaxGbaseError`（本包从设计上就不会写生产库）。
* 连接参数白名单：配置里多写的说明性字段不会传给 pymysql 导致连接失败。

## 3. 表与分区保留期（`SHOW TABLES LIKE` 实测 2026-09-16）

| 表族 | 粒度 | 分区数 | 覆盖 | 备注 |
|---|---|---|---|---|
| `aggr_5gsa_flow_ciservice` | day | 90 | 20260618 ~ 20260916 | **缺 20260907** |
| `aggr_5gsa_flow_ciservice` | hour | 94 | — | 小时级要用 `_hour_` 表 |
| `aggr_5gsa_flow_ciservice` | 15min | 11 | 20260909 ~ 20260919 | 含未来空分区 |
| `aggr_ds_250024`（活跃用户） | day | 96 | 20260616 ~ 20260919 | |
| `aggr_5gsa_flow_spservice` / `aggr_5gsa_video_spservice` / `aggr_5gsa_game_spservice` | day | ~90 | 同上 | 业务/APP 维度 |
| `aggr_5gsa_spservice` | month | 2 | 202509 / 202510 | |

推论与教训：

1. **门户页面上的「可选 90 天」= 数仓分区保留期**（不是页面限制），两者天然一致；
2. 分区会**缺表**（如 20260907）与**出现未来空分区**，所以取数前一律 `SHOW TABLES LIKE` 探分区，
   缺表按「跳过并记录」处理（`available_days()` 返回 `(有表日, 缺表日)`）；
3. `_day_` 表里 `hh` 只有 0，要小时级必须换 `_hour_` 表；
4. 基表（`aggr_5gsa_flow_ciservice` 无分区后缀）当前 `LIMIT 1` 查不到数据，**必须带分区后缀**。

## 4. 口径对账（为什么敢直接替代人工 notebook）

* **总额**：2026-09-15 数仓 `SUM(ppb400401001+ppb400401002)=299326487733949` 字节，
  与门户 `ppc400401001` 合计**逐字节相同**（上/下行 33589790199375 / 265736697534574）。
* **维度成员**：2026-09-10 门户 9 个维度成员与数仓按 `targetid` 分组**逐个数值精确匹配**，
  并据此确定映射：`50331658→SGW_HQ_122`、`50331660→SGW_ODC_22`、`0→0`、
  `234881042→Gardnesville JJY Comm`、`234881143→Sand Beach`、`234881205→Vai Town`、
  `234881338`/`234881110→Town Hall`、`234881127→Lakpazee`。
* **多日回归**：2026-09-11 ~ 09-15 数仓与门户天粒度**每天一致**（见
  `tests/test_olib_soc_report.py --live` 第 10 节，会自动对账最近 5 个已完成日）。
* **⚠️ 「当天」是移动靶**：2026-09-16 16:50 抓的门户快照是 68.31 TB，19:50 再查门户与数仓
  **同为 122.25 TB** —— 两边口径一致，只是当天分区在持续累积。因此报表默认出**上一个自然月**，
  窗口含当天时摘要里会标 `partial_days` 并给出警告。
* **⚠️ 上游也会缺数**：2026-08-11~14 活跃用户表 `aggr_ds_250024` 当天只有 1.3~5.3 万行
  （正常 2,049 万行），活跃用户数掉到 401~102,786，而同期流量/TCP 指标完全正常 ——
  数仓只是忠实反映上游采集缺数。使用方（`olib_soc_report`）因此加了「当日主指标 vs 窗口中位数」
  的数据量自检，把这类日子标出来而不是当成真实 KPI 展示。

## 5. API

```python
from backend.services.vmax_gbase import (
    VmaxGbaseClient, VmaxGbaseError, VmaxGbaseUnavailable,
    resolve_dsn, dsn_summary, day_range, day_table, partition_days, available_days,
)

VmaxGbaseClient(cfg=None, dsn=None, credential_key="vmax_gbase", **overrides)
    .connect() / .close() / with 语句 / .connected
    .query(sql, params=None)        -> (columns, rows)
    .query_dicts(sql, params=None)  -> [dict]
    .query_df(sql, params=None)     -> pandas.DataFrame（本机已装 pandas）
    .scalar(sql)                    -> 单值
    .healthy()                      -> (bool, "版本 | CURRENT_USER | db | 地址")
    .tables_like(pattern) / .table_exists(t) / .describe(t)
    .partition_days(family, granularity="day") -> ["20260915", ...]
    .available_days(family, begin, end, granularity="day") -> (有表日, 缺表日)
    .latest_day(family) / .queries / .seconds
```

* 参数优先级：`DEFAULT_DSN` < 传入配置 < 环境变量（`VMAX_GBASE_HOST/PORT/DB/USER/PASS`）< 凭据库；
  `dsn_summary()` 输出脱敏串（不含密码），可直接写日志/摘要。
* 断线自愈：`_execute()` 遇到 `2006/2013/2014/2055` 或 `Lost connection` 会自动重连重试（默认 2 次）。
* **线程模型**：pymysql 连接不能跨线程共用，多线程取数请每线程各自 `VmaxGbaseClient`
  （`olib_soc_report` 里的 `_ClientPool` 就是这么做的）。

## 6. 相关文件

* 客户端：`backend/services/vmax_gbase/vmax_gbase_client.py`
* 使用方：`backend/services/olib_soc_report/`（任务 42 `olib_soc_vmax_report`）
* 对照实现（门户接口）：`backend/services/vmax_multi_data/`
* 自测：`python tests/test_olib_soc_report.py [--live]`
