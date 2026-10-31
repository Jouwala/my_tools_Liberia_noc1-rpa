# -*- coding: utf-8 -*-
"""SOC 多维趋势看板的读取侧计算：序列组装 / 双基线告警 / 异常雷达。

口径约定（指标定义与告警参数见 soc_trend_metrics，改口径去那里）
------------------------------------------------------------------
* 本地库只存原始计数器（见 soc_trend_store），比率一律在此现算；
* GB 一律按 1024^3（与 olib_soc_report / VMAX 门户既有展示口径一致）；
* 告警：D-1 与 D-7 **双基线同时越限**才触发；方向只取「不利」一侧 ——
  体量/速率/成功率下降、重传/乱序/丢包/RTT 上升；
* 归因贡献按**同一维度互斥切片**：体量类指标把其它维度的成员不利变化量归一成占比
  （比率类指标不可加，不给贡献占比，只给自身偏差）。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.services.soc_trend import soc_trend_store as store
from backend.services.soc_trend.soc_trend_metrics import (  # noqa: F401 （dict_payload 再导出）
    ALARM_METRICS, CATS, CAT_DIMS, CAT_METRICS, DAY_TREND_DAYS, GIB, METRICS,
    MIN_BASE_GB, MIN_DEN, NEUTRAL_MEMBER, RATE_MIN_DELTA_PP, SRC_CAT, THRESH_CRIT,
    THRESH_MAJOR, VOLUME_METRICS, dict_payload,
)

logger = logging.getLogger("soc_trend")


# ==========================================================================
# 数值计算
# ==========================================================================
def _point_values(row: Dict[str, Any], gran: str, metrics: Sequence[str],
                  seconds: Optional[float] = None) -> Dict[str, Optional[float]]:
    ul = float(row.get("ul_bytes") or 0)
    dl = float(row.get("dl_bytes") or 0)
    out: Dict[str, Optional[float]] = {}
    sec = seconds if seconds else (3600.0 if gran == "hour" else 86400.0)
    for mid in metrics:
        if mid == "total_gb":
            out[mid] = (ul + dl) / GIB
        elif mid == "ul_gb":
            out[mid] = ul / GIB
        elif mid == "dl_gb":
            out[mid] = dl / GIB
        elif mid == "tput_mbps":
            out[mid] = dl * 8.0 / sec / 1e6
        elif mid == "video_tput_mbps":
            den = float(row.get("vt_den") or 0) * 1024 * 1024
            out[mid] = (float(row.get("vt_num") or 0) * 8000.0 / den) if den > 0 else None
        elif mid == "conn_rate":
            att = float(row.get("conn_att") or 0)
            out[mid] = (float(row.get("conn_ok") or 0) / att * 100) if att > 0 else None
        elif mid in ("rt_rate_ul", "dis_rate_ul", "loss_rate_ul"):
            col = {"rt_rate_ul": ("rt_bad_ul", "rt_att_ul"), "dis_rate_ul": ("dis_bad_ul", "rt_att_ul"),
                   "loss_rate_ul": ("loss_bad_ul", "rt_att_ul")}[mid]
            out[mid] = _ratio(row, col[0], col[1])
        elif mid in ("rt_rate_dl", "dis_rate_dl", "loss_rate_dl"):
            col = {"rt_rate_dl": ("rt_bad_dl", "rt_att_dl"), "dis_rate_dl": ("dis_bad_dl", "rt_att_dl"),
                   "loss_rate_dl": ("loss_bad_dl", "rt_att_dl")}[mid]
            out[mid] = _ratio(row, col[0], col[1])
        elif mid == "rtt_ul":
            out[mid] = _ratio(row, "rtt_sum_ul", "rtt_att_ul")
        elif mid == "rtt_dl":
            out[mid] = _ratio(row, "rtt_sum_dl", "rtt_att_dl")
        else:
            out[mid] = None
    return out


def _ratio(row: Dict[str, Any], num_col: str, den_col: str) -> Optional[float]:
    den = float(row.get(den_col) or 0)
    if den <= 0:
        return None
    return float(row.get(num_col) or 0) / den * 100.0


_WINDOW_KEYS = ("ul_bytes", "dl_bytes", "conn_att", "conn_ok", "rt_att_ul", "rt_bad_ul",
                "rt_att_dl", "rt_bad_dl", "dis_bad_ul", "dis_bad_dl", "loss_bad_ul", "loss_bad_dl",
                "rtt_att_ul", "rtt_sum_ul", "rtt_att_dl", "rtt_sum_dl", "vt_num", "vt_den")


def _window_counters(rows: List[Dict[str, Any]], gran: str, end_hh: Optional[int]) -> Dict[str, float]:
    """把窗口内（hour: hh<=end_hh；day: 全部）的计数器求和。"""
    out = {k: 0.0 for k in _WINDOW_KEYS}
    for r in rows:
        if gran == "hour" and end_hh is not None and int(r.get("hh") or 0) > end_hh:
            continue
        for k in _WINDOW_KEYS:
            out[k] += float(r.get(k) or 0)
    return out


def _value_from_counters(mid: str, c: Dict[str, float], gran: str,
                         seconds: Optional[float] = None) -> Optional[float]:
    vals = _point_values(c, gran, [mid], seconds)
    return vals.get(mid)


# ==========================================================================
# 组装 payload（routers 调用）
# ==========================================================================
def _member_label(dim: str, member: str, areas: Dict[str, Any], nes: Dict[str, str],
                  locale_hint: str = "zh") -> str:
    if dim == "total":
        return "全网" if locale_hint == "zh" else "Whole Network"
    if dim == "ne":
        return nes.get(member, "target_%s" % member)
    if member == NEUTRAL_MEMBER:
        return "未归类" if locale_hint == "zh" else "Unclassified"
    info = areas.get(member) or {}
    return info.get("name") or member


def _neighbors(day_iso: str) -> Tuple[str, str]:
    d = date.fromisoformat(day_iso)
    return (d - timedelta(days=1)).isoformat(), (d - timedelta(days=7)).isoformat()


def _primary_metric(cat: str) -> str:
    return "video_tput_mbps" if cat == "video" else "total_gb"


def meta_payload(conn) -> Dict[str, Any]:
    """看板首屏需要的可用性信息：有哪几天、类目就绪情况、成员字典、刷新时间。"""
    hour_days = store.stored_days(conn, "hour")
    day_days = store.stored_days(conn, "day")
    cats = {}
    for cat in CATS:
        dims = CAT_DIMS[cat]
        ready = False
        if dims:
            src = SRC_CAT.get(cat, cat)
            row = conn.execute("SELECT 1 FROM kpi_hour WHERE cat = ? LIMIT 1", (src,)).fetchone()
            ready = row is not None
        cats[cat] = {"ready": ready, "dims": dims, "metrics": CAT_METRICS[cat],
                     "alarm_metrics": ALARM_METRICS[cat]}
    run = store.last_run(conn)
    latest_hour_day = hour_days[-1] if hour_days else None
    return {
        "updated_at": (run or {}).get("finished_at"),
        "last_run_status": (run or {}).get("status"),
        "hour_days": hour_days, "day_days": day_days,
        "latest_hour_day": latest_hour_day,
        "latest_day": day_days[-1] if day_days else None,
        "window_end_hour": store.window_end_hour(conn, latest_hour_day) if latest_hour_day else -1,
        "cats": cats,
        "area_names": store.area_names(conn),
        "ne_names": store.ne_names(conn),
        "thresholds": {"critical": THRESH_CRIT, "major": THRESH_MAJOR},
        "day_trend_days": DAY_TREND_DAYS,
        "notes": {
            "control": "控制面表族在数仓暂无数据（aggr_base_control_* / 2b2c 信令族为空），先占位",
            "voice": "VoLTE/VoNR KQI 表族为空，语音页签先占位；OTT语音(VoIP) 数据在「数据」页",
            "source": "VMAX 数仓 GBase 只读直连（任务 soc_trend_sync）",
        },
    }


def series_payload(conn, gran: str, day_iso: str, cat: str, dim: str) -> Dict[str, Any]:
    """趋势序列：hour=当日 0..23 时 × D/D-1/D-7 三条线；day=最近 30 天同一时段（0..H）总量。

    ⚠ 天视图刻意**不读 kpi_day**（2026-10-30 实测：数仓 `_day_` 当天分区比 `_hour_`
    滞后数小时，61TB vs 131TB，且「当天半截 vs 基线全天」会产生假告警）——
    统一由小时表按「0:00 至所选日最后完整小时」同时段聚合，与告警窗口口径一致。

    dim='app'（业务 APP Top-N，仅 5 个分业务类目）从 kpi_app_hour 取数，其余同构。
    """
    if dim not in CAT_DIMS.get(cat, []):
        return {"error": "类目 %s 不支持维度 %s" % (cat, dim)}
    metrics = CAT_METRICS.get(cat, [])
    src = SRC_CAT.get(cat, cat)
    d1, d7 = _neighbors(day_iso)
    areas = store.area_names(conn)
    nes = store.ne_names(conn)
    app_names = store.app_names(conn)
    members_out: List[Dict[str, Any]] = []

    if dim == "app":
        # APP 维度：member='service:appid'，名称取 dim_app；D/D-1/D-7 与 30 天趋势都从小时表聚合
        def app_label(member: str) -> str:
            return app_names.get(member) or member

        if gran == "hour":
            days = [day_iso, d1, d7]
            rows = store.fetch_app_rows(conn, days, cat)
            by_member: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {}
            for r in rows:
                slot = by_member.setdefault(str(r["member"]), {}).setdefault(str(r["day"]), {})
                slot[int(r.get("hh") or 0)] = r
            members = sorted(by_member.keys(),
                             key=lambda m: -sum(float(x.get("dl_bytes") or 0)
                                                for dm in by_member[m].values()
                                                for x in dm.values()))[:40]
            for member in members:
                per_day: Dict[str, List[Optional[Dict[str, Any]]]] = {}
                for d in days:
                    recs = by_member[member].get(d, {})
                    per_day[d] = [
                        {"hh": hh, "values": _point_values(recs[hh], "hour", metrics)}
                        if hh in recs else None for hh in range(24)]
                members_out.append({"member": member, "name": app_label(member),
                                    "points": per_day})
            return {"gran": gran, "day": day_iso, "d1": d1, "d7": d7, "cat": cat, "dim": dim,
                    "metrics": metrics, "primary_metric": _primary_metric(cat),
                    "window_end_hour": store.window_end_hour(conn, day_iso),
                    "members": members_out}
        all_days = [d for d in store.stored_days(conn, "hour") if d <= day_iso][-DAY_TREND_DAYS:]
        rows = store.fetch_app_rows(conn, all_days, cat)
        end_hh = store.window_end_hour(conn, day_iso)
        win_seconds = (end_hh + 1) * 3600.0
        by_member: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for r in rows:
            by_member.setdefault(str(r["member"]), {}).setdefault(str(r["day"]), []).append(r)
        members = sorted(by_member.keys(),
                         key=lambda m: -sum(float(r.get("dl_bytes") or 0)
                                            for lst in by_member[m].values() for r in lst))[:40]
        for member in members:
            values: Dict[str, Dict[str, Optional[float]]] = {}
            for d in all_days:
                c = _window_counters(by_member[member].get(d, []), "hour", end_hh)
                vals = _point_values(dict(c), "day", metrics, seconds=win_seconds)
                values[d] = {m: vals.get(m) for m in metrics}
            members_out.append({"member": member, "name": app_label(member), "values": values})
        return {"gran": gran, "day": day_iso, "d1": d1, "d7": d7, "cat": cat, "dim": dim,
                "metrics": metrics, "primary_metric": _primary_metric(cat),
                "window_end_hour": end_hh, "days": all_days, "members": members_out}

    # （dim=app 分支已提前返回，以下为 total/area/ne 维度）
    if gran == "hour":
        days = [day_iso, d1, d7]
        rows = store.fetch_rows(conn, "hour", days, src, dim)
        by_member: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = {}
        for r in rows:
            slot = by_member.setdefault(str(r["member"]), {}).setdefault(str(r["day"]), {})
            slot[int(r.get("hh") or 0)] = r
        members = sorted(by_member.keys(),
                         key=lambda m: (m == NEUTRAL_MEMBER, -sum(
                             float(x.get("dl_bytes") or 0)
                             for days_map in by_member[m].values() for x in days_map.values())))
        for member in members:
            per_day: Dict[str, List[Optional[Dict[str, Any]]]] = {}
            for d in days:
                recs = by_member[member].get(d, {})
                points: List[Optional[Dict[str, Any]]] = []
                for hh in range(24):
                    row = recs.get(hh)
                    # 全指标逐时数值：前端切指标不重拉（主指标由前端选择）
                    points.append({"hh": hh, "values": _point_values(row, "hour", metrics)}
                                  if row else None)
                per_day[d] = points
            members_out.append({
                "member": member, "name": _member_label(dim, member, areas, nes),
                "points": per_day,
            })
        payload = {"gran": gran, "day": day_iso, "d1": d1, "d7": d7, "cat": cat, "dim": dim,
                   "metrics": metrics, "primary_metric": _primary_metric(cat),
                   "window_end_hour": store.window_end_hour(conn, day_iso),
                   "members": members_out}
    else:
        all_days = [d for d in store.stored_days(conn, "hour") if d <= day_iso][-DAY_TREND_DAYS:]
        rows = store.fetch_rows(conn, "hour", all_days, src, dim)
        end_hh = store.window_end_hour(conn, day_iso)          # 所选日的最后完整小时（同时段口径）
        win_seconds = (end_hh + 1) * 3600.0
        by_member: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for r in rows:
            slot = by_member.setdefault(str(r["member"]), {}).setdefault(str(r["day"]), [])
            slot.append(r)
        members = sorted(by_member.keys(),
                         key=lambda m: (m == NEUTRAL_MEMBER, -sum(
                             float(r.get("dl_bytes") or 0)
                             for lst in by_member[m].values() for r in lst)))
        for member in members:
            values: Dict[str, Dict[str, Optional[float]]] = {}
            for d in all_days:
                c = _window_counters(by_member[member].get(d, []), "hour", end_hh)
                row_view = dict(c)
                vals = _point_values(row_view, "day", metrics, seconds=win_seconds)
                values[d] = {m: vals.get(m) for m in metrics}
            members_out.append({"member": member, "name": _member_label(dim, member, areas, nes),
                                "values": values})
        payload = {"gran": gran, "day": day_iso, "d1": d1, "d7": d7, "cat": cat, "dim": dim,
                   "metrics": metrics, "primary_metric": _primary_metric(cat),
                   "window_end_hour": end_hh,
                   "days": all_days, "members": members_out}
    return payload


# ==========================================================================
# 双基线告警 + 局部异常雷达
# ==========================================================================
def alarms_payload(conn, gran: str, day_iso: str) -> Dict[str, Any]:
    # 天粒度与小时粒度共用同一套窗口计算：一律读小时表、取「0:00 至所选日最后完整小时」
    # 同时段对比（kpi_day 当天分区滞后数小时且半截对全天会产生假告警，2026-10-30 实测）。
    d1, d7 = _neighbors(day_iso)
    end_hh = store.window_end_hour(conn, day_iso)
    have_d1 = store.day_has_data(conn, "hour", d1)
    have_d7 = store.day_has_data(conn, "hour", d7)
    areas = store.area_names(conn)
    nes = store.ne_names(conn)
    alarms: List[Dict[str, Any]] = []
    for cat in CATS:
        src = SRC_CAT.get(cat, cat)
        for dim in CAT_DIMS[cat]:
            if dim == "app":
                continue              # APP 成员每日 Top-N 滚动，不参与告警（避免成员漂移噪声）
            days = [day_iso, d1, d7]
            rows = store.fetch_rows(conn, "hour", days, src, dim)
            if not rows:
                continue
            by: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
            for r in rows:
                by.setdefault((str(r["day"]), str(r["member"])), []).append(r)
            for member, members_days in _by_member(by).items():
                cur = _window_counters(members_days.get(day_iso, []), "hour", end_hh)
                b1 = _window_counters(members_days.get(d1, []), "hour", end_hh)
                b7 = _window_counters(members_days.get(d7, []), "hour", end_hh)
                for mid in ALARM_METRICS[cat]:
                    alarm = _check_metric(cat, dim, member, mid, cur, b1, b7, gran,
                                          have_d1 and have_d7, areas, nes,
                                          seconds=(end_hh + 1) * 3600.0)
                    if alarm:
                        alarms.append(alarm)
    alarms.sort(key=lambda a: (0 if a["level"] == "critical" else 1, -abs(a["d1_pct"])))
    _attach_contributions(conn, gran, day_iso, d1, end_hh, alarms, areas, nes)
    radar = _radar_groups(alarms, areas, nes)
    return {"gran": gran, "day": day_iso, "d1": d1, "d7": d7,
            "window_end_hour": end_hh if end_hh is not None else 23,
            "baselines_ready": bool(have_d1 and have_d7),
            "thresholds": {"critical": THRESH_CRIT, "major": THRESH_MAJOR},
            "alarms": alarms, "radar": radar}


def _by_member(by: Dict[Tuple[str, str], List[Dict[str, Any]]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for (day, member), rows in by.items():
        out.setdefault(member, {})[day] = rows
    return out


def _check_metric(cat: str, dim: str, member: str, mid: str, cur: Dict[str, float],
                  b1: Dict[str, float], b7: Dict[str, float], gran: str, baselines_ready: bool,
                  areas: Dict[str, Any], nes: Dict[str, str],
                  seconds: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """单指标双基线判定。基线无效/低于规模地板时不触发。"""
    if not baselines_ready:
        return None
    v_cur = _value_from_counters(mid, cur, gran, seconds)
    v_1 = _value_from_counters(mid, b1, gran, seconds)
    v_7 = _value_from_counters(mid, b7, gran, seconds)
    if v_cur is None or v_1 in (None, 0) or v_7 in (None, 0):
        return None
    adverse = METRICS[mid]["adverse"]
    if adverse == "drop":
        p1 = (v_cur - v_1) / v_1 * 100
        p7 = (v_cur - v_7) / v_7 * 100
        breached = p1 <= -THRESH_MAJOR and p7 <= -THRESH_MAJOR
        direction = "drop"
    else:
        p1 = (v_cur - v_1) / v_1 * 100 if v_1 > 0 else 0.0
        p7 = (v_cur - v_7) / v_7 * 100 if v_7 > 0 else 0.0
        breached = p1 >= THRESH_MAJOR and p7 >= THRESH_MAJOR
        direction = "rise"
    if not breached:
        return None
    # 规模地板：体量类看基线体量，比率类看分母；% 类指标再加绝对百分点门槛
    # （2026-10-30 实测：丢包率 0.13%->0.47% 属真劣化应保留，而 0.01%->0.04% 的
    #  +300% 属小基数噪声，须滤掉 —— 相对与绝对双门槛同时满足才触发）
    if mid in VOLUME_METRICS:
        if max(v_1, v_7) < MIN_BASE_GB:
            return None
    else:
        den = _denominator(mid, b1, b7)
        if den < MIN_DEN:
            return None
        if METRICS[mid]["unit"] == "%" and (
                abs(v_cur - v_1) < RATE_MIN_DELTA_PP or abs(v_cur - v_7) < RATE_MIN_DELTA_PP):
            return None
    level = "critical" if (abs(p1) >= THRESH_CRIT and abs(p7) >= THRESH_CRIT) else "major"
    return {"cat": cat, "dim": dim, "member": member,
            "name": _member_label(dim, member, areas, nes),
            "metric": mid, "level": level, "direction": direction,
            "d1_pct": round(p1, 1), "d7_pct": round(p7, 1),
            "value": round(v_cur, 2),
            "base_gb": round((float(b1.get("ul_bytes") or 0) + float(b1.get("dl_bytes") or 0)) / GIB, 1)}


def _denominator(mid: str, b1: Dict[str, float], b7: Dict[str, float]) -> float:
    pairs = {"conn_rate": ("conn_att",), "rt_rate_ul": ("rt_att_ul",), "rt_rate_dl": ("rt_att_dl",),
             "dis_rate_ul": ("rt_att_ul",), "dis_rate_dl": ("rt_att_dl",),
             "loss_rate_ul": ("rt_att_ul",), "loss_rate_dl": ("rt_att_dl",),
             "rtt_ul": ("rtt_att_ul",), "rtt_dl": ("rtt_att_dl",),
             "video_tput_mbps": ("vt_den",)}
    cols = pairs.get(mid)
    if not cols:
        return 0.0
    total = 0.0
    for c in cols:
        total += float(b1.get(c) or 0) + float(b7.get(c) or 0)
    return total


def _attach_contributions(conn, gran: str, day_iso: str, d1: str, end_hh: Optional[int],
                          alarms: List[Dict[str, Any]], areas: Dict[str, Any],
                          nes: Dict[str, str]) -> None:
    """给体量类告警附「同一维度互斥切片」的其它维度贡献占比（只取不利方向）。"""
    volume_alarms = [a for a in alarms if a["metric"] in VOLUME_METRICS]
    if not volume_alarms:
        return
    need: Dict[Tuple[str, str], None] = {}
    for a in volume_alarms:
        for d2 in CAT_DIMS[a["cat"]]:
            if d2 != a["dim"]:
                need[(a["cat"], d2)] = None
    data: Dict[Tuple[str, str], Dict[Tuple[str, str], Dict[str, float]]] = {}
    for cat, dim in need:
        rows = store.fetch_rows(conn, "hour", [day_iso, d1], SRC_CAT.get(cat, cat), dim)
        agg: Dict[Tuple[str, str], Dict[str, float]] = {}
        for r in rows:
            key = (str(r["day"]), str(r["member"]))
            slot = agg.setdefault(key, {"ul_bytes": 0.0, "dl_bytes": 0.0})
            slot["ul_bytes"] += float(r.get("ul_bytes") or 0)
            slot["dl_bytes"] += float(r.get("dl_bytes") or 0)
        data[(cat, dim)] = agg
    for a in volume_alarms:
        contribs: List[Dict[str, Any]] = []
        col = "ul_bytes" if a["metric"] == "ul_gb" else (
            "dl_bytes" if a["metric"] == "dl_gb" else None)
        if col is None:                      # total_gb -> ul+dl
            col = "__total"
        for d2 in CAT_DIMS[a["cat"]]:
            if d2 == a["dim"]:
                continue
            agg = data.get((a["cat"], d2)) or {}
            deltas: List[Tuple[str, float]] = []
            members = set(k[1] for k in agg)
            for member in members:
                cur = agg.get((day_iso, member))
                base = agg.get((d1, member))
                if not cur or not base:
                    continue
                cv = (cur["ul_bytes"] + cur["dl_bytes"]) if col == "__total" else cur.get(col, 0.0)
                bv = (base["ul_bytes"] + base["dl_bytes"]) if col == "__total" else base.get(col, 0.0)
                delta = (bv - cv) if a["direction"] == "drop" else (cv - bv)
                if delta > 0:
                    deltas.append((member, delta))
            total = sum(d for _, d in deltas)
            if total <= 0:
                continue
            deltas.sort(key=lambda x: -x[1])
            for member, delta in deltas[:3]:
                contribs.append({
                    "dim": d2, "member": member,
                    "name": _member_label(d2, member, areas, nes),
                    "share_pct": round(delta / total * 100, 1)})
        a["contributions"] = contribs


def _radar_groups(alarms: List[Dict[str, Any]], areas: Dict[str, Any],
                  nes: Dict[str, str]) -> List[Dict[str, Any]]:
    """按成员聚合告警（异常雷达）：Critical 优先、项数与最差指标排序。"""
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for a in alarms:
        if a["dim"] == "total":
            continue                          # 雷达只看「局部」（区域/网元），全网告警在上方列表
        key = (a["dim"], a["member"])
        g = groups.setdefault(key, {
            "dim": a["dim"], "member": a["member"],
            "name": _member_label(a["dim"], a["member"], areas, nes),
            "level": "major", "count": 0, "worst": None, "base_gb": 0.0})
        g["count"] += 1
        if a["level"] == "critical":
            g["level"] = "critical"
        score = abs(a["d1_pct"]) + abs(a["d7_pct"])
        if g["worst"] is None or score > g["worst"]["score"]:
            g["worst"] = {"metric": a["metric"], "d1_pct": a["d1_pct"], "d7_pct": a["d7_pct"],
                          "score": score, "level": a["level"]}
        g["base_gb"] = max(g["base_gb"], a.get("base_gb") or 0.0)
    out = list(groups.values())
    out.sort(key=lambda g: (0 if g["level"] == "critical" else 1, -g["count"],
                            -(g["worst"] or {}).get("score", 0)))
    for g in out:
        g["worst"] = ({k: v for k, v in (g["worst"] or {}).items() if k != "score"} or None)
    return out
