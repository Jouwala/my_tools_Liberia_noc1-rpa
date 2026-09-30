# -*- coding: utf-8 -*-
"""BP Report —— 三个 BP 条件指标的取数与**忙时**聚合（UME PM API 小时粒度）。

=========================== 为什么单独一个模块 ===========================

BP 的三个条件指标要跨两个数据源才能凑齐，且**口径必须一致**：

- PRB 利用率 / DL 吞吐：`4G_Main_Kpi_Cell_Daily` 里**有**，但那是**日均值**；
- `Average DL Active User Number`：该表**没有**，且**加不进去** ——
  它只在小时粒度（`gr=3600`）可用，日粒度下 UME 返回 HTTP 200 但
  **静默丢弃该列**（UME 原文 `0001610001 ... PDF counter/indicator
  dimension is illegal`）。

**口径标定结论（2026-09-30，实测）**：umlaut 的三个条件是按**忙时**判定的，
即取「AU 最大的那个小时」的 PRB/Thr/AU 三值作为当天数据：
在 2026-09-21 上，该口径命中 607 个小区，与 Excel `BP Cells List` 明细
（607 个）**逐小区完全一致（Jaccard=1.00）**；而日均值口径只有 17 个
（差 30 倍）；"任一小时满足"口径会多 41 个误命中（Jaccard=0.94）。
因此本模块按小时取数，**按 AU 最大小时聚合出当天的三值**。

=========================== 取数姿势（实测确定）===========================

必须按 `data\\umlaut_data\\url.txt` 抓到的 payload 形态，关键项：

- `gr="3600"`：小时粒度，不能改 86400（AU 会被静默丢弃）；
- 三个 items 的 `itemsposition` 全为 **0**（位置由后两个数组承担）；
- `itemsposition1`：PRB/Thr 取 **2**，AU 取 **1**；
- `itempositionbusiness`：PRB/Thr 取 **1**，AU 取 **0**；
- `indexfillingtype="zeroDenominator"`；
- `groupbygroup=false`、`grouplayer="me,eNodeBFunction,EUtranCellFDD"`；
- **不带 `filter`**（url.txt 里的 `operation=200 value=0` 是 UI 过滤，
  会漏掉 AU=0 的小区）。

⚠️ **响应解析的两个坑（都实测踩过）**：
1. 数值是**字符串**且 PRB 带**百分号**（`'2.46%'`），必须去 `%` 再 `/100`，
   否则 `float()` 全部抛异常、静默得到 0 个小区；
2. `v1/history/page` **只创建查询不取数**，必须轮询就绪后拉页 ——
   未等就绪时 `totalcount` 会是半截值（实测 3.6 万 vs 实际 15.3 万）。

=========================== 性能 ===========================

分页耗时与 `pagesize` 无关（约 90s 的服务端固定查询准备成本），
一次大 `pagesize` 取回全天（实测 15 万行约 96s）。
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bp_active_user")

# ============================================================
# 一、指标与请求形态常量
# ============================================================

#: UME item code（`KPI_Template.xlsx` 与 `url.txt` 一致）。
ITEM_AU = "C373384373"
#: [FDD]DL PRB Utilization Rate[SDR_ITBBU]
ITEM_PRB = "1638004469342"
#: [FDD]DL IP Throughput(Mbps)[SDR_ITBBU]
ITEM_THR = "1638004469332"

#: 一次查询带的三个指标（顺序即 items 数组顺序）。
ITEMS = [ITEM_PRB, ITEM_THR, ITEM_AU]

#: AU 列名（UME 返回的 name 即此，无前缀）。
COL_AU_NAME = "Average DL Active User Number"

_GRANULARITY = "3600"
_GROUPLAYER = "me,eNodeBFunction,EUtranCellFDD"
_BUSINESS_MOTID = "FDDV3.EUtranCellFDD,EUtranCellFDD,CUEUtranCellFDDLTE"
_NFCTID = "ITBBU,SDR,#"
_MOTID = "EUtranCellFDD"

_COL_CELL = "EUtranCellFDD"
_COL_BEGIN = "begintime"

_PAGE_SIZE = 200000
_POLL_INTERVAL = 5
_POLL_MAX = 90
_CREATE_RETRIES = 5
_CREATE_BACKOFF = 10


class ActiveUserUnavailable(RuntimeError):
    """该日三指标取不到（区别于「值很小」）。调用方应保持 `is_bp = NULL`。"""


def _parse_num(s: Any) -> Optional[float]:
    """UME 数值解析。

    ⚠️ 返回的是**字符串**，且 PRB 带**百分号**（`'2.46%'` = 0.0246）。
    直接 `float()` 会全部抛异常 → 静默得到 0 个小区（实测踩过）。
    """
    s = str(s).strip() if s is not None else ""
    if not s:
        return None
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _build_payload(day: str) -> Dict[str, Any]:
    """构造一天的小时级三指标查询 payload（形态依据 url.txt，见模块 docstring）。"""
    d = _dt.date(*[int(x) for x in day.split("-")])
    nxt = (d + _dt.timedelta(days=1)).isoformat()
    return {
        "arraycounterinfos": [], "datatype": 0, "displaymode": 0,
        "favoriteconditionname": "BP Busy Hour", "gr": _GRANULARITY,
        "groupattributetype": 0, "groupbygroup": False, "groupbyplmn": False,
        "grouptype": 0,
        "items": ITEMS, "itemsposition": [0, 0, 0],
        "itemsposition1": [2, 2, 1], "itempositionbusiness": [1, 1, 0],
        "motid": _MOTID, "nfctid": _NFCTID,
        "plmnpdfdisplaymode": False, "queryallbusiness": False,
        "showbusinesscolumn": True, "showintegrity": False,
        "straightquery": False, "versiondatacompare": False,
        "needdeployfilter": False,
        "timeinfo": {
            "mode": 1, "start": day + "T00:00:00.000Z",
            "end": nxt + "T00:00:00.000Z", "relative": -7,
            "timezonetype": "1", "clienttimezone": "Atlantic/Reykjavik",
            "showtimezoneoffset": False,
            "querylongtime": {"type": 3, "value": 1},
            "timespanfilter": "00:00:00-24:00:00",
            "dayfiltertype": 0, "dayinmonthfilter": "1" * 31,
        },
        "indexfillingtype": "zeroDenominator",
        "businessmotid": _BUSINESS_MOTID,
        "templatetype": 0, "filterlayer": "all",
        "grouplayer": _GROUPLAYER, "containvcell": 0,
        "resfilterattribute": "", "uilocations": [], "reslocation": [],
        "inexistenceres": False, "groupbusinessids": [],
        "businessfilterscope": [], "firstDayOfWeek": 7,
        "iswireless": True, "hidehistorystopbutton": True,
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
    }


def _assert_items_returned(cols: List[str], day: str) -> None:
    """校验请求的三个指标都出现在返回列里。

    UME 对不支持的指标是**静默丢弃**：HTTP 200、有 queryid、列里没有它。
    不校验就会把「指标没取到」当成「指标值为空」，进而把 BP 判错。
    """
    missing = set(ITEMS) - set(cols)
    if missing:
        raise ActiveUserUnavailable(
            f"{day}: UME 未返回 {sorted(missing)}。返回列 = {cols}。"
            f"该组指标需要小时粒度（gr={_GRANULARITY}），"
            f"日粒度下会被静默丢弃。")


def _post_json(mk, path: str, body: Dict[str, Any],
               headers) -> Dict[str, Any]:
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    _st, _h, _rh, data = mk._http_request_with_retry(
        "POST", path, headers_extra=headers, body=raw, max_retries=3)
    return json.loads(data.decode("utf-8", "replace"))


def _login_headers(mk):
    auth = mk.login()
    return mk._auth_headers(auth.get("cookie", ""),
                            auth.get("forgery_token", ""))


def fetch_day_busy_hour(day: str) -> Dict[str, Dict[str, float]]:
    """取一天全部小区的**忙时**（AU 最大小时）三指标值。

    Returns:
        `{cell: {"prb": 忙时PRB(小数), "thr": 忙时吞吐Mbps,
        "au": 忙时AU, "hour": "HH:MM"}}`。

    Raises:
        ActiveUserUnavailable: 指标未返回 / 创建失败 / 数据被截断。
    """
    from backend.services import ran_ume_main_kpi as mk

    try:
        headers = _login_headers(mk)
    except Exception as e:
        raise ActiveUserUnavailable(f"{day}: UME 鉴权失败: {e}") from e

    resp = None
    for attempt in range(_CREATE_RETRIES):
        try:
            resp = _post_json(mk, mk.HISTORY_PATH, _build_payload(day), headers)
        except Exception as e:
            logger.warning("[BP-BUSY] %s 创建查询异常(第%d次): %s",
                           day, attempt + 1, e)
            resp = None
        if resp and resp.get("queryid"):
            break
        logger.warning("[BP-BUSY] %s 创建查询未拿到 queryid(第%d次): %s",
                       day, attempt + 1, (resp or {}).get("errorcode"))
        _sleep(_CREATE_BACKOFF)
    if not resp or not resp.get("queryid"):
        raise ActiveUserUnavailable(
            f"{day}: UME 创建查询失败（重试 {_CREATE_RETRIES} 次）")

    cols = [str(c.get("id")) for c in resp.get("columns") or []]
    _assert_items_returned(cols, day)
    qid = resp["queryid"]
    i_prb = cols.index(ITEM_PRB)
    i_thr = cols.index(ITEM_THR)
    i_au = cols.index(ITEM_AU)
    i_cell = cols.index(_COL_CELL)
    i_beg = cols.index(_COL_BEGIN)

    rows = _fetch_all_pages(day, qid)
    # {cell: {begintime: (prb, thr, au)}}
    hourly: Dict[str, Dict[str, Tuple[float, float, float]]] = defaultdict(dict)
    skipped = 0
    for row in rows:
        v = row.get("values") or []
        if len(v) <= max(i_prb, i_thr, i_au, i_cell, i_beg):
            skipped += 1
            continue
        cell = v[i_cell]
        if not cell:
            skipped += 1
            continue
        prb = _parse_num(v[i_prb])
        thr = _parse_num(v[i_thr])
        au = _parse_num(v[i_au])
        if prb is None or thr is None or au is None:
            # 该小时缺任一值：跳过该小时（不当作 0，避免选错忙时）
            skipped += 1
            continue
        hourly[str(cell)][str(v[i_beg])] = (prb, thr, au)

    out: Dict[str, Dict[str, float]] = {}
    for cell, hh in hourly.items():
        if not hh:
            continue
        bk = max(hh, key=lambda k: hh[k][2])   # AU 最大的小时 = 忙时
        prb, thr, au = hh[bk]
        out[cell] = {"prb": prb, "thr": thr, "au": au,
                     "hour": bk[11:16] if len(bk) >= 16 else bk}
    logger.info("[BP-BUSY] %s 取回 %d 行 → %d 小区（跳过 %d 行）",
                day, len(rows), len(out), skipped)
    if not out and rows:
        raise ActiveUserUnavailable(
            f"{day}: 收到 {len(rows)} 行但解析出 0 个小区，"
            f"响应格式可能已变化")
    return out


def _sleep(seconds: float) -> None:
    import time
    time.sleep(seconds)


def _fetch_all_pages(day: str, qid: str) -> List[Dict[str, Any]]:
    """等查询就绪后一次取回全天行。

    必须先轮询就绪：查询未完成时 `rows` 会**边跑边返回部分行**，
    实测未等待时 `totalcount` 只有 3.6 万（实际 15.3 万），会静默取到半截数据。
    """
    from backend.services import ran_ume_main_kpi as mk

    headers = _login_headers(mk)
    ready = None
    for _ in range(_POLL_MAX):
        d = _post_json(mk, "/api/pm-analysis/v1/history/page",
                       {"type": 1, "queryfilters": [], "pagesize": 5,
                        "page": 1, "queryid": qid, "pagesortfields": []},
                       headers)
        if d.get("querystate") == 1 or (d.get("progress") or 0) >= 100:
            ready = d
            break
        _sleep(_POLL_INTERVAL)
    if ready is None:
        raise ActiveUserUnavailable(f"{day}: 查询 {qid} 超时未就绪")

    total = int(ready.get("totalcount") or 0)
    if total <= 0:
        logger.info("[BP-BUSY] %s totalcount=0，该日无数据", day)
        return []

    d = _post_json(mk, "/api/pm-analysis/v1/history/page",
                   {"type": 1, "queryfilters": [],
                    "pagesize": max(total + 1000, _PAGE_SIZE), "page": 1,
                    "queryid": qid, "pagesortfields": []}, headers)
    rows = d.get("rows") or []
    if d.get("cuthappened"):
        raise ActiveUserUnavailable(
            f"{day}: 响应 cuthappened=true，数据被截断（totalcount={total}，"
            f"收到 {len(rows)}）")
    if len(rows) < total:
        logger.warning("[BP-BUSY] %s 期望 %d 行，实收 %d 行",
                       day, total, len(rows))
    return rows


def fetch_days_busy(days: List[str]) -> Tuple[Dict[str, Dict[str, Dict[str, float]]],
                                              Dict[str, str]]:
    """取多天的忙时三值。

    Returns:
        `(busy, errors)`：
        - `busy = {day: {cell: {"prb","thr","au","hour"}}}`，失败的天不在其中；
        - `errors = {day: 原因}`，供调用方告警（**绝不静默当 0 处理**）。

    单天失败不影响其它天：缺哪天就让哪天 `is_bp = NULL`（不可判定）。
    """
    busy: Dict[str, Dict[str, Dict[str, float]]] = {}
    errors: Dict[str, str] = {}
    for day in days:
        try:
            busy[day] = fetch_day_busy_hour(day)
        except ActiveUserUnavailable as e:
            errors[day] = str(e)
            logger.warning("[BP-BUSY] %s 取数失败: %s", day, e)
        except Exception as e:
            errors[day] = f"{type(e).__name__}: {e}"
            logger.exception("[BP-BUSY] %s 取数异常", day)
    return busy, errors
