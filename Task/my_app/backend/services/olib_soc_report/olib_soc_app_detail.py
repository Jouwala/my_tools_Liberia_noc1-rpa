# -*- coding: utf-8 -*-
"""OLIB SOC 看板的「分业务明细下钻层」—— 一天 × 一业务一行的 drill-down 数据。

分层关系（与 olib_soc_kpi_store 的 daily_kpi 卡片层互补）：
    daily_app_offload  一天一业务一行：总流量 / 缓存占比两张卡的下钻（本地/海外/未识别三桶）
    daily_video_app    一天一视频 APP 一行：视频流量 / 视频速率 / 视频占比三张卡的下钻
    daily_game_app     一天一游戏 APP 一行：游戏流量卡的下钻（含按流量加权的 TCP RTT）

与 daily_kpi 分表存放的原因（沿用 kpi_store 的结论）：daily_kpi 是「一天一行的卡片
口径」，残缺日自愈按 REQUIRED_COLUMNS 逐列判空；明细混进同一张表会让「某个 APP
没取到」被误判成整天残缺，触发无意义的重取。

三张明细表共用同一份 builder 载荷契约（status/as_of/window/day/window_agg，最新一天
与窗口累计两套行 + TOP-N 之外的并成「其它」+ 合计行），前端弹窗按列配置渲染 ——
看板再加一张下钻卡 = 一张明细表 + 一个 builder + 一份列集，不再各写一套。
第 4 张下钻表 daily_tcp_target（TCP 三卡的逐网元明细，键列 target_ne）在
olib_soc_ne_detail：键列与载荷语义不同（原始计数现算比率 vs 数值直存），但建表写入
复用本模块的 _upsert_rows（key_col 参数化），缺口判定复用 gap_days（tables 参数化）。

写入方（olib_soc_report_service）：offload 由 persist_app_offload 逐日专查 spservice
表族；video/game 直接复用 video/game 块**本来就按 appname 查询**的结果帧，extract
后落库，不增加任何数仓查询。本模块对 sqlite 只读（query_only）或建表/upsert，
接口全部只读。
"""
import logging
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.services.olib_soc_report import olib_soc_kpi_store as kpi_store

logger = logging.getLogger("olib_soc_app_detail")

# ---- 表名与数值列（主键都是 (day, appname)，重跑同一天幂等覆盖） ----
APP_OFFLOAD_TABLE = "daily_app_offload"
APP_OFFLOAD_COLUMNS: Tuple[str, ...] = ("total_tb", "local_tb", "abroad_tb", "unknown_tb")
VIDEO_APP_TABLE = "daily_video_app"
VIDEO_APP_COLUMNS: Tuple[str, ...] = ("traffic_tb", "thr_mbps")
GAME_APP_TABLE = "daily_game_app"
GAME_APP_COLUMNS: Tuple[str, ...] = ("traffic_tb", "ul_rtt_ms", "dl_rtt_ms")
OFFLOAD_TOP = 40                                            # 下钻表默认展开前 N 个业务，其余并入「其它」


def ensure_schema(conn) -> None:
    """建三张明细表 + day 索引（IF NOT EXISTS，存量库补建无害）。"""
    conn.execute("""CREATE TABLE IF NOT EXISTS %s (
        day TEXT, appname TEXT,
        total_tb REAL, local_tb REAL, abroad_tb REAL, unknown_tb REAL,
        run_id TEXT, updated_at TEXT,
        PRIMARY KEY (day, appname))""" % APP_OFFLOAD_TABLE)
    conn.execute("""CREATE TABLE IF NOT EXISTS %s (
        day TEXT, appname TEXT,
        traffic_tb REAL, thr_mbps REAL,
        run_id TEXT, updated_at TEXT,
        PRIMARY KEY (day, appname))""" % VIDEO_APP_TABLE)
    conn.execute("""CREATE TABLE IF NOT EXISTS %s (
        day TEXT, appname TEXT,
        traffic_tb REAL, ul_rtt_ms REAL, dl_rtt_ms REAL,
        run_id TEXT, updated_at TEXT,
        PRIMARY KEY (day, appname))""" % GAME_APP_TABLE)
    for table in (APP_OFFLOAD_TABLE, VIDEO_APP_TABLE, GAME_APP_TABLE):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_%s_day ON %s(day)" % (table, table))
    conn.commit()


