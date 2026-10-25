# -*- coding: utf-8 -*-
"""eflow_push_rule_history.py - 规则的「历史建 WO 率」
====================================================

从 `eflow_push_rules_checker.py` 拆出（AGENTS.md 三.2：单文件不超过 500 行）。

为什么需要它：规则 200（Regular电源故障推送TT到IPT）在最近 1000 条样本里有 340 张
「规则说该建 WO、实际没建」。若不提供对照，使用者会以为这是**这次规则变更造成的**；
而实测该条件的历史单里只有约 0.5% 建过 WO —— 这条规则长期就没生效过。页面据此在规则行上
标注历史建 WO 率，让人一眼分清「历来如此」与「这次改坏的」。

统计口径：按规则的 `alarmCode` + `siteSubType` 条件筛历史单，看其中有 `wo_no` 的比例。
条件里**没有正向 alarmCode** 时不给比例（显示 `—`），不做近似猜测。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_ALARM_CODE_COND_RE = re.compile(r"alarmCode\s+(?:=|in|not\s+in)\s+'([^']*)'", re.IGNORECASE)


def _s(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _load_rules() -> List[Dict[str, str]]:
    """规则表（与求值用的同一份、同一筛选条件）。延迟导入避免环。"""
    from backend.services.eflow_rules import eflow_push_rule_eval as EV
    from backend.services.eflow_rules.eflow_push_rules_checker import PUSH_RULES_XLSX
    return EV.load_push_rules(PUSH_RULES_XLSX)


def _norm_code(v: Any) -> str:
    s = _s(v)
    return s[:-2] if s.endswith(".0") else s


def _rule_history(per_rule: List[Dict[str, Any]], attrs: Dict[str, Dict[str, Any]],
                  window_days: int = 365) -> List[Dict[str, Any]]:
    """每条规则在**历史上**的实际生效情况（用于区分「本次新变化」与「历来如此」）。

    为什么要算这个：规则 200（Regular电源故障推送TT到IPT）在最近 1000 条样本里
    有 340 张单「规则说该建 WO、实际没建」。若不提供对照，使用者会以为这是
    **这次规则变更造成的**；而实测全库 17576 张该条件的单里只有 90 张建过 WO ——
    这条规则长期就没生效过。页面据此在规则行上标注「历史建 WO 率」，让人一眼分清：

      · 历史建 WO 率 ≈ 0、当前大量 mismatch  → 规则本身有问题，不是这次改坏的
      · 历史建 WO 率高、当前大量 mismatch    → 这次变更确实改变了派单行为

    统计口径：按规则的告警码条件筛历史单，看其中有 wo_no 的比例。
    **只在规则条件里含 alarmCode 时才算**（其它条件如站型无法在 SQL 里等价表达，
    强行近似会给出错误的比例 —— 宁可显示 `—`）。窗口按 created_time 取最近 N 天。
    """
    import pandas as pd
    from backend.database import get_raw_connection
    from backend.services.eflow_rules import eflow_rules_matcher as M

    out = []
    for pr in per_rule:
        item = dict(pr)
        item["history"] = None
        rid = _s(pr.get("rule_id"))
        codes = _alarm_codes_of_rule(rid)
        if codes:
            try:
                # 截止时间在 Python 侧算好再当参数传：`datetime('now', '-N day')` 只有
                # SQLite 有，PG 会直接报「函数 datetime 不存在」（2026-10-23 实测）。
                since = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(time.time() - int(window_days) * 86400))
                # alarm_code 在库里两种写法都有（'99933' 与 '99933.0'），两个都取
                vals = sorted({c for c in codes} | {c + ".0" for c in codes})
                ph = ",".join("?" * len(vals))
                # 站型条件（siteSubType）进 SQL 才能算出「**这条规则**的」历史生效率：
                # 只看告警码会把 ERA 站的单也算进 REGULAR 规则里（实测 99933 全量
                # 建 WO 率 13.7%，但其中绝大部分是 ERA 站，REGULAR 站几乎为 0）。
                sub = _rule_site_subtype(rid)
                sub_sql, sub_params = "", ()
                if sub:
                    # 列名用 PG 的**小写**形式 `site_id`：SQLite 下同样能命中
                    # （列名大小写不敏感），而 PG 下 `"Site ID"` 会报「字段不存在」
                    # —— 两库的列名风格不一致，只有小写写法两边都成立。
                    sub_sql = (
                        "AND CAST(site_id AS TEXT) IN ("
                        "  SELECT CAST(site_id AS TEXT) FROM eflow_site "
                        "   WHERE UPPER(TRIM(COALESCE(sitesubtype, ''))) = ?)"
                    )
                    sub_params = (sub,)
                sql = (
                    "SELECT COUNT(*), "
                    "       SUM(CASE WHEN wo_no IS NOT NULL AND wo_no != '' THEN 1 ELSE 0 END) "
                    "FROM eflow_tt "
                    f"WHERE alarm_code IN ({ph}) "
                    "  AND created_time >= ? "
                    f"  {sub_sql}"
                )
                with get_raw_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(sql, tuple(vals) + (since,) + sub_params)
                    n, wo = cur.fetchone()
                n = int(n or 0)
                wo = int(wo or 0)
                item["history"] = {
                    "window_days": window_days,
                    "alarm_codes": codes,
                    "total": n,
                    "with_wo": wo,
                    "wo_rate": round(wo / n, 4) if n else None,
                }
            except Exception as e:  # noqa: BLE001
                logger.debug("规则 %s 历史统计失败：%s", rid, e)
        out.append(item)
    return out


def _rule_site_subtype(rule_id: str) -> str:
    """规则条件里的 `siteSubType = 'REGULAR'/'ERA'`（用于历史统计的站型过滤）。

    条件里没有正向 siteSubType 等值时返回空串（不加过滤）。
    """
    for rec in _load_rules():
        if _s(rec.get("ID")) != rule_id:
            continue
        m = re.search(r"siteSubType\s*=\s*'([^']*)'", _s(rec.get("条件")), re.IGNORECASE)
        if m:
            return m.group(1).strip().upper()
    return ""


def _alarm_codes_of_rule(rule_id: str) -> List[str]:
    """从规则的条件里抽出 alarmCode 的取值列表（用于历史近似统计）。

    只处理**正向**条件（`=` / `in`）；`not in` 是排除语义，不能用来圈定样本，
    遇到含 `not in` 的条件直接返回空（该规则不给历史比例）。
    """
    for rec in _load_rules():
        if _s(rec.get("ID")) != rule_id:
            continue
        txt = _s(rec.get("条件"))
        if re.search(r"alarmCode\s+not\s+in", txt, re.IGNORECASE):
            return []
        codes: List[str] = []
        for m in _ALARM_CODE_COND_RE.finditer(txt):
            for v in m.group(1).split(","):
                v = _norm_code(v)
                if v:
                    codes.append(v)
        return sorted(set(codes))
    return []


def rule_history(per_rule, attrs=None, window_days=365):
    return _rule_history(per_rule, attrs or {}, window_days=window_days)
