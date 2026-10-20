"""OLIB SOC VMAX 例行报表（直连 GBase 数仓，SQL 取自用户的 notebook）。

数据来源
--------
用户 JupyterLab 上的 `OLIB SOC VMAX Routine Report` notebook：`import VmaxTool as vt`，
`vt.GetDBConn("GBASE")` 拿到 `['GBASE','10.123.255.12','5258','gbase',<password>,'zxvmax']`
（口令不写在这里，2026-10-04 改为占位符；实际值走 `credential_store` 的 `vmax_gbase` 分组），
然后按天循环 `vt.QueryDB_df(dsn, sql)`，最后写成一个多 sheet 的 Excel。本模块把那 9 段 SQL
原样移植过来（只把表名做成参数），并补上窗口/分片/容错/落库/可选邮件。

为什么直连数仓（而不是走门户 vreport 接口，见 backend/services/vmax_multi_data）
------------------------------------------------------------------------------
* 门户接口只有预聚合粒度（hour/day/week/month）且**单请求按 TopN 截断、翻页无效**，
  拿不到「按业务/APP/缓存服务器/网元」的拆分；
* 直连可任意聚合，且实测与门户口径**逐字节一致**（2026-09-15 总额 299326487733949 双方相同，
  9 个维度成员逐个数值精确匹配），所以门户上的数字能 1:1 复现；
* 保留期（`SHOW TABLES LIKE` 实测）：`_day_` ≈ 90 天、`_hour_` ≈ 94 天、`_15min_` = 11 天。
  注意会有缺表（如 20260907）与未来空分区，取数前一律探测分区再查。

9 个报表块 → 9 个 sheet（与 notebook 的 sheet 名保持一致）
--------------------------------------------------------
    traffic       每日总流量 TB                    aggr_5gsa_flow_ciservice_day_*
    Active_user   活跃用户数（distinct msisdn）     aggr_ds_250024_day_*
    cache         缓存 / 非缓存 服务器流量与 RTT     aggr_5gsa_flow_spservice_day_*
    GUW           核心网元（SGW_HQ_122 / SGW_ODC_22）aggr_5gsa_flow_ciservice_day_*
    Video         视频 APP 流量与下载速率            aggr_5gsa_video_spservice_day_*
    game          游戏 APP 流量与 RTT                aggr_5gsa_game_spservice_day_*
    TCP           TCP 成功率/重传/乱序/丢包/RTT      aggr_5gsa_flow_ciservice_day_*
    df_TOP_Service TOP 业务流量                     aggr_5gsa_flow_spservice_day_*
    df_TOP_Video   TOP 视频 APP 流量                aggr_5gsa_flow_spservice_day_*

用法
----
    # 上一个自然月（默认，任务用）
    python -m backend.services.olib_soc_report.olib_soc_report_service

    # 指定窗口 / 最近 N 天 / 上一周
    python -m backend.services.olib_soc_report.olib_soc_report_service --start 2026-08-01 --end 2026-08-31
    python -m backend.services.olib_soc_report.olib_soc_report_service --mode last_n_days --days 7
    python -m backend.services.olib_soc_report.olib_soc_report_service --mode weekly

    # 体检（只连库看版本/分区，不取数）
    python -m backend.services.olib_soc_report.olib_soc_report_service --check

    # 只跑某几个块，打印明细
    python -m backend.services.olib_soc_report.olib_soc_report_service --blocks traffic,GUW --full

产物：`data/olib_soc_report/OLIB SOC VMAX <label>.xlsx` + `olib_soc_report.sqlite3`
（report_runs 每次运行 / block_runs 每个块），摘要同时写 `<run_id>.summary.json`。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

if __package__ in (None, ""):                                            # 直接 python 跑本文件时
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.services.vmax_gbase import vmax_gbase_client as vgc
from backend.services.olib_soc_report import olib_soc_kpi_store as kpi_store

logger = logging.getLogger("olib_soc_report")

_ROOT = Path(__file__).resolve().parents[3]                              # my_app/
CONFIG_PATH = Path(__file__).resolve().parents[1] / "olib_soc_report_config.json"
DATA_DIR = _ROOT / "data" / "olib_soc_report"
SQLITE_PATH = DATA_DIR / "olib_soc_report.sqlite3"

# 缓存服务器判定用的 IP（notebook 里硬编码的 5 个，放配置里便于维护）
DEFAULT_CACHE_IPS = ["41.191.107.211", "41.191.107.212", "41.191.107.222",
                     "41.191.107.225", "41.191.107.228"]
# 分业务「本地 / 海外」分流用 sp_country_id（服务器所在国家，32=Liberia，
# 取自 dim_comm_country_scr；用缓存段 IP 反查实测两个缓存集群 100% 落在 32）。
# 不用 IP 白名单：上面那 5 个 IP 只是 Facebook 视频那几台，同集群的 WhatsApp 缓存
# （41.191.107.227/.226/.224）与整套 Google 缓存（196.49.16.0/24：YouTube/Play/Ads）
# 都不在里面 —— 2026-10-19 实测各漏 3.73 TB 与 10.28 TB。国家维度不用维护清单。
LOCAL_COUNTRY_ID = 32
# 全量业务都落库、不按流量阈值截断：接口只展示 TOP N + 「其它」rollup，但「合计」必须
# 等于当日总流量，否则下钻表格的合计与 traffic 卡片对不上账（实测截 5GB 少 0.46TB/0.33%）。
# 实测规模：单日 3000~3800 个业务（绝大多数是长尾），90 天约 29 万行，库文件 +30MB，
# 接口一次窗口聚合 0.2s（点一次才查一次，可接受）。
# 核心网元 targetid → 名称（notebook 里 CASE WHEN 50331658 = SGW_HQ_122）
DEFAULT_TARGET_NAMES = {"50331658": "SGW_HQ_122", "50331660": "SGW_ODC_22"}
# 视频 / 游戏业务 (service_id, subservice_id)（notebook 里写死的组合）
DEFAULT_VIDEO_APPS = [[5, 26], [5, 74961], [5, 74676]]
DEFAULT_GAME_APPS = [[8, 74866], [8, 80693], [8, 78027]]

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "gbase": {"host": "10.123.255.12", "port": 5258, "user": "gbase",
              "database": "zxvmax", "charset": "utf8mb4",
              "connect_timeout": 8, "read_timeout": 300},
    "credential_key": "vmax_gbase",
    # 窗口：last_month(默认) / this_month / last_n_days / weekly / explicit
    "range_mode": "last_month",
    "days": 30,
    "max_days": 92,                       # 数仓 `_day_` 只留 ~90 天，超了没数据
    "granularity": "day",
    "workers": 3,                         # 每天每块一条 SQL；3 个并发连接足够且不压库
    "cache_server_ips": list(DEFAULT_CACHE_IPS),
    "core_target_names": dict(DEFAULT_TARGET_NAMES),
    # 与 notebook 一致：未映射的 targetid（站点级小流量）并入 SGW_ODC_22；留空则按 target_<id> 分开
    "core_fold_unmapped_to": "SGW_ODC_22",
    "video_apps": [list(x) for x in DEFAULT_VIDEO_APPS],
    "game_apps": [list(x) for x in DEFAULT_GAME_APPS],
    "top_service_limit": 20,
    "top_video_limit": 10,
    # 看板数据源（?page=vmaxCxoDashboard_90Days）的每日增量同步参数
    "kpi_sync": {"days_back": 7, "only_missing": True, "refresh_last_days": 1},
    "blocks": {"traffic": True, "active_user": True, "cache": True, "core": True,
               "video": True, "game": True, "tcp": True, "top_service": True,
               "top_video": True},
    "persist": {"write_excel": True, "write_sqlite": True, "keep_csv": False,
                "write_kpi": True},
    "mail": {"enabled": False, "smtp_host": "smtp.126.com", "smtp_port": 465,
             "credential_key": "mail_126", "sender": "", "sender_name": "ZTE NOC",
             "recipients": [], "subject_prefix": "OLIB SOC VMAX Report"},
}

# 块定义：sheet 名与 notebook 完全一致；family = 表族；sql = 带 {t} 占位的模板
BLOCKS: Dict[str, Dict[str, Any]] = {
    "traffic": {
        "sheet": "traffic", "title": "每日总流量", "family": vgc.FAMILY_FLOW_CISERVICE,
        "sql": """
select t.clttime, round(SUM(ppb400401001 + ppb400401002)/1024/1024/1024/1024,2) as Total_traffic_TB
from (
    select clttime, SUM(ppb400401002) as ppb400401002, SUM(ppb400401001) as ppb400401001
    from {t}
    group by clttime
) t
group by clttime order by clttime asc"""},
    "active_user": {
        "sheet": "Active_user", "title": "活跃用户数", "family": vgc.FAMILY_DS_250024,
        "sql": """
select clttime, count(distinct msisdn) as Active_user_cnt
from {t}
group by clttime order by clttime asc"""},
    "top_service": {
        "sheet": "df_TOP_Service", "title": "TOP 业务流量", "family": vgc.FAMILY_FLOW_SPSERVICE,
        "sql": """
select t.clttime, servicename, Round(SUM(ppb400401001 + ppb400401002)/1024/1024/1024/1024,2) as TrafficTB
from (
    select clttime, service_id, SUM(ppb400401002) as ppb400401002, SUM(ppb400401001) as ppb400401001
    from {t}
    group by service_id, clttime
) t left join (select serviceid, servicename from dim_service group by serviceid, servicename) b
    on t.service_id = b.serviceid
group by servicename, clttime
order by clttime asc, TrafficTB desc
limit {top_service_limit}"""},
    "top_video": {
        "sheet": "df_TOP_Video", "title": "TOP 视频 APP", "family": vgc.FAMILY_FLOW_SPSERVICE,
        "sql": """
select t.clttime, servicename, appname, Round(SUM(ppb400401001 + ppb400401002)/1024/1024/1024/1024,2) as TrafficTB
from (
    select clttime, service_id, subservice_id, SUM(ppb400401002) as ppb400401002, SUM(ppb400401001) as ppb400401001
    from {t}
    where (service_id = 5)
    group by service_id, subservice_id, clttime
) t left join (select serviceid, servicename, appid, appname from dim_service
                group by serviceid, servicename, appid, appname) b
    on t.service_id = b.serviceid and t.subservice_id = b.appid
group by servicename, appname, clttime
order by clttime asc, TrafficTB desc
limit {top_video_limit}"""},
    "tcp": {
        "sheet": "TCP", "title": "TCP 流量与性能", "family": vgc.FAMILY_FLOW_CISERVICE,
        "sql": """