# ==========================================================================
# 写入（三个 upsert 共用同一份逐行 INSERT OR REPLACE；row 字典键与列名一致）
# ==========================================================================
def _upsert_rows(table: str, value_cols: Tuple[str, ...],
                 rows: Iterable[Dict[str, Any]], path: Optional[Path],
                 key_col: str = "appname", ensure=None) -> int:
    """按 (day, key_col) 幂等覆盖写一行。key_col 默认 appname（分业务三表）；
    逐网元明细表（olib_soc_ne_detail.daily_tcp_target）传 target_ne + 自带建表函数 ——
    同一份写入契约，两类下钻共用，建表/upsert 语义完全一致。"""
    items = [r for r in rows
             if r.get("day") not in (None, "") and r.get(key_col) not in (None, "")]
    if not items:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = ["day", key_col] + list(value_cols) + ["run_id", "updated_at"]
    placeholders = ",".join("?" for _ in cols)
    with closing(kpi_store.connect(path)) as conn:
        # 只管明细层自己的表：daily_kpi 归 kpi_store（details_only 回填不碰卡片口径表）
        (ensure or ensure_schema)(conn)
        for row in items:
            conn.execute("INSERT OR REPLACE INTO %s (%s) VALUES (%s)"
                         % (table, ",".join(cols), placeholders),
                         [kpi_store.iso_day(row["day"]), str(row[key_col])[:120]]
                         + [row.get(c) for c in value_cols]
                         + [row.get("run_id"), row.get("updated_at") or now])
        conn.commit()
    return len(items)


