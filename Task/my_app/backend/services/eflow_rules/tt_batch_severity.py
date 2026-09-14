# -*- coding: utf-8 -*-
"""TT 批量级别核查（Batch TT Severity Check）
=================================================
用户在 eFlow 知识库页面「TT 批量核查」上传一份 TT 单号清单（xlsx / csv / txt 或直接粘贴），
本模块逐单取出 eflow_tt 记录，套用 eFlow「TT Update Severity Rule」判定**当前级别是否正常**：

    正常（ok）      当前 ticket_severity 与规则建议级别一致
    需调整（adjust）规则命中且建议级别与当前不一致
    无法判定（unknown） 规则未命中，或工单当前级别为空 —— 需人工确认

匹配逻辑**完全复用** `eflow_rules_matcher`（与每天 04:20 的定时任务 eflow_tt_rules_check 同源），
只把「取最新 1000 条」换成「取用户指定的 TT 列表」，因此判定口径与 Email Reports →
eflow_tt_rules_check 页签的矫正表逐字一致。

设计要点
--------
* 只读：不写库、不落盘（导出 Excel 由前端按项目统一格式生成）。
* 双模连接：走 backend.database.get_raw_connection()，sqlite / pg 两种部署都能用
  （eflow_rules_matcher 内部直连 sqlite 文件，仅适用于定时任务本机 sqlite 场景）。
* 规则热加载：按 eflow_TT_rules.xlsx 的 mtime 缓存已解析规则，规则刷新后自动重载。
* 单次上限 MAX_BATCH 条，超出截断并在摘要中标注，避免把接口拖死。
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)

MAX_BATCH = 500

# 单号白名单：字母数字与 - _（与 /inspect-tt 的校验一致），且必须含数字、长度 >= 5。
# 后者用于挡掉文件表头/粘贴文本里的噪声词（如 "TT号"、"NOT"、"A"）。
_TT_RE = re.compile(r"^[A-Z0-9_\-]+$")
_TT_MIN_LEN = 5

# 分隔符：换行 / 空格 / 逗号 / 分号 / 制表符 / 竖线（中英文标点都收）
_SPLIT_RE = re.compile(r"[\s,;，；\t|]+")


def _looks_like_tt(s: str) -> bool:
    return len(s) >= _TT_MIN_LEN and bool(_TT_RE.match(s)) and any(ch.isdigit() for ch in s)

# 与 eflow_rules_matcher.get_eflow_tt_data 取的列保持一致（匹配所需 + 展示所需）
_TT_COLUMNS = (
    "wo_no", "tt_no", "ticket_no", "title",
    "alarm_code", "alarm_category", "alarm_subcategory", "alarm_type",
    "alarm_severity", "ticket_severity",
    "site_name", "ne_name", "domain", "status", "ticket_type",
    "project_name", "template_name",
    "vip_site", "site_type", "site_class", "down_site_count", "site_information",
    "root_cause", "sub_root_cause", "alarm_occur_time", "created_time", "last_modified_time",
)


# ------------------------------------------------------------------ #
# 入参清洗
# ------------------------------------------------------------------ #

def normalize_tt_list(items: Iterable[str], limit: int = MAX_BATCH) -> dict:
    """清洗用户输入：去空白 / 大写 / 去重 / 白名单过滤（含数字且长度 >= 5）/ 截断。

    返回 {"valid": [...], "invalid": [...], "duplicated": n, "truncated": bool}
    """
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    duplicated = 0
    for raw in items or []:
        if raw is None:
            continue
        # 每个元素再按分隔符拆一次：既能吃前端传的单号数组，也能吃
        # 一整行 / 一个单元格里塞了多个单号的脏输入。
        for part in _SPLIT_RE.split(str(raw).strip()):
            s = part.strip().upper()
            if not s:
                continue
            if not _looks_like_tt(s):
                if s not in invalid:
                    invalid.append(s)
                continue
            if s in seen:
                duplicated += 1
                continue
            seen.add(s)
            valid.append(s)
    truncated = len(valid) > limit
    return {"valid": valid[:limit], "invalid": invalid, "duplicated": duplicated, "truncated": truncated}


# ------------------------------------------------------------------ #
# 数据读取（双模：sqlite / pg）
# ------------------------------------------------------------------ #

def _fetch_tt_rows(tts: Sequence[str]) -> tuple[list[dict], dict[str, str]]:
    """按单号列表取 eflow_tt 行。返回 (rows, {请求单号: 实际命中列})。

    tt_no 优先、ticket_no 兜底（部分历史数据的真实单号落在 ticket_no）。
    """
    if not tts:
        return [], {}
    from backend.database import get_raw_connection

    ph = ",".join(["?"] * len(tts))
    cols_sql = ", ".join(_TT_COLUMNS)
    sql = (
        f"SELECT {cols_sql} FROM eflow_tt "
        f"WHERE UPPER(TRIM(COALESCE(tt_no, ''))) IN ({ph}) "
        f"   OR UPPER(TRIM(COALESCE(ticket_no, ''))) IN ({ph})"
    )
    params = tuple(tts) + tuple(tts)
    with get_raw_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]

    want = set(tts)
    hit_col: dict[str, str] = {}
    out: list[dict] = []
    for r in rows:
        key = str(r.get("tt_no") or "").strip().upper()
        col = "tt_no"
        if key not in want:
            key = str(r.get("ticket_no") or "").strip().upper()
            col = "ticket_no"
        if key not in want or key in hit_col:
            continue  # 非请求单号 / 同单号重复行只取第一条
        hit_col[key] = col
        out.append(r)
    return out, hit_col


# ------------------------------------------------------------------ #
# 规则加载（按文件 mtime 缓存）
# ------------------------------------------------------------------ #

_RULES_CACHE: dict = {"mtime": None, "ready": None, "count": 0}


def load_rules_ready(force: bool = False):
    """加载并解析 ACTIVE 规则；xlsx 未变更时复用缓存。返回 (rules_ready, rules_count)。"""
    from backend.services.eflow_rules import eflow_rules_matcher as M

    try:
        mtime = M.RULES_XLSX.stat().st_mtime
    except OSError as e:
        raise RuntimeError(f"规则文件不可用：{M.RULES_XLSX}（{e}）") from e

    if not force and _RULES_CACHE["mtime"] == mtime and _RULES_CACHE["ready"] is not None:
        return _RULES_CACHE["ready"], _RULES_CACHE["count"]

    # eflow_rules_matcher 是 CLI 与定时任务共用的脚本，内部用 print 输出进度；
    # 这里在 Web 请求路径上复用时把它的 stdout 静音，避免污染后端日志。
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rules_df = M.load_rules()
        ready = M.prepare_rules(rules_df)
    _RULES_CACHE.update({"mtime": mtime, "ready": ready, "count": int(len(ready))})
    return ready, int(len(ready))


# ------------------------------------------------------------------ #
# 结果整形
# ------------------------------------------------------------------ #

def _s(v) -> str:
    """NaN / None → 空串；整数值浮点去掉 .0；其余转字符串并去首尾空白。"""
    if v is None:
        return ""
    try:
        import pandas as pd
        if v is pd.NaT:
            return ""
        if isinstance(v, float):
            if pd.isna(v):
                return ""
            if v.is_integer():
                return str(int(v))
    except Exception:  # noqa: BLE001
        pass
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _row_from_match(req_tt: str, src: dict, matched: dict | None) -> dict:
    """把「数据库行 + 匹配结果」拼成前端/导出用的一行。"""
    cur_sev = _s(src.get("ticket_severity")).upper()
    new_sev = _s((matched or {}).get("New_Severity")).upper()
    rule_id = _s((matched or {}).get("Matched_Rule_ID"))
    if rule_id.lower().replace(" ", "") == "nomatch":
        rule_id = ""
    changed = _s((matched or {}).get("Severity_Changed")).upper() == "YES"

    if not cur_sev:
        level_status, level_text = "unknown", "当前级别为空"
    elif not rule_id:
        level_status, level_text = "unknown", "规则未命中"
    elif changed:
        level_status, level_text = "adjust", "需调整"
    else:
        level_status, level_text = "ok", "正常"

    alarm_code = _s(src.get("alarm_code"))
    if alarm_code.endswith(".0"):
        alarm_code = alarm_code[:-2]

    return {
        "tt_no": _s(src.get("tt_no")) or req_tt,
        "req_tt": req_tt,
        "found": True,
        "level_status": level_status,
        "level_text": level_text,
        "ticket_severity": cur_sev,
        "expected_severity": new_sev if rule_id else "",
        "matched_rule_id": rule_id,
        "matched_rule_name": _s((matched or {}).get("Matched_Rule_Name")),
        "matched_priority": _s((matched or {}).get("Matched_Priority")),
        "match_details": _s((matched or {}).get("Match_Details")),
        "site_name": _s(src.get("site_name")),
        "alarm_code": alarm_code,
        "alarm_severity": _s(src.get("alarm_severity")),
        "vip_site": _s(src.get("vip_site")),
        "site_type": _s(src.get("site_type")),
        "down_site_count": _s(src.get("down_site_count")),
        "domain": _s(src.get("domain")),
        "project_name": _s(src.get("project_name")),
        "ticket_type": _s(src.get("ticket_type")),
        "status": _s(src.get("status")),
        "title": _s(src.get("title")),
        "wo_no": _s(src.get("wo_no")),
        "ticket_no": _s(src.get("ticket_no")),
        "root_cause": _s(src.get("root_cause")),
        "sub_root_cause": _s(src.get("sub_root_cause")),
        "alarm_occur_time": _s(src.get("alarm_occur_time")),
        "created_time": _s(src.get("created_time")),
        "last_modified_time": _s(src.get("last_modified_time")),
    }


def _missing_row(req_tt: str) -> dict:
    row = {k: "" for k in (
        "tt_no", "req_tt", "level_status", "level_text", "ticket_severity", "expected_severity",
        "matched_rule_id", "matched_rule_name", "matched_priority", "match_details",
        "site_name", "alarm_code", "alarm_severity", "vip_site", "site_type", "down_site_count",
        "domain", "project_name", "ticket_type", "status", "title", "wo_no", "ticket_no",
        "root_cause", "sub_root_cause", "alarm_occur_time", "created_time", "last_modified_time",
    )}
    row.update({"tt_no": req_tt, "req_tt": req_tt, "found": False,
                "level_status": "unknown", "level_text": "本地未找到该工单"})
    return row


# ------------------------------------------------------------------ #
# 主入口
# ------------------------------------------------------------------ #

def check_batch(tts: Iterable[str], limit: int = MAX_BATCH) -> dict:
    """批量核查入口：清洗单号 → 取数 → 规则匹配 → 汇总。

    始终返回 200 语义的 dict（ok=False 时带 error），由路由层决定状态码。
    """
    t0 = time.perf_counter()
    norm = normalize_tt_list(tts, limit=limit)
    valid: list[str] = norm["valid"]
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")

    if not valid:
        return {
            "ok": False,
            "error": "没有可核查的 TT 单号（请检查文件内容或粘贴的列表）",
            "generated_at": generated_at,
            "input": {"total": 0, "valid": 0, "invalid": norm["invalid"],
                      "duplicated": norm["duplicated"], "truncated": False},
            "summary": {"found": 0, "not_found": 0, "level_ok": 0, "level_adjust": 0, "level_unknown": 0},
            "rows": [], "not_found": [],
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }

    # 规则（失败不阻断：全部落 unknown 并给出 error，前端仍能看到单号清单）
    rules_ready = None
    rules_count = 0
    rules_updated_at = ""
    rules_error = ""
    try:
        rules_ready, rules_count = load_rules_ready()
        from backend.services.eflow_rules import eflow_rules_matcher as M
        rules_updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(M.RULES_XLSX.stat().st_mtime))
    except Exception as e:  # noqa: BLE001
        rules_error = f"{type(e).__name__}: {e}"
        logger.warning("TT 批量核查：规则加载失败 %s", rules_error)

    rows_src, hit_col = _fetch_tt_rows(valid)
    by_req: dict[str, dict] = {}
    for r in rows_src:
        key = str(r.get("tt_no") or "").strip().upper()
        if key not in hit_col:
            key = str(r.get("ticket_no") or "").strip().upper()
        by_req[key] = r

    # 命中的行做规则匹配（一次向量化，不是逐单循环）
    matched_by_req: dict[str, dict] = {}
    if rules_ready is not None and by_req:
        try:
            import pandas as pd
            from backend.services.eflow_rules import eflow_rules_matcher as M
            df = pd.DataFrame([by_req[k] for k in by_req], columns=list(_TT_COLUMNS))
            res = M.match_all(df, rules_ready)
            for _, mr in res.iterrows():
                k = _s(mr.get("tt_no")).upper()
                if k not in by_req:
                    k = _s(mr.get("ticket_no")).upper()
                matched_by_req[k] = mr.to_dict()
        except Exception as e:  # noqa: BLE001
            rules_error = rules_error or f"规则匹配失败 {type(e).__name__}: {e}"
            logger.exception("TT 批量核查：规则匹配失败")

    rows: list[dict] = []
    not_found: list[str] = []
    for tt in valid:
        src = by_req.get(tt)
        if src is None:
            rows.append(_missing_row(tt))
            not_found.append(tt)
        else:
            rows.append(_row_from_match(tt, src, matched_by_req.get(tt)))

    summary = {
        "found": sum(1 for r in rows if r["found"]),
        "not_found": len(not_found),
        "level_ok": sum(1 for r in rows if r["level_status"] == "ok"),
        "level_adjust": sum(1 for r in rows if r["level_status"] == "adjust"),
        "level_unknown": sum(1 for r in rows if r["level_status"] == "unknown"),
    }

    return {
        "ok": True,
        "error": rules_error,
        "generated_at": generated_at,
        "rules": {"count": rules_count, "updated_at": rules_updated_at,
                  "file": "eflow_TT_rules.xlsx"},
        "input": {"total": len(valid) + len(norm["invalid"]), "valid": len(valid),
                  "invalid": norm["invalid"], "duplicated": norm["duplicated"],
                  "truncated": norm["truncated"], "limit": limit},
        "summary": summary,
        "rows": rows,
        "not_found": not_found,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
    }


def parse_tt_text(text: str) -> list[str]:
    """把粘贴/上传的纯文本列表拆成单号数组（逗号 / 分号 / 制表符 / 换行分隔）。"""
    if not text:
        return []
    return [p for p in re.split(r"[\s,;，；\t|]+", str(text)) if p]


__all__ = ["MAX_BATCH", "check_batch", "normalize_tt_list", "parse_tt_text", "load_rules_ready"]