select t.clttime,
    (CASE WHEN SUM(ppb400403020) = 0 THEN 100 ELSE ROUND(SUM(ppb400403021)*100.0/SUM(ppb400403020),2) END) as Avg_TCP_Connection_Successful_Rate,
    (CASE WHEN SUM(ppb400403007) = 0 THEN 0 ELSE ROUND(SUM(ppb400403015)*100.0/SUM(ppb400403007),2) END) as Avg_TCP_UL_Retrans_Rate,
    (CASE WHEN SUM(ppb400403008) = 0 THEN 0 ELSE ROUND(SUM(ppb400403016)*100.0/SUM(ppb400403008),2) END) as Avg_TCP_DL_Retrans_Rate,
    (CASE WHEN SUM(ppb400403007) = 0 THEN 0 ELSE ROUND(SUM(ppb400403013)*100.0/SUM(ppb400403007),2) END) as Avg_TCP_UL_Disorder_Rate,
    (CASE WHEN SUM(ppb400403008) = 0 THEN 0 ELSE ROUND(SUM(ppb400403014)*100.0/SUM(ppb400403008),2) END) as Avg_TCP_DL_Disorder_Rate,
    Round(SUM(ppb400403001 + ppb400403002)/1024/1024/1024/1024,2) as TCP_Total_Traffic_TB,
    (CASE WHEN SUM(ppb400403007) = 0 THEN 0 ELSE ROUND(SUM(ppb400403041)*100.0/SUM(ppb400403007),2) END) as Avg_TCP_UL_Lost_Rate,
    (CASE WHEN SUM(ppb400403008) = 0 THEN 0 ELSE ROUND(SUM(ppb400403042)*100.0/SUM(ppb400403008),2) END) as Avg_TCP_DL_Lost_Rate,
    (CASE WHEN SUM(ppb400403038) = 0 THEN 0 ELSE ROUND(SUM(ppb400403044)*1.0/SUM(ppb400403038),2) END) as Avg_Tcp_UL_RTT_ms,
    (CASE WHEN SUM(ppb400403039) = 0 THEN 0 ELSE ROUND(SUM(ppb400403045)*1.0/SUM(ppb400403039),2) END) as Avg_Tcp_DL_RTT_ms
from (
    select clttime, SUM(ppb400403021) as ppb400403021, SUM(ppb400403020) as ppb400403020,
           SUM(ppb400403007) as ppb400403007, SUM(ppb400403015) as ppb400403015,
           SUM(ppb400403008) as ppb400403008, SUM(ppb400403016) as ppb400403016,
           SUM(ppb400403013) as ppb400403013, SUM(ppb400403014) as ppb400403014,
           SUM(ppb400403001) as ppb400403001, SUM(ppb400403002) as ppb400403002,
           SUM(ppb400403041) as ppb400403041, SUM(ppb400403042) as ppb400403042,
           SUM(ppb400403038) as ppb400403038, SUM(ppb400403044) as ppb400403044,
           SUM(ppb400403039) as ppb400403039, SUM(ppb400403045) as ppb400403045
    from {t}
    group by clttime
) t
group by clttime order by clttime asc"""},
    "cache": {
        "sheet": "cache", "title": "缓存 / 非缓存服务器", "family": vgc.FAMILY_FLOW_SPSERVICE,
        "sql": """
select t.clttime,
    (case when t.Server_ip in ({cache_ips}) then 'Cache_server' else 'Non_Cache_server' end) as server_type,
    round(SUM(ppb400402001 + ppb400402002 + ppb400403001 + ppb400403002)/1024/1024/1024/1024,2) as Total_traffic_TB,
    (CASE WHEN SUM(ppb400403038) = 0 THEN 0 ELSE ROUND(SUM(ppb400403044)*1.0/SUM(ppb400403038),2) END) as Avg_Tcp_UL_RTT_ms,
    (CASE WHEN SUM(ppb400403039) = 0 THEN 0 ELSE ROUND(SUM(ppb400403045)*1.0/SUM(ppb400403039),2) END) as Avg_Tcp_DL_RTT_ms
from (
    select clttime, server_ip, SUM(ppb400403020) as ppb400403020, SUM(ppb400402001) as ppb400402001,
           SUM(ppb400402002) as ppb400402002, SUM(ppb400403001) as ppb400403001,
           SUM(ppb400403002) as ppb400403002, SUM(ppb400403038) as ppb400403038,
           SUM(ppb400403044) as ppb400403044, SUM(ppb400403039) as ppb400403039,
           SUM(ppb400403045) as ppb400403045
    from {t}
    group by server_ip, clttime
) t
group by server_type, t.clttime"""},
    "core": {
        "sheet": "GUW", "title": "核心网元流量与 RTT", "family": vgc.FAMILY_FLOW_CISERVICE,
        "sql": """
select t.clttime, {core_case} as Target_NE,
    round(SUM(ppb400402001 + ppb400402002 + ppb400403001 + ppb400403002)/1024/1024/1024/1024,2) as Total_Traffic_TB,
    (CASE WHEN SUM(ppb400403038) = 0 THEN 0 ELSE ROUND(SUM(ppb400403044)*1.0/SUM(ppb400403038),2) END) as Avg_Tcp_UL_RTT_ms,
    (CASE WHEN SUM(ppb400403039) = 0 THEN 0 ELSE ROUND(SUM(ppb400403045)*1.0/SUM(ppb400403039),2) END) as Avg_Tcp_DL_RTT_ms
from (
    select clttime, targetid, SUM(ppb400402001) as ppb400402001, SUM(ppb400402002) as ppb400402002,
           SUM(ppb400403001) as ppb400403001, SUM(ppb400403002) as ppb400403002,
           SUM(ppb400403038) as ppb400403038, SUM(ppb400403044) as ppb400403044,
           SUM(ppb400403039) as ppb400403039, SUM(ppb400403045) as ppb400403045
    from {t}
    group by targetid, clttime
) t
group by Target_NE, clttime order by clttime asc"""},
    "video": {
        "sheet": "Video", "title": "视频业务流量与速率", "family": vgc.FAMILY_VIDEO_SPSERVICE,
        "sql": """
select t.clttime, a.appname,
    round(SUM(ppb400464001 + ppb400464002)/1024/1024/1024/1024,2) as Total_traffic_TB,
    (CASE WHEN SUM(ppb400464051*1024) = 0 THEN 0 ELSE ROUND(SUM(ppb400464018*8000)*1.0/SUM(ppb400464051*1024*1024),2) END) as Valid_video_download_throughput_Mbps
from (
    select clttime, service_id, subservice_id, SUM(ppb400464002) as ppb400464002,
           SUM(ppb400464001) as ppb400464001, SUM(ppb400464051) as ppb400464051,
           SUM(ppb400464018) as ppb400464018
    from {t}
    where ((service_id, subservice_id) in ({video_apps}))
    group by subservice_id, service_id, clttime
) t
left join dim_service a on t.service_id = a.serviceid and t.subservice_id = a.appid
group by appname, clttime order by clttime asc"""},
    "game": {
        "sheet": "game", "title": "游戏业务流量与 RTT", "family": vgc.FAMILY_GAME_SPSERVICE,
        "sql": """
select t.clttime, a.appname,
    round(SUM(ppb400401001 + ppb400401002)/1024/1024/1024/1024,2) as Total_traffic_TB,
    (CASE WHEN SUM(ppb400403038) = 0 THEN 0 ELSE ROUND(SUM(ppb400403044)*1.0/SUM(ppb400403038),2) END) as Avg_TCP_UL_RTT_ms,
    (CASE WHEN SUM(ppb400403039) = 0 THEN 0 ELSE ROUND(SUM(ppb400403045)*1.0/SUM(ppb400403039),2) END) as Avg_TCP_DL_RTT_ms
