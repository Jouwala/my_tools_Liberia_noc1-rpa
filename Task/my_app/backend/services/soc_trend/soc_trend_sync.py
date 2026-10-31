# -*- coding: utf-8 -*-
"""SOC 多维趋势同步（任务 47 soc_trend_sync）：GBase 只读拉取 → 本地 sqlite。

取数模型（对照 olib_soc_report 的实测结论，README 见 backend/services/vmax_gbase/）
--------------------------------------------------------------------------------
* 数仓 `zxvmax` 库按「表族_粒度_YYYYMMDD」分表；`_hour_` 约留 94 天、`_day_` 约留 90 天，
  且存在缺表与未来空分区 —— 一律先 `SHOW TABLES` 探分区再查（VmaxGbaseClient.partition_days）；
* 当天分区是移动靶（持续累积），所以「最近 2 天」每次运行都重拉，其余缺哪天补哪天；
* 本模块对数仓**只发 SELECT/SHOW**（VmaxGbaseClient._assert_readonly 强制），
  产物只落 data/soc_trend/soc_trend.sqlite3。

每个分区 4 条聚合 SQL（小时/天同构，天版少 hh 列）：
    C1 flow_ciservice  按 hh×area_id   -> 流量/TCP 全套（cat=flow，dim=area/total）
    C2 flow_ciservice  按 hh×targetid  -> 同上（dim=ne，仅 flow 有网元维度；零流量噪声
                                          targetid 在落盘前过滤，2026-10-30 实测 8 个全 0 成员）
    S1 flow_spservice  按 hh×service_id（仅 5 个类目 service）-> 分业务流量/TCP（dim=total）
    V1 video_spservice 按 hh           -> 视频有效下载速率计数器（并入 cat=video 行）
类目映射（dim_service，2026-10-30 实测）：视频=5、OTT视频=23(Video Live)、网页=15(Web Browse)、
游戏=8(Game)、OTT语音=13(VoIP)；控制面表族实测全空，不落行（前端空态占位）。
⚠ spservice 的 area_id 实测恒为 0（业务侧无区域归属），故分业务类目只有全网维度，
  区域/网元维度仅 flow / tcp（ciservice 表）可用 —— CAT_DIMS 与此对应。
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

if __package__ in (None, ""):                                            # 直接 python 跑本文件时
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.services.soc_trend import soc_trend_store as store
from backend.services.vmax_gbase import vmax_gbase_client as vgc

logger = logging.getLogger("soc_trend")

FAM_CI = vgc.FAMILY_FLOW_CISERVICE                                       # aggr_5gsa_flow_ciservice
FAM_SP = vgc.FAMILY_FLOW_SPSERVICE                                       # aggr_5gsa_flow_spservice
FAM_VD = vgc.FAMILY_VIDEO_SPSERVICE                                      # aggr_5gsa_video_spservice

HOUR_LOOKBACK = 35                                                       # 天视图要画 30 天趋势，小时表留 ~94 天足够
DAY_LOOKBACK = 92                                                        # 天表 ~90 天保留，拉满（kpi_day 归档备用）
REFRESH_LAST_DAYS = 2                                                    # 最近 N 天每次重拉（当天在累积）
WORKERS = 3                                                              # 与 olib_soc_report 同款并发度
TOP_APPS_PER_CAT = 20                                                    # 每类目每分区按流量取 Top-N APP（Web 有 1810 个，全存不现实）
# 分业务类目 -> service_id（dim_service 实测，见模块头注释）
CAT_SERVICE_IDS: Dict[str, Tuple[int, ...]] = {
    "video": (5,), "ottvideo": (23,), "web": (15,), "game": (8,), "ottvoice": (13,),
}
_APP_SERVICE_IDS = (5, 23, 15, 8, 13)                                    # SQL IN 常量（与 CAT_SERVICE_IDS 一致）
# 网元 targetid -> 名称（olib_soc_report 2026-09 实测映射；未映射 targetid 出现时按原 id 展示）
NE_NAMES: Dict[str, str] = {"50331658": "SGW_HQ_122", "50331660": "SGW_ODC_22"}

# 公共计数器列（列名与 soc_trend_store.COUNTER_COLS 一一对应）
_COUNTER_SELECT = """
    SUM(ppb400401001) AS ul_bytes, SUM(ppb400401002) AS dl_bytes,
    SUM(ppb400403020) AS conn_att,  SUM(ppb400403021) AS conn_ok,
    SUM(ppb400403007) AS rt_att_ul, SUM(ppb400403015) AS rt_bad_ul,
    SUM(ppb400403008) AS rt_att_dl, SUM(ppb400403016) AS rt_bad_dl,
    SUM(ppb400403013) AS dis_bad_ul, SUM(ppb400403014) AS dis_bad_dl,
    SUM(ppb400403041) AS loss_bad_ul, SUM(ppb400403042) AS loss_bad_dl,
    SUM(ppb400403038) AS rtt_att_ul, SUM(ppb400403044) AS rtt_sum_ul,
    SUM(ppb400403039) AS rtt_att_dl, SUM(ppb400403045) AS rtt_sum_dl"""

# 每个分区的 4 条聚合 SQL（{t}=分区表名；HOUR 版多取 hh 列）
SQLS = {
    "hour": {
        "ci_area": "select hh, area_id, COUNT(*) AS n, %s from {t} group by hh, area_id" % _COUNTER_SELECT,
        "ci_ne": "select hh, targetid, COUNT(*) AS n, %s from {t} group by hh, targetid" % _COUNTER_SELECT,
        "sp": ("select hh, service_id, COUNT(*) AS n, %s from {t} "
               "where service_id in (5, 23, 15, 8, 13) "
               "group by hh, service_id" % _COUNTER_SELECT),
        "vd": ("select hh, COUNT(*) AS n, SUM(ppb400464018) AS vt_num, "
               "SUM(ppb400464051) AS vt_den from {t} group by hh"),
        # APP 维度：先按分区总量排名（SQL-A），再只拉 Top-N 的小时明细（SQL-B，Tuple IN）
        "app_rank": ("select service_id, subservice_id, SUM(ppb400401001+ppb400401002) AS v "
                     "from {t} where service_id in (5, 23, 15, 8, 13) "
                     "group by service_id, subservice_id"),
    },
    "day": {
        "ci_area": "select area_id, COUNT(*) AS n, %s from {t} group by area_id" % _COUNTER_SELECT,
        "ci_ne": "select targetid, COUNT(*) AS n, %s from {t} group by targetid" % _COUNTER_SELECT,
        "sp": ("select service_id, COUNT(*) AS n, %s from {t} "
               "where service_id in (5, 23, 15, 8, 13) "
               "group by service_id" % _COUNTER_SELECT),
        "vd": ("select COUNT(*) AS n, SUM(ppb400464018) AS vt_num, "
               "SUM(ppb400464051) AS vt_den from {t}"),
        # 天分区不拉 APP（dim=app 的天视图由小时表同时段聚合，口径与总览一致）
        "app_rank": None,
    },
}
_ZERO = {c: 0 for c in store.COUNTER_COLS}


def _table(family: str, day_compact: str, gran: str) -> str:
    return "%s_%s_%s" % (family, gran, day_compact)


def _day_window(lookback: int, today: date) -> List[str]:
    """窗口内的 'YYYYMMDD'（含今天，升序）。"""
    return [(today - timedelta(days=i)).strftime("%Y%m%d")
            for i in range(lookback - 1, -1, -1)]


def _pick_days(available: List[str], window: List[str], stored_iso: List[str],
               refresh_all: bool = False) -> List[str]:
    """窗口 ∩ 有分区，且（本地缺 或 在 REFRESH_LAST_DAYS 重拉带内）的日清单。

    refresh_all=True 时整窗全拉（结构变更后的一次性回填入口，如新增 APP 维度）。
    """
    stored = {d.replace("-", "") for d in stored_iso}                    # ISO -> 紧凑格式对齐
    refresh = set(window[-REFRESH_LAST_DAYS:])
    return [d for d in window if d in set(available)
            and (refresh_all or d not in stored or d in refresh)]


def _num(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def svc_name_of(service_id: int) -> Optional[str]:
    """service_id -> 类目 key（不在 5 个类目内返回 None）。"""
    for cat, ids in CAT_SERVICE_IDS.items():
        if service_id in ids:
            return cat
    return None


def fetch_app_dims(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """dim_service 的 APP 名字典（5 个类目约 5900 行，每次运行整体刷新进 dim_app）。"""
    with vgc.VmaxGbaseClient(cfg=cfg) as client:
        rows = client.query_dicts(
            "select serviceid, appid, min(appname) AS appname from dim_service "
            "where serviceid in (5, 23, 15, 8, 13) group by serviceid, appid")
    return [{"member": "%d:%d" % (int(_num(r.get("serviceid"))), int(_num(r.get("appid")))),
             "cat": svc_name_of(int(_num(r.get("serviceid")))),
             "app_name": r.get("appname")} for r in rows]


def _base_row(gran: str, day_iso: str, hh: Any, cat: str, dim: str, member: Any,
              rec: Dict[str, Any]) -> Dict[str, Any]:
    row = {"day": day_iso, "cat": cat, "dim": dim,
           "member": str(member if member is not None else 0),
           "rows_n": int(_num(rec.get("n")))}
    if gran == "hour":
        row["hh"] = int(hh)
    for col in store.COUNTER_COLS:
        row[col] = _num(rec.get(col))
    return row


def _sum_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把同 (day,hh,cat,dim) 的多行合并成 total 行（计数器直接相加）。"""
    out = {"rows_n": 0}
    for r in rows:
        out["rows_n"] += int(r.get("rows_n") or 0)
        for col in store.COUNTER_COLS:
            out[col] = out.get(col, 0.0) + float(r.get(col) or 0.0)
    return out