def upsert_app_offload(rows: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    """写入分业务本地/海外分流明细，按 (day, appname) 覆盖 —— 同一天重跑幂等。"""
    return _upsert_rows(APP_OFFLOAD_TABLE, APP_OFFLOAD_COLUMNS, rows, path)


def upsert_video_app(rows: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    """写入视频逐 APP 明细（流量 + 有效下载速率）。"""
    return _upsert_rows(VIDEO_APP_TABLE, VIDEO_APP_COLUMNS, rows, path)


def upsert_game_app(rows: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    """写入游戏逐 APP 明细（流量 + 上/下行 RTT）。"""
    return _upsert_rows(GAME_APP_TABLE, GAME_APP_COLUMNS, rows, path)


def detail_days(table: str, path: Optional[Path] = None) -> List[str]:
    """某张明细表已覆盖的天（升序）。"""
    try:
        with closing(kpi_store.connect(path, readonly=True)) as conn:
            return [kpi_store.iso_day(r[0]) for r in conn.execute(
                "SELECT DISTINCT day FROM %s ORDER BY day" % table)]
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-app-detail] 读取 %s 日清单失败: %s", table, exc)
        return []


def gap_days(days_back: int = 7, path: Optional[Path] = None,
             today: Optional[date] = None, refresh_last: int = 1,
             tables: Optional[Sequence[str]] = None) -> List[str]:
    """明细缺哪些天：窗口内 tables 各明细表**任一张**没有的天，外加最新 N 天重取。

    单独一套缺口的原因：明细表跟着块的结果帧走，而 daily_kpi 的 gap_days
    只看 `daily_kpi` 有没有那一行。两者一旦脱钩（例如某次只跑了 --kpi-only、或明细表
    是后加的），daily_kpi 有行而明细没有，看板下钻就会缺这一天，且永远不会自愈。
    重取是幂等的（按 (day, key) 覆盖），所以「最近 N 天重取」与卡片层的
    refresh_last_days 同一思路：数仓当天分区常晚到，第二天自动纠正。
    `refresh_last=0` 表示**不做任何重取**（与 run_olib_soc_kpi_sync 的
    refresh_last=0 语义严格对齐，否则「零查询」就被明细重取偷偷打破了）。

    tables 默认「分业务两表」（video∩game）；逐网元 TCP 明细（olib_soc_ne_detail）
    接入续写后由同步侧传三表 —— 判缺口径是「任一明细表缺这天就重取当天」，
    取数本来就是一趟全块重放，多一张表的缺口不多花一次查询。
    """
    today = today or date.today()
    end = today - timedelta(days=1)
    begin = end - timedelta(days=max(1, int(days_back)) - 1)
    gap_tables = tuple(tables) if tables else (VIDEO_APP_TABLE, GAME_APP_TABLE)
    have: Optional[set] = None
    for table in gap_tables:
        covered = set(detail_days(table, path))
        have = covered if have is None else (have & covered)
    have = have or set()
    window = [(begin + timedelta(days=i)).isoformat()
              for i in range((end - begin).days + 1)]
    refreshed = set(window[-int(refresh_last):]) if int(refresh_last) > 0 else set()
    return [d for d in window if d not in have or d in refreshed]


# ==========================================================================
# builder 载荷（day + window_agg 两套行，前端弹窗按列配置渲染）
# ==========================================================================
def _f(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fresh_body(detail: str, days: int, top: int) -> Dict[str, Any]:
    return {"status": "ok", "source": "olib_soc_report", "detail": detail,
            "window_days": days, "top": top,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "as_of": None, "window": {},
            "day": {"rows": [], "others": None, "totals": None},
            "window_agg": {"rows": [], "others": None, "totals": None}}


def _error_body(body: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
    logger.warning("[olib-app-detail] %s 明细查询失败: %s", body.get("detail"), exc)
    body["status"] = "error"
    body["message"] = "%s: %s" % (type(exc).__name__, exc)
    return body


def _window_bounds(have: List[str], days: int, as_of: Optional[str],
                   today: Optional[date] = None) -> Tuple[str, str]:
    """最新一天（as_of 合法性由路由层先验）与窗口起点。

    最新一天夹到「昨天」：当天分区仍在累积（与卡片层 `end = today - 1` 同一约定），
    否则白天点开下钻会看到半天的数据，「数据截至」跑到卡片前面去。
    """
    newest = kpi_store.iso_day(as_of) if as_of else have[-1]
    completed = (today or date.today()) - timedelta(days=1)
    if newest > completed.isoformat():
        newest = completed.isoformat()
    begin = (date.fromisoformat(newest) - timedelta(days=days - 1)).isoformat()
    return begin, newest


def _preflight(body: Dict[str, Any], table: str, days: int, as_of: Optional[str],
               path: Optional[Path], empty_msg: str,
               today: Optional[date] = None) -> bool:
    """前置检查 + 写入窗口信息；False = 库/明细为空，body 已带空态消息。

    「库尚未生成」按**文件**判断，不按 daily_kpi 表判断：明细层与卡片层各管各的表
    （details_only 回填不建 daily_kpi），明细表自己有数就该能服务下钻。
    """
    if not (Path(path) if path else kpi_store.KPI_DB_PATH).exists():
        body["status"] = "empty"
        body["message"] = "KPI 库尚未生成，明细也就没有"
        return False
    have = detail_days(table, path)
    if not have:
        body["status"] = "empty"
        body["message"] = empty_msg
        return False
    begin, newest = _window_bounds(have, days, as_of, today)
    body["as_of"] = newest
    body["window"] = {"begin": begin, "end": newest,
                      "stored_days": len([d for d in have if begin <= d <= newest])}
    return True


# ---- offload（原 kpi_store.build_app_offload 原样迁入，行为契约不变） ----
def _offload_pack(name: str, values: Sequence[Any]) -> Dict[str, Any]:
    total, local, abroad, unknown = [float(v or 0) for v in values[:4]]
    known = local + abroad
    return {"appname": str(name), "total_tb": round(total, 3), "local_tb": round(local, 3),
            "abroad_tb": round(abroad, 3), "unknown_tb": round(unknown, 3),
            # 本地占的分母**只含已识别服务器 IP 的流量**：解析不出 server_ip 的那部分
            # （HTTPS/QUIC/UDP，实测约占全天 9%）既没走本地也没走海外，
            # 塞进任一边都会让比例失真 —— 单列 unknown_tb，分母用 total_tb - unknown_tb。
            "local_pct": (round(local / known * 100.0, 1) if known > 0 else None)}


def _offload_rollup(rows: List[Dict[str, Any]], limit: int
                    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """前 limit 行原样返回，其余合并成一行「其它」；totals 由调用方按全量算，不丢数。"""
    if len(rows) <= limit:
        return rows, None
    tail = rows[limit:]
    rest = [sum(float(r.get(c) or 0) for r in tail) for c in APP_OFFLOAD_COLUMNS]
    return rows[:limit], _offload_pack("", rest)


def build_app_offload(days: int = 90, as_of: Optional[str] = None,
                      top: int = OFFLOAD_TOP, path: Optional[Path] = None,
                      today: Optional[date] = None) -> Dict[str, Any]:
    """下钻载荷：最新一天的分业务本地/海外拆分 + 窗口累计（同一份数据两种视角）。"""
    days = max(1, min(int(days or 90), 400))
    top = max(5, min(int(top or OFFLOAD_TOP), 200))
    body = _fresh_body("app_offload", days, top)
    if not _preflight(body, APP_OFFLOAD_TABLE, days, as_of, path,
                      "分业务分流明细为空：跑一次 olib_soc_kpi_daily_sync（或月报）即写入",
                      today=today):
        return body
    begin, newest = body["window"]["begin"], body["as_of"]
    try:
        with closing(kpi_store.connect(path, readonly=True)) as conn:
            cur = conn.execute("SELECT appname, total_tb, local_tb, abroad_tb, unknown_tb "
                               "FROM %s WHERE day=? ORDER BY total_tb DESC" % APP_OFFLOAD_TABLE,
                               (newest,))
            day_rows = [_offload_pack(r[0], r[1:]) for r in cur.fetchall()]
            cur = conn.execute("SELECT appname, SUM(total_tb), SUM(local_tb), SUM(abroad_tb), "
                               "SUM(unknown_tb) FROM %s WHERE day>=? AND day<=? "
                               "GROUP BY appname ORDER BY SUM(total_tb) DESC"
                               % APP_OFFLOAD_TABLE, (begin, newest))
            win_rows = [_offload_pack(r[0], r[1:]) for r in cur.fetchall()]
    except Exception as exc:                                             # noqa: BLE001
        return _error_body(body, exc)
    for key, rows in (("day", day_rows), ("window_agg", win_rows)):
        shown, others = _offload_rollup(rows, top)
        totals = _offload_pack("", [sum(float(r.get(c) or 0) for r in rows)
                                    for c in APP_OFFLOAD_COLUMNS])
        totals["apps"] = len(rows)
        body[key] = {"rows": shown, "others": others, "totals": totals}
    return body


# ---- video / game：窗口原始行取回后按 appname 聚合，口径与卡片周汇总一致 ----
def _agg_group(raw: Sequence[Dict[str, Any]],
               wavg_cols: Sequence[str]) -> Dict[str, Dict[str, float]]:
    """按 appname 分组累计：traffic_tb 求和；wavg 列按 traffic_tb 加权（存分子分母）。"""
    grouped: Dict[str, Dict[str, float]] = {}
    for r in raw:
        g = grouped.setdefault(str(r.get("appname") or ""), {})
        weight = r.get("traffic_tb") or 0.0
        g["traffic_tb"] = g.get("traffic_tb", 0.0) + (r.get("traffic_tb") or 0.0)
        for col in wavg_cols:
            value = r.get(col)
            if value is not None and weight > 0:
                g["num_" + col] = g.get("num_" + col, 0.0) + value * weight
                g["den_" + col] = g.get("den_" + col, 0.0) + weight
    return grouped


def _wavg(g: Dict[str, float], col: str) -> Optional[float]:
    den = g.get("den_" + col)
    return (g["num_" + col] / den) if den else None


def _weighted(rows: Sequence[Dict[str, Any]], col: str) -> Optional[float]:
    """对已打包的行按 traffic_tb 加权平均；全 None 给 None（界面显示 —，不能显示 0）。"""
    num = sum(r["traffic_tb"] * r[col] for r in rows if r.get(col) is not None)
    den = sum(r["traffic_tb"] for r in rows if r.get(col) is not None)
    return (num / den) if den > 0 else None


# -- video：流量求和 + 速率按流量加权（库存 Mbps，界面与卡片同用 kbps，×1000） --
def _video_pack(name: str, traffic_tb: Optional[float], thr_mbps: Optional[float],
                net_total: Optional[float]) -> Dict[str, Any]:
    thr = None if thr_mbps is None else thr_mbps * 1000.0
    return {"appname": str(name or ""), "traffic_tb": round(traffic_tb or 0.0, 3),
            "thr_kbps": None if thr is None else round(thr, 1),
            # share 的分母是当日全网总流量（daily_kpi.traffic_tb），与「视频流量占比」同口径：
            # 三家合计 ≈ 卡片数值；当天缺总流量时给 None（显示 —），不用 0 硬算
            "share_pct": (round((traffic_tb or 0.0) / net_total * 100.0, 1)
                          if net_total else None)}


def build_video_apps(days: int = 90, as_of: Optional[str] = None,
                     top: int = OFFLOAD_TOP, path: Optional[Path] = None,
                     today: Optional[date] = None) -> Dict[str, Any]:
    """视频逐 APP 下钻：流量 + 有效下载速率 + 占全网总流量比。"""
    days = max(1, min(int(days or 90), 400))
    top = max(5, min(int(top or OFFLOAD_TOP), 200))
    body = _fresh_body("video_app", days, top)
    if not _preflight(body, VIDEO_APP_TABLE, days, as_of, path,
                      "视频逐 APP 明细为空：跑一次 olib_soc_kpi_daily_sync（或 --details-only 回填）即写入",
                      today=today):
        return body
    begin, newest = body["window"]["begin"], body["as_of"]
    try:
        with closing(kpi_store.connect(path, readonly=True)) as conn:
            cur = conn.execute("SELECT day, appname, traffic_tb, thr_mbps FROM %s "
                               "WHERE day >= ? AND day <= ?" % VIDEO_APP_TABLE, (begin, newest))
            raw = [{"day": kpi_store.iso_day(r[0]), "appname": r[1],
                    "traffic_tb": _f(r[2]), "thr_mbps": _f(r[3])} for r in cur.fetchall()]
            try:
                net = {kpi_store.iso_day(d): _f(t) for d, t in conn.execute(
                    "SELECT day, traffic_tb FROM %s WHERE day >= ? AND day <= ?"
                    % kpi_store.DAILY_TABLE, (begin, newest))}
            except Exception:                                            # noqa: BLE001
                # daily_kpi 表还没建（如 details_only 回填先于首次 KPI 同步）：
                # share 全为 None（界面显示 —），明细行本身照常可用，不 500
                net = {}
    except Exception as exc:                                             # noqa: BLE001
        return _error_body(body, exc)
    day_rows = [_video_pack(r["appname"], r["traffic_tb"], r["thr_mbps"], net.get(newest))
                for r in raw if r["day"] == newest]
    day_rows.sort(key=lambda r: r["traffic_tb"], reverse=True)
    # 窗口视图的分子分母用**同一天集合**：只算 daily_kpi 有总流量的天，
    # 否则「明细有天、总流量缺天」会让占比虚高
    win_src = [r for r in raw if net.get(r["day"]) is not None]
    grouped = _agg_group(win_src, ("thr_mbps",))
    win_total = sum(v for v in net.values() if v is not None)
    win_rows = [_video_pack(name, g.get("traffic_tb"), _wavg(g, "thr_mbps"), win_total)
                for name, g in grouped.items()]
    win_rows.sort(key=lambda r: r["traffic_tb"], reverse=True)
    for key, rows, total in (("day", day_rows, net.get(newest)),
                             ("window_agg", win_rows, win_total)):
        shown, others = _rollup_video(rows, total, top)
        body[key] = {"rows": shown, "others": others, "totals": _video_totals(rows, total)}
    return body


def _video_totals(rows: List[Dict[str, Any]],
                  net_total: Optional[float]) -> Dict[str, Any]:
    traffic = sum(r["traffic_tb"] for r in rows)
    thr = _weighted(rows, "thr_kbps")
    return {"appname": "", "traffic_tb": round(traffic, 3),
            "thr_kbps": None if thr is None else round(thr, 1),
            "share_pct": (round(traffic / net_total * 100.0, 1) if net_total else None),
            "apps": len(rows)}


def _rollup_video(rows: List[Dict[str, Any]], net_total: Optional[float], limit: int
                  ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if len(rows) <= limit:
        return rows, None
    return rows[:limit], _video_totals(rows[limit:], net_total)


# -- game：流量求和 + RTT 按流量加权 --
def _game_pack(name: str, traffic_tb: Optional[float], ul_rtt: Optional[float],
               dl_rtt: Optional[float]) -> Dict[str, Any]:
    return {"appname": str(name or ""), "traffic_tb": round(traffic_tb or 0.0, 3),
            "ul_rtt_ms": None if ul_rtt is None else round(ul_rtt, 2),
            "dl_rtt_ms": None if dl_rtt is None else round(dl_rtt, 2)}


def build_game_apps(days: int = 90, as_of: Optional[str] = None,
                    top: int = OFFLOAD_TOP, path: Optional[Path] = None,
                    today: Optional[date] = None) -> Dict[str, Any]:
    """游戏逐 APP 下钻：流量 + 上/下行 RTT（合计行 RTT = 各 APP 按流量加权）。"""
    days = max(1, min(int(days or 90), 400))
    top = max(5, min(int(top or OFFLOAD_TOP), 200))
    body = _fresh_body("game_app", days, top)
    if not _preflight(body, GAME_APP_TABLE, days, as_of, path,
                      "游戏逐 APP 明细为空：跑一次 olib_soc_kpi_daily_sync（或 --details-only 回填）即写入",
                      today=today):
        return body
    begin, newest = body["window"]["begin"], body["as_of"]
    try:
        with closing(kpi_store.connect(path, readonly=True)) as conn:
            cur = conn.execute("SELECT day, appname, traffic_tb, ul_rtt_ms, dl_rtt_ms FROM %s "
                               "WHERE day >= ? AND day <= ?" % GAME_APP_TABLE, (begin, newest))
            raw = [{"day": kpi_store.iso_day(r[0]), "appname": r[1],
                    "traffic_tb": _f(r[2]), "ul_rtt_ms": _f(r[3]), "dl_rtt_ms": _f(r[4])}
                   for r in cur.fetchall()]
    except Exception as exc:                                             # noqa: BLE001
        return _error_body(body, exc)
    day_rows = [_game_pack(r["appname"], r["traffic_tb"], r["ul_rtt_ms"], r["dl_rtt_ms"])
                for r in raw if r["day"] == newest]
    day_rows.sort(key=lambda r: r["traffic_tb"], reverse=True)
    grouped = _agg_group(raw, ("ul_rtt_ms", "dl_rtt_ms"))
    win_rows = [_game_pack(name, g.get("traffic_tb"),
                           _wavg(g, "ul_rtt_ms"), _wavg(g, "dl_rtt_ms"))
                for name, g in grouped.items()]
    win_rows.sort(key=lambda r: r["traffic_tb"], reverse=True)
    for key, rows in (("day", day_rows), ("window_agg", win_rows)):
        shown, others = _rollup_game(rows, top)
        body[key] = {"rows": shown, "others": others, "totals": _game_totals(rows)}
    return body


def _game_totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = _game_pack("", sum(r["traffic_tb"] for r in rows),
                     _weighted(rows, "ul_rtt_ms"), _weighted(rows, "dl_rtt_ms"))
    out["apps"] = len(rows)
    return out


def _rollup_game(rows: List[Dict[str, Any]], limit: int
                 ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if len(rows) <= limit:
        return rows, None
    return rows[:limit], _game_totals(rows[limit:])