from (
    select clttime, service_id, subservice_id, SUM(ppb400401001) as ppb400401001,
           SUM(ppb400401002) as ppb400401002, SUM(ppb400403038) as ppb400403038,
           SUM(ppb400403044) as ppb400403044, SUM(ppb400403039) as ppb400403039,
           SUM(ppb400403045) as ppb400403045
    from {t}
    where ((service_id, subservice_id) in ({game_apps}))
    group by service_id, subservice_id, clttime
) t
left join dim_service a on t.service_id = a.serviceid and t.subservice_id = a.appid
group by a.appname, clttime order by clttime asc"""},
}
# sheet 顺序（与 notebook 的 writer 顺序一致，便于人工对照）
SHEET_ORDER = ["traffic", "active_user", "cache", "core", "video", "game",
               "tcp", "top_service", "top_video"]
# 每块用来做「当日数据量体检」的主指标：某天该指标远低于窗口中位数 -> 疑似上游数据缺失
DAILY_METRIC = {
    "traffic": "Total_traffic_TB", "active_user": "Active_user_cnt",
    "cache": "Total_traffic_TB", "core": "Total_Traffic_TB", "video": "Total_traffic_TB",
    "game": "Total_traffic_TB", "tcp": "TCP_Total_Traffic_TB",
    "top_service": "TrafficTB", "top_video": "TrafficTB",
}
# 体检阈值：某天主指标 < 中位数 * SUSPECT_RATIO 且窗口 >= SUSPECT_MIN_DAYS 天就记一笔
# 实测依据：正常日流量波动只有 ±10%、活跃用户 ±15%，而 2026-08-12~14 活跃用户掉到中位数的
# 0.3%~0.08%（上游 aggr_ds_250024 当日只有 1.3~5.3 万行 vs 正常 2049 万行），0.5 倍足够稳。
SUSPECT_RATIO = 0.5
SUSPECT_MIN_DAYS = 5
QUALITY_SHEET = "_数据质量"
# 看板（?page=vmaxCxoDashboard_90Days）需要的块：比全量报表少 top_video，其余全部要用
KPI_BLOCKS = ["traffic", "active_user", "cache", "video", "game", "tcp", "top_service"]

# 「某天查出来是空」不算异常的块：这些块天然可能整天没有产出，缺一天不代表取数失败。
#   * top_service / top_video 是「TOP 业务」排行，理论上每天都有；但它们查的是 dim_service
#     关联后的聚合，若当天数仓该分区刚生成、关联表还没就绪，空结果是正常的过渡态。
#   * game 是游戏业务流量，运营侧可能整天没有游戏流量。
# 这些块的空天只记录、不降级（不触发 partial/告警）；其余「基础量块」（traffic/active_user/
# cache/video/tcp）每天都必须有数，空一天即为异常，计入 days_empty 并把块降级为 partial。
BLOCKS_ALLOW_EMPTY_DAY = {"top_service", "top_video", "game"}


# ==========================================================================
# 配置
# ==========================================================================
def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """读配置（缺文件/字段回退 DEFAULTS；嵌套字典做合并）。"""
    cfg = json.loads(json.dumps(DEFAULTS))                               # deep copy
    real = Path(path or CONFIG_PATH)
    if real.exists():
        try:
            data = json.loads(real.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                        cfg[key].update(value)
                    else:
                        cfg[key] = value
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[olib_soc] 配置读取失败，使用默认: %s", exc)
    if os.environ.get("OLIB_SOC_RANGE_MODE"):
        cfg["range_mode"] = os.environ["OLIB_SOC_RANGE_MODE"]
    if os.environ.get("OLIB_SOC_WORKERS"):
        try:
            cfg["workers"] = max(1, int(os.environ["OLIB_SOC_WORKERS"]))
        except ValueError:
            pass
    return cfg


def enabled_blocks(cfg: Dict[str, Any], keys: Optional[Iterable[str]] = None) -> List[str]:
    """按配置 + 命令行选择要跑的块（保持 SHEET_ORDER 顺序）。"""
    flags = cfg.get("blocks") or {}
    chosen = [k for k in SHEET_ORDER if flags.get(k, True)]
    if keys:
        wanted = {str(k).strip().lower() for k in keys if str(k).strip()}
        if "all" not in wanted:
            chosen = [k for k in chosen
                      if k.lower() in wanted or str(BLOCKS[k]["sheet"]).lower() in wanted]
    return chosen


# ==========================================================================
# 时间窗口
# ==========================================================================
def resolve_window(mode: Optional[str] = None, days: Optional[int] = None,
                   start: Any = None, end: Any = None,
                   today: Optional[date] = None) -> Tuple[str, str, str]:
    """算出 (begin, end, mode)，**统一返回 'YYYYMMDD'**（与 vgc 的分区/表名工具一致）。

    mode: last_month(默认) / this_month / last_n_days / weekly / explicit
    * last_month  = 上一个自然月整月
    * this_month  = 本月 1 号 ~ 今天
    * last_n_days = 最近 N 天（含今天）
    * weekly      = 上一个完整周（周一 ~ 周日）
    * explicit    = 用传入的 start/end（可与任何 mode 混用，给了 start/end 就优先）
    """
    today = today or date.today()
    if start and end:
        return vgc.norm_day(start), vgc.norm_day(end), "explicit"
    mode = str(mode or "last_month").strip().lower()
    if mode == "explicit":
        raise vgc.VmaxGbaseError("mode=explicit 必须同时给 start 与 end")
    if mode == "last_month":
        last_prev = today.replace(day=1) - timedelta(days=1)
        begin, end = last_prev.replace(day=1), last_prev
    elif mode == "this_month":
        begin, end = today.replace(day=1), today
    elif mode == "weekly":
        monday = today - timedelta(days=today.weekday() + 7)             # 上一个周一
        begin, end = monday, monday + timedelta(days=6)
    elif mode == "last_n_days":
        n = max(1, int(days or 30))
        begin, end = today - timedelta(days=n - 1), today
    else:
        raise vgc.VmaxGbaseError("不支持的 range_mode: %r（last_month/this_month/last_n_days/weekly/explicit）"
                                 % (mode,))
    return vgc.norm_day(begin), vgc.norm_day(end), mode


def clamp_window(begin: str, end: str, max_days: int) -> Tuple[str, str, Optional[str]]:
    """窗口超长时按「保留最近」截断，返回 (begin, end, 警告文本或 None)。"""
    span = (datetime.strptime(end, "%Y%m%d") - datetime.strptime(begin, "%Y%m%d")).days + 1
    if max_days <= 0 or span <= max_days:
        return begin, end, None
    new_begin = (datetime.strptime(end, "%Y%m%d") - timedelta(days=max_days - 1)).strftime("%Y%m%d")
    return new_begin, end, ("窗口 %d 天超过 max_days=%d（数仓 _day_ 只保留约 90 天），"
                            "已截断为 %s ~ %s" % (span, max_days, new_begin, end))


def window_label(mode: str, begin: str, end: str) -> str:
    """输出文件名用的标签（begin/end 为 'YYYYMMDD'）。"""
    if mode == "last_month" or (begin[:6] == end[:6] and begin[6:] == "01" and end[6:] >= "28"):
        return "Monthly-Report%s-%s" % (begin[:4], begin[4:6])           # OLIB SOC VMAX Monthly-Report2026-08
    if mode == "weekly":
        return "Weekly-Report%s_%s" % (begin, end)
    return "Range-Report%s_%s" % (begin, end)


# ==========================================================================
# SQL 组装
# ==========================================================================
def _sql_literal_list(values: Sequence[Any]) -> str:
    return ", ".join("'%s'" % str(v).replace("'", "''") for v in values)


def _pairs_sql(pairs: Sequence[Sequence[Any]]) -> str:
    return ", ".join("(%s, %s)" % (int(p[0]), int(p[1])) for p in pairs if len(p) >= 2)


def _core_case(cfg: Dict[str, Any]) -> str:
    """targetid → 网元名（与 notebook 的 CASE 等价，未映射项按配置归档）。"""
    mapping = cfg.get("core_target_names") or {}
    whens = " ".join("WHEN targetid = %s THEN '%s'" % (int(k), str(v).replace("'", "''"))
                     for k, v in mapping.items())
    fold = str(cfg.get("core_fold_unmapped_to") or "")
    fallback = ("'%s'" % fold.replace("'", "''")) if fold else "CONCAT('target_', targetid)"
    return "CASE %s ELSE %s END" % (whens or "1 = 0", fallback)


def build_sql(block: str, table: str, cfg: Dict[str, Any]) -> str:
    """把块模板里的占位符替换成实际值。"""
    spec = BLOCKS[block]
    return spec["sql"].format(
        t=table,
        cache_ips=_sql_literal_list(cfg.get("cache_server_ips") or DEFAULT_CACHE_IPS),
        core_case=_core_case(cfg),
        video_apps=_pairs_sql(cfg.get("video_apps") or DEFAULT_VIDEO_APPS),
        game_apps=_pairs_sql(cfg.get("game_apps") or DEFAULT_GAME_APPS),
        top_service_limit=int(cfg.get("top_service_limit") or 20),
        top_video_limit=int(cfg.get("top_video_limit") or 10),
    ).strip()


# ==========================================================================
# 连接池（pymysql 连接不能跨线程共用，故按线程各持一条）
# ==========================================================================
class _ClientPool:
    """按线程分配 GBase 连接（同一条连接不可多线程并发使用）。"""

    def __init__(self, cfg: Dict[str, Any]):
        self._cfg = cfg
        self._local = threading.local()
        self._all: List[vgc.VmaxGbaseClient] = []
        self._lock = threading.Lock()

    def get(self) -> vgc.VmaxGbaseClient:
        client = getattr(self._local, "client", None)
        if client is None:
            client = vgc.VmaxGbaseClient(self._cfg.get("gbase") or {},
                                         credential_key=self._cfg.get("credential_key"))
            client.connect()
            self._local.client = client
            with self._lock:
                self._all.append(client)
        return client

    @property
    def primary(self) -> vgc.VmaxGbaseClient:
        return self.get()

    def close_all(self) -> None:
        with self._lock:
            clients, self._all = self._all, []
        for c in clients:
            c.close()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            clients = list(self._all)
        return {"connections": len(clients),
                "queries": sum(c.queries for c in clients),
                "sql_seconds": round(sum(c.seconds for c in clients), 2)}


# ==========================================================================
# 取数
# ==========================================================================
def run_block(pool: _ClientPool, block: str, days: Sequence[str], cfg: Dict[str, Any],
              progress: bool = False) -> Dict[str, Any]:
    """跑一个报表块：逐日查该块的表分区，拼接成一张 DataFrame（按 clttime 升序）。

    除了 `days_missing`（分区不存在的天）与 `errors`（查询报错的天），本函数还输出
    `days_empty`：**该块本应有数却没拿到**的天，含两种情形 ——
      1. 分区不存在（`days_missing` 里、且不是窗口内的今天/未来）；
      2. 分区在、但查出来 0 行（上游分区刚生成/未完成时的过渡态）。
    背景（反复复发的事故）：旧逻辑只把「查询抛异常」记为 errors，导致「分区在但查出空」
    或「分区缺失」时块 status 仍是 ok —— 数据缺了一天却无人知晓，`daily_kpi` 里那列留
    NULL，看板对应卡片就「比其他指标少一天」。见 kpi_store.incomplete_days 的注释。

    `BLOCKS_ALLOW_EMPTY_DAY` 里的块（TOP 业务 / 游戏）天然可能整天无产出，只记录不降级。
    """
    import pandas as pd

    spec = BLOCKS[block]
    family = spec["family"]
    client = pool.get()
    # 只查「被请求的那些天」：缺口补齐时 days 可能不连续，不能按首尾区间张成整段
    days = sorted({vgc.norm_day(d) for d in days})
    present_all, _ = client.available_days(family, days[0], days[-1])
    have = set(present_all)
    wanted = set(days)
    present = [d for d in present_all if d in wanted]
    missing = [d for d in days if d not in have]
    # 窗口内的今天/未来日分区本就还没生成（当天仍在累积），不算「缺数」
    today_str = date.today().strftime("%Y%m%d")
    frames: List[Any] = []
    errors: List[str] = []
    empty_day: List[str] = []
    t0 = time.time()
    for day in present:
        table = vgc.day_table(family, day, cfg.get("granularity") or "day")
        sql = build_sql(block, table, cfg)
        try:
            df = pool.get().query_df(sql)
        except Exception as exc:                                         # noqa: BLE001
            message = "%s %s: %s" % (block, day, exc)
            logger.warning("[olib_soc] %s", message)
            errors.append(message)
            continue
        if df is not None and not df.empty:
            df = df.copy()
            if "clttime" in df.columns:
                df["clttime"] = pd.to_datetime(df["clttime"], errors="coerce")
            frames.append(df)
        elif day < today_str:                                            # 分区在却查出空：这天该有数
            empty_day.append(vgc.iso_day(day))
            logger.warning("[olib_soc] %s %s: 分区存在但查出 0 行", block, day)
        if progress:
            print("[olib_soc] %-12s %s -> %d 行" % (block, day, 0 if df is None else len(df)),
                  flush=True)
    # 分区缺失的天（排除今天/未来）同样算「本应有数却没拿到」
    for day in missing:
        if day < today_str:
            empty_day.append(vgc.iso_day(day))
    empty_day = sorted(set(empty_day))
    empty_is_error = block not in BLOCKS_ALLOW_EMPTY_DAY
    if frames:
        out = pd.concat(frames, ignore_index=True)
        if "clttime" in out.columns:
            out = out.sort_values("clttime", kind="stable").reset_index(drop=True)
    else:
        out = pd.DataFrame(columns=["clttime"])
    suspect = _suspect_days(block, out)
    if errors:
        status = "partial" if len(out) else "failed"
    elif empty_is_error and empty_day:
        # 有数但缺天 -> partial；**一天都没取到** -> failed（更强信号，别再当"正常"）
        status = "partial" if len(out) else "failed"
    else:
        status = "ok"
    return {"block": block, "sheet": spec["sheet"], "title": spec["title"],
            "family": family, "frame": out, "rows": int(len(out)),
            "days_present": len(present), "days_missing": missing,
            "days_empty": empty_day,
            "seconds": round(time.time() - t0, 2), "errors": errors,
            "suspect_days": suspect,
            "status": status}


def _suspect_days(block: str, frame: Any) -> List[Dict[str, Any]]:
    """当日数据量体检：主指标不足窗口中位数的 SUSPECT_RATIO 就记一笔（只提示，不改数据）。"""
    metric = DAILY_METRIC.get(block)
    if not metric or frame is None or frame.empty or metric not in frame.columns:
        return []
    if "clttime" not in frame.columns or frame["clttime"].isna().all():
        return []
    try:
        per_day = frame.groupby(frame["clttime"].dt.strftime("%Y%m%d"))[metric].sum()
    except Exception:                                                    # noqa: BLE001
        return []
    if len(per_day) < SUSPECT_MIN_DAYS:
        return []
    median = float(per_day.median())
    if median <= 0:
        return []
    out: List[Dict[str, Any]] = []
    for day, value in per_day.items():
        ratio = float(value or 0) / median
        if ratio < SUSPECT_RATIO:
            out.append({"day": str(day), "metric": metric, "value": round(float(value or 0), 2),
                        "median": round(median, 2), "ratio": round(ratio, 4)})
    return out


# ==========================================================================
# 落盘
# ==========================================================================
def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------- 日粒度 KPI 入库 ------------------------------
def kpi_db_path() -> Path:
    """看板 KPI 库位置：跟随本模块 `DATA_DIR`（单一真相源，便于测试隔离）。"""
    return Path(DATA_DIR) / kpi_store.KPI_DB_PATH.name


def _open_probe_client(cfg: Dict[str, Any]) -> Any:
    """开一条临时 GBase 连接做轻量元数据探测（如历史残留的分区预检）。

    调用方负责 `close()`；仅用于 `partition_days` 这类 SHOW TABLES 级探测，
    不进 `_ClientPool`（那条池是给正式取数用的）。
    """
    client = vgc.VmaxGbaseClient(cfg.get("gbase") or {},
                                 credential_key=cfg.get("credential_key"))
    client.connect()
    return client


def _by_day(frame: Any, column: str, how: str = "sum") -> Dict[str, float]:
    """把某块的结果按天聚合出一列 {YYYY-MM-DD: 值}。"""
    if frame is None or frame.empty or column not in frame.columns:
        return {}
    import pandas as pd

    work = frame.copy()
    if "clttime" not in work.columns:
        return {}
    work["_day"] = pd.to_datetime(work["clttime"], errors="coerce").dt.strftime("%Y-%m-%d")
    work = work[work["_day"].notna()]
    work[column] = pd.to_numeric(work[column], errors="coerce")
    grouped = work.groupby("_day")[column]
    series = grouped.sum() if how == "sum" else (grouped.max() if how == "max" else grouped.mean())
    return {str(k): float(v) for k, v in series.items() if v == v}       # 去掉 NaN


def _days_in(frame: Any) -> List[str]:
    """某块结果里出现过的日期（YYYY-MM-DD），用于统计每天有几块有数据。"""
    if frame is None or frame.empty or "clttime" not in frame.columns:
        return []
    import pandas as pd

    stamps = pd.to_datetime(frame["clttime"], errors="coerce").dropna()
    return sorted(set(stamps.dt.strftime("%Y-%m-%d")))


def extract_daily_kpi(results: Dict[str, Dict[str, Any]], run_id: str,
                      days: Sequence[str]) -> List[Dict[str, Any]]:
    """把各块的结果整理成 `daily_kpi` 的一行/天（看板数据源）。

    口径都取自 notebook 原 SQL 的列，此处只做「同一天多行 -> 一行」的合并：
      * 视频下载速率：按各 APP 的**流量加权**（简单平均会被小 APP 拉偏）
      * 缓存占比：分别汇总缓存/非缓存服务器的流量，占比留给查询时现算
      * TOP 业务：取当天 TrafficTB 最大的那行
    """
    import pandas as pd

    frames = {key: res.get("frame") for key, res in (results or {}).items()}
    traffic = _by_day(frames.get("traffic"), "Total_traffic_TB")
    active = _by_day(frames.get("active_user"), "Active_user_cnt", "max")
    game = _by_day(frames.get("game"), "Total_traffic_TB")
    tcp_tb = _by_day(frames.get("tcp"), "TCP_Total_Traffic_TB")
    tcp_succ = _by_day(frames.get("tcp"), "Avg_TCP_Connection_Successful_Rate", "mean")
    tcp_ul_re = _by_day(frames.get("tcp"), "Avg_TCP_UL_Retrans_Rate", "mean")
    tcp_dl_re = _by_day(frames.get("tcp"), "Avg_TCP_DL_Retrans_Rate", "mean")
    tcp_ul_rtt = _by_day(frames.get("tcp"), "Avg_Tcp_UL_RTT_ms", "mean")
    tcp_dl_rtt = _by_day(frames.get("tcp"), "Avg_Tcp_DL_RTT_ms", "mean")

    # 视频：流量合计 + 按流量加权的有效下载速率
    video_tb: Dict[str, float] = {}
    video_mbps: Dict[str, float] = {}
    vframe = frames.get("video")
    if vframe is not None and not vframe.empty and "Total_traffic_TB" in vframe.columns:
        work = vframe.copy()
        work["_day"] = pd.to_datetime(work["clttime"], errors="coerce").dt.strftime("%Y-%m-%d")
        work["Total_traffic_TB"] = pd.to_numeric(work["Total_traffic_TB"], errors="coerce")
        thr_col = "Valid_video_download_throughput_Mbps"
        work[thr_col] = pd.to_numeric(work.get(thr_col), errors="coerce") \
            if thr_col in work.columns else None
        for day, part in work.groupby("_day"):
            tb = float(part["Total_traffic_TB"].sum() or 0)
            video_tb[str(day)] = tb
            if thr_col in part.columns:
                weighted = part.dropna(subset=[thr_col, "Total_traffic_TB"])
                weight = float(weighted["Total_traffic_TB"].sum() or 0)
                if weight > 0:
                    video_mbps[str(day)] = float(
                        (weighted[thr_col] * weighted["Total_traffic_TB"]).sum() / weight)

    # 缓存 / 非缓存
    cache_tb: Dict[str, float] = {}
    noncache_tb: Dict[str, float] = {}
    cframe = frames.get("cache")
    if cframe is not None and not cframe.empty and "server_type" in cframe.columns:
        for kind, bucket in (("Cache_server", cache_tb), ("Non_Cache_server", noncache_tb)):
            part = cframe[cframe["server_type"] == kind]
            bucket.update(_by_day(part, "Total_traffic_TB"))

    # TOP 业务（每天取流量最大的一行）
    top_service: Dict[str, str] = {}
    top_service_tb: Dict[str, float] = {}
    tframe = frames.get("top_service")
    if tframe is not None and not tframe.empty and "TrafficTB" in tframe.columns:
        work = tframe.copy()
        work["_day"] = pd.to_datetime(work["clttime"], errors="coerce").dt.strftime("%Y-%m-%d")
        work["TrafficTB"] = pd.to_numeric(work["TrafficTB"], errors="coerce")
        for day, part in work.groupby("_day"):
            best = part.sort_values("TrafficTB", ascending=False).head(1)
            if len(best):
                top_service[str(day)] = str(best.iloc[0].get("servicename") or "")
                top_service_tb[str(day)] = float(best.iloc[0]["TrafficTB"] or 0)

    # 每天有几块拿到数据 + 数据质量标记
    blocks_ok: Dict[str, int] = {}
    suspects: Dict[str, List[Dict[str, Any]]] = {}
    for key, res in (results or {}).items():
        for day in _days_in(res.get("frame")):
            blocks_ok[day] = blocks_ok.get(day, 0) + 1
        for item in res.get("suspect_days") or []:
            # 带上块名便于看板/报表定位；day 统一成 ISO（原始 item 里是 YYYYMMDD）
            suspects.setdefault(vgc.iso_day(item.get("day")),
                                []).append({"block": key, **item})

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: List[Dict[str, Any]] = []
    for day in sorted({vgc.iso_day(d) for d in days}):
        if not any(day in bucket for bucket in (traffic, active, video_tb, cache_tb, noncache_tb,
                                                tcp_tb, game)):
            continue
        rows.append({
            "day": day, "traffic_tb": traffic.get(day), "active_user":
            int(active[day]) if active.get(day) is not None else None,
            "video_tb": video_tb.get(day), "video_mbps": video_mbps.get(day),
            "cache_tb": cache_tb.get(day), "noncache_tb": noncache_tb.get(day),
            "tcp_tb": tcp_tb.get(day), "tcp_success_pct": tcp_succ.get(day),
            "tcp_ul_retrans_pct": tcp_ul_re.get(day), "tcp_dl_retrans_pct": tcp_dl_re.get(day),
            "tcp_ul_rtt_ms": tcp_ul_rtt.get(day), "tcp_dl_rtt_ms": tcp_dl_rtt.get(day),
            "game_tb": game.get(day),
            "top_service": top_service.get(day), "top_service_tb": top_service_tb.get(day),
            "blocks_ok": blocks_ok.get(day), "suspect_json": suspects.get(day) or None,
            "run_id": run_id, "updated_at": now,
        })
    return rows


def persist_daily_kpi(results: Dict[str, Dict[str, Any]], run_id: str,
                      days: Sequence[str]) -> Dict[str, Any]:
    """把日粒度 KPI 写入 `daily_kpi`（看板数据源）。写库失败不影响报表产出。

    库文件跟随本模块的 `DATA_DIR`（测试把 DATA_DIR 指到临时目录时不会写进生产库）。
    """
    try:
        rows = extract_daily_kpi(results, run_id, days)
        db_path = kpi_db_path()
        written = kpi_store.upsert_days(rows, path=db_path)
        if written:
            logger.info("[olib_soc] 日粒度 KPI 入库 %d 天（%s ~ %s）", written,
                        rows[0]["day"], rows[-1]["day"])
        return {"days": written, "range": [rows[0]["day"], rows[-1]["day"]] if rows else None,
                "days_list": [r["day"] for r in rows], "db": str(db_path)}
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib_soc] 日粒度 KPI 入库失败: %s", exc)
        return {"days": 0, "error": "%s: %s" % (type(exc).__name__, exc)}


# ==========================================================================
# 分业务「本地 / 海外 / 未识别」服务器流量（看板点击下钻的数据源）
# 独立一步，不进 BLOCKS/SHEET_ORDER：那 9 个块是月报 Excel 的契约（与 notebook 逐日
# 对账过），加第 10 个块等于改月报结构；而这份明细只服务看板的下钻表格。
# ==========================================================================
def offload_sql(table: str) -> str:
    """单日分业务的本地/海外服务器流量三桶拆分。

    三桶互斥且相加=当日全量，所以 `本地占` 的分母用 `total - unknown`：
    DPI 解析不出 server_ip 的那部分（HTTPS/QUIC/UDP，实测约占全天 9%）既没走本地也没走
    海外，硬塞给任何一边都会把比例做歪。四个计数列相加沿用 cache 块原样写法（含它的
    NULL 传播特性），保证两块数字可对账。
    """
    flow = "(ppb400402001 + ppb400402002 + ppb400403001 + ppb400403002)"
    return """
