# -*- coding: utf-8 -*-
"""
告警归因服务（Data Agent 原型）

做什么
------
把「这个站点/网络为什么反复告警」从「人工翻三张表」变成「一段带数字依据的结论」。

数据来源（均为只读，且走 search_path，不写 schema 前缀）：
- `realtime_alarm`  当前活跃告警（实测 46 行 / 149 列）
- `history_alarm`   历史告警（实测 12,338 行 / 173 列）
- `eflow_tt`        工单（实测 36,226 行 / 161 列）

为什么独立成文件
----------------
`incident_ai_service.py` **恰好 500 行，已达项目单文件上限**
（AGENTS.md 第三节原则 2）。故本模块**只 import 复用**其 provider 分发能力，
不修改原文件一行 —— 避免把一个已达上限的文件继续撑大。

失败模式与应对
--------------
归因结论来自 LLM，**可能语义有误**。因此：
1. 先把 SQL 聚合出的**客观统计**算好（这部分是确定性的），再交给模型**解释**；
2. 返回体里同时带上原始统计（`evidence`），用户可自行核对；
3. AI 不可用时**降级为本地规则结论**，不返回错误页
   —— 沿用 `incident_overview_service.py:576-597` 既有的降级约定。

MOCK 说明：本模块不写任何数据；api_key 由前端传入，服务端不落盘、不写日志。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.database import get_raw_connection

logger = logging.getLogger(__name__)

# 单次归因取样的告警条数上限：归因看的是「模式」，不需要全量。
SAMPLE_LIMIT = 500


def _q(conn, sql: str, params=None) -> List[Dict[str, Any]]:
    """执行只读查询并返回 dict 列表。所有 SQL 均为本模块内置常量，不含用户输入。"""
    cur = conn.execute(sql, params) if params else conn.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _table_exists(conn, name: str) -> bool:
    try:
        conn.execute(f'SELECT 1 FROM "{name}" LIMIT 1')
        return True
    except Exception:  # noqa: BLE001
        return False


def collect_evidence(site: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
    """收集归因所需的客观统计（确定性计算，不含 LLM）。

    site: 站点名；为空则做全网概览归因。
    days: 回看天数（用于工单侧）。
    """
    evidence: Dict[str, Any] = {"site": site, "days": days, "sources": {}}
    days = max(1, min(int(days or 7), 90))

    with get_raw_connection() as conn:
        try:
            # ---- 1. 当前活跃告警：按站点/网元/严重度聚合 ----
            if _table_exists(conn, "realtime_alarm"):
                where, params = ("WHERE site_name = ?", [site]) if site else ("", None)
                by_site = _q(conn, f"""
                    SELECT site_name, COUNT(*) AS alarm_count
                    FROM realtime_alarm {where}
                    GROUP BY site_name ORDER BY alarm_count DESC LIMIT 15
                """, params)
                by_net = _q(conn, f"""
                    SELECT networktype, COUNT(*) AS alarm_count
                    FROM realtime_alarm {where}
                    GROUP BY networktype ORDER BY alarm_count DESC LIMIT 10
                """, params)
                evidence["sources"]["realtime_alarm"] = {
                    "by_site": by_site, "by_network": by_net,
                }

            # ---- 2. 历史告警：站点 Top + 告警类型 Top ----
            # 列名实测为 snake_case（app.history_alarm）；若环境切到 eflow schema
            # （Title Case 列名，见 DATA_AGENT_EVALUATION.md 2.2）会走 except 分支，
            # 降级为「该数据源不可用」而不是给出错误答案。
            if _table_exists(conn, "history_alarm"):
                where, params = ("WHERE site_name = ?", [site]) if site else ("", None)
                hist_site = _q(conn, f"""
                    SELECT site_name, COUNT(*) AS alarm_count
                    FROM history_alarm {where}
                    GROUP BY site_name ORDER BY alarm_count DESC LIMIT 15
                """, params)
                hist_type = _q(conn, f"""
                    SELECT type, COUNT(*) AS alarm_count
                    FROM history_alarm {where}
                    GROUP BY type ORDER BY alarm_count DESC LIMIT 15
                """, params)
                evidence["sources"]["history_alarm"] = {
                    "by_site": hist_site, "by_type": hist_type,
                }

            # ---- 3. 工单：该站点/全网的 TT 状态与严重度分布 ----
            if _table_exists(conn, "eflow_tt"):
                where = ""
                params = None
                if site:
                    where = "WHERE title LIKE ? OR project_name LIKE ?"
                    params = [f"%{site}%", f"%{site}%"]
                tt_status = _q(conn, f"""
                    SELECT status, COUNT(*) AS cnt FROM eflow_tt {where}
                    GROUP BY status ORDER BY cnt DESC LIMIT 10
                """, params)
                tt_sev = _q(conn, f"""
                    SELECT ticket_severity, COUNT(*) AS cnt FROM eflow_tt {where}
                    GROUP BY ticket_severity ORDER BY cnt DESC LIMIT 10
                """, params)
                evidence["sources"]["eflow_tt"] = {
                    "by_status": tt_status, "by_severity": tt_sev,
                }
        except Exception as e:  # noqa: BLE001
            logger.warning("[alarm-attribution] 取证失败: %s", e, exc_info=True)
            evidence["error"] = str(e)
        finally:
            conn.close()

    return evidence


def local_summary(evidence: Dict[str, Any]) -> str:
    """本地规则结论（无 LLM 时的降级路径，也是给 LLM 的事实底稿）。"""
    site = evidence.get("site")
    src = evidence.get("sources") or {}
    scope = f"站点「{site}」" if site else "全网"
    lines: List[str] = [f"{scope}告警归因（本地规则结论）："]

    rt = src.get("realtime_alarm") or {}
    if rt.get("by_site"):
        top = rt["by_site"][0]
        lines.append(
            f"- 当前活跃告警 Top1：{top.get('site_name')}"
            f"（{top.get('alarm_count')} 条）"
        )
    if rt.get("by_network"):
        dist = "、".join(
            f"{r.get('networktype') or '未标注'} {r.get('alarm_count')}"
            for r in rt["by_network"][:5]
        )
        lines.append(f"- 活跃告警按制式分布：{dist}")

    hist = src.get("history_alarm") or {}
    if hist.get("by_type"):
        dist = "、".join(
            f"{r.get('type') or '未标注'} {r.get('alarm_count')}"
            for r in hist["by_type"][:5]
        )
        lines.append(f"- 历史告警类型 Top5：{dist}")

    tt = src.get("eflow_tt") or {}
    if tt.get("by_status"):
        dist = "、".join(
            f"{r.get('status') or '未标注'} {r.get('cnt')}" for r in tt["by_status"][:5]
        )
        lines.append(f"- 工单状态分布：{dist}")

    if len(lines) == 1:
        lines.append("- 未取到可用的告警或工单数据，请检查数据源是否已同步。")
    lines.append("（以上为客观统计，未经过 AI 解读。）")
    return "\n".join(lines)


def build_prompt(evidence: Dict[str, Any], lang: str = "zh") -> str:
    """把客观统计拼成提示词。

    安全考量：**不把原始数据行直接塞给模型**，只给聚合后的统计 ——
    既控制 token，也降低「表内数据含指令」的提示注入面
    （该风险在 DATA_AGENT_EVALUATION.md 第六节列为后续项）。
    """
    is_en = (lang or "zh").lower() == "en"
    facts = local_summary(evidence)
    if is_en:
        return (
            "You are a telecom NOC analyst. Based on the aggregated alarm/ticket "
            "statistics below, explain the most likely root causes and give 3 "
            "concrete next actions. Be concise. Do not invent data beyond the "
            "statistics given.\n\n"
            f"STATISTICS:\n{facts}"
        )
    return (
        "你是电信网络运维（NOC）分析师。请基于下面的告警/工单聚合统计，"
        "分析最可能的根因，并给出 3 条可执行的下一步排查建议。"
        "要求简洁、直接，**不要编造统计中没有的数据**。\n\n"
        f"统计事实：\n{facts}"
    )


def attribute(site: Optional[str] = None, days: int = 7,
              provider: str = "local", api_key: str = "",
              model: str = "", base_url: str = "",
              lang: str = "zh") -> Dict[str, Any]:
    """归因主入口：先算客观统计，再让 AI 解读；AI 不可用则降级本地规则。"""
    evidence = collect_evidence(site=site, days=days)
    base = {
        "site": site,
        "days": days,
        "evidence": evidence,
        "local_summary": local_summary(evidence),
    }

    provider = (provider or "local").lower()
    if provider == "local" or not api_key:
        base["analysis"] = base["local_summary"]
        base["provider"] = "local"
        return base

    prompt = build_prompt(evidence, lang=lang)
    try:
        # 复用既有 provider 分发（不修改 incident_ai_service.py）
        from backend.services import incident_ai_service as ai_svc
        payload, status = ai_svc.dispatch(
            provider, {"api_key": api_key, "prompt": prompt, "model": model}
        )
        if status != 200 or not payload.get("analysis"):
            raise RuntimeError(payload.get("error") or f"status={status}")
        base["analysis"] = payload["analysis"]
        base["provider"] = provider
        if payload.get("reasoning"):
            base["reasoning"] = payload["reasoning"]
    except Exception as e:  # noqa: BLE001
        # 降级：沿用 incident_overview_service.py:594-597 的既有约定 ——
        # 返回本地规则结论 + note，而不是把错误抛给用户。
        logger.warning("[alarm-attribution] AI 调用失败，回退本地规则: %s", e)
        base["analysis"] = base["local_summary"]
        base["provider"] = "local"
        base["note"] = f"AI 调用失败，已回退本地规则：{e}"
    return base
