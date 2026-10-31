# -*- coding: utf-8 -*-
"""OLIB SOC 看板的「逐网元质量明细下钻层」—— 一天 × 一核心网元一行的 drill-down 数据。

daily_tcp_target   一天一网元一行：TCP 建链成功率 / 下行重传率 / 下行时延三张卡的下钻。

与分业务明细（olib_soc_app_detail）分模块的原因：键列不同（target_ne vs appname）、
数据来源是独立的伪块 tcp_ne 而非现有块的顺手落库；建表/upsert/载荷契约仍共用
app_detail 的同一套助手 —— 「看板再加一张下钻 = 一张明细表 + 一个 builder +
一份列集」的约定在这里继续成立。

**存原始分子/分母计数、比率查询时现算**（2026-10-31 设计要点）：卡片三比率都是
`SUM(分子)/SUM(分母)` 形态（见 olib_soc_report_service 的 tcp 块 SQL），明细表存同一批
原始计数后，「网元拆分的重聚合」与「卡片整日聚合」是对同一行集合套同一公式 ——
下钻合计 = 卡片数值是数学恒等式，不是加权平均的近似。分母为 0 的兜底值也与 tcp 块
SQL 的 CASE 逐条对齐（成功率 100 / 重传 0 / RTT 0）—— 卡片当天就是这么显示的，
下钻若显示 — 会被用户当成「表格与卡片对不上」的 bug（AGENTS.md 三.1b 第一铁律）。

数据源与生产库纪律：tcp_ne 伪块对 `aggr_5gsa_flow_ciservice_day_*`（tcp/core 块**已在
扫的同一天分区**）多跑一条按 targetid 分组的 SELECT —— 全链路只读。按
工作区总纲 AGENTS.md 第四节第 8 条 / my_app AGENTS.md 第三节第 12 条：
GBase 是生产数仓，**禁止**任何 CREATE/INSERT（含临时表、汇总表）；本模块所有写入
只落本地 sqlite。数仓侧负载纪律：每日同步只多 1 条单日分区查询（workers 并发不变），
配置 `blocks.tcp_ne=false` 可整体关停 = 软回滚，无需改代码。
"""
import logging
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.services.olib_soc_report import olib_soc_app_detail as app_detail
from backend.services.olib_soc_report import olib_soc_kpi_store as kpi_store

logger = logging.getLogger("olib_soc_ne_detail")

# ---- 表与列（主键 (day, target_ne)，重跑同一天幂等覆盖） ----
TCP_TARGET_TABLE = "daily_tcp_target"
TCP_TARGET_COLUMNS: Tuple[str, ...] = ("syn_attempts", "syn_success",   # 建链请求/成功
                                       "dl_segments", "dl_retrans",     # 下行段数/重传
                                       "dl_rtt_sum", "dl_rtt_cnt",      # 下行 RTT 分子/分母
                                       "tcp_tb")                        # 流量权重（TB）


def ensure_schema(conn) -> None:
    """建逐网元明细表 + day 索引（IF NOT EXISTS，存量库补建无害）。"""
    conn.execute("""CREATE TABLE IF NOT EXISTS %s (
        day TEXT, target_ne TEXT,
        %s,
        run_id TEXT, updated_at TEXT,
        PRIMARY KEY (day, target_ne))"""
        % (TCP_TARGET_TABLE, ", ".join("%s REAL" % c for c in TCP_TARGET_COLUMNS)))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_%s_day ON %s(day)"
                 % (TCP_TARGET_TABLE, TCP_TARGET_TABLE))
    conn.commit()


def upsert_tcp_target(rows: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    """写入逐网元 TCP 明细（rows 的键：day / target_ne / 上列原始计数）。"""
    return app_detail._upsert_rows(TCP_TARGET_TABLE, TCP_TARGET_COLUMNS, rows, path,
                                   key_col="target_ne", ensure=ensure_schema)


# ---- 比率：与 tcp 块 SQL 的 CASE 逐条同式（见模块 docstring 的对账说明） ----
def _success_pct(num: float, den: float) -> float:
    return 100.0 if den == 0 else round(num * 100.0 / den, 2)


def _ratio_pct(num: float, den: float) -> float:
    return 0.0 if den == 0 else round(num * 100.0 / den, 2)


def _rtt_ms(total: float, cnt: float) -> float:
    return 0.0 if cnt == 0 else round(total / cnt, 2)


def _pack(name: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """一行原始计数 → 一行展示载荷（比率现算，与卡片同式）。"""
    get = lambda c: float(raw.get(c) or 0)                                # noqa: E731
    return {"target_ne": str(name or ""),
            "success_pct": _success_pct(get("syn_success"), get("syn_attempts")),
            "dl_retrans_pct": _ratio_pct(get("dl_retrans"), get("dl_segments")),
            "dl_rtt_ms": _rtt_ms(get("dl_rtt_sum"), get("dl_rtt_cnt")),
            "tcp_tb": round(get("tcp_tb"), 3)}


def _sum_raw(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    return {c: sum(float(r.get(c) or 0) for r in rows) for c in TCP_TARGET_COLUMNS}


def build_tcp_targets(days: int = 90, as_of: Optional[str] = None,
                      top: int = app_detail.OFFLOAD_TOP, path: Optional[Path] = None,
                      today: Optional[date] = None) -> Dict[str, Any]:
    """逐网元 TCP 质量下钻：最新一天 + 窗口累计；合计行 = 计数重聚合，与卡片恒等。"""
    days = max(1, min(int(days or 90), 400))
    top = max(5, min(int(top or app_detail.OFFLOAD_TOP), 200))
    body = app_detail._fresh_body("tcp_target", days, top)
    if not app_detail._preflight(body, TCP_TARGET_TABLE, days, as_of, path,
                                 "逐网元 TCP 明细为空：跑一次 olib_soc_kpi_daily_sync"
                                 "（或 --details-only --blocks tcp_ne 回填）即写入",
                                 today=today):
        return body
    begin, newest = body["window"]["begin"], body["as_of"]
    sum_cols = ", ".join("SUM(%s)" % c for c in TCP_TARGET_COLUMNS)
    try:
        with closing(kpi_store.connect(path, readonly=True)) as conn:
            cur = conn.execute("SELECT target_ne, %s FROM %s WHERE day=?"
                               % (", ".join(TCP_TARGET_COLUMNS), TCP_TARGET_TABLE),
                               (newest,))
            day_raw = [dict(zip(("target_ne",) + TCP_TARGET_COLUMNS, r)) for r in cur.fetchall()]
            cur = conn.execute("SELECT target_ne, %s FROM %s WHERE day>=? AND day<=? "
                               "GROUP BY target_ne" % (sum_cols, TCP_TARGET_TABLE),
                               (begin, newest))
            win_raw = [dict(zip(("target_ne",) + TCP_TARGET_COLUMNS, r)) for r in cur.fetchall()]
    except Exception as exc:                                             # noqa: BLE001
        return app_detail._error_body(body, exc)
    for key, raw_rows in (("day", day_raw), ("window_agg", win_raw)):
        packed = sorted((_pack(r["target_ne"], r) for r in raw_rows),
                        key=lambda r: r["tcp_tb"], reverse=True)
        totals = _pack("", _sum_raw(raw_rows))                            # 合计从原始计数重算
        totals["apps"] = len(raw_rows)
        others = None
        if len(packed) > top:
            others = _pack("", _sum_raw(raw_rows[top:]))                  # 「其它」同样是计数合计
            packed = packed[:top]
        body[key] = {"rows": packed, "others": others, "totals": totals}
    return body