select coalesce(d.appname, '<未识别业务>') as appname,
    round(sum(t.allb)/1024/1024/1024/1024, 4) as total_tb,
    round(sum(t.localb)/1024/1024/1024/1024, 4) as local_tb,
    round(sum(t.abroadb)/1024/1024/1024/1024, 4) as abroad_tb,
    round(sum(t.unknownb)/1024/1024/1024/1024, 4) as unknown_tb
from (
    select service_id, subservice_id,
        sum(""" + flow + """) as allb,
        sum(case when server_ip is not null and sp_country_id = """ + str(LOCAL_COUNTRY_ID) + """
                 then """ + flow + """ else 0 end) as localb,
        sum(case when server_ip is not null and sp_country_id is not null
                  and sp_country_id <> """ + str(LOCAL_COUNTRY_ID) + """
                 then """ + flow + """ else 0 end) as abroadb,
        sum(case when server_ip is null or sp_country_id is null
                 then """ + flow + """ else 0 end) as unknownb
    from """ + str(table) + """
    group by service_id, subservice_id
) t
left join (select serviceid, appid, min(appname) as appname
           from dim_service group by serviceid, appid) d
    on t.service_id = d.serviceid and t.subservice_id = d.appid
group by appname
order by total_tb desc"""


def _to_float(value: Any) -> Optional[float]:
    """GBase 的 decimal 列经 pymysql 回来是 Decimal，sqlite 绑不了 —— 落库前转 float。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):                                      # noqa: BLE001
        return None