def fetch_day(gran: str, day_compact: str, cfg: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """拉一个分区（标准 4 条 SQL + APP 2 条），返回 (day_iso, 行清单, APP 行清单)。线程内各自持有连接。"""
    with vgc.VmaxGbaseClient(cfg=cfg) as client:
        day_iso = vgc.iso_day(day_compact)
        sqls = SQLS[gran]
        ci_area = client.query_dicts(sqls["ci_area"].format(t=_table(FAM_CI, day_compact, gran)))
        ci_ne = client.query_dicts(sqls["ci_ne"].format(t=_table(FAM_CI, day_compact, gran)))
        sp = client.query_dicts(sqls["sp"].format(t=_table(FAM_SP, day_compact, gran)))
        vd = client.query_dicts(sqls["vd"].format(t=_table(FAM_VD, day_compact, gran)))
        app_rows: List[Dict[str, Any]] = []
        if sqls.get("app_rank"):
            rank = client.query_dicts(sqls["app_rank"].format(t=_table(FAM_SP, day_compact, gran)))
            app_rows = _fetch_top_apps(client, gran, day_compact, rank)

    hh_key = "hh" if gran == "hour" else None
    rows: List[Dict[str, Any]] = []
    # C1: flow（area + total）
    for rec in ci_area:
        rows.append(_base_row(gran, day_iso, rec.get(hh_key) if hh_key else None,
                              "flow", "area", rec.get("area_id"), rec))
    by_hh: Dict[Any, List[Dict[str, Any]]] = {}
    for r in rows:
        by_hh.setdefault(r.get("hh"), []).append(r)
    for hh, group in by_hh.items():
        rows.append(_base_row(gran, day_iso, hh, "flow", "total", "all", _sum_rows(group)))
    # C2: flow/ne —— 过滤零流量噪声 targetid（保留分区总量 ≥ max(1GB, 最大成员 0.1%) 的成员）
    ne_totals: Dict[str, float] = {}
    for rec in ci_ne:
        ne_totals[str(rec.get("targetid"))] = (
            _num(rec.get("ul_bytes")) + _num(rec.get("dl_bytes")))
    ne_keep = {m for m, v in ne_totals.items()
               if v >= max(1e9, 0.001 * max(ne_totals.values() or [0.0]))}
    for rec in ci_ne:
        member = str(rec.get("targetid"))
        if member not in ne_keep:
            continue
        rows.append(_base_row(gran, day_iso, rec.get(hh_key) if hh_key else None,
                              "flow", "ne", member, rec))
    # S1: 分业务类目（dim=total；spservice 的 area_id 实测恒 0，见模块头注释）
    #     V1 的视频速率计数器按 hh 并入 cat=video 的行
    vt: Dict[Any, Dict[str, Any]] = {
        (rec.get(hh_key) if hh_key else None): rec for rec in vd}
    svc_name = {sid: cat for cat, ids in CAT_SERVICE_IDS.items() for sid in ids}
    grouped: Dict[Tuple[Any, str], List[Dict[str, Any]]] = {}
    for rec in sp:
        cat = svc_name.get(int(_num(rec.get("service_id"))))
        if not cat:
            continue
        grouped.setdefault((rec.get(hh_key) if hh_key else None, cat), []).append(rec)
    for (hh, cat), recs in grouped.items():
        row = _base_row(gran, day_iso, hh, cat, "total", "all", _sum_rows(recs))
        vrec = vt.get(hh)
        if cat == "video" and vrec:
            row["vt_num"] = _num(vrec.get("vt_num"))
            row["vt_den"] = _num(vrec.get("vt_den"))
            row["rows_n"] += int(_num(vrec.get("n")))
        rows.append(row)
    return day_iso, rows, app_rows


def _fetch_top_apps(client: "vgc.VmaxGbaseClient", gran: str, day_compact: str,
                    rank_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按分区总量给每类目取 Top-N APP，再拉它们的小时明细（Tuple IN，与 olib 同款写法）。"""
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for rec in rank_rows:
        sid = int(_num(rec.get("service_id")))
        cat = svc_name_of(sid)
        if cat:
            by_cat.setdefault(cat, []).append(rec)
    pairs: List[Tuple[int, int]] = []
    for cat, recs in by_cat.items():
        recs.sort(key=lambda r: -_num(r.get("v")))
        for rec in recs[:TOP_APPS_PER_CAT]:
            pairs.append((int(_num(rec.get("service_id"))), int(_num(rec.get("subservice_id")))))
    if not pairs:
        return []
    pair_sql = ", ".join("(%d, %d)" % p for p in pairs)
    sql = ("select hh, service_id, subservice_id, COUNT(*) AS n, %s from {t} "
           "where (service_id, subservice_id) in (%s) "
           "group by hh, service_id, subservice_id" % (_COUNTER_SELECT, pair_sql))
    recs = client.query_dicts(sql.format(t=_table(FAM_SP, day_compact, gran)))
    svc_map = {sid: cat for cat, ids in CAT_SERVICE_IDS.items() for sid in ids}
    rows: List[Dict[str, Any]] = []
    for rec in recs:
        member = "%d:%d" % (int(_num(rec.get("service_id"))), int(_num(rec.get("subservice_id"))))
        row = {"day": vgc.iso_day(day_compact), "cat": svc_map.get(int(_num(rec.get("service_id")))),
               "member": member, "rows_n": int(_num(rec.get("n"))), "hh": int(_num(rec.get("hh")))}
        for col in store.COUNTER_COLS:
            row[col] = _num(rec.get(col))
        rows.append(row)
    return rows


def fetch_area_dims(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """dim_comm_area 成员（行数极少，每次运行刷新进本地库）。"""
    with vgc.VmaxGbaseClient(cfg=cfg) as client:
        rows = client.query_dicts(
            "select area_id, area_name, city_name from dim_comm_area order by area_id")
    return [{"area_id": str(r.get("area_id")), "area_name": r.get("area_name"),
             "city_name": r.get("city_name")} for r in rows]


def run_soc_trend_sync(hour_lookback: int = HOUR_LOOKBACK, day_lookback: int = DAY_LOOKBACK,
                       workers: int = WORKERS, refresh_all: bool = False) -> Dict[str, Any]:
    """任务入口：补齐小时/天两个粒度的缺口并刷新最近 2 天。GBase 不可用时降级返回。

    refresh_all=True：整窗全拉（表结构/口径变更后的一次性回填，如 kpi_app_hour 新增）。
    """
    start = time.time()
    run_id = uuid.uuid4().hex[:12]
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    today = date.today()
    cfg: Dict[str, Any] = {}
    summary: Dict[str, Any] = {"success": False, "hour_days": 0, "day_days": 0,
                               "skipped_days": 0, "run_id": run_id}

    probe = vgc.VmaxGbaseClient(cfg=cfg)
    try:
        ok, detail = probe.healthy()
    except Exception as exc:                                             # noqa: BLE001
        ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
    if not ok:
        msg = "GBase 不可用，跳过本次同步: %s" % detail
        logger.warning("[soc_trend] %s", msg)
        summary["error"] = msg
        return summary

    conn = store.connect()
    store.init_db(conn)
    tasks: List[Tuple[str, str]] = []
    try:
        hour_have, hour_miss = probe.available_days(FAM_CI, today - timedelta(days=hour_lookback - 1),
                                                    today, "hour")
        day_have, day_miss = probe.available_days(FAM_CI, today - timedelta(days=day_lookback - 1),
                                                  today, "day")
        summary["skipped_days"] = len(hour_miss) + len(day_miss)
        stored_hour = store.stored_days(conn, "hour")
        stored_day = store.stored_days(conn, "day")
        for gran, have, window, stored in (
                ("hour", hour_have, _day_window(hour_lookback, today), stored_hour),
                ("day", day_have, _day_window(day_lookback, today), stored_day)):
            for day in _pick_days(have, window, stored, refresh_all=refresh_all):
                tasks.append((gran, day))
        logger.info("[soc_trend] 本次待拉 %d 个分区（hour %d / day %d）",
                    len(tasks), sum(1 for g, _ in tasks if g == "hour"),
                    sum(1 for g, _ in tasks if g == "day"))

        errors: List[str] = []
        lock = threading.Lock()
        pool = ThreadPoolExecutor(max_workers=max(1, int(workers)))

        def _one(item: Tuple[str, str]) -> None:
            gran, day = item
            try:
                day_iso, rows, app_rows = fetch_day(gran, day, cfg)
                with lock:
                    store.replace_day(conn, gran, day_iso, rows)
                    if app_rows:
                        store.replace_app_day(conn, day_iso, app_rows)
                with lock:
                    if gran == "hour":
                        summary["hour_days"] += 1
                    else:
                        summary["day_days"] += 1
                logger.info("[soc_trend] %s %s -> %d 行 (+APP %d)",
                            gran, day_iso, len(rows), len(app_rows))
            except Exception as exc:                                     # noqa: BLE001
                with lock:
                    errors.append("%s %s: %s: %s" % (gran, day, type(exc).__name__, exc))

        try:
            for _ in pool.map(_one, tasks):
                pass
        finally:
            pool.shutdown(wait=True)

        store.replace_dims(conn, fetch_area_dims(cfg),
                           [{"targetid": k, "ne_name": v} for k, v in NE_NAMES.items()])
        store.replace_app_dims(conn, fetch_app_dims(cfg))

        finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        seconds = time.time() - start
        status = "ok" if not errors else "partial"
        error = "; ".join(errors[:5]) + (" ..." if len(errors) > 5 else "")
        store.record_run(conn, run_id, started_at, finished_at, status,
                         summary["hour_days"], summary["day_days"], summary["skipped_days"],
                         error, seconds)
        summary.update(success=True, status=status, seconds=round(seconds, 1), error=error or None)
        return summary
    finally:
        conn.close()
        probe.close()


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_soc_trend_sync(), ensure_ascii=False, indent=2))