def fetch_app_offload(client: Any, cfg: Dict[str, Any], days: Sequence[str],
                      run_id: str = "") -> Tuple[List[Dict[str, Any]], List[str]]:
    """逐日取分业务分流明细，返回 (明细行, 因上游分区已过期而跳过的天)。"""
    gran = str(cfg.get("granularity") or "day")
    want = [vgc.iso_day(d) for d in days]
    try:
        have = {vgc.iso_day(d) for d in
                client.partition_days(vgc.FAMILY_FLOW_SPSERVICE, gran)}
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib_soc] 分流块分区预检失败（改为逐日直接尝试）: %s", exc)
        have = set(want)
    rows: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for day in want:
        if day not in have:
            skipped.append(day)                                          # 超保留期，不徒劳查
            continue
        table = vgc.day_table(vgc.FAMILY_FLOW_SPSERVICE, day, gran)
        try:
            got = client.query_dicts(offload_sql(table))
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[olib_soc] %s 分业务分流取数失败: %s", day, exc)
            continue
        for item in got:
            # GBase 的 decimal(65,0) 经 pymysql 回来是 Decimal，直接绑进 sqlite 会
            # ProgrammingError（sqlite 不认 Decimal）—— 落库前一律转 float。
            rows.append({"day": day, "appname": item.get("appname"),
                         "total_tb": _to_float(item.get("total_tb")),
                         "local_tb": _to_float(item.get("local_tb")),
                         "abroad_tb": _to_float(item.get("abroad_tb")),
                         "unknown_tb": _to_float(item.get("unknown_tb")),
                         "run_id": run_id})
    return rows, skipped


def persist_app_offload(pool: Any, cfg: Dict[str, Any], days: Sequence[str],
                        run_id: str = "") -> Dict[str, Any]:
    """分业务分流明细落库；任何失败只记日志，不影响报表与 KPI 产出（同 persist_daily_kpi）。"""
    if pool is None:
        return {"rows": 0, "skipped": "无可用连接池"}
    try:
        rows, skipped = fetch_app_offload(pool.get(), cfg, days, run_id)
        written = kpi_store.upsert_app_offload(rows, path=kpi_db_path())
        if written:
            logger.info("[olib_soc] 分业务分流入库 %d 行 / %d 天", written,
                        len({r["day"] for r in rows}))
        return {"rows": written, "days": len({r["day"] for r in rows}),
                "skipped_no_partition": skipped}
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib_soc] 分业务分流入库失败: %s", exc)
        return {"rows": 0, "error": "%s: %s" % (type(exc).__name__, exc)}


def excel_path_for(label: str) -> Path:
    return DATA_DIR / ("OLIB SOC VMAX %s.xlsx" % label)


def write_excel(results: Dict[str, Dict[str, Any]], path: Path,
                keep_csv: bool = False) -> Optional[str]:
    """写多 sheet Excel（sheet 名与 notebook 一致；有数据质量异常时追加 `_数据质量` 表）。"""
    import pandas as pd

    _ensure_dirs()
    sheets = [(k, results[k]) for k in SHEET_ORDER if k in results]
    if not sheets:
        return None
    quality = []
    for key, res in sheets:
        for item in res.get("suspect_days") or []:
            quality.append({"block": key, "sheet": res["sheet"], **item})
    tmp = path.with_suffix(".xlsx.tmp")
    with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
        for key, res in sheets:
            df = res["frame"]
            if df is None or df.empty:
                df = pd.DataFrame({"note": ["窗口内无数据"]})
            df.to_excel(writer, sheet_name=str(res["sheet"])[:31], index=False)
        if quality:
            # 只在真有异常时追加，正常窗口的 sheet 集合仍与 notebook 完全一致
            pd.DataFrame(quality).to_excel(writer, sheet_name=QUALITY_SHEET[:31], index=False)
    os.replace(tmp, path)                                                # 原子替换，避免半截文件
    if keep_csv:
        csv_dir = path.parent / (path.stem + "_csv")
        csv_dir.mkdir(parents=True, exist_ok=True)
        for key, res in sheets:
            res["frame"].to_csv(csv_dir / ("%s.csv" % res["sheet"]), index=False,
                                encoding="utf-8-sig")
    return str(path)


def _sqlite() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(str(SQLITE_PATH), timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS report_runs (
        run_id TEXT PRIMARY KEY, mode TEXT, window_begin TEXT, window_end TEXT, days INTEGER,
        missing_days TEXT, status TEXT, blocks_ok INTEGER, blocks_failed INTEGER, rows INTEGER,
        excel_path TEXT, elapsed_seconds REAL, started_at TEXT, finished_at TEXT, error TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS block_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, block TEXT, sheet TEXT, rows INTEGER,
        days_present INTEGER, days_missing INTEGER, seconds REAL, status TEXT, error TEXT,
        executed_at TEXT)""")
    # 2026-10-15 补列 `invoked_by`：记录这次运算是**哪个 my_app 任务**发起的
    # （`run_olib_soc_report` / `run_olib_soc_kpi_sync`）。旧库缺列时按 ALTER 补上，
    # 存量行留 NULL。用途：任务列表的「最近运行」兜底（task_stats 提供者）需要把
    # 月度报表任务自己的运行与每日 KPI 同步借道 `run_olib_soc_report(kpi_only=True)`
    # 写入的 explicit_* 行区分开 —— 单看 mode 无法区分（两者都是 explicit），
    # 靠调用方标记才是显式、可自解释的判据。
    cols = {row[1] for row in conn.execute("PRAGMA table_info(report_runs)")}
    if "invoked_by" not in cols:
        conn.execute("ALTER TABLE report_runs ADD COLUMN invoked_by TEXT")
    conn.commit()
    return conn


def persist_run(summary: Dict[str, Any]) -> None:
    """记录一次运行（report_runs + 每块 block_runs）。失败只记日志，不影响报表产出。"""
    conn = _sqlite()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO report_runs (run_id, mode, window_begin, window_end, days,"
            " missing_days, status, blocks_ok, blocks_failed, rows, excel_path, elapsed_seconds,"
            " started_at, finished_at, error, invoked_by)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (summary["run_id"], summary["mode"], summary["window"][0], summary["window"][1],
             summary["days"], ",".join(summary.get("missing_days") or []), summary["status"],
             summary["blocks_ok"], summary["blocks_failed"], summary["rows"],
             summary.get("excel") or "", summary["elapsed_seconds"], summary["started_at"],
             summary["finished_at"], "; ".join(summary.get("errors") or [])[:2000],
             summary.get("invoked_by") or ""))
        for key, res in (summary.get("blocks") or {}).items():
            conn.execute(
                "INSERT INTO block_runs (run_id, block, sheet, rows, days_present, days_missing,"
                " seconds, status, error, executed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (summary["run_id"], key, res.get("sheet"), res.get("rows"),
                 res.get("days_present"), len(res.get("days_missing") or []), res.get("seconds"),
                 res.get("status"), "; ".join(res.get("errors") or [])[:1000],
                 summary["finished_at"]))
        conn.commit()
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib_soc] 运行记录写入失败: %s", exc)
    finally:
        conn.close()


def summary_json_path(run_id: str) -> Path:
    return DATA_DIR / ("%s.summary.json" % run_id)


def recent_runs_for_task(task_id: str = "olib_soc_vmax_report") -> List[Dict[str, Any]]:
    """任务列表「最近运行」兜底：从 `report_runs` 读该任务的最近若干次运行。

    背景（2026-10-15）：月报任务 cron 是每月 1 日，而任务列表读的
    `task_execution_log` 只保留 7 天 —— 月中查看时月报记录已被清掉，界面显示
    「No Record」。报表本身一直正常（产物与 `report_runs` 都在），这里把产物库
    的历史补回给任务列表。

    * 只返回**由该任务发起**的运行：每日 KPI 同步会借道
      `run_olib_soc_report(kpi_only=True)` 往 report_runs 写 explicit_* 行，靠
      `invoked_by` 区分（月度报表任务为 `olib_soc_vmax_report`）。存量旧行
      `invoked_by` 为 NULL，按「非 kpi 同步」处理 —— 用 `mode='last_month'` 兜底，
      因为同步写入的都是 explicit 模式。
    * 返回字段与前端 RunRecord 对齐（trigger 固定 `scheduled` 之外的值标为 `manual`，
      这里不区分触发源，统一 `scheduled`；success 由 status 推导为 ok/partial）。
    * 只读、异常吞掉返回空列表：列表接口绝不因此 500。
    """
    try:
        if not SQLITE_PATH.exists():
            return []
        conn = sqlite3.connect(str(SQLITE_PATH), timeout=5)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(report_runs)")}
            has_invoked = "invoked_by" in cols
            if has_invoked:
                # 归属本任务：显式标记为本任务，或（旧数据）模式为 last_month 的月报。
                where = ("WHERE invoked_by = ? OR (COALESCE(invoked_by,'') = '' AND mode = 'last_month')",
                         (task_id,))
            else:
                where = ("WHERE mode = 'last_month'", ())
            rows = conn.execute(
                "SELECT run_id, status, elapsed_seconds, started_at, finished_at, error"
                " FROM report_runs %s ORDER BY started_at DESC LIMIT 10" % where[0],
                where[1]
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib_soc] 读取 report_runs 作为最近运行失败: %s", exc)
        return []
    runs: List[Dict[str, Any]] = []
    for (run_id, status, elapsed, started_at, finished_at, error) in rows:
        # partial 仍算成功（块都跑完，只是某天缺数），与任务状态机口径一致；
        # 只有 failed / unavailable 记为失败，前端才会标红并显示 error。
        ok = status not in ("failed", "unavailable")
        runs.append({
            "task_id": task_id,
            # 不放翻译后的名字（提供者不知道调用方语言）；前端展示用的是 task.name，
            # 这里给 task_id 作为缺省即可。
            "task_name": task_id,
            "category": "olib_soc",
            "trigger": "scheduled",
            "success": bool(ok),
            "started_at": (started_at or "").replace(" ", "T"),
            "completed_at": (finished_at or "").replace(" ", "T"),
            "elapsed_seconds": float(elapsed or 0),
            "error": None if ok else (error or ("status=%s" % status)),
            "error_trace": None,
            # 便于排查/前端可选展示；RunRecord 允许额外字段
            "source": "provider",
            "run_id": run_id,
        })
    return runs


# ==========================================================================
# 邮件投递（默认关闭；配置 mail.enabled=true + recipients 才发）
# ==========================================================================
def deliver_mail(cfg: Dict[str, Any], xlsx: Optional[str], summary: Dict[str, Any]) -> Dict[str, Any]:
    mail = cfg.get("mail") or {}
    if not mail.get("enabled"):
        return {"sent": False, "skipped": "mail.enabled=false"}
    recipients = [str(r).strip() for r in (mail.get("recipients") or []) if str(r).strip()]
    if not recipients:
        return {"sent": False, "skipped": "mail.recipients 为空"}
    if not xlsx or not Path(xlsx).exists():
        return {"sent": False, "skipped": "没有可发送的 Excel"}
    try:
        from backend.services.credential_store import get_credential
    except Exception:                                                    # noqa: BLE001
        get_credential = None                                            # type: ignore[assignment]
    sender = mail.get("sender") or ""
    secret = ""
    if get_credential is not None:
        try:
            sender, secret = get_credential(str(mail.get("credential_key") or "mail_126"),
                                            sender, "")
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[olib_soc] 发信凭据读取失败: %s", exc)
    if not sender or not secret:
        return {"sent": False, "skipped": "缺少发信凭据（credential_store 分组 %s）"
                                          % mail.get("credential_key")}
    subject = "%s %s ~ %s" % (mail.get("subject_prefix") or "OLIB SOC VMAX Report",
                              summary["window"][0], summary["window"][1])
    rows_html = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (escape(str(res.get("sheet"))), escape(str(res.get("rows"))),
           escape(str(res.get("days_present"))), escape(str(res.get("status"))))
        for res in (summary.get("blocks") or {}).values())
    warn_html = ""
    if summary.get("warnings"):
        warn_html = ("<p style='color:#b00'><b>提示</b><br>%s</p>"
                     % "<br>".join(escape(str(w)) for w in summary["warnings"]))
    body = ("<html><body style='font-family:Arial,Microsoft YaHei,sans-serif'>"
            "<h3>OLIB SOC VMAX Report %s ~ %s</h3>"
            "<p>窗口 %s 天，块 %s 个，合计 %s 行，状态 %s。</p>%s"
            "<table border='1' cellspacing='0' cellpadding='6'>"
            "<tr><th>Sheet</th><th>行数</th><th>有数据天数</th><th>状态</th></tr>%s</table>"
            "</body></html>"
            % (escape(summary["window"][0]), escape(summary["window"][1]), summary["days"],
               summary["blocks_ok"], summary["rows"], escape(summary["status"]), warn_html,
               rows_html))
    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((str(mail.get("sender_name") or "ZTE NOC"), sender))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"] = formatdate(usegmt=True)
    msg.attach(MIMEText(body, "html", "utf-8"))
    with open(xlsx, "rb") as fh:
        part = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        part.set_payload(fh.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment; filename=\"%s\"" % Path(xlsx).name)
    msg.attach(part)
    try:
        with smtplib.SMTP_SSL(str(mail.get("smtp_host") or "smtp.126.com"),
                              int(mail.get("smtp_port") or 465), timeout=30) as server:
            server.login(sender, secret)
            server.sendmail(sender, recipients, msg.as_string())
        return {"sent": True, "recipients": recipients}
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib_soc] 邮件发送失败: %s", exc)
        return {"sent": False, "error": "%s: %s" % (type(exc).__name__, exc)}


# ==========================================================================
# 编排
# ==========================================================================
def run_olib_soc_report(mode: Optional[str] = None, days: Optional[int] = None,
                        start: Any = None, end: Any = None,
                        blocks: Optional[Iterable[str]] = None,
                        persist: bool = True, send_mail: Optional[bool] = None,
                        progress: bool = False, preview_rows: int = 0,
                        kpi_only: bool = False, excel: Optional[bool] = None,
                        client: Any = None,
                        config_path: Optional[Path] = None,
                        today: Optional[date] = None,
                        invoked_by: Optional[str] = None) -> Dict[str, Any]:
    """任务入口（注册给 task_runner，无参调用）：出 OLIB SOC VMAX 报表并落盘。

    * client 仅供测试注入（假客户端）；正常走 `_ClientPool` 自建连接。
    * preview_rows>0 时摘要里附每块前 N 行明细（CLI --full 用）。
    * persist=False 时只返回摘要，不写 Excel / sqlite / KPI 库 / 摘要 JSON。
    * kpi_only=True 时只跑看板需要的 7 个块、默认不写 Excel（每日增量同步用）。
    * excel 显式覆盖配置里的 persist.write_excel（None=按配置；名字不用 write_excel，
      否则会在函数内遮蔽同名的 `write_excel()` 函数）。
    * invoked_by 记录发起本次运行的任务 id（落进 report_runs.invoked_by），供任务列表
      「最近运行」兜底区分月报任务与每日 KPI 同步借道写入的行（详见 _sqlite 补列注释）。
    """
    started = time.time()
    cfg = load_config(config_path)
    begin, end, real_mode = resolve_window(mode or cfg.get("range_mode"),
                                           days if days is not None else cfg.get("days"),
                                           start, end, today=today)
    begin, end, clamp_warning = clamp_window(begin, end, int(cfg.get("max_days") or 92))
    all_days = vgc.day_range(begin, end)
    # 当天（及未来）分区仍在累积：实测 2026-09-16 16:50 门户=68.31TB、19:50 门户与数仓同为
    # 122.25TB —— 两边口径一致，只是「今天」是移动靶。取完整数据请把 end 设为昨天。
    today_str = (today or date.today()).strftime("%Y%m%d")
    partial_days = [d for d in all_days if d >= today_str]
    run_id = "%s_%s_%s" % (real_mode, begin, end)
    chosen = enabled_blocks(cfg, blocks)
    if kpi_only:
        chosen = [b for b in chosen if b in KPI_BLOCKS]
    want_excel = bool((cfg.get("persist") or {}).get("write_excel", True)) \
        if excel is None else bool(excel)
    if kpi_only and excel is None:
        want_excel = False                                               # 每日同步不重复出 Excel
    summary: Dict[str, Any] = {
        "status": "ok", "run_id": run_id, "mode": real_mode,
        "window": [begin, end], "days": len(all_days), "source": "gbase",
        "transport": vgc.dsn_summary(vgc.resolve_dsn(cfg.get("gbase") or {})),
        "blocks": {}, "blocks_ok": 0, "blocks_failed": 0, "rows": 0, "errors": [],
        "excel": None, "elapsed_seconds": 0.0, "missing_days": [], "mail": None,
        "partial_days": partial_days,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": "", "warnings": [clamp_warning] if clamp_warning else [],
        "invoked_by": invoked_by or "",
    }
    if clamp_warning:
        logger.warning("[olib_soc] %s", clamp_warning)
    if partial_days:
        summary["warnings"].append(
            "窗口包含当天/未来日期 %s：这些分区仍在累积（同一天两边口径一致，但数值随时间增长），"
            "要出完整数据请把窗口结束日设为昨天" % ",".join(partial_days[:3]))
        logger.warning("[olib_soc] 窗口含未完成日期: %s", ",".join(partial_days[:5]))

    pool = None
    owns_client = client is None
    try:
        if not chosen:
            summary.update(status="no_block", errors=["没有启用的报表块（检查 blocks 配置）"])
        else:
            if client is not None:                                       # 测试注入
                class _Injected:
                    def get(self_inner):
                        return client

                    @property
                    def primary(self_inner):
                        return client

                    def close_all(self_inner):
                        return None

                    def stats(self_inner):
                        return {}
                pool = _Injected()                                       # type: ignore[assignment]
            else:
                pool = _ClientPool(cfg)
            # 两条路径都做健康检查：注入的假客户端若实现了 healthy 也照此判定
            try:
                ok, info = pool.primary.healthy()
            except Exception as exc:                                     # noqa: BLE001
                ok, info = False, "%s: %s" % (type(exc).__name__, exc)
            if not ok:
                summary.update(status="unavailable", errors=["GBase 不可用: %s" % info])
            else:
                summary["transport"] = info

        if summary["status"] == "ok" and chosen and pool is not None:
            missing_union: List[str] = []
            workers = max(1, int(cfg.get("workers") or 1))

            def _one(block: str) -> Dict[str, Any]:
                return run_block(pool, block, all_days, cfg, progress=progress)  # type: ignore[arg-type]

            if workers > 1 and len(chosen) > 1:
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    fetched = list(ex.map(_one, chosen))
            else:
                fetched = [_one(b) for b in chosen]

            empty_union: List[str] = []
            for res in fetched:
                key = res["block"]
                for day in res["days_missing"]:
                    if day not in missing_union:
                        missing_union.append(day)
                for day in res.get("days_empty") or []:
                    if day not in empty_union:
                        empty_union.append(day)
                summary["blocks"][key] = {k: v for k, v in res.items() if k != "frame"}
                summary["blocks"][key]["title"] = res["title"]
                summary["rows"] += res["rows"]
                # blocks_ok/failed 维持「块级」口径：只有查询报错（errors）才算 failed。
                # 「缺了某天」（days_empty）单独用 days_empty 汇总，不混进块级计数，
                # 否则会让既有的 blocks_ok == 块总数 口径失真（文档/测试都依赖它）。
                if res["errors"]:
                    summary["blocks_failed"] += 1
                    summary["errors"].extend(res["errors"][:3])
                else:
                    summary["blocks_ok"] += 1
                for item in res.get("suspect_days") or []:
                    summary.setdefault("suspect_days", []).append({"block": key, **item})
                if preview_rows > 0:
                    head = res["frame"].head(int(preview_rows))
                    summary.setdefault("preview", {})[key] = head.where(
                        head.notna(), None).to_dict(orient="records")
            summary["missing_days"] = sorted(missing_union)
            summary["days_empty"] = sorted(empty_union)
            if summary["missing_days"]:
                summary["warnings"].append("窗口内 %d 天没有分区表（数仓缺表/未生成），已跳过: %s"
                                           % (len(summary["missing_days"]),
                                              ",".join(summary["missing_days"][:10])))
            if summary["days_empty"]:
                summary["warnings"].append(
                    "有 %d 天本应有数却未取到（分区缺失或查出 0 行），这些天在看板会显示为缺数: %s"
                    % (len(summary["days_empty"]), ",".join(summary["days_empty"][:10])))
            if summary.get("suspect_days"):
                detail = "; ".join("%s %s=%s(中位数 %s)" % (i["block"], i["day"], i["value"],
                                                            i["median"])
                                   for i in summary["suspect_days"][:5])
                summary["warnings"].append(
                    "有 %d 项数据量异常（当日主指标远低于窗口中位数，疑似上游数据缺失，"
                    "已在 Excel 的 %s 表列出）: %s"
                    % (len(summary["suspect_days"]), QUALITY_SHEET, detail))
                logger.warning("[olib_soc] 数据量异常 %d 项: %s", len(summary["suspect_days"]),
                               detail)
            if summary["blocks_failed"] and summary["blocks_ok"]:
                summary["status"] = "partial"
            elif summary["blocks_failed"] and not summary["blocks_ok"]:
                summary["status"] = "failed"
            elif summary.get("days_empty"):
                # 块都跑成，但有天没取到数：降级为 partial，让任务可见、可告警
                # （不改 success，避免 auto_retry 因「数仓晚到」这种正常情况反复重跑）
                summary["status"] = "partial"
            stats = pool.stats()
            if isinstance(stats, dict) and stats:
                summary["sql"] = stats

            label = window_label(real_mode, begin, end)
            xlsx = None
            # persist=False 表示「不落盘」（CLI --no-persist）：Excel/数据库/摘要全部不写
            result_map = {r["block"]: r for r in fetched}
            if persist and want_excel:
                xlsx = write_excel(result_map, excel_path_for(label),
                                   keep_csv=bool((cfg.get("persist") or {}).get("keep_csv")))
                summary["excel"] = xlsx
            if persist and (cfg.get("persist") or {}).get("write_kpi", True):
                summary["kpi"] = persist_daily_kpi(result_map, run_id, all_days)
                # 分业务分流明细：只要这次跑了 spservice 表族的块就顺带取一次，
                # 月报全量跑与看板每日增量跑同一条路径，历史回补不需要单独的命令。
                summary["app_offload"] = persist_app_offload(pool, cfg, all_days, run_id)
            summary["mail"] = (deliver_mail(cfg, xlsx, summary) if send_mail is not False
                               else {"sent": False, "skipped": "send_mail=False"})
    except vgc.VmaxGbaseUnavailable as exc:
        summary.update(status="unavailable", errors=[str(exc)])
    except Exception as exc:                                             # noqa: BLE001
        logger.exception("[olib_soc] 报表生成失败")
        summary.update(status="failed", errors=["%s: %s" % (type(exc).__name__, exc)])
    finally:
        if pool is not None and owns_client:
            pool.close_all()
        summary["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary["elapsed_seconds"] = round(time.time() - started, 2)

    if persist:
        try:
            persist_run(summary)
            summary_json_path(run_id).write_text(
                json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[olib_soc] 落盘记录失败: %s", exc)
    logger.info("[olib_soc] %s blocks=%d/%d rows=%d elapsed=%.1fs errors=%s",
                summary["status"], summary["blocks_ok"],
                summary["blocks_ok"] + summary["blocks_failed"], summary["rows"],
                summary["elapsed_seconds"], summary["errors"][:2])
    return summary


# ==========================================================================
# 每日增量：补齐看板 KPI 库缺的日期（任务 olib_soc_kpi_daily_sync）
# ==========================================================================
def run_olib_soc_kpi_sync(days_back: Optional[int] = None, only_missing: bool = True,
                          persist: bool = True, progress: bool = False,
                          client: Any = None, config_path: Optional[Path] = None,
                          today: Optional[date] = None,
                          refresh_last: Optional[int] = None) -> Dict[str, Any]:
    """看板数据源的每日增量同步（任务入口，无参调用）。

    * 默认只看最近 `kpi_sync.days_back`（默认 7）天，只补库里没有的天 —— 幂等、自愈（
      某天同步失败/数仓晚到，第二天会自动补上），正常情况下每天只查 1 天、几秒钟。
    * 另外把窗口内**最新 `kpi_sync.refresh_last_days`（默认 1）天重取一遍**：数仓当天
      分区常晚到，取到未完成的一天或某次运行被跳过时，下次运行自动纠正。
    * only_missing=False 时强制重取整个窗口（数仓回补历史时用）。
    * 不写 Excel，只写 KPI 库（`daily_kpi`）。
    """
    started = time.time()
    cfg = load_config(config_path)
    sync_cfg = cfg.get("kpi_sync") or {}
    window = int(days_back if days_back is not None
                 else (sync_cfg.get("days_back") or 7))
    base = today or date.today()
    end = base - timedelta(days=1)
    begin = end - timedelta(days=max(1, window) - 1)
    summary: Dict[str, Any] = {
        "status": "ok", "task": "olib_soc_kpi_daily_sync", "source": "gbase",
        "window": [vgc.norm_day(begin), vgc.norm_day(end)], "days_back": window,
        "only_missing": bool(only_missing), "requested_days": [], "rows": 0,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "finished_at": "",
        "elapsed_seconds": 0.0, "warnings": [], "errors": [],
    }
    historical: List[str] = []                                           # 窗口外、保留期内的历史残缺日
    abandoned: List[str] = []                                            # 超出上游保留期、放弃重取的残缺日
    if only_missing:
        gaps = kpi_store.gap_days(window, path=kpi_db_path(), today=base)
        # 除了「整天没有行」的天，还要补「有行但关键指标为 NULL」的天：某次运行若单个块
        # 临时取数失败，仍会写入一行（其余块有值），只是该块那列是 NULL。这类天不算
        # gap_days 的缺口，不特意捞出来就会**永久残留**（2026-09-18~23 的 active_user
        # 连丢 6 天即此因）。取数本身是幂等的，重取一次即可自愈。
        for day in kpi_store.incomplete_days(window, path=kpi_db_path(), today=base):
            if day not in gaps:
                gaps.append(day)
        # **窗口之外**的历史残缺日单独收集：incomplete_days 只看最近 N 天，一旦某个残缺日
        # 滑出窗口就再也补不到（2026-09-07 的 traffic_tb 就是这么遗留了整整一个月）。
        # 这些天**不能并进上面的 gaps**：主调用按 gaps[0]~gaps[-1] 张成连续区间，混入一个
        # 一个月前的日子会让区间暴涨、把中间几十天全部重查一遍。所以走单独一次调用。
        #
        # 但**必须设上限**：上游数仓只保留约 90 天，超出保留期的残缺日再怎么重取也拿不回来
        # （实测 2026-09-07 的 aggr_5gsa_flow_ciservice 分区已消失）。若不加限制，任务会每天
        # 徒劳重取这些天、永远补不上、还每天刷一条 warning。所以只重取**保留期之内**的天，
        # 更早的交给 incomplete_days 语义在看板上如实标注（而不是无限重试）。
        window_iso = {vgc.iso_day(d) for d in vgc.day_range(begin, end)}
        retention_days = int(sync_cfg.get("residual_lookback_days") or 95)
        floor = (base - timedelta(days=retention_days)).isoformat()
        for d in kpi_store.all_incomplete_days(path=kpi_db_path()):
            if d in window_iso:
                continue
            if d >= floor:
                historical.append(d)
            else:
                abandoned.append(d)                                      # 超出保留期，放弃重取
        # 再把窗口里**最新的 N 天重取一遍**（默认 1）：数仓当天的分区常常晚到
        # （实测次日仍在累积），若某次同步恰好取到未完成的一天，或某天任务因重启/
        # 停机被跳过，下一次运行会自动把它纠正过来 —— 否则 only_missing 会让
        # 这个错误的日值永久留在库里。
        refresh = int(refresh_last if refresh_last is not None
                      else (sync_cfg.get("refresh_last_days") or 0))
        if refresh > 0:
            tail = [vgc.iso_day(d) for d in vgc.day_range(begin, end)][-refresh:]
            already = set(kpi_store.stored_days(path=kpi_db_path()))
            for day in tail:
                if day in already and day not in gaps:
                    gaps.append(day)
            gaps.sort()
    else:
        # 统一成 ISO：与 gap_days 的返回格式、与 kpi.days_list 的比较口径保持一致，
        # 否则 force 重取后 `still_missing` 会把所有天都误报成「仍然缺」
        gaps = [vgc.iso_day(d) for d in vgc.day_range(begin, end)]
    summary["requested_days"] = gaps
    if not gaps and not historical:
        summary["status"] = "up_to_date"
        summary["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary["elapsed_seconds"] = round(time.time() - started, 2)
        # 无缺口要补，但若有超保留期的残留，仍要如实报一声（否则巡检看不到"看板有残缺"）
        if abandoned:
            summary["abandoned_days"] = abandoned
            summary["warnings"].append(
                "以下残缺日上游分区已不可用（超出保留期或已删除），无法回补（看板会如实标注为残缺，不再重试）: %s"
                % ",".join(abandoned[:10]))
        logger.info("[olib_soc] KPI 增量：最近 %d 天已齐，无需取数", window)
        return summary
    # 主调用：窗口内的缺口。若窗口内无缺口（gaps 为空）则跳过，只跑下面的历史残留。
    inner: Dict[str, Any] = {}
    if gaps:
        inner = run_olib_soc_report(mode="explicit", start=gaps[0], end=gaps[-1],
                                    blocks=KPI_BLOCKS, persist=persist, kpi_only=True,
                                    excel=False, client=client,
                                    config_path=config_path, today=today,
                                    invoked_by="olib_soc_kpi_daily_sync")
    # 历史残留在真正重取前，先用**一次**上游分区清单检查把它们再筛一遍：
    # 数仓只留约 90 天，某些残留（如 2026-09-07 的流量/TCP 分区）其实早已消失 ——
    # 这种"永远补不上"的天若每天都重取，只会每天徒劳查询 + 每天刷一条 warning。
    # 用便宜的 SHOW TABLES（partition_days）确认分区确实还在，才值得重取；
    # 分区已消失的直接归入 abandoned（如实告警，不再重试）。
    if historical:
        probe = client
        owned_probe = None
        try:
            if probe is None:
                owned_probe = _open_probe_client(cfg)
                probe = owned_probe
            # 一天要能补上，**每个**看板块的 family 都必须还有那天的分区 —— 只要有一个
            # family 的分区没了，那天就永远补不全（如 09-07：active_user 在、traffic/tcp 已没）。
            families = {BLOCKS[b]["family"] for b in KPI_BLOCKS if b in BLOCKS}
            have_by_fam = {fam: {vgc.iso_day(d)
                                 for d in probe.partition_days(fam, "day")}
                           for fam in families}
            retryable, gone = [], []
            for d in historical:
                if all(d in have_by_fam[fam] for fam in families):
                    retryable.append(d)
                else:
                    gone.append(d)
            if gone:
                abandoned.extend(gone)
            historical = retryable
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[olib_soc] 历史残留分区预检失败（仍按原列表重取）: %s", exc)
        finally:
            if owned_probe is not None:
                try:
                    owned_probe.close()
                except Exception:                                        # noqa: BLE001
                    pass
    # 历史残留（窗口之外）：按 min~max 区间单独跑一次 —— 这些天通常极少（多为 0），
    # 且彼此可能相隔很远，用区间而非逐天是为了复用现成的 run_olib_soc_report 入口。
    hist_summary: Dict[str, Any] = {}
    if historical:
        hist_summary = run_olib_soc_report(mode="explicit", start=historical[0],
                                           end=historical[-1], blocks=KPI_BLOCKS,
                                           persist=persist, kpi_only=True, excel=False,
                                           client=client, config_path=config_path,
                                           today=today,
                                           invoked_by="olib_soc_kpi_daily_sync")
    # 主调用与历史残留调用的结果合并：状态取「更差」的一个，天数/行数/缺口取并集。
    parts = [p for p in (inner, hist_summary) if p]
    worst = "ok"
    for p in parts:
        st = p.get("status") or "ok"
        if st in ("failed", "unavailable"):
            worst = st
        elif st == "partial" and worst == "ok":
            worst = "partial"
    filled: set = set()
    empty_days: List[str] = []
    for p in parts:
        filled |= set((p.get("kpi") or {}).get("days_list") or [])
        for d in p.get("days_empty") or []:
            if d not in empty_days:
                empty_days.append(d)
    summary.update({
        "status": worst,
        "rows": sum(int(p.get("rows") or 0) for p in parts),
        "days": sum(int(p.get("days") or 0) for p in parts),
        "blocks_ok": inner.get("blocks_ok") if inner else None,
        "blocks_failed": inner.get("blocks_failed") if inner else None,
        "kpi": inner.get("kpi") or hist_summary.get("kpi"),
        "missing_days": inner.get("missing_days"),
        "warnings": (inner.get("warnings") or []) + (hist_summary.get("warnings") or []),
        "errors": (inner.get("errors") or []) + (hist_summary.get("errors") or []),
        "days_empty": sorted(empty_days),
        "elapsed_seconds": sum(float(p.get("elapsed_seconds") or 0) for p in parts),
        "historical_days": historical,
        "abandoned_days": abandoned,
        "detail": {k: v for k, v in (inner or hist_summary or {}).items()
                   if k not in ("blocks", "preview", "warnings", "errors")},
    })
    # 缺口里仍没拿到的天（数仓还没生成分区）单独提示，方便排查
    still = [d for d in (gaps + historical) if d not in filled]
    if still:
        summary["still_missing"] = still
        summary["warnings"].append("以下日期仍无数据（数仓未生成分区或上游缺数）: %s"
                                   % ",".join(still[:10]))
    # 超出上游保留期、已放弃重取的残留（不是本次任务的锅，但要让看板用户知道）
    if abandoned:
        summary["warnings"].append(
            "以下残缺日上游分区已不可用（超出保留期或已删除），无法回补（看板会如实标注为残缺，不再重试）: %s"
            % ",".join(abandoned[:10]))
    summary["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not summary.get("elapsed_seconds"):
        summary["elapsed_seconds"] = round(time.time() - started, 2)
    logger.info("[olib_soc] KPI 增量完成: 请求 %d 天（含历史残留 %d 天）/ 入库 %s 天 / %s",
                len(gaps) + len(historical), len(historical),
                (inner.get("kpi") or {}).get("days"), summary["status"])
    return summary


# ==========================================================================
# CLI
# ==========================================================================
def _cmd_check(cfg: Dict[str, Any]) -> int:
    client = vgc.VmaxGbaseClient(cfg.get("gbase") or {},
                                 credential_key=cfg.get("credential_key"))
    try:
        ok, info = client.healthy()
        print("GBase:", "OK  " if ok else "FAIL", info)
        if not ok:
            return 3
        for family in (vgc.FAMILY_FLOW_CISERVICE, vgc.FAMILY_FLOW_SPSERVICE,
                       vgc.FAMILY_VIDEO_SPSERVICE, vgc.FAMILY_GAME_SPSERVICE,
                       vgc.FAMILY_DS_250024):
            for gran in ("day", "hour"):
                days = client.partition_days(family, gran)
                if days:
                    print("  %-28s %-4s 分区 %3d 个  %s ~ %s"
                          % (family, gran, len(days), days[0], days[-1]))
        return 0
    finally:
        client.close()


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="OLIB SOC VMAX 例行报表（直连 GBase 数仓）")
    ap.add_argument("--mode", default=None,
                    help="last_month|this_month|last_n_days|weekly|explicit（默认取配置）")
    ap.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD（给了 start/end 即按此窗口）")
    ap.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=None, help="last_n_days 的天数")
    ap.add_argument("--blocks", default=None, help="逗号分隔的块/sheet 名，默认全部")
    ap.add_argument("--workers", type=int, default=None, help="并发连接数（默认取配置 3）")
    ap.add_argument("--check", action="store_true", help="只体检（版本/分区/授权），不取数")
    ap.add_argument("--list", action="store_true", help="列出报表块")
    ap.add_argument("--sync-kpi", action="store_true",
                    help="只做看板 KPI 增量同步（补最近 N 天缺的日期），不出 Excel")
    ap.add_argument("--days-back", type=int, default=None, help="--sync-kpi 的回看天数（默认配置 7）")
    ap.add_argument("--force", action="store_true", help="--sync-kpi 时强制重取窗口内所有天")
    ap.add_argument("--kpi-only", action="store_true", help="只跑看板用的 7 个块，跳过 top_video")
    ap.add_argument("--no-excel", action="store_true", help="不写 Excel（只入库/打印摘要）")
    ap.add_argument("--no-persist", action="store_true", help="不落盘（只打印摘要）")
    ap.add_argument("--mail", action="store_true", help="强制发送邮件（需配置 mail 收件人）")
    ap.add_argument("--no-mail", action="store_true", help="本次不发送邮件")
    ap.add_argument("--progress", action="store_true", help="打印每块每天的进度")
    ap.add_argument("--full", action="store_true", help="打印每块前 10 行明细")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.workers:
        cfg["workers"] = max(1, args.workers)
    if args.list:
        for key in SHEET_ORDER:
            spec = BLOCKS[key]
            print("%-12s sheet=%-16s %-20s %s"
                  % (key, spec["sheet"], spec["title"], spec["family"]))
        return 0
    if args.check:
        return _cmd_check(cfg)

    if args.sync_kpi:
        sync = run_olib_soc_kpi_sync(days_back=args.days_back, only_missing=not args.force,
                                     persist=not args.no_persist, progress=args.progress)
        print(json.dumps(sync, ensure_ascii=False, indent=1, default=str))
        if sync.get("still_missing"):
            print("仍缺:", ",".join(sync["still_missing"]))
        return 0 if sync.get("status") in ("ok", "up_to_date", "partial") else 2

    summary = run_olib_soc_report(mode=args.mode, days=args.days, start=args.start, end=args.end,
                                  blocks=(args.blocks.split(",") if args.blocks else None),
                                  persist=not args.no_persist,
                                  send_mail=(True if args.mail else (False if args.no_mail else None)),
                                  progress=args.progress,
                                  kpi_only=args.kpi_only,
                                  excel=False if args.no_excel else None,
                                  preview_rows=10 if args.full else 0)
    shown = {k: v for k, v in summary.items() if k not in ("blocks", "preview")}
    print(json.dumps(shown, ensure_ascii=False, indent=1, default=str))
    print("\n块结果:")
    for key in SHEET_ORDER:
        res = (summary.get("blocks") or {}).get(key)
        if not res:
            continue
        print("  %-12s sheet=%-16s rows=%-6s 有数据天=%-3s 缺表天=%-3s %-8s %s"
              % (key, res.get("sheet"), res.get("rows"), res.get("days_present"),
                 len(res.get("days_missing") or []), res.get("status"),
                 ("%.1fs" % res.get("seconds")) if res.get("seconds") is not None else ""))
    if args.full:
        for key in SHEET_ORDER:
            res = (summary.get("blocks") or {}).get(key)
            if not res:
                continue
            print("\n=== %s (%s) ===" % (key, res.get("sheet")))
            for row in (summary.get("preview") or {}).get(key, [])[:10]:
                print("  ", json.dumps(row, ensure_ascii=False, default=str)[:400])
    for warn in summary.get("warnings") or []:
        print("警告:", warn)
    if summary.get("status") in ("unavailable", "failed", "no_block"):
        return 2 if summary.get("status") != "unavailable" else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
