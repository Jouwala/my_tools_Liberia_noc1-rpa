"""TT 复盘报告 + NOC 操作人分析 数据服务。

新增于 2026-09-23，依据复盘报告 TT202609160106/TT202609210140 的核心发现实现：
- §3.4 WO 派单机制真相：依据 eflow_site.sitesubtype 与 ocrule_details.status 判定
  "为何没派 WO"（规则停用 / 规则真空 / NOC 人工判断）
- §4 NOC 根因误填：以 history_alarm.reason_type 为权威，比对 NOC 的 root_cause
- §5 NOC 时延分析：Accept→Submit/Confirm 时段、派单延迟、SLA 达成率
- §7 NOC 操作人画像：错位率、平均 Accept→Confirm 时长、夜班单占比

输入：tt_no（单条）或 时间窗 + 操作人筛选（批量）。
输出：纯 dict，无外部副作用；上游 routers/eflow_qa.py 的 _tt_postmortem_* 端点透传。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection

logger = logging.getLogger("tt_postmortem")

# 告警码 → 系统语义（来自 history_alarm 实测权威映射，2026-09 校准）
ALARM_CODE_SEMANTICS = {
    "99933": {"name": "SITE DOWN DUE TO POWER OFF", "reason_type": "TRM"},
    "9995":  {"name": "MW LINK DOWN",               "reason_type": "TRM"},
    "9920":  {"name": "Complete site down (CSD)",   "reason_type": "TRM"},
    "9910":  {"name": "Partial site down (PSD)",    "reason_type": "TRM"},
    "9970":  {"name": "4G SITE DOWN",               "reason_type": "TRM"},
    "9980":  {"name": "2G SITE DOWN",               "reason_type": "TRM"},
    "9990":  {"name": "3G SITE DOWN",               "reason_type": "TRM"},
    "9981":  {"name": "2G CELL DOWN",               "reason_type": "OTHER"},
    "9991":  {"name": "3G CELL DOWN",               "reason_type": "OTHER"},
    "9971":  {"name": "4G CELL DOWN",               "reason_type": "OTHER"},
    "4758":  {"name": "Fiber Break",                "reason_type": None},
}
# 故障域族（用于站点级降级匹配）
POWER_HINTS = ("POWER", "GENSET", "BATTERY", "FUEL", "ENERGY", "GRID", "MAINS", "COMMERCIAL")
TRM_HINTS = ("MW LINK", "MICROWAVE", "FIBER", "LINK DOWN", "TRANSMISSION", "MW ")


def _norm_alarm_id(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _infer_fault_domain(codename: str, reason_type: str, alarmcode: str) -> Tuple[str, str]:
    cn = (codename or "").upper()
    if any(h in cn for h in POWER_HINTS):
        return "POWER", f"codename='{codename}' 含供电语义"
    if any(h in cn for h in TRM_HINTS):
        return "TRM", f"codename='{codename}' 含传输语义"
    if reason_type:
        return reason_type, f"reason_type='{reason_type}'"
    sem = ALARM_CODE_SEMANTICS.get(_norm_alarm_id(alarmcode))
    if sem and sem.get("reason_type"):
        return sem["reason_type"], f"alarmcode={alarmcode} 静态语义表"
    if sem:
        return "UNKNOWN", f"alarmcode={alarmcode} 语义未知（{sem.get('name')}）"
    return "UNKNOWN", "无可用告警链路信息"


def _alarm_family(alarmcode: str, codename: str, reason_type: str) -> str:
    code = _norm_alarm_id(alarmcode)
    cn = (codename or "").upper()
    if any(h in cn for h in POWER_HINTS):
        return "POWER"
    if code == "9995" or "MW LINK" in cn or "MICROWAVE" in cn:
        return "MW_LINK"
    if code in ("9970", "9980", "9990", "9910", "9920", "99933"):
        return "SITE_DOWN"
    if code in ("9971", "9981", "9991") or "CELL DOWN" in cn:
        return "CELL_DOWN"
    if code == "4758" or "FIBER" in cn:
        return "FIBER"
    if reason_type == "TRM":
        return "SITE_DOWN"
    return "UNKNOWN"


def _fetch_alarm_chain(conn, tt_no: str, alarm_id, site_id,
                       alarm_code=None, tt_reason_type=None) -> Tuple[List[Any], str]:
    """三级策略取告警链路。

    返回 (rows, linkage)：
    - exact: tt_id 精确
    - site_fallback: 同站点+同码
    - site_reason_fallback: 同站点+同 reason_type（断站类码共享 TRM）
    - site_fallback_unrelated: 同站点但不同域
    - none: 无可用告警
    """
    cols = "alarmcode, codename, reason_type, alarm_source, restypename, alarmkey, site_name"

    try:
        rows = conn.execute(
            f"SELECT {cols} FROM history_alarm WHERE tt_id = ? LIMIT 20", (tt_no,)
        ).fetchall()
        if rows:
            return rows, "exact"
    except Exception:
        logger.warning("[tt_postmortem] tt_id 关联失败", exc_info=True)

    nid = _norm_alarm_id(alarm_id)
    if nid:
        try:
            rows = conn.execute(
                f"SELECT {cols} FROM history_alarm WHERE CAST(id AS TEXT) = ? LIMIT 20", (nid,)
            ).fetchall()
            if rows:
                return rows, "exact"
        except Exception:
            logger.warning("[tt_postmortem] alarm_id 关联失败", exc_info=True)

    if site_id is not None and str(site_id).strip() not in ("", "None"):
        try:
            rows = conn.execute(
                f"""SELECT {cols} FROM history_alarm WHERE CAST(site_id AS TEXT) = ?
                    ORDER BY alarmraisedtime DESC LIMIT 50""",
                (str(site_id),),
            ).fetchall()
            if rows:
                tt_code = _norm_alarm_id(alarm_code)
                if tt_code:
                    matched = [r for r in rows if _norm_alarm_id(dict(r).get("alarmcode")) == tt_code]
                    if matched:
                        return matched, "site_fallback"
                tt_reason = (tt_reason_type or "").strip().upper()
                if not tt_reason and tt_code:
                    sem = ALARM_CODE_SEMANTICS.get(tt_code)
                    tt_reason = ((sem or {}).get("reason_type") or "").strip().upper()
                if tt_reason:
                    same_reason = [r for r in rows
                                   if (dict(r).get("reason_type") or "").strip().upper() == tt_reason]
                    if same_reason:
                        return same_reason, "site_reason_fallback"
                return [], "site_fallback_unrelated"
        except Exception:
            logger.warning("[tt_postmortem] site_id 降级关联失败", exc_info=True)

    return [], "none"


# ========================= 规则地图 =========================

def _load_push_rules(conn) -> Dict[str, Any]:
    """读取 ocrule_details 中 ttPushOrderRule / ttDispatchRule 的 ACTIVE 规则，
    并标注与断站类告警码相关的覆盖情况。

    列名兼容：原表（sqlite 同步的副本）列名小写无空格；PG 模式下列名为带空格的"Rule Name"等。
    使用下方的 _pick_columns 自动适配可用列。
    """
    cols = _detect_ocrule_columns(conn)
    if not cols:
        return {"rules": [], "down_alarm_codes_active": [], "down_alarm_codes_stopped": []}

    available = cols["_columns"]
    select_fields = []
    name_map: Dict[str, str] = {}  # canonical -> 实际列名（用于回查）
    for canonical, candidates in [
        ("rule_name", ("ruleName", "Rule Name", "rule_name")),
        ("rule_type", ("ruleType", "Rule Type", "rule_type")),
        ("trigger_step", ("triggerStep", "Trigger Step", "trigger_step")),
        ("status", ("status", "Status")),
        ("priority", ("rulePriority", "Rule Priority", "rule_priority")),
        ("handler_name", ("targetHandlerName", "Target Handler Name", "target_handler_name")),
        ("handler_id", ("targetHandlerId", "Target Handler Id", "target_handler_id")),
        ("update_time", ("updateTime", "Update Time", "update_time")),
        ("description", ("description", "Description")),
    ]:
        c = next((x for x in candidates if x in available), None)
        if c:
            select_fields.append(f"{_qcol(c)} AS {canonical}")
            name_map[canonical] = c

    if not select_fields or "rule_type" not in name_map:
        return {"rules": [], "down_alarm_codes_active": [], "down_alarm_codes_stopped": []}

    rt_quoted = _qcol(name_map["rule_type"])
    # ORDER BY 必须引用**原始列名**（PG 下别名不带引号会被折叠成小写而找不到）；
    # 且只对确实存在的列排序，避免列名差异导致整条查询失败。
    order_cols = [name_map[c] for c in ("status", "rule_type", "priority") if c in name_map]
    order_sql = (" ORDER BY " + ", ".join(_qcol(c) for c in order_cols)) if order_cols else ""
    sql = (f"SELECT {', '.join(select_fields)} FROM ocrule_details "
           f"WHERE {rt_quoted} IN ('ttPushOrderRule','ttDispatchRule'){order_sql}")
    try:
        rows = conn.execute(sql).fetchall()
    except Exception:
        logger.warning("[tt_postmortem] ocrule_details 查询失败: %s", sql, exc_info=True)
        return {"rules": [], "down_alarm_codes_active": [], "down_alarm_codes_stopped": []}

    rules = []
    active_codes: set = set()
    stopped_codes: set = set()
    down_codes = ("9970", "9980", "9990", "9910", "9920", "9995", "99933")
    # 只把"明确在自动推单 ttPushOrderRule 中"且规则名/描述表明覆盖断站类告警的规则
    # 计入覆盖集合；"无线断站级别重定义-Px-ruleN"是 ttLevelRule，不是推单规则，不计入。
    # 此外告警码仅当规则名/描述中显式提到才计入；规则名"ERA断站推单到ZTE WO"已含
    # 完整语义（断站码集），自动覆盖所有 down_codes。
    for r in rows:
        d = dict(r)
        text = (d.get("rule_name") or "") + " " + (d.get("description") or "")
        rule_type = (d.get("rule_type") or "").strip()
        status = d.get("status")
        is_push = rule_type == "ttPushOrderRule"
        covers = is_push and ("断站" in text or "微波" in text or "能源" in text or any(c in text for c in down_codes))
        if not covers:
            continue
        target_set = active_codes if status == "ACTIVE" else stopped_codes if status == "STOP" else None
        if target_set is None:
            continue
        # "断站"类规则覆盖所有 down_codes（典型如 #203、#201）；其他规则仅当显式列出码时计入。
        if "断站" in text:
            target_set.update(down_codes)
        else:
            for c in down_codes:
                if c in text:
                    target_set.add(c)
        rules.append(d)

    return {
        "rules": rules,
        "down_alarm_codes_active": sorted(active_codes),
        "down_alarm_codes_stopped": sorted(stopped_codes),
    }


def _load_rule_catalog(conn) -> List[Dict[str, Any]]:
    """读取**全部** ttPushOrderRule / ttDispatchRule 规则（不过滤关键词）。

    与 `_load_push_rules` 的区别：后者只为「断站类码覆盖」统计服务，
    会按规则名/描述里的关键词（断站/微波/能源/告警码）过滤，
    因此 `小区故障派ZTE WO`、`Regular电源故障推送TT到IPT` 这类**不含"断站"字样
    但同样是 ACTIVE 推单规则**的条目会被丢掉——它们恰恰是判定
    「为什么这单没自动派 WO」时必须摆出来的证据。

    返回每条规则含：rule_name / rule_type / trigger_step / status /
    priority / handler / description / update_time。
    """
    cols = _detect_ocrule_columns(conn)
    if not cols:
        return []
    available = cols["_columns"]
    select_fields: List[str] = []
    name_map: Dict[str, str] = {}
    for canonical, candidates in [
        ("rule_name", ("ruleName", "Rule Name", "rule_name")),
        ("rule_type", ("ruleType", "Rule Type", "rule_type")),
        ("trigger_step", ("triggerStep", "Trigger Step", "trigger_step")),
        ("status", ("status", "Status")),
        ("priority", ("rulePriority", "Rule Priority", "rule_priority")),
        ("handler_name", ("targetHandlerName", "Target Handler Name", "target_handler_name")),
        ("handler_id", ("targetHandlerId", "Target Handler ID", "target_handler_id")),
        ("description", ("description", "Description")),
        ("update_time", ("updateTime", "Update Time", "update_time")),
    ]:
        c = next((x for x in candidates if x in available), None)
        if c:
            select_fields.append(f"{_qcol(c)} AS {canonical}")
            name_map[canonical] = c
    if not select_fields or "rule_type" not in name_map:
        return []

    rt = _qcol(name_map["rule_type"])
    # 同时纳入群组指派类规则：ttDispatchRule 只决定"走 BO 还是 FO 通道"，
    # 真正决定"落到哪个群组池、候选人是哪些人"的是 ttGroupConfigRule /
    # ttGroupDefaultRule。要回答"指派给谁"必须把它们一起读出来。
    sql = (f"SELECT {', '.join(select_fields)} FROM ocrule_details "
           f"WHERE {rt} IN ('ttPushOrderRule','ttDispatchRule',"
           f"'ttGroupConfigRule','ttGroupDefaultRule')")
    try:
        rows = conn.execute(sql).fetchall()
    except Exception:
        logger.warning("[tt_postmortem] 规则目录查询失败: %s", sql, exc_info=True)
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["rule_name"] = (d.get("rule_name") or "").strip()
        d["rule_type"] = (d.get("rule_type") or "").strip()
        d["trigger_step"] = (d.get("trigger_step") or "").strip()
        d["status"] = (d.get("status") or "").strip()
        out.append(d)
    return out


# 规则关键词 → 本单特征 的判定表。
# 用途：把「规则名/描述里写了什么」翻译成「它想命中什么样的单」，
# 再与当前 TT 的站点/告警特征比对，得出「这条规则适不适用于本单」。
# 关键词是**推断依据**而非 eFlow 内部真实条件——报告里必须把规则原文一并展示，
# 让人能自己核对（我们看不到 eFlow 的规则表达式，只能从命名与描述反推）。
_RULE_SIGNATURE_KEYS: Dict[str, Tuple[str, ...]] = {
    "REGULAR": ("regular", "normal", "cool", "常规"),
    "ERA": ("era",),
    "SITE_DOWN": ("断站", "site down", "site_down", "sitedown"),
    "CELL": ("小区", "cell"),
    "POWER": ("电源", "power", "gense"),
    "MICROWAVE": ("微波", "microwave", "mw link"),
    "ENERGY": ("能源", "energy"),
    "IP_DWDM": ("ip_dwdm", "dwdm", "ip dwdm"),
    "VMAX": ("vmax",),
    "IPT": ("ipt",),
    "WO_TARGET": ("wo", "工单"),
}


def _has_word(text: str, word: str) -> bool:
    """英文关键词按**整词**匹配（前后不能紧邻字母）。

    ⚠ 必须整词匹配的实证原因：站点名 "Qcell LMTI (Marshall)" 里含 "cell" 子串，
    用 `"cell" in text` 会把「Partial site down (PSD)」这类**站点级**断站
    误判成**小区级**故障，进而错误套用「小区故障派ZTE WO」规则，
    在 200 单回归里造出 7 个"应建 WO 却没建"的假异常。
    整词匹配后 `qcell` 因 "cell" 前紧邻字母 `q` 而不命中。
    """
    return re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None


def _ticket_signature(t: Dict[str, Any], site_subtype: Optional[str]) -> Dict[str, bool]:
    """把当前 TT 的特征归一化成一组布尔标记，供规则关键词比对。

    依据：站点子类型（REGULAR/ERA）+ 告警名/描述/专业 + 根因类型。
    例：siteSubType=REGULAR、告警名「2G SITE DOWN」→ {REGULAR: True, SITE_DOWN: True}

    ⚠ 刻意**不把 `title` 纳入比对文本**：title 形如
    ` 4583.[Qcell LMTI (Marshall)]Partial site down (PSD)`，里面嵌了**站点名**。
    站点名是专有名词，可能恰好包含特征词（"Qcell" 含 "cell"），
    把它纳入会引入无法预期的假命中。告警语义只从 alarm_description /
    codename / alarm_name 取。
    """
    sub = (site_subtype or "").strip().upper()
    alarm_text = " ".join(str(t.get(k) or "") for k in
                          ("alarm_description", "codename", "alarm_name")).lower()
    domain = str(t.get("domain") or "").strip().upper()
    reason = str(t.get("alarm_reason_type") or t.get("reason_type") or "").strip().upper()

    sig: Dict[str, bool] = {}
    sig["REGULAR"] = sub in ("REGULAR", "NORMAL", "COOL") or _has_word(alarm_text, "regular")
    sig["ERA"] = sub == "ERA" or _has_word(alarm_text, "era")
    sig["SITE_DOWN"] = any(k in alarm_text for k in ("site down", "site_down", "断站"))
    sig["CELL"] = _has_word(alarm_text, "cell") or "小区" in alarm_text
    sig["POWER"] = (_has_word(alarm_text, "power") or _has_word(alarm_text, "gense")
                    or "power off" in alarm_text or reason.startswith("POWER"))
    sig["MICROWAVE"] = (_has_word(alarm_text, "microwave") or "mw link" in alarm_text
                        or "mw_link" in alarm_text)
    sig["ENERGY"] = _has_word(alarm_text, "energy")
    sig["IP_DWDM"] = _has_word(alarm_text, "dwdm")
    sig["VMAX"] = _has_word(alarm_text, "vmax")
    # IPT / WO_TARGET 是**目标系统**而非本单特征，比对时视为"总是可满足"
    sig["IPT"] = True
    sig["WO_TARGET"] = True
    if domain == "MW":
        sig["MICROWAVE"] = True
    return sig


def _rule_wants_keys(rule: Dict[str, Any]) -> List[str]:
    """从规则名+描述里抽出它声明要命中的特征键。

    英文关键词同样走 `_has_word` 整词匹配：否则规则描述里的
    "operation" 会因含 "era" 子串被误判为「针对 ERA 站点」。
    """
    text = (str(rule.get("rule_name") or "") + " " + str(rule.get("description") or "")).lower()
    wants: List[str] = []
    for key, tokens in _RULE_SIGNATURE_KEYS.items():
        if key in ("IPT", "WO_TARGET"):
            continue  # 目标系统不是筛选条件
        if any(_has_word(text, tok) if tok.isascii() else (tok in text) for tok in tokens):
            wants.append(key)
    return wants


def _rule_target(rule: Dict[str, Any]) -> str:
    """判定规则的**派发目标**：WO（建工单）/ IPT / BO / MANUAL（人工）/ UNKNOWN。

    ⚠ 这个区分是必需的，否则会造出大量假阳性：
    实测 200 单里有 81 单命中 `Regular电源故障推送TT到IPT`（ACTIVE），
    但该规则的**目标是 IPT 而不是建 WO** —— 若把它当成"应建 WO 却未建"，
    就会把正常的规则行为误报成 89 单规则失效（真实只有 8 单）。
    同理 `...手动到FO` 的设计意图本就是人工，也不该算作"应建 WO"。
    """
    name = (rule.get("rule_name") or "").upper()
    if "手动" in (rule.get("rule_name") or ""):
        return "MANUAL"
    if "IPT" in name:
        return "IPT"
    if "WO" in name or "工单" in (rule.get("rule_name") or ""):
        return "WO"
    if "BO" in name:
        return "BO"
    return "UNKNOWN"


def _resolve_assignment(t: Dict[str, Any], dispatch_path: Dict[str, Any],
                        create_info: Dict[str, Any],
                        catalog: List[Dict[str, Any]]) -> Dict[str, Any]:
    """回答"这单指派给谁了"——分三层，缺一层都不能下结论。

    eFlow 的指派不是一条规则说了算：
      ① 通道规则 ttDispatchRule(autoDispatch)：只决定走 BO 还是 FO 通道，
         `targetHandlerName` 实测**全为 None** —— 它根本不管派给谁；
      ② 建单默认群组 ttGroupDefaultRule(GroupDefault_Create)：决定单子落进哪个群组池；
      ③ 环节群组配置 ttGroupConfigRule(GroupConfig_*)：决定各环节的候选人范围。
    而**真正落到某个人**要看 create_detail 的 `Assign To` / `Assignee Group`，
    以及 eflow_tt.current_handler。

    ⚠ 实测 TT202609220139：`Assign To` 与 `Assignee Group` **都是空的**，
    `current_handler = G:ZTE_NOC_FO`（G: 前缀表示**群组**而非个人）。
    也就是说建单后单子只是躺在一个 20 人的群组池里、没有具体负责人 ——
    这正是它 15.81 小时没人动的原因。报告必须把"未指派到人"说清楚，
    而不是含糊地写一句"系统自动派单"。
    """
    def _rules(*, rtype: str, step: str) -> List[Dict[str, Any]]:
        return [r for r in catalog
                if r.get("rule_type") == rtype and r.get("trigger_step") == step]

    # ① 通道
    channel_rules = [r for r in _rules(rtype="ttDispatchRule", step="autoDispatch")
                     if (r.get("status") or "").upper() == "ACTIVE"]
    channel = dispatch_path.get("category")
    channel_targets = [
        {"rule_name": r.get("rule_name"), "priority": r.get("priority"),
         "handler_name": r.get("handler_name"), "handler_id": r.get("handler_id")}
        for r in channel_rules
    ]
    # ②③ 群组池（按环节）
    pools: List[Dict[str, Any]] = []
    for rtype, step, stage in (
        ("ttGroupDefaultRule", "GroupDefault_Create", "建单默认群组"),
        ("ttGroupConfigRule", "GroupConfig_FOAccept", "FO 接单环节"),
        ("ttGroupConfigRule", "GroupConfig_FOProcess", "FO 处理环节"),
        ("ttGroupConfigRule", "GroupConfig_Confirm", "确认关单环节"),
        ("ttGroupDefaultRule", "GroupDefault_FOProcess", "FO 处理默认审批人"),
    ):
        for r in _rules(rtype=rtype, step=step):
            if (r.get("status") or "").upper() != "ACTIVE":
                continue
            pools.append({
                "stage": stage,
                "rule_name": r.get("rule_name"),
                "priority": r.get("priority"),
                "handler_name": r.get("handler_name"),
                "handler_id": r.get("handler_id"),
                "description": r.get("description"),
            })

    assign_to = create_info.get("assign_to")
    assignee_group = create_info.get("assignee_group")
    current_handler = t.get("current_handler")
    # `G:` 前缀 = 群组；无前缀且非空 = 具体人
    ch_is_group = bool(current_handler and str(current_handler).startswith("G:"))
    ch_person = (str(current_handler)[2:] if ch_is_group
                 else (current_handler or None))

    if assign_to:
        who = f"建单即指派到人：{assign_to}"
    elif assignee_group:
        who = f"建单即指派到群组：{assignee_group}（未指定个人）"
    elif current_handler and not ch_is_group:
        who = f"建单未指定指派对象，当前处理人：{current_handler}"
    elif ch_is_group:
        who = (f"建单**未指派到任何人**，仅落入群组池 `{current_handler}`"
               f"（G: 前缀表示群组）；当前处理人 `{ch_person}` 是群组而非个人")
    else:
        who = "建单未指派到任何人，且当前处理人为空"

    return {
        "channel": channel,
        "channel_rules": channel_targets,
        "channel_note": ("ttDispatchRule 只决定走 BO/FO 通道，实测其 targetHandlerName 全为空，"
                         "不承担「派给谁」的职责"),
        "create_assign_to": assign_to,
        "create_assignee_group": assignee_group,
        "create_operator_group": create_info.get("operator_group"),
        "next_status": create_info.get("next_status"),
        "current_handler": current_handler,
        "current_handler_is_group": ch_is_group,
        "current_handler_person": ch_person,
        "group_pools": pools,
        "conclusion": who,
        "unassigned": not (assign_to or assignee_group),
    }


def _analyze_dispatch_reason(t: Dict[str, Any], site_subtype: Optional[str],
                             wo_record: Optional[Dict[str, Any]],
                             catalog: List[Dict[str, Any]]) -> Dict[str, Any]:
    """**核心分析**：依据当前 TT Push Order Rule 解释「这单为什么走了人工派单」。

    判定链路（eFlow 三段式）：
      1. `ttDispatchRule`（autoDispatch）决定 TT 落到 BO 还是 FO 通道；
      2. `ttPushOrderRule`（triggerStep=FOAccept）决定 FO 接单时**是否自动建 WO**；
      3. 若第 2 步没有任何 ACTIVE 规则命中 → 不建 WO → FO 只能人工接单并手工判断，
         现场是否出人无法由系统保证（本单即为此类）。

    输出把 FOAccept 阶段**所有**推单规则逐条摆开，标注每条对本单是否适用、
    是否因 STOP 而失效，最后给出结论与兜底规则。
    """
    tt_no = t.get("tt_no")
    sig = _ticket_signature(t, site_subtype)
    has_wo = bool(t.get("wo_no") and wo_record)
    # eflow_tt 没有 alarm_name 列，告警名优先取 alarm_description，
    # 再退回告警码语义表（ALARM_CODE_SEMANTICS），最后才用 title。
    _acode = _norm_alarm_id(t.get("alarm_code"))
    alarm_name = (str(t.get("alarm_description") or "").strip()
                  or (ALARM_CODE_SEMANTICS.get(_acode) or {}).get("name")
                  or str(t.get("title") or "").strip())

    # 目标阶段：无 WO 时看 FOAccept（决定自动建 WO 的那一步）
    target_step = "FOAccept"
    push_rules = [r for r in catalog if r.get("rule_type") == "ttPushOrderRule"]
    at_step = [r for r in push_rules if (r.get("trigger_step") or "") == target_step]
    # 兜底派单规则（ttDispatchRule）
    dispatch_rules = [r for r in catalog if r.get("rule_type") == "ttDispatchRule"]

    evaluated: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    for r in at_step:
        wants = _rule_wants_keys(r)
        hits = [k for k in wants if sig.get(k)]
        misses = [k for k in wants if not sig.get(k)]
        applicable = bool(wants) and not misses
        if applicable:
            candidates.append(r)
            if r.get("status") == "ACTIVE":
                verdict = "matched"
                why = f"规则要求 {'/'.join(wants)}，本单均满足；状态 ACTIVE → 应自动建 WO"
            else:
                verdict = "blocked_by_status"
                why = (f"规则要求 {'/'.join(wants)}，本单**本应命中**，"
                       f"但规则状态为 {r.get('status')} → 已停用，不再生效")
                blocked.append(r)
        elif wants:
            verdict = "not_applicable"
            why = f"规则针对 {'/'.join(wants)}，本单缺少 {'/'.join(misses)} → 不适用"
        else:
            verdict = "unknown_scope"
            why = "规则名/描述未含可识别特征词，无法从命名反推适用范围（需人工确认）"
        evaluated.append({
            "rule_name": r.get("rule_name"),
            "status": r.get("status"),
            "priority": r.get("priority"),
            "description": r.get("description"),
            "update_time": r.get("update_time"),
            "wants_keys": wants,
            "miss_keys": misses,
            "target": _rule_target(r),
            "verdict": verdict,
            "why": why,
        })

    active_candidates = [r for r in candidates if r.get("status") == "ACTIVE"]

    # 「设计即人工」判定：规则名里带"手动"的规则，其**设计意图本身就是人工处理**
    # （典型：`Regular断站故障手动到FO`，描述 Normal+COOL站点）。
    # 这类规则即使 ACTIVE 也不会自动建 WO —— 因此"没有 WO"对这类单是**设计如此**，
    # 不是规则故障。这个区分对复盘很关键：前者要改规则，后者要改流程预期。
    manual_rules = [r for r in candidates if "手动" in (r.get("rule_name") or "")]
    manual_by_design = bool(manual_rules)

    # 命中的 ACTIVE 规则里，**真正会建 WO** 的那些（其余是路由到 IPT/BO 或目标未知）
    wo_active = [r for r in active_candidates if _rule_target(r) == "WO"]
    other_active = [r for r in active_candidates if _rule_target(r) != "WO"]

    # 本阶段**有能力自动建 WO** 的 ACTIVE 规则（不论是否适用本单）
    wo_capable = [r for r in at_step
                  if r.get("status") == "ACTIVE" and _rule_target(r) == "WO"]
    wo_capable_eval = [{
        "rule_name": r.get("rule_name"),
        "wants_keys": _rule_wants_keys(r),
        "applies": not [k for k in _rule_wants_keys(r) if not sig.get(k)],
    } for r in wo_capable]

    if has_wo:
        conclusion = (f"本单已产生 WO（{(wo_record or {}).get('wo_no')}），"
                      f"说明 FO Accept 阶段有推单规则生效，无需人工判断是否派现场。")
        overall = "auto_dispatched"
    elif wo_active:
        names = "、".join(x.get("rule_name") or "" for x in wo_active)
        conclusion = (f"FOAccept 阶段存在 ACTIVE 且适用于本单的**建 WO** 规则（{names}），"
                      f"按规则应自动建 WO，但库中无 WO → **规则未生效，属异常**，需查规则引擎。")
        overall = "rule_should_have_fired"
    elif len({_rule_target(r) for r in candidates}) > 1:
        # 多条**目标不同**的规则同时适用（如 REGULAR 站"断电导致断站"同时满足
        # 「Regular断站故障手动到FO」与「Regular电源故障推送TT到IPT」）。
        # 此时不该替 eFlow 猜哪条生效 —— 并列展示并请人工按优先级/实测确认。
        detail = "；".join(
            f"「{r.get('rule_name')}」（优先级 {r.get('priority')}，"
            f"{r.get('status')}，目标 {_rule_target(r)}，描述 {r.get('description') or '无'}）"
            for r in candidates)
        _targets = {_rule_target(r) for r in candidates}
        if "WO" not in _targets:
            # 关键：候选规则里**没有一条会建 WO**（一条人工、一条推 IPT 之类）。
            # 那么无论 eFlow 最终选哪条，结果都是"不建 WO"——结论是**确定的**，
            # 不必因为"分不清哪条生效"就放弃回答。
            conclusion = (
                f"**本单无 WO 的结果是确定的**：同时适用于本单的规则有 {detail}。"
                f"虽然无法从规则表判定 eFlow 最终按哪条执行（看不到引擎优先级表达式），"
                f"但这几条的目标分别是 "
                + "、".join(sorted(_targets))
                + f"——**没有一条会建 WO**，因此「无 WO」与该组合的规则设计一致，"
                f"不是规则失效。真正需要关注的是：这类单**没有自动派现场的机制**。")
            overall = "no_wo_by_design_multi"
        else:
            conclusion = (
                f"**本单有多条目标不同的规则同时适用，无法从规则表单独判定**：{detail}。"
                f"实际走哪条取决于 eFlow 规则引擎的优先级/匹配顺序（我们只能看到规则表，"
                f"看不到引擎表达式）。因此本单「是否应建 WO」需人工按上表核对；"
                f"库中事实是：**无 WO**。")
            overall = "ambiguous"
    elif manual_by_design:
        m = manual_rules[0]
        conclusion = (
            f"**本单走人工派单属设计如此**：适用于本单（siteSubtype="
            f"{site_subtype or '-'} + 断站）的推单规则是「{m.get('rule_name')}」"
            f"（描述：{m.get('description') or '无'}），规则名明确写的是"
            f"**「手动到FO」**——即该组合的设计意图就是人工接单处理，不自动建 WO。"
            f"本阶段仅有 {'、'.join(x['rule_name'] for x in wo_capable_eval) or '无'} "
            f"具备自动建 WO 能力，但分别要求 "
            + "、".join("/".join(x["wants_keys"]) for x in wo_capable_eval)
            + f"，均不适用于本单。"
            f"⚠ 另需注意：该「手动到FO」规则当前状态为 **{m.get('status')}**，"
            f"连这条显式人工路由也已停用，现由兜底规则「TT单直接派FO accept」承接，"
            f"行为等价但失去显式声明。")
        overall = "manual_by_design"
    elif other_active:
        # 命中了 ACTIVE 规则，但它的目标是别的系统（如 IPT）——不建 WO 属**预期行为**
        names = "、".join(
            f"{x.get('rule_name')}（目标 {_rule_target(x)}）" for x in other_active)
        conclusion = (
            f"**本单无 WO 属规则预期行为**：FOAccept 阶段命中 ACTIVE 规则 {names}，"
            f"但该规则的目标**不是建 WO**（而是把 TT 推送到其它系统/通道），"
            f"因此不产生 WO 是规则设计的结果，不是规则失效。"
            f"本阶段具备建 WO 能力的 ACTIVE 规则为 "
            f"{'、'.join(x['rule_name'] for x in wo_capable_eval) or '无'}"
            f"（要求 {'、'.join('/'.join(x['wants_keys']) for x in wo_capable_eval) or '-'}），"
            f"均不适用于本单。")
        overall = "routed_to_other_system"
    elif blocked:
        names = "、".join(
            f"{x.get('rule_name')}（{x.get('status')}，{x.get('description') or '无描述'}）"
            for x in blocked)
        conclusion = (
            f"**本单需人工派单的原因**：FOAccept 阶段唯一适用于本单的建 WO 规则 "
            f"{names} **已停用**；其余同阶段 ACTIVE 规则（"
            + "、".join(x["rule_name"] or "" for x in evaluated
                        if x["verdict"] == "not_applicable") +
            "）均针对其它站点类型/告警类型，不适用于本单。"
            f"因此没有任何规则自动建 WO，TT 落到兜底派单规则后由 NOC 人工接单，"
            f"现场是否出人无系统保证。")
        overall = "no_active_rule_matched"
    else:
        conclusion = (f"FOAccept 阶段没有任何适用于本单的推单规则（本单特征："
                      f"siteSubtype={site_subtype or '-'}，告警={alarm_name or '-'}），"
                      f"属**规则真空**：无规则可依，只能人工派单。建议评估是否需要新增覆盖规则。")
        overall = "rule_vacuum"

    return {
        "trigger_step": target_step,
        "step_meaning": "FO Accept 阶段：决定 FO 接单时是否自动建 WO（派现场）",
        "signature": {k: v for k, v in sig.items() if k not in ("IPT", "WO_TARGET")},
        "site_subtype": site_subtype,
        "alarm_name": alarm_name or None,
        "alarm_code": _acode,
        "has_wo": has_wo,
        "rules_at_step": evaluated,
        "candidate_rules": [r.get("rule_name") for r in candidates],
        "blocked_rules": [{
            "rule_name": r.get("rule_name"),
            "status": r.get("status"),
            "description": r.get("description"),
            "update_time": r.get("update_time"),
            "priority": r.get("priority"),
        } for r in blocked],
        "active_candidate_rules": [r.get("rule_name") for r in active_candidates],
        "wo_active_rules": [r.get("rule_name") for r in wo_active],
        "other_active_rules": [{
            "rule_name": r.get("rule_name"),
            "target": _rule_target(r),
        } for r in other_active],
        "manual_by_design": manual_by_design,
        "manual_rules": [{
            "rule_name": r.get("rule_name"),
            "status": r.get("status"),
            "description": r.get("description"),
        } for r in manual_rules],
        "wo_capable_active_rules": wo_capable_eval,
        "fallback_rules": [{
            "rule_name": r.get("rule_name"),
            "priority": r.get("priority"),
            "status": r.get("status"),
            "description": r.get("description"),
        } for r in dispatch_rules],
        "overall": overall,
        "conclusion": conclusion,
        "caveat": ("规则适用范围由规则名/描述关键词反推（看不到 eFlow 规则表达式），"
                   "结论供定位方向；判定依据与规则原文已并列展示，请人工复核。"),
    }


def _detect_ocrule_columns(conn) -> Dict[str, str]:
    """探测 ocrule_details 的实际列名（兼容 sqlite / pg 两套），返回原始列名集合。"""
    names: set = set()
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='ocrule_details'"
        ).fetchall()
        names = {(r[0] if isinstance(r[0], str) else str(r[0])) for r in rows}
    except Exception:
        try:
            rows = conn.execute("PRAGMA table_info(ocrule_details)").fetchall()
            names = {str(r[1]) for r in rows}
        except Exception:
            return {}

    return {"_columns": names}


def _qcol(name: str) -> str:
    """列名安全引用。

    ⚠ 关键坑（2026-09-23 修复）：PG 会把未加引号的标识符**折叠成小写**，
    因此 `ocrule_details` 里的 camelCase 列（ruleName / ruleType / status…）
    在 `SELECT ruleName` 时会报 `字段 "rulename" 不存在`。原实现只在列名含
    空格/引号时才加引号，导致 PG 模式下整条规则查询失败 → `_load_push_rules`
    静默返回空 → 页面上「断站类码 ACTIVE 覆盖」永远是「（无）」、
    active_rule_count 恒为 0，而派单分类却仍按 siteSubtype 给出结论
    （两处证据自相矛盾）。

    修法：**一律加双引号**。sqlite 中双引号同样合法（标准 SQL 标识符引用），
    故两方言通用；内部的双引号按 SQL 规范翻倍转义。
    """
    return '"' + str(name).replace('"', '""') + '"'


def _detect_eflow_site_columns(conn) -> Dict[str, str]:
    """探测 eflow_site 的列名（小写无空格 / 带空格两套），返回 {id, sitesubtype}（已加引号）。"""
    names: set = set()
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='eflow_site'"
        ).fetchall()
        names = {(r[0] if isinstance(r[0], str) else str(r[0])) for r in rows}
    except Exception:
        try:
            rows = conn.execute("PRAGMA table_info(eflow_site)").fetchall()
            names = {str(r[1]) for r in rows}
        except Exception:
            return {}

    def _find(*cands):
        for c in cands:
            if c in names:
                return _qcol(c)
        lower = {n.lower().replace(" ", ""): n for n in names}
        for c in cands:
            key = c.lower().replace(" ", "")
            if key in lower:
                return _qcol(lower[key])
        return None

    id_col = _find("site_id", "Site ID")
    sub_col = _find("sitesubtype", "Site Sub Type", "site_subtype")
    if not (id_col and sub_col):
        return {}
    return {"id": id_col, "sitesubtype": sub_col}

    rules = []
    active_codes = set()
    stopped_codes = set()
    down_codes = ("9970", "9980", "9990", "9910", "9920", "9995", "99933")

    for r in rows:
        d = dict(r)
        # 仅根据规则名/描述判定是否覆盖断站类码（粗略但够用，更精确的需要解 条件 JSON）
        text = (d.get("ruleName") or "") + " " + (d.get("description") or "")
        covers = []
        for c in down_codes:
            if c in text or "断站" in text and d.get("status") == "ACTIVE":
                covers.append(c)
        if covers:
            (active_codes if d.get("status") == "ACTIVE" else stopped_codes).update(covers)
        rules.append(d)

    return {
        "rules": rules,
        "down_alarm_codes_active": sorted(active_codes),
        "down_alarm_codes_stopped": sorted(stopped_codes),
    }


# ========================= 单 TT 复盘报告 =========================

def _parse_operator(detail: str) -> Tuple[str, str]:
    """从 detail 文本里提取 Operator 与时间戳。"""
    if not detail:
        return "", ""
    m = re.search(r"Operator:([^(]+)\(([^)]*)\)", str(detail))
    op = f"{m.group(1).strip()}({m.group(2).strip()})" if m else ""
    tm = re.search(r"Operation Time:([0-9\-: ]+)", str(detail))
    ts = tm.group(1).strip() if tm else ""
    return op, ts


# create_detail 里"指派给谁"的字段。实测样例（TT202609220139）：
#   Operation Step:Create. Operation Result:FO Accept. Operation Time:2026-9-22 16:53:50.
#   Operator:assign_rule(assign_rule). Operator Group:. Next Status:Waiting for FO Accept.
#   Assign To:. Assignee Group:. Remark:
# 注意 `Assign To` 与 `Assignee Group` **经常是空的** —— 建单时并没有指派到具体人，
# 单子只是落进某个群组池等接单。这正是"为什么长时间没人动"的关键线索，
# 不能因为取不到值就不显示，要**如实显示为空并说明含义**。
_CREATE_FIELDS = ("Operation Result", "Operator Group", "Next Status",
                  "Assign To", "Assignee Group", "Remark")


def _parse_create_detail(raw) -> Dict[str, Any]:
    """解析建单明细里的指派信息（含"未指派"这一事实）。

    用**字段名联合前瞻**逐个取值，而不是"值到下一个大写词"的模糊匹配——
    后者会把字段之间的分隔句点当成值（实测 `Assign To:. Assignee Group:.`
    被解析成 `assign_to='.'`，于是报告写成"已指派到人：."）。
    取到值后去掉首尾空白与分隔句点，空串一律归一为 None。
    """
    txt = str(raw or "")
    out: Dict[str, Any] = {}
    alt = "|".join(re.escape(f) for f in _CREATE_FIELDS)
    for m in re.finditer(rf"({alt}):(.*?)(?=(?:{alt}):|$)", txt, re.S):
        val = m.group(2).strip().strip(".").strip()
        out[m.group(1)] = val or None
    return {
        "assign_to": out.get("Assign To"),
        "assignee_group": out.get("Assignee Group"),
        "operator_group": out.get("Operator Group"),
        "next_status": out.get("Next Status"),
        "operation_result": out.get("Operation Result"),
        "remark": out.get("Remark"),
    }


def build_tt_postmortem(tt_no: str) -> Dict[str, Any]:
    """单张 TT 的完整复盘报告。"""
    with get_raw_connection() as conn:
        row = conn.execute(
            """SELECT tt_no, site_id, site_name, alarm_code, alarm_id, ticket_severity,
                      alarm_severity, status, root_cause, sub_root_cause, root_cause_description,
                      alarm_reason_type, last_processer, last_processer_group,
                      last_modified_time, created_time, alarm_occur_time, alarm_clear_time,
                      create_detail, fo_accept_detail, fo_process_detail, confirm_detail,
                      creator, wo_no, domain
               FROM eflow_tt WHERE tt_no = ?""",
            (tt_no,),
        ).fetchone()
        if not row:
            return {"tt_no": tt_no, "found": False, "message": "未找到该工单"}

        t = dict(row)

        # 告警链路
        alarm_rows, linkage = _fetch_alarm_chain(
            conn, tt_no, t.get("alarm_id"), t.get("site_id"),
            t.get("alarm_code"), t.get("alarm_reason_type"),
        )

        # 站点子类型（影响派单路径判定）。eflow_site 列名兼容：小写无空格（my_app）
        # vs 带空格（部分同步副本）；用 information_schema 检测后拼接。
        site_subtype = None
        site_cols = _detect_eflow_site_columns(conn)
        if t.get("site_id") and site_cols:
            try:
                sub_col = site_cols.get("sitesubtype")
                id_col = site_cols.get("id")
                sql = (f"SELECT {sub_col} AS sitesubtype "
                       f"FROM eflow_site WHERE CAST({id_col} AS TEXT) = ?")
                r2 = conn.execute(sql, (str(t["site_id"]),)).fetchone()
                if r2:
                    site_subtype = dict(r2).get("sitesubtype")
            except Exception:
                logger.warning("[tt_postmortem] eflow_site.sitesubtype 读取失败", exc_info=True)

        # WO 与原始告警（链路下钻用）
        wo_record = None
        if t.get("wo_no"):
            try:
                w = conn.execute(
                    "SELECT wo_no, status, creator, source, created_time FROM eflow_wo WHERE wo_no = ?",
                    (t["wo_no"],),
                ).fetchone()
                if w:
                    wo_record = dict(w)
            except Exception:
                pass

        # 派单规则地图
        rules_meta = _load_push_rules(conn)

        # 同站近 90 天告警指纹（用于 history_match 字段）
        history_match = ""
        if t.get("site_id"):
            try:
                cnt = conn.execute(
                    """SELECT COUNT(*) FROM history_alarm
                       WHERE CAST(site_id AS TEXT) = ?""",
                    (str(t["site_id"]),),
                ).fetchone()[0]
                history_match = f"该站 history_alarm 共 {cnt} 条告警指纹"
            except Exception:
                pass

        conn.close()

    # === NOC 填报层 ===
    filed_by_accept, _ = _parse_operator(t.get("fo_accept_detail") or "")
    filed_by_process, filed_at = _parse_operator(t.get("fo_process_detail") or "")
    confirm_by, confirm_at = _parse_operator(t.get("confirm_detail") or "")
    create_by, create_at = _parse_operator(t.get("create_detail") or "")

    # === 系统判定层 ===
    system_judged = None
    if alarm_rows:
        best, best_domain, best_basis = None, "UNKNOWN", ""
        for r in alarm_rows:
            d = dict(r)
            dom, basis = _infer_fault_domain(
                d.get("codename"), d.get("reason_type"), d.get("alarmcode")
            )
            if dom != "UNKNOWN":
                best, best_domain, best_basis = d, dom, basis
                break
            if best is None:
                best, best_domain, best_basis = d, dom, basis
        codes = [str(dict(r).get("alarmcode")) for r in alarm_rows]
        names = [str(dict(r).get("codename")) for r in alarm_rows]
        system_judged = {
            "fault_domain": best_domain,
            "basis": best_basis,
            "alarmcode": best.get("alarmcode") if best else None,
            "codename": best.get("codename") if best else None,
            "reason_type": best.get("reason_type") if best else None,
            "alarm_source": best.get("alarm_source") if best else None,
            "restypename": best.get("restypename") if best else None,
            "alarmkey": best.get("alarmkey") if best else None,
            "linkage": linkage,
            "alarm_count": len(alarm_rows),
            "distinct_codes": sorted(set(codes)),
            "distinct_names": sorted(set(names)),
        }
    elif t.get("alarm_reason_type"):
        system_judged = {
            "fault_domain": t["alarm_reason_type"],
            "basis": "eflow_tt.alarm_reason_type（系统字段，无告警链路佐证）",
            "alarmcode": t.get("alarm_code"),
            "reason_type": t["alarm_reason_type"],
            "linkage": linkage,
            "alarm_count": 0,
        }

    # === 一致性判定 ===
    noc_rc = (t.get("root_cause") or "").strip().upper()
    consistency = None
    mismatch_type = ""
    confidence = "low"
    note = ""
    if system_judged and noc_rc:
        sys_domain = system_judged["fault_domain"]
        if sys_domain in ("POWER", "TRM", "OTHER"):
            confidence = ("high" if linkage == "exact"
                          else "medium" if linkage in ("site_fallback", "site_reason_fallback")
                          else "low")
            if noc_rc == "POWER" and sys_domain == "TRM":
                consistency = False
                mismatch_type = "POWER<-TRM"
                note = "NOC 填报 POWER（供电类），但告警链路显示为传输类（TRM）故障，疑似误填。"
            elif noc_rc == "POWER" and sys_domain == "POWER":
                consistency = True
                note = "NOC 填报 POWER，告警链路同样指向供电类，一致。"
            elif noc_rc in ("MW", "FIBER", "RAN", "IP-DWDM NETWORK") and sys_domain == "TRM":
                consistency = True
                note = "NOC 填报传输类，与告警链路一致。"
            elif sys_domain == "POWER" and noc_rc != "POWER":
                consistency = False
                mismatch_type = f"{noc_rc}<-POWER"
                note = "告警链路指向供电类，但 NOC 未填报 POWER。"
            else:
                note = f"告警链路判定为 {sys_domain}，NOC 填报 {noc_rc}，需人工复核。"
    elif not noc_rc:
        note = "NOC 未填报根因（root_cause 为空），无法比对。"
    elif linkage == "site_fallback_unrelated":
        note = "该站 48h 窗口内有其它单子的告警，但告警码与本单不匹配，不能作为本单判据。"
    else:
        note = "缺少可用告警链路，无法比对（告警可能已滚出 48h 窗口）。"

    # === 派单机制真相（§3.4 复用）===
    dispatch_path = _infer_dispatch_path(t, wo_record, site_subtype, rules_meta)

    # === 阶段时延 ===
    durations = _calc_durations(t)

    # === 里程碑时间轴 + 应做/实做对比 + 偏离（2026-09-23 增强）===
    # 独立成子视图，复用同一套 WHERE 与解析器；失败不应拖垮主报告。
    #
    # ⚠ 必须在 suggested_actions **之前**构建：下面的建议要用到
    # `dispatch_analysis`，而它由 build_tt_timeline 产出。
    # 曾经在本函数里**另算一份** dispatch_analysis，结果两份输入不同
    # （本函数的 SELECT 没有 alarm_description）→ 特征识别不到「断站」，
    # 规则匹配静默变成 0 命中，导致"建议"与报告 5b 节自相矛盾。
    # 只保留**一处**计算，从根上消除这种分歧。
    timeline_view: Dict[str, Any] = {}
    try:
        timeline_view = build_tt_timeline(tt_no)
    except Exception:
        logger.warning("[tt_postmortem] 时间轴构建失败（主报告继续返回）", exc_info=True)
    # 规则匹配分析：与报告 5b 节同源
    dispatch_analysis = timeline_view.get("dispatch_analysis") or {}

    # === 报告整合 ===
    suggested_actions = []
    if consistency is False and mismatch_type == "POWER<-TRM":
        suggested_actions.append("建议追溯该站上联传输链路（MW 微波 / PTN / 光纤），核查是否为链路反复中断")
    if dispatch_path.get("category") == "rule_stopped":
        stopped = ", ".join(rules_meta.get("down_alarm_codes_stopped") or []) or "断站类码"
        suggested_actions.append(f"覆盖该单告警码的推单规则已停用（覆盖码：{stopped}），需评估恢复或新增兜底规则")
    if dispatch_path.get("category") == "rule_vacuum":
        suggested_actions.append("该单告警码不在任何 ACTIVE 推单规则命中范围，需新增兜底或人工甄别")
    # 规则匹配分析给出的**指名**建议（比上面的"覆盖码集合"更可执行）
    if dispatch_analysis.get("blocked_rules"):
        for b in dispatch_analysis["blocked_rules"]:
            suggested_actions.append(
                f"推单规则「{b.get('rule_name')}」对本单本应命中但已停用"
                f"（描述：{b.get('description') or '无'}，最后更新 {b.get('update_time') or '-'}）；"
                f"若该组合确实需要自动派现场，需评估恢复此规则")
    elif dispatch_analysis.get("manual_by_design"):
        _mr = (dispatch_analysis.get("manual_rules") or [{}])[0]
        suggested_actions.append(
            f"该组合（siteSubtype={site_subtype or '-'} + 断站）按规则「{_mr.get('rule_name')}」"
            f"**设计即为人工处理**，不自动建 WO；若要改为自动派现场，需新增/修改推单规则")
    if durations.get("fo_process_seconds") and durations["fo_process_seconds"] > 8 * 3600:
        suggested_actions.append(f"FO Process 阶段耗时 {durations['fo_process_seconds']/3600:.1f}h，建议加 'Night Accept → Day Handover' 硬约束")

    # ---- 由「时间都花哪了」的瓶颈直接产出建议 ----
    # 复盘的价值就在于"最大的那块时间"能对应到一个可执行动作。
    # 曾经出现"瓶颈 15.81 小时却零条建议"的情况——建议只跟着派单规则走，
    # 而这条单的派单没问题、问题全在现场响应等待上，于是报告什么都没说。
    _ts = timeline_view.get("time_spent") or {}
    _bn = _ts.get("bottleneck") or {}
    _bsec = int(_bn.get("seconds") or 0)
    _bph = _bn.get("phase") or ""
    _blab = _bn.get("phase_label") or _bn.get("label") or ""
    _bown = _bn.get("owner") or "-"
    if _bsec > 2 * 3600:
        _HINT = {
            "onsite_wait": ("现场响应等待过长：WO 派出后长时间无人到场，"
                            "建议对 WO 建立「到场时限 + 超时自动升级/改派」机制，"
                            "并核查是否只是机器人建单、无人真正接手"),
            "detect":      ("建单时延过长：告警发生到建单耗时显著，"
                            "建议核查告警采集/建单规则（ttLevelRule）的触发时延与积压"),
            "assign":      ("接单等待过长：TT 建好后长时间无人接单，"
                            "建议对 FO 通道设置接单超时提醒与值班兜底"),
            "handle":      ("提交关单耗时过长：建议核查 FO 填报环节的作业与审批阻塞点"),
            "close":       ("关单确认耗时过长：建议核查确认/自动关闭规则（ttAutoCloseRule）是否生效"),
            "clear":       ("告警清除耗时过长：告警长时间未恢复，建议核查现场处置质量与恢复确认流程"),
            "onsite_work": ("现场作业耗时过长：建议核查备件、上站条件与作业工时"),
        }
        _hint = _HINT.get(_bph)
        suggested_actions.append(
            f"时间瓶颈：「{_blab}」占 {_bn.get('pct')}%（{_bn.get('seconds') and round(_bsec/3600.0, 1)}h），"
            f"责任方 {_bown}。" + (_hint or "建议针对该阶段做专项分析"))

    # ---- 由「指派给谁」产出建议 ----
    _asg = timeline_view.get("assignment") or {}
    if _asg.get("unassigned"):
        _ch = _asg.get("current_handler")
        _pool = f"仅落入群组池 `{_ch}`" if _ch else "且当前处理人为空，连群组池都没有"
        suggested_actions.append(
            f"建单时**未指派到任何个人**（`Assign To` / `Assignee Group` 均为空），"
            f"{_pool}；群组池没有明确的接单责任人，是长时间无人响应的结构性原因，"
            f"建议为 FO 通道配置带时限的轮值/派单到人规则")

    # === 里程碑时间轴 + 应做/实做对比 + 偏离（2026-09-23 增强）===
    # （已在前面构建，此处只做返回组装）
    return {
        "tt_no": tt_no,
        "found": True,
        "timeline": timeline_view.get("timeline") or [],
        "expected_actions": timeline_view.get("expected_actions") or [],
        "missing_actions": timeline_view.get("missing_actions") or [],
        "deviations": timeline_view.get("deviations") or [],
        "site_history": timeline_view.get("site_history") or [],
        "timeline_meta": timeline_view.get("meta") or {},
        # 时间归因 / SLA / 责任人（2026-09-23 增强）
        "time_spent": timeline_view.get("time_spent") or {},
        "sla": timeline_view.get("sla") or {},
        "people": timeline_view.get("people") or {},
        # 派单归因：依据 TT Push Order Rule 解释"为什么这单走人工派单"
        "dispatch_analysis": dispatch_analysis,
        # 指派归因：这单指派给谁了（含"未指派到人"这一事实）
        "assignment": timeline_view.get("assignment") or {},
        "site": {
            "site_id": t.get("site_id"),
            "site_name": t.get("site_name"),
            "site_subtype": site_subtype,
        },
        "ticket": {
            "ticket_severity": t.get("ticket_severity"),
            "alarm_severity": t.get("alarm_severity"),
            "alarm_code": t.get("alarm_code"),
            "status": t.get("status"),
            "domain": t.get("domain"),
            "alarm_occur_time": t.get("alarm_occur_time"),
            "alarm_clear_time": t.get("alarm_clear_time"),
            "create_time": t.get("create_time"),
            "last_modified_time": t.get("last_modified_time"),
        },
        "operators": {
            "create": {"operator": create_by, "time": create_at},
            "fo_accept": {"operator": filed_by_accept, "time": ""},
            "fo_process": {"operator": filed_by_process, "time": filed_at},
            "confirm": {"operator": confirm_by, "time": confirm_at},
            "last_processer": t.get("last_processer"),
            "last_processer_group": t.get("last_processer_group"),
        },
        "noc_filled": {
            "root_cause": t.get("root_cause"),
            "sub_root_cause": t.get("sub_root_cause"),
            "root_cause_description": t.get("root_cause_description"),
            "filed_by": filed_by_process or t.get("last_processer"),
            "filed_at": filed_at or t.get("last_modified_time"),
        },
        "system_judged": system_judged,
        "consistency": consistency,
        "mismatch_type": mismatch_type,
        "confidence": confidence,
        "note": note,
        "history_match": history_match,
        "wo": {
            "wo_no": (wo_record or {}).get("wo_no") or t.get("wo_no"),
            "status": (wo_record or {}).get("status"),
            "creator": (wo_record or {}).get("creator"),
            "source": (wo_record or {}).get("source"),
            "created_time": (wo_record or {}).get("created_time"),
        },
        "dispatch_path": dispatch_path,
        "durations": durations,
        "rules_snapshot": {
            "down_alarm_codes_active": rules_meta.get("down_alarm_codes_active") or [],
            "down_alarm_codes_stopped": rules_meta.get("down_alarm_codes_stopped") or [],
            "active_rule_count": sum(1 for x in rules_meta.get("rules") or [] if x.get("status") == "ACTIVE"),
            "stopped_rule_count": sum(1 for x in rules_meta.get("rules") or [] if x.get("status") == "STOP"),
        },
        "suggested_actions": suggested_actions,
    }


def _infer_dispatch_path(t: Dict[str, Any], wo_record: Optional[Dict[str, Any]],
                          site_subtype: Optional[str], rules_meta: Dict[str, Any]) -> Dict[str, Any]:
    """§3.4 复用：判定派单路径与成因。"""
    wo_creator = (wo_record or {}).get("creator") or ""
    fo_accept = t.get("fo_accept_detail") or ""
    tt_alarm_code = _norm_alarm_id(t.get("alarm_code"))
    is_down_class = tt_alarm_code in ("9970", "9980", "9990", "9910", "9920", "9995", "99933")

    info: Dict[str, Any] = {
        "wo_no": t.get("wo_no"),
        "wo_creator": wo_creator,
        "site_subtype": site_subtype,
        "tt_alarm_code": tt_alarm_code,
        "category": None,
        "explanation": "",
    }

    if t.get("wo_no") and wo_record:
        info["category"] = "auto_dispatched"
        info["explanation"] = f"WO 由 {wo_creator} {'自动' if wo_creator in ('fe_robot','auto_robot') else '人工'} 建单"
        return info

    # 无 WO，按规则覆盖情况推断
    # 注意：即便 site_subtype 未读到（PG 列名差异），只要 alarms_meta 中标记 REGULAR/ERA 覆盖已停用，
    # 仍能给出 rule_stopped 判定。
    stopped_codes = set(rules_meta.get("down_alarm_codes_stopped") or [])
    active_codes = set(rules_meta.get("down_alarm_codes_active") or [])

    if is_down_class and site_subtype == "ERA":
        info["category"] = "rule_vacuum"
        info["explanation"] = "ERA 站断站类告警，规则 #203 应覆盖但未建 WO —— 异常，需查 #203 与站点数据"
    elif is_down_class and site_subtype == "REGULAR":
        info["category"] = "rule_stopped"
        info["explanation"] = ("REGULAR 站断站类告警，自动推单规则 #201 已于 2026-08-20 16:16:41 停用，"
                               "本单落入 NOC 人工通道 → 无 WO")
    elif is_down_class and tt_alarm_code in stopped_codes:
        info["category"] = "rule_stopped"
        info["explanation"] = (f"告警码 {tt_alarm_code} 所属的推单规则已 STOP（覆盖码集合："
                               f"{sorted(stopped_codes)}）；落回 NOC 人工通道 → 无 WO")
    elif is_down_class and tt_alarm_code not in active_codes and active_codes:
        info["category"] = "rule_vacuum"
        info["explanation"] = (f"告警码 {tt_alarm_code} 不在 ACTIVE 推单规则覆盖集合 "
                               f"{sorted(active_codes)} 内；规则真空，需新增兜底")
    elif is_down_class:
        info["category"] = "rule_vacuum"
        info["explanation"] = f"断站类告警码 {tt_alarm_code}，未命中任何 ACTIVE 推单规则（siteSubtype={site_subtype}）"
    else:
        info["category"] = "no_rule_or_p4"
        info["explanation"] = f"告警码 {tt_alarm_code} 不在断站类集合内，可能为小区级 / 板件级告警，或 P4 自愈型无需现场"

    # 补充：FO Accept 派单目标
    m = re.search(r"Assign To:([^\s.]+(?:\([^)]*\))?)", fo_accept)
    if m:
        info["fo_assign_to"] = m.group(1).strip()
    return info


def _parse_dt(s) -> Optional[datetime]:
    """解析 eFlow / 库中出现的各种时间串。

    ⚠ 关键坑（2026-09-23 修复）：eFlow 的 `*_detail` 文本里的 Operation Time
    **月/日不补零**（实测 `2026-9-21 23:25:35`）。原实现只用 `%Y-%m-%d %H:%M:%S`
    等补零格式，解析失败后回落到 `datetime.fromisoformat('2026-9-21 23:25:35')`，
    而 fromisoformat 会把 `2026-9-2` 当成「2026-09-02」再把 `1 23:25:35` 当别的字段，
    于是**静默算错**（实测 23:25:35 被解析成 23:25:03 —— 秒被吃掉、日被误读）。
    这类错误不抛异常，只让所有阶段时长集体偏差，因此这里显式支持不补零格式，
    并且**不再回落到 fromisoformat 去猜**（猜错比失败更危险）。
    """
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    # 先做规范化：把 "2026-9-21 23:25:35" → "2026-09-21 23:25:35"，
    # 避免落到 fromisoformat 的错误猜测分支。
    norm = re.sub(r"^(\d{4})-(\d{1,2})-(\d{1,2})",
                  lambda m: f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(norm[:len(fmt) + 6 if "%f" in fmt else len(fmt)], fmt)
        except Exception:
            continue
    try:
        # ISO with Z / 带时区：仅在这种**明确**形态下才用 fromisoformat
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1])
        if "+" in s[10:] or re.search(r"\d{2}:\d{2}:\d{2}", s):
            return datetime.fromisoformat(norm)
    except Exception:
        pass
    logger.warning("[tt_postmortem] 无法解析时间串: %r（将按缺失处理）", s)
    return None


def _calc_durations(t: Dict[str, Any]) -> Dict[str, Any]:
    """从 *_detail 文本里提取时戳，计算阶段时长（秒）。"""
    out: Dict[str, Any] = {
        "create_to_accept_seconds": None,
        "accept_to_process_seconds": None,
        "process_to_confirm_seconds": None,
        "total_seconds": None,
    }

    def _ts(detail: str) -> Optional[datetime]:
        m = re.search(r"Operation Time:([0-9\-: T]+)", str(detail or ""))
        if not m:
            return None
        return _parse_dt(m.group(1).strip())

    t_create = _ts(t.get("create_detail"))
    t_accept = _ts(t.get("fo_accept_detail"))
    t_process = _ts(t.get("fo_process_detail"))
    t_confirm = _ts(t.get("confirm_detail"))

    def diff(a, b):
        if not a or not b:
            return None
        try:
            return max(0, int((b - a).total_seconds()))
        except Exception:
            return None

    out["create_to_accept_seconds"] = diff(t_create, t_accept)
    out["accept_to_process_seconds"] = diff(t_accept, t_process)
    out["process_to_confirm_seconds"] = diff(t_process, t_confirm)
    out["total_seconds"] = diff(t_create, t_confirm)
    return out


# ========================= 里程碑时间轴 · 应做/实做/偏离 =========================
# 设计要点（2026-09-23 增强）：
#   1) 只做「事实提取」——每一跳都从库里已有字段解析出来，并带上 source 与 raw，
#      任何结论都能被人工回溯到原始 `*_detail` 文本（AGENTS.md 约束 8）。
#   2) 「该有的动作」来自 eFlow 三段式契约（autoCreateTT → ttDispatchRule →
#      ttPushOrderRule → FO Accept → WO → FO Process → Confirm），
#      不是凭空发明；契约里每个必需动作若缺失/越序，就是一处偏离。
#   3) 「偏离」分四级：missing（该做没做）/ late（做了但超阈值）/ out_of_order（越序）/
#      data_conflict（字段间自相矛盾）。severity 用 critical/major/minor 三档，
#      前端按颜色分档展示。

# ---- 阶段契约：eFlow 标准链路（顺序即期望顺序）----
# expected: 该阶段在正常链路里是否**必须**出现
STAGE_CONTRACT: List[Dict[str, Any]] = [
    {"key": "alarm_occur",     "label": "告警发生",        "actor": "system", "expected": True},
    {"key": "tt_create",       "label": "TT 自动建单",     "actor": "system", "expected": True},
    {"key": "dispatch_route",  "label": "派单路由决定",    "actor": "system", "expected": True},
    {"key": "fo_accept",       "label": "FO Accept 接单",  "actor": "human",  "expected": True},
    {"key": "wo_dispatch",     "label": "WO 派单",         "actor": "system", "expected": False},
    {"key": "onsite_action",   "label": "现场处置",        "actor": "human",  "expected": False},
    {"key": "alarm_clear",     "label": "告警清除/自愈",   "actor": "system", "expected": True},
    {"key": "fo_process",      "label": "FO Process 填报", "actor": "human",  "expected": True},
    {"key": "confirm",         "label": "Confirm 关单",    "actor": "system", "expected": True},
]

# 契约必需动作（缺失即偏离）。wo_dispatch / onsite_action 属条件动作，单独判定。
REQUIRED_STAGES = ("alarm_occur", "tt_create", "fo_accept", "alarm_clear", "fo_process", "confirm")

# 各阶段超时阈值（秒）→ 超过则判 late。依据复盘报告 §5 的口径：
#   - 建单：autoCreateTT 设计值 15min，容忍到 30min
#   - Accept：P1/P2 要求 30min 内接单（夜班同为硬指标）
#   - Accept→Process：SLA 默认 8h，超过即已越线
#   - 告警已清除后仍不关单：再给 2h 的文书时间
STAGE_THRESHOLDS: Dict[str, int] = {
    "tt_create": 30 * 60,
    "fo_accept": 30 * 60,
    "fo_process": 8 * 3600,
    "confirm": 2 * 3600,
}

# 需要「现场介入」的判据：断站类告警 + 站点等级高 / 时长长
DOWN_CLASS_CODES = ("9970", "9980", "9990", "9910", "9920", "9995", "99933")
HIGH_SEVERITY = ("P1", "P2")


def _milestone(key: str, label: str, actor: str, ts: Optional[datetime],
               *, raw: str = "", source: str = "", detail: str = "",
               ok: Optional[bool] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构造一个里程碑节点（统一结构，前端按同一模板渲染）。"""
    node: Dict[str, Any] = {
        "key": key,
        "label": label,
        "actor": actor,          # system | human
        "time": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else None,
        "time_present": ts is not None,
        "source": source,        # 该时间取自库中哪个字段
        "raw": raw,              # 原始文本片段（可回溯）
        "detail": detail,        # 人话说明
    }
    if ok is not None:
        node["ok"] = ok
    if extra:
        node.update(extra)
    return node


# 系统/机器人账号标识。出现在 *_detail 的 Operator 或 eflow_wo.creator 里时，
# 说明该动作是**系统自动执行**，不能记成"人工"。
_ROBOT_TOKENS = ("fe_robot", "auto_robot", "assign_rule", "system", "robot", "auto_")


def _is_robot_operator(operator: Optional[str]) -> bool:
    """判断操作人是否是系统/机器人账号。

    ⚠ 实证必要性（2026-09-23）：`fo_accept_detail` 的 Operator 可能是
    `FE Robot(fe_robot)` —— 这是**机器人自动接单**，但旧实现把 fo_accept /
    fo_process 的 actor 写死为 "human"，报告里就出现
    「FO Accept 接单 | 人工 | FE Robot(fe_robot)」这种自相矛盾的结论。
    """
    if not operator:
        return False
    low = str(operator).lower()
    return any(tok in low for tok in _ROBOT_TOKENS)


def _actor_of(operator: Optional[str], default: str = "human") -> str:
    """由操作人反推执行方：机器人 → system，其余按 default。"""
    if _is_robot_operator(operator):
        return "system"
    return default


def _gap_seconds(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
    """b - a 的秒数；任一为空返回 None（不要用 0 冒充"瞬时"）。"""
    if not a or not b:
        return None
    try:
        return int((b - a).total_seconds())
    except Exception:
        return None


def build_tt_timeline(tt_no: str) -> Dict[str, Any]:
    """单张 TT 的「里程碑时间轴 + 应做/实做对比 + 偏离清单」。

    与 build_tt_postmortem 的关系：本函数是它的一个**子视图**，复用同一套
    解析器（_parse_operator / _calc_durations / _infer_dispatch_path），
    因此不会出现"复盘说一致、时间轴说错位"的第二套结论。
    """
    tt_no = (tt_no or "").strip().upper()
    with get_raw_connection() as conn:
        row = conn.execute(
            """SELECT tt_no, site_id, site_name, alarm_code, alarm_id,
                      ticket_severity, alarm_severity, status, sla_status, sla_deadline,
                      sla_remain_time, fault_duration_time, fault_resolved,
                      root_cause, sub_root_cause, root_cause_description,
                      alarm_reason_type, last_processer, last_processer_group,
                      created_time, last_modified_time, last_process_time,
                      alarm_occur_time, alarm_clear_time, alarm_server_time,
                      create_detail, fo_accept_detail, fo_process_detail,
                      confirm_detail, closed_detail, wo_no, domain,
                      impacted_service, site_class, vip_site, hub_site,
                      site_outage, down_site_count, ne_name, moc,
                      sla_time, group_sla_status, group_sla_time,
                      group_sla_deadline_time, group_sla_remains_time,
                      creator, title, ticket_type, alarm_description,
                      tt_source, region_id, region_level1, site_type,
                      actual_completion_time, fault_recovery_time,
                      assignment_suggestions, creator_contact_info,
                      current_handler, last_processer, last_processer_group,
                      maintenance_team, organization_id
               FROM eflow_tt WHERE tt_no = ?""",
            (tt_no,),
        ).fetchone()
        if not row:
            conn.close()
            return {"tt_no": tt_no, "found": False, "message": "未找到该工单"}

        t = dict(row)

        site_subtype = None
        site_cols = _detect_eflow_site_columns(conn)
        if t.get("site_id") and site_cols:
            try:
                r2 = conn.execute(
                    f"SELECT {site_cols['sitesubtype']} AS sitesubtype FROM eflow_site "
                    f"WHERE CAST({site_cols['id']} AS TEXT) = ?",
                    (str(t["site_id"]),),
                ).fetchone()
                if r2:
                    site_subtype = dict(r2).get("sitesubtype")
            except Exception:
                logger.warning("[tt_timeline] eflow_site.sitesubtype 读取失败", exc_info=True)

        wo_record = None
        if t.get("wo_no"):
            try:
                w = conn.execute(
                    """SELECT wo_no, status, creator, source, created_time,
                              current_handler, last_processer, accept_detail,
                              start_trip_detail, arrive_site_detail, leave_site_detail,
                              process_detail, confirm_detail, closed_detail,
                              actual_finish_time, fault_resolved_by,
                              fault_resolving_time, processing_description,
                              travel_time, sla_deadline, last_modified_time,
                              expected_finish_time, reject_reason, last_reject_time
                       FROM eflow_wo WHERE wo_no = ?""",
                    (t["wo_no"],),
                ).fetchone()
                if w:
                    wo_record = dict(w)
            except Exception:
                logger.debug("[tt_timeline] eflow_wo 读取失败", exc_info=True)

        rules_meta = _load_push_rules(conn)
        # 全量规则目录（不过滤关键词），供"为什么人工派单"的规则匹配分析使用
        rule_catalog = _load_rule_catalog(conn)

        # 同站历史告警（用于"该站反复同源故障"的佐证）
        site_history: List[Dict[str, Any]] = []
        if t.get("site_id"):
            try:
                for h in conn.execute(
                    """SELECT tt_id, alarmcode, codename, reason_type, alarmkey,
                              alarmraisedtime, alarmclearedtime
                       FROM history_alarm WHERE CAST(site_id AS TEXT) = ?
                       ORDER BY alarmraisedtime DESC LIMIT 20""",
                    (str(t["site_id"]),),
                ).fetchall():
                    hd = dict(h)
                    site_history.append({
                        "tt_no": hd.get("tt_id"),
                        "alarmcode": _norm_alarm_id(hd.get("alarmcode")),
                        "codename": hd.get("codename"),
                        "reason_type": hd.get("reason_type"),
                        "raised": _ms_to_str(hd.get("alarmraisedtime")),
                        "cleared": _ms_to_str(hd.get("alarmclearedtime")),
                        "is_self": hd.get("tt_id") == tt_no,
                    })
            except Exception:
                logger.warning("[tt_timeline] 同站历史告警读取失败", exc_info=True)

        conn.close()

    # ---------- 解析各跳时间 ----------
    t_alarm = _parse_dt(t.get("alarm_occur_time"))
    t_alarm_srv = _parse_dt(t.get("alarm_server_time"))
    t_create = _parse_dt(t.get("created_time")) or _detail_ts(t.get("create_detail"))
    t_accept = _detail_ts(t.get("fo_accept_detail"))
    t_process = _detail_ts(t.get("fo_process_detail"))
    t_confirm = _detail_ts(t.get("confirm_detail"))
    t_clear = _parse_dt(t.get("alarm_clear_time"))
    t_wo = _parse_dt((wo_record or {}).get("created_time"))

    create_by, _ = _parse_operator(t.get("create_detail"))
    accept_by, _ = _parse_operator(t.get("fo_accept_detail"))
    process_by, _ = _parse_operator(t.get("fo_process_detail"))
    confirm_by, _ = _parse_operator(t.get("confirm_detail"))
    # 建单时的指派信息（含"根本没指派给谁"这个事实）
    create_info = _parse_create_detail(t.get("create_detail"))

    dispatch_path = _infer_dispatch_path(t, wo_record, site_subtype, rules_meta)
    # 规则匹配分析：依据当前 TT Push Order Rule 解释"为什么这单走了人工派单"
    dispatch_analysis = _analyze_dispatch_reason(t, site_subtype, wo_record, rule_catalog)
    # 指派归因：这单到底指派给谁了（含"没指派到人"这一事实）
    assignment = _resolve_assignment(t, dispatch_path, create_info, rule_catalog)

    # ---------- 里程碑时间轴 ----------
    timeline: List[Dict[str, Any]] = []

    timeline.append(_milestone(
        "alarm_occur", "告警发生", "system", t_alarm,
        source="eflow_tt.alarm_occur_time",
        detail=(f"{t.get('alarm_code')} {t.get('ne_name') or ''}".strip()
                + f"（{t.get('alarm_severity')}，{t.get('moc') or '-'}）"),
        extra={"server_time": t_alarm_srv.strftime("%Y-%m-%d %H:%M:%S") if t_alarm_srv else None},
    ))

    timeline.append(_milestone(
        "tt_create", "TT 自动建单", "system", t_create,
        source="eflow_tt.created_time / create_detail",
        raw=t.get("create_detail") or "",
        detail=(f"creator={t.get('creator') or create_by or '-'}，级别 {t.get('ticket_severity')}"
                f"；指派：{assignment.get('conclusion')}"),
        extra={"gap_from_prev_s": _gap_seconds(t_alarm, t_create),
               "operator": create_by,
               # 指派给谁（建单明细原值，空值也是信息）
               "assign_to": create_info.get("assign_to"),
               "assignee_group": create_info.get("assignee_group"),
               "operator_group": create_info.get("operator_group"),
               "next_status": create_info.get("next_status"),
               "current_handler": t.get("current_handler"),
               "assignment": assignment},
    ))

    # 派单路由：不是"动作"而是"决策"，时间点即建单时刻
    route_ok = dispatch_path.get("category") == "auto_dispatched"
    timeline.append(_milestone(
        "dispatch_route", "派单路由决定", "system", t_create,
        source="dispatch_path（由 ocrule_details + eflow_site.sitesubtype 推断）",
        detail=dispatch_path.get("explanation") or "",
        ok=route_ok,
        extra={"category": dispatch_path.get("category"),
               "assign_to": dispatch_path.get("fo_assign_to"),
               "site_subtype": site_subtype},
    ))

    timeline.append(_milestone(
        "fo_accept", "FO Accept 接单", _actor_of(accept_by), t_accept,
        source="eflow_tt.fo_accept_detail",
        raw=t.get("fo_accept_detail") or "",
        detail=(f"{accept_by or '-'} 接单"
                + ("（机器人自动接单）" if _is_robot_operator(accept_by) else "")
                + ("（夜班时段）" if _is_night_accept(t.get("fo_accept_detail")) else "")
                + f"，Assign To={dispatch_path.get('fo_assign_to') or '-'}"),
        extra={"gap_from_prev_s": _gap_seconds(t_create, t_accept),
               "operator": accept_by,
               "is_robot": _is_robot_operator(accept_by),
               "is_night": _is_night_accept(t.get("fo_accept_detail"))},
    ))

    has_wo = bool(t.get("wo_no"))
    _wo_creator = (wo_record or {}).get("creator") or ""
    # WO 创建者性质：机器人/系统账号建的 WO 只是**系统自动生成的工单**，
    # 不能作为"现场有人"的证据。
    _wo_creator_kind = (
        "系统自动" if _wo_creator.lower() in ("fe_robot", "auto_robot", "system", "assign_rule")
        else ("人工" if _wo_creator else "未知")
    )
    timeline.append(_milestone(
        "wo_dispatch", "WO 派单", "system", t_wo if has_wo else None,
        source="eflow_wo.wo_no / created_time",
        detail=(f"WO {t.get('wo_no')}，创建者={_wo_creator or '-'}（{_wo_creator_kind}）"
                if has_wo else f"未产生 WO（{dispatch_path.get('category')}）"),
        ok=has_wo,
        extra={"wo_no": t.get("wo_no"),
               "wo_creator": _wo_creator,
               "wo_creator_kind": _wo_creator_kind,
               "expected": False},
    ))

    # 现场处置：先占位（保证节点一定存在于时间轴中），随后有 WO 现场步骤时覆写。
    # 覆盖顺序很重要：契约校验（for spec in STAGE_CONTRACT）会按 key 找节点，
    # 节点缺失会直接 StopIteration，因此**必须先 append 再覆写**。
    #
    # ⚠ 这里**不能**用"存在 WO"当现场介入的证据（2026-09-23 修正）：
    #   - WO 的 creator 若是 fe_robot / auto_robot，说明这只是**系统自动生成的工单**，
    #     与"有没有人到现场"无关；
    #   - eflow_tt 也没有独立的到场时间字段。
    # 旧实现把 WO 的 created_time 当作现场处置时间、actor 写死 human、ok=has_wo，
    # 于是页面上出现「现场处置 人工 2026-09-22 16:53:51」这种**无依据的结论**。
    # 现在：没有出发/到场/离场明细时，一律报「未证实」——actor=unknown、
    # 不给时间、ok=False，并说明 WO 是谁建的。
    timeline.append(_milestone(
        "onsite_action", "现场处置", "unknown", None,
        source="eflow_wo.start_trip_detail / arrive_site_detail / leave_site_detail",
        detail=("无现场动作证据：WO 的出发/到场/离场明细均为空，且 eflow_tt 无独立到场字段。"
                + (f"WO {t.get('wo_no')} 由 {_wo_creator}（{_wo_creator_kind}）创建，"
                   f"**不能据此推定现场有人**。" if has_wo
                   else "本单未产生 WO。")
                ),
        ok=False,
        extra={"expected": False, "proxy": False, "evidence": "none",
               "wo_creator_kind": _wo_creator_kind},
    ))

    # 有 WO 现场步骤（出发/到场/离场）时，用真实时间与责任人覆写上一步的占位。
    _wo_steps: List[Dict[str, Any]] = []
    if wo_record:
        for f, label in (("start_trip_detail", "出发"),
                         ("arrive_site_detail", "到场"),
                         ("leave_site_detail", "离场")):
            op, ts = _parse_wo_json_step(wo_record.get(f))
            if not (op or ts):
                op, ts = _parse_operator(wo_record.get(f) or "")
            if op or ts:
                _wo_steps.append({"label": label, "operator": op, "time": ts, "source": f"eflow_wo.{f}"})

    if _wo_steps:
        first = min(_wo_steps, key=lambda x: x["time"] or "9999")
        idx = next((i for i, n in enumerate(timeline) if n["key"] == "onsite_action"), None)
        if idx is not None:
            timeline[idx] = _milestone(
                "onsite_action", "现场处置", "human", _parse_dt(first["time"]),
                source="; ".join(s["source"] for s in _wo_steps),
                detail="；".join(
                    f'{s["label"]} {s["time"] or "-"} {s["operator"] or "-"}' for s in _wo_steps
                ),
                ok=True,
                extra={"expected": False, "proxy": False, "evidence": "wo_steps",
                       "wo_steps": _wo_steps, "operator": first["operator"]},
            )
        # 告警清除的说明要与"是否真有现场动作、以及先后关系"一致。
        # 不能只说"有现场动作明细"——实测 TT202609220139 告警 09-22 16:55 就清了，
        # 而现场动作在 09-23 08:44，两者相隔 16 小时；笼统写"有现场动作"会误导。
        _first_step_dt = _parse_dt(_wo_steps[0]["time"]) if _wo_steps else None
        if _first_step_dt and t_clear and _first_step_dt > t_clear:
            _clear_note = "（告警先清除，现场动作在其后 —— 属自愈/远程恢复后补现场动作）"
        elif _first_step_dt and t_clear:
            _clear_note = "（现场动作早于告警清除）"
        elif has_wo:
            _clear_note = "（无现场动作明细，判定为自愈/远程收口）"
        else:
            _clear_note = "（未见现场动作，判定为自愈）"
    else:
        _clear_note = ("（无现场动作明细，判定为自愈/远程收口）" if has_wo
                       else "（未见现场动作，判定为自愈）")

    timeline.append(_milestone(
        "alarm_clear", "告警清除/自愈", "system", t_clear,
        source="eflow_tt.alarm_clear_time",
        detail=f"持续 {t.get('fault_duration_time') or '-'}" + (f" {_clear_note}" if t_clear else ""),
        extra={"fault_duration": t.get("fault_duration_time"),
               "gap_from_accept_s": _gap_seconds(t_accept, t_clear)},
    ))

    timeline.append(_milestone(
        "fo_process", "FO Process 填报", _actor_of(process_by), t_process,
        source="eflow_tt.fo_process_detail",
        raw=t.get("fo_process_detail") or "",
        detail=(f"{process_by or '-'} 提交 Confirm，填报根因 "
                f"{t.get('root_cause') or '（空）'}/{t.get('sub_root_cause') or '（空）'}"
                + ("（机器人自动填报）" if _is_robot_operator(process_by) else "")),
        extra={"gap_from_prev_s": _gap_seconds(t_clear, t_process),
               "gap_from_accept_s": _gap_seconds(t_accept, t_process),
               "is_robot": _is_robot_operator(process_by),
               "operator": process_by},
    ))

    timeline.append(_milestone(
        "confirm", "Confirm 关单", _actor_of(confirm_by, default="system"), t_confirm,
        source="eflow_tt.confirm_detail",
        raw=t.get("confirm_detail") or "",
        detail=(f"{confirm_by or '-'} 确认关闭，状态 {t.get('status')}"
                + ("（机器人自动关单）" if _is_robot_operator(confirm_by) else "")),
        extra={"gap_from_prev_s": _gap_seconds(t_process, t_confirm),
               "is_robot": _is_robot_operator(confirm_by),
               "operator": confirm_by},
    ))

    # ---------- 时间轴排序 ----------
    # 时间轴必须按**真实发生顺序**呈现，而不是按契约顺序硬排。
    # 反例（实测 TT202609230005）：WO 在 00:27 派、现场 07:38 到场、告警 07:27 清除，
    # 若按契约顺序把"现场处置"排在"告警清除"之前，再对相邻跳算 gap，
    # 就会出现 "-7.00 小时"这种负数间隔，读者会以为数据错了。
    # 约定：有时间戳的按时间升序；无时间戳的（缺失动作）按其契约位置插回队尾，
    # 保持"缺失项集中在后"的可读性。
    _contract_pos = {s["key"]: i for i, s in enumerate(STAGE_CONTRACT)}
    timeline.sort(key=lambda n: (
        0 if n["time_present"] else 1,
        _parse_dt(n["time"]) if n["time_present"] else datetime.max,
        _contract_pos.get(n["key"], 99),
    ))
    # 排序后重算"距上一跳"，避免沿用排序前的错误间隔
    _prev_dt = None
    for n in timeline:
        if not n["time_present"]:
            n.pop("gap_from_prev_s", None)
            continue
        cur = _parse_dt(n["time"])
        if _prev_dt is not None and cur is not None:
            n["gap_from_prev_s"] = _gap_seconds(_prev_dt, cur)
        else:
            n.pop("gap_from_prev_s", None)
        _prev_dt = cur

    # ---------- 应做 / 实做 / 缺失 / 越序 ----------
    done_keys = {n["key"] for n in timeline if n["time_present"]}
    expected_actions: List[Dict[str, Any]] = []
    missing_actions: List[Dict[str, Any]] = []
    deviations: List[Dict[str, Any]] = []

    for spec in STAGE_CONTRACT:
        node = next(n for n in timeline if n["key"] == spec["key"])
        did = node["time_present"]
        # 三态，而不是"做了/没做"两态：
        #   done      有确凿时间戳
        #   unproven  取不到证据，但**也不能断定没做**（如"有 WO 却无现场动作明细"——
        #             eflow_tt 本就没有到场字段，WO 又可能是 fe_robot 自动建的）
        #   missing   必需动作确实缺失
        # 把 unproven 单独列出来，是为了不把"查不到"说成"没执行"。
        if did:
            status = "done"
        elif node.get("evidence") == "none":
            status = "unproven"
        else:
            status = "missing"
        expected_actions.append({
            "key": spec["key"],
            "label": spec["label"],
            "actor": spec["actor"],
            "required": spec["expected"],
            "done": did,
            "status": status,
            "evidence": node.get("evidence"),
            "time": node["time"],
            "operator": node.get("operator"),
            "detail": node["detail"],
        })
        if spec["expected"] and not did:
            missing_actions.append({
                "key": spec["key"], "label": spec["label"], "actor": spec["actor"],
                "reason": f"契约要求该动作必须出现，但库中 {node['source']} 为空/无法解析",
            })

    # --- 偏离 1：必需动作缺失 ---
    for m in missing_actions:
        deviations.append({
            "code": f"missing_stage:{m['key']}",
            "kind": "missing",
            "severity": "critical" if m["key"] in ("fo_accept", "fo_process", "confirm") else "major",
            "label": f"缺少「{m['label']}」",
            "expected": f"契约要求必须执行「{m['label']}」",
            "actual": "库中无对应时间戳/操作人",
            "impact": m["reason"],
        })

    # --- 偏离 2：超时（做了但晚） ---
    for prev_key, cur_key, field in (
        ("alarm_occur", "tt_create", "tt_create"),
        ("tt_create", "fo_accept", "fo_accept"),
        ("fo_accept", "fo_process", "fo_process"),
    ):
        prev = next((n for n in timeline if n["key"] == prev_key), None)
        cur = next((n for n in timeline if n["key"] == cur_key), None)
        if not (prev and cur and prev["time_present"] and cur["time_present"]):
            continue
        gap = _gap_seconds(_parse_dt(prev["time"]), _parse_dt(cur["time"]))
        limit = STAGE_THRESHOLDS.get(field)
        if gap is None or limit is None or gap <= limit:
            continue
        label = f"{prev['label']} → {cur['label']}"
        deviations.append({
            "code": f"late_stage:{cur_key}",
            "kind": "late",
            "severity": "critical" if field == "fo_process" else "major",
            "label": f"「{label}」超时",
            "expected": f"应 ≤ {_fmt_h(limit)}",
            "actual": f"实际 {_fmt_h(gap)}（超 {_fmt_h(gap - limit)}）",
            "impact": (
                "FO Process 超过 8h SLA 窗口，直接导致 SLA Failed"
                if field == "fo_process" else
                "接单/建单超时，压缩了后续处置窗口"
            ),
        })

    # --- 偏离 3：越序（时间倒挂） ---
    # ⚠ 只对**契约上有先后约束**的相邻动作判越序，"告警清除 → FO Process" 不算：
    # 告警自愈本来就早于文书流程，这是常态（实测 120 单里 86 单如此），
    # 把它当偏离会制造噪声、淹没真问题。
    _ORDER_PAIRS = {
        ("alarm_occur", "tt_create"), ("tt_create", "fo_accept"),
        ("fo_accept", "fo_process"), ("fo_process", "confirm"),
    }
    ordered = [n for n in timeline if n["time_present"] and n["key"] != "wo_dispatch"]
    for a, b in zip(ordered, ordered[1:]):
        if (a["key"], b["key"]) not in _ORDER_PAIRS:
            continue
        ta, tb = _parse_dt(a["time"]), _parse_dt(b["time"])
        if ta and tb and tb < ta:
            deviations.append({
                "code": f"out_of_order:{a['key']}->{b['key']}",
                "kind": "out_of_order",
                "severity": "major",
                "label": f"「{b['label']}」早于「{a['label']}」",
                "expected": f"{a['label']} 应先于 {b['label']}",
                "actual": f"{a['label']}={a['time']}，{b['label']}={b['time']}",
                "impact": "时间倒挂，说明字段填报或同步存在错位，需人工核对原始记录",
            })

    # --- 偏离 4：应派 WO 而未派（三维兜底判据） ---
    is_down = _norm_alarm_id(t.get("alarm_code")) in DOWN_CLASS_CODES
    sev = (t.get("ticket_severity") or "").strip().upper()
    is_vip = str(t.get("vip_site") or "").strip().lower() == "yes"
    is_hub = str(t.get("hub_site") or "").strip().lower() == "yes"
    resolved_by_selfheal = bool(t_clear and not has_wo)
    should_dispatch = is_down and (sev in HIGH_SEVERITY or is_vip or is_hub)
    if should_dispatch and not has_wo:
        reasons = []
        if sev in HIGH_SEVERITY:
            reasons.append(f"级别 {sev}")
        if is_vip:
            reasons.append("VIP 站")
        if is_hub:
            reasons.append("Hub 枢纽站")
        deviations.append({
            "code": "no_wo_for_critical_outage",
            "kind": "missing",
            "severity": "critical",
            "label": "高等级断站未派 WO",
            "expected": f"{' + '.join(reasons)} 的断站类故障应派 WO 现场处置",
            "actual": f"wo_no 为空（派单分类 {dispatch_path.get('category')}）",
            "impact": (f"该单横跨 {_fmt_h(_gap_seconds(t_alarm, t_clear))} 全靠自愈收口，"
                       "现场未介入；叠加根因误填后，真实故障域未被追溯"),
        })

    # --- 偏离 5：根因填报与系统语义冲突 ---
    # ⚠ 口径说明（2026-09-23 校准，避免噪声淹没真问题）：
    #   NOC 的 root_cause（POWER / RAN / Fiber / Planned work …）与系统的
    #   alarm_reason_type（实测本库 99% 都是 TRM）**是两套不同粒度的分类法**，
    #   直接比对会让几乎所有单子都"错位"（实测 120 单命中 120 单 = 100%），
    #   那样报告就失去区分度。
    #   因此这里只把**语义上确凿冲突**的一类计入偏离：NOC 填 POWER（供电类）
    #   而告警链路判定为 TRM（传输类）—— 这是复盘报告 §4 已用 2,529 张单验证过的
    #   真实系统性问题；其余组合只在报告正文的"根因对比"表里并列展示，不判偏离。
    is_mis, mis_kind = _mismatch_of(t)
    sys_rt = (t.get("alarm_reason_type") or "").strip().upper()
    if is_mis and mis_kind == "POWER<-TRM":
        deviations.append({
            "code": "root_cause_mismatch",
            "kind": "data_conflict",
            "severity": "critical",
            "label": "根因填报错位（POWER←TRM）",
            "expected": f"告警链路判定为 {sys_rt or 'TRM'}（传输类），应据此填报",
            "actual": (f"NOC 填 {t.get('root_cause') or '（空）'} / "
                       f"{t.get('sub_root_cause') or '（空）'} / "
                       f"{t.get('root_cause_description') or '（空）'}"),
            "impact": "故障域统计被污染，该站真实同源故障长期未被追溯",
        })

    # --- 偏离 6：告警已清除但仍拖延关单 ---
    gap_clear_process = _gap_seconds(t_clear, t_process)
    if gap_clear_process is not None and gap_clear_process > STAGE_THRESHOLDS["confirm"]:
        deviations.append({
            "code": "late_close_after_clear",
            "kind": "late",
            "severity": "minor",
            "label": "告警已清除后仍延迟关单",
            "expected": f"告警清除后应 ≤ {_fmt_h(STAGE_THRESHOLDS['confirm'])} 内完成填报关单",
            "actual": f"实际 {_fmt_h(gap_clear_process)}",
            "impact": "占用工单时长统计，虚增 MTTR",
        })

    # --- 偏离 7：SLA 已失败 ---
    if (t.get("sla_status") or "").strip().lower() == "failed":
        deviations.append({
            "code": "sla_failed",
            "kind": "late",
            "severity": "critical",
            "label": "SLA Failed",
            "expected": f"应在 {t.get('sla_deadline') or 'SLA 期限'} 前闭环",
            "actual": f"超时 {t.get('sla_remain_time') or '-'}，最终 {t.get('status')}",
            "impact": "违反 SLA 承诺；根因是 Accept 后长期无现场动作",
        })

    durations = _calc_durations(t)
    _SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}
    deviations.sort(key=lambda d: _SEV_ORDER.get(d["severity"], 9))

    # ---------- 时间归因（时间都花哪了）----------
    # WO 生命周期先算出来，交给 _build_time_spent 用于细分「FO 接单 → 提交关单」
    wo_timeline = build_wo_timeline(wo_record, tt_accept=t_accept, tt_process=t_process)
    time_spent = _build_time_spent(t, timeline, durations, _wo_steps, wo_timeline)

    # ---------- SLA 判定 ----------
    sla = _build_sla(t, t_create, t_accept, t_process, t_confirm, t_clear)

    # ---------- 责任人（TT 单信息里必须能看到"谁干的"）----------
    people = _build_people(t, timeline, wo_record, create_by, accept_by, process_by, confirm_by)

    return {
        "tt_no": tt_no,
        "found": True,
        "site": {
            "site_id": t.get("site_id"),
            "site_name": t.get("site_name"),
            "site_subtype": site_subtype,
            "site_class": t.get("site_class"),
            "vip_site": t.get("vip_site"),
            "hub_site": t.get("hub_site"),
            "region": t.get("region_level1") or t.get("region_id"),
            "site_type": t.get("site_type"),
            "site_outage": t.get("site_outage"),
            "ne_name": t.get("ne_name"),
            "moc": t.get("moc"),
        },
        "ticket": {
            "title": t.get("title"),
            "ticket_type": t.get("ticket_type"),
            "ticket_severity": t.get("ticket_severity"),
            "alarm_severity": t.get("alarm_severity"),
            "alarm_code": _norm_alarm_id(t.get("alarm_code")),
            "alarm_name": ALARM_CODE_SEMANTICS.get(_norm_alarm_id(t.get("alarm_code")), {}).get("name"),
            "alarm_description": t.get("alarm_description"),
            "status": t.get("status"),
            "domain": t.get("domain"),
            "tt_source": t.get("tt_source"),
            "sla_status": t.get("sla_status"),
            "sla_deadline": t.get("sla_deadline"),
            "sla_remain_time": t.get("sla_remain_time"),
            "fault_duration_time": t.get("fault_duration_time"),
            "impacted_service": t.get("impacted_service"),
            "alarm_occur_time": t.get("alarm_occur_time"),
            "alarm_clear_time": t.get("alarm_clear_time"),
            "created_time": t.get("created_time"),
            "last_modified_time": t.get("last_modified_time"),
            "wo_no": t.get("wo_no"),
        },
        "people": people,
        "sla": sla,
        "time_spent": time_spent,
        "meta": {
            # 窗口用 time_spent 修正后的口径（终点取所有已知活动的最晚时间，
            # 而不是 last_modified_time —— 后者可能早于现场动作，会把现场等待切掉）
            "window": time_spent.get("window") or {
                "start": t.get("alarm_occur_time"), "end": t.get("last_modified_time")},
            # 总历时优先用 time_spent 的口径（告警 → 关单/末次修改），
            # 与页面「时间都花哪了」的合计保持一致；取不到再退回 durations。
            "total_seconds": (time_spent.get("total_seconds")
                              if time_spent.get("total_seconds") is not None
                              else durations.get("total_seconds")),
            "stage_count": len(timeline),
            "done_count": len(done_keys),
            "expected_count": sum(1 for s in STAGE_CONTRACT if s["expected"]),
            "missing_count": len(missing_actions),
            "deviation_count": len(deviations),
            "max_severity": deviations[0]["severity"] if deviations else None,
            "thresholds": {k: _fmt_h(v) for k, v in STAGE_THRESHOLDS.items()},
            "note": "时间点全部来自 eflow_tt 的 *_detail 原文解析与系统字段，source 字段标明出处",
        },
        "timeline": timeline,
        "expected_actions": expected_actions,
        "missing_actions": missing_actions,
        "deviations": deviations,
        "site_history": site_history,
        "dispatch_path": dispatch_path,
        "dispatch_analysis": dispatch_analysis,
        "assignment": assignment,
        "durations": durations,
        "wo_timeline": wo_timeline,
    }


# ---------- 时间归因 / SLA / 责任人 ----------

# 归因分段：把时间轴切成互不重叠的连续区间（覆盖全流程，不重不漏）
# 与原始 durations 的区别：durations 是"阶段时长"，这里是"时间花在谁手里"。
# 末段终点用"最后发生过的动作"，而不是写死 confirm —— 有些单没有 confirm 或缺
# 时间戳，写死会让分段之和远小于总历时，出现说不清去向的黑洞。
# 时间归因分段的**语义标签**：按"这一段等到的那个事件"给名字与责任方类型。
# 分段本身不再写死，而是由真实事件链相邻两跳的间隔生成（见 _build_time_spent）。
#
# 为什么改成事件驱动：旧实现固定 4 段（detect/assign/handle/close，端点全是文档流程
# 节点）。实测 TT202609220139 —— WO 派单 2026-09-22 16:53:51、现场到场 2026-09-23
# 08:44:25，中间**等现场响应 15.81 小时**；但 fo_process 被机器人秒填在 16:53:51，
# 于是这段等待全部挤进"提交 → 确认关单"，而窗口终点又取 last_modified_time
# （早于现场动作）→ 整段等待**落在窗口之外**，页面只显示"总历时 18 分钟"，
# 与时间轴上横跨 16 小时的记录直接矛盾。用户看到的正是这个。
_SEG_META = {
    "alarm_occur":    ("detect",      "告警发生",              "system"),
    "tt_create":      ("detect",      "TT 建单",               "system"),
    "dispatch_route": ("dispatch",    "派单路由决定",           "system"),
    "fo_accept":      ("assign",      "FO 接单",               "human"),
    "wo_dispatch":    ("dispatch",    "WO 派单",               "system"),
    "onsite_action":  ("onsite_wait", "现场出发",              "human"),
    "wo_step":        ("onsite_work", "现场步骤",              "human"),
    "alarm_clear":    ("clear",       "告警清除/自愈",          "system"),
    "fo_process":     ("handle",      "FO 提交关单",           "human"),
    "confirm":        ("close",       "确认关单",              "system"),
}
# 这些事件到达前的那段时间属于"在等人动手"，责任方取该事件的操作人
_WAIT_FOR_OPERATOR = ("fo_accept", "fo_process", "onsite_action", "wo_step")

# 分段的"阶段名"（给人和界面看的短标签，比"A → B"更好读）
_PHASE_LABEL = {
    "detect":      "建单时延",
    "assign":      "接单等待",
    "dispatch":    "派单",
    "onsite_wait": "现场响应等待",
    "onsite_work": "现场作业",
    "clear":       "告警清除",
    "handle":      "提交关单",
    "close":       "关单确认",
    "other":       "其他",
}


def _build_time_spent(t: Dict[str, Any], timeline: List[Dict[str, Any]],
                      durations: Dict[str, Any],
                      extra_wo_steps: Optional[List[Dict[str, Any]]] = None,
                      wo_timeline: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把"时间到底花在哪"算清楚：分段耗时 + 占比 + 责任人 + 是否超期。

    这是复盘最该被强调的一段——「总历时 12.2 小时」本身没有信息量，
    真正的问题是"其中 11.86 小时压在 NOC 手里没人动"。
    因此每段都带上 owner（谁该为这段时间负责）与是否超阈值。
    """
    by_key = {n["key"]: n for n in timeline}

    # ---------- 事件锚点：所有有确凿时间戳的真实事件，按时间排序 ----------
    # 分段 = 相邻两锚点的间隔。**任何一段等待都不可能被藏起来**，
    # 因为分段端点就是真实事件本身，而不是预先挑好的文档流程节点。
    events: List[Dict[str, Any]] = []
    for n in timeline:
        if not n.get("time_present"):
            continue
        dt = _parse_dt(n["time"])
        if dt:
            events.append({"dt": dt, "key": n["key"], "label": n["label"],
                           "operator": n.get("operator"), "actor": n.get("actor")})
    # WO 的现场步骤（出发/到场/离场/处理）也是真实事件，粒度比 onsite_action 更细
    for s in (extra_wo_steps or []):
        dt = _parse_dt(s.get("time"))
        if dt:
            events.append({"dt": dt, "key": "wo_step", "label": f"现场·{s.get('label')}",
                           "operator": s.get("operator"), "actor": "human"})
    events.sort(key=lambda e: e["dt"])

    # 同一秒发生的多个事件合并成一个锚点（如 tt_create + dispatch_route、
    # fo_accept + wo_dispatch + fo_process 常在同一秒），避免产生一串 0 秒分段。
    # 代表事件取**契约位置最靠前**的那个 —— 它才是"刚刚发生的那个动作"，
    # 用它给"到达该锚点前的那段等待"命名才准确。
    _contract_pos = {s["key"]: i for i, s in enumerate(STAGE_CONTRACT)}

    def _rep_of(members: List[Dict[str, Any]]) -> Dict[str, Any]:
        return min(members, key=lambda m: _contract_pos.get(m["key"], 99))

    anchors: List[Dict[str, Any]] = []
    for e in events:
        if anchors and (e["dt"] - anchors[-1]["dt"]).total_seconds() == 0:
            anchors[-1]["members"].append(e)
        else:
            anchors.append({"dt": e["dt"], "members": [e]})
    for a in anchors:
        a["rep"] = _rep_of(a["members"])
    _last_key = anchors[-1]["rep"]["key"] if anchors else None

    # ---------- 窗口 ----------
    # 起点 = 告警发生；终点 = **所有已知活动的最晚时间**。
    # ⚠ 旧实现终点只取 confirm_detail / last_modified_time。实测 TT202609220139：
    # last_modified_time 停在 2026-09-22 16:56，而现场动作在次日 08:44 ——
    # 窗口提前关闭，15.81 小时的现场等待整段落在窗口之外，
    # 页面显示"总历时 18 分钟"，与时间轴横跨 16 小时直接矛盾。
    _t_start = _parse_dt(t.get("alarm_occur_time"))
    _end_cands = [
        _detail_ts(t.get("confirm_detail")),
        _parse_dt(t.get("last_modified_time")),
        _parse_dt(t.get("alarm_clear_time")),
    ]
    if anchors:
        _end_cands.append(anchors[-1]["dt"])
    _t_end = max([d for d in _end_cands if d], default=None)
    if _t_start and _t_end and _t_end < _t_start:
        _t_end = _t_start
    total = _gap_seconds(_t_start, _t_end)

    # ---------- 分段 ----------
    segments: List[Dict[str, Any]] = []
    # 边 = (起点时刻, 终点时刻, 起点事件, 终点锚点)。起点事件用于给分段起名，
    # 不能写成"（上一跳）"—— 那样读不出这段等待是"从哪之后开始等的"。
    _edges: List[Tuple[Optional[datetime], Optional[datetime],
                       Optional[Dict[str, Any]], Optional[Dict[str, Any]]]] = []
    if anchors:
        if _t_start and _t_start < anchors[0]["dt"]:
            _edges.append((_t_start, anchors[0]["dt"], None, anchors[0]))
        for i in range(len(anchors) - 1):
            _edges.append((anchors[i]["dt"], anchors[i + 1]["dt"],
                           anchors[i]["rep"], anchors[i + 1]))
        # 尾段：最后一个锚点 → 窗口终点（单子还没关时，这段是真实存在的等待）
        if _t_end and _t_end > anchors[-1]["dt"]:
            _edges.append((anchors[-1]["dt"], _t_end, anchors[-1]["rep"], None))

    for ta, tb, src, dst in _edges:
        sec = _gap_seconds(ta, tb)
        if sec is None or sec < 0:
            continue
        # 目的事件的语义（首/尾段没有目的事件 → 按"延续到窗口边界"处理）
        if dst is not None:
            d_key = dst["rep"]["key"]
            d_op = dst["rep"].get("operator")
        else:
            d_key = _last_key if tb == _t_end else None
            d_op = None
        phase, d_short, owner_kind = _SEG_META.get(
            d_key, ("other", (dst["rep"]["label"] if dst else "—"), "system"))
        # 起点名：首段起点就是告警发生；否则用起点事件自己的名字
        src_short = (_SEG_META.get(src["key"], ("", src["label"], ""))[1]
                     if src else "告警发生")
        # 尾段终点不是事件而是窗口边界 → 标签要说实话
        if dst is None:
            label = f"{src_short} → 至今（未见关单）"
        else:
            label = f"{src_short} → {d_short}"

        # owner：这段时间在等谁。到达"等人动手"类事件时归该事件的操作人；
        # 其余归系统/流程。取不到操作人时如实写"未知"。
        if d_key in _WAIT_FOR_OPERATOR:
            owner = d_op or "（未记录操作人）"
            owner_kind = "human"
        elif d_key in ("alarm_occur", "tt_create", "dispatch_route", "wo_dispatch", "confirm"):
            owner = "系统/流程"
            owner_kind = "system"
        elif d_key == "alarm_clear":
            owner = "系统/自愈"
            owner_kind = "system"
        else:
            owner = d_op or "系统/流程"
        limit = STAGE_THRESHOLDS.get(d_key) if d_key else None
        over = bool(limit is not None and sec > limit)
        segments.append({
            "key": f"{phase}:{d_key or 'tail'}",
            "phase": phase,
            "phase_label": _PHASE_LABEL.get(phase, phase),
            "label": label,
            "owner": owner,
            "owner_kind": owner_kind,
            "seconds": sec,
            "pct": round(100.0 * sec / total, 1) if total else None,
            "from": ta.strftime("%Y-%m-%d %H:%M:%S") if ta else None,
            "to": tb.strftime("%Y-%m-%d %H:%M:%S") if tb else None,
            "threshold_s": limit,
            "over_threshold": over,
            "over_by_s": (sec - limit) if (over and limit is not None) else None,
        })


    # 分段之和与总数的差（时间轴跳之间未覆盖的空隙）——显式暴露，不假装严丝合缝
    seg_sum = sum(s["seconds"] for s in segments)
    unaccounted = (total - seg_sum) if total is not None else None

    segments.sort(key=lambda s: -s["seconds"])
    top = segments[0] if segments else None

    # 未覆盖区间显式暴露（不假装严丝合缝）。常见原因：
    # ① 单子没有 confirm（未走完流程）；② 现场处置时间落在分段端点之外。
    unaccounted_note = None
    if unaccounted and unaccounted > 60:
        unaccounted_note = (
            f"有 {_fmt_h(unaccounted)} 未被上述分段覆盖：通常是该单缺少 FO Accept / Confirm"
            "等中间节点，或现场步骤时间戳缺失，需人工核对原始记录"
        )

    # ---------- 阶段归并（把细分段按 phase 合并）----------
    # 事件驱动分段会产生较多细分段（一条单可能有 5~6 段），逐段看容易失焦。
    # 按 phase 归并后才是"NOC 手里多久、现场多久、系统多久"这种可比较的口径。
    _phase_acc: Dict[str, Dict[str, Any]] = {}
    for s in segments:
        ph = s.get("phase") or "other"
        e = _phase_acc.setdefault(ph, {
            "phase": ph,
            "phase_label": _PHASE_LABEL.get(ph, ph),
            "seconds": 0.0,
            "segments": 0,
            "owner_kind": s.get("owner_kind"),
        })
        e["seconds"] += float(s["seconds"])
        e["segments"] += 1
    phase_tot = sum(v["seconds"] for v in _phase_acc.values())
    phases = sorted(_phase_acc.values(), key=lambda x: -x["seconds"])
    for e in phases:
        e["seconds"] = round(e["seconds"], 1)
        e["pct"] = round(100.0 * e["seconds"] / phase_tot, 1) if phase_tot else None

    # ---------- NOC / 人工动作及时性 ----------
    # 直接回答"NOC 处理得及时不及时"：把每个**人工动作的等待时间**列出来，
    # 并与契约时限对比。机器动作（自动建单/自动关单）不在这里，避免稀释结论。
    # 关注点与「时间都花哪了」不同：那边问"时间在谁手里"，这边问"该动的时候动没动"。
    _by_key2 = {n["key"]: n for n in timeline}

    def _t_of(k: str) -> Optional[datetime]:
        n = _by_key2.get(k)
        return _parse_dt(n["time"]) if (n and n.get("time_present")) else None

    noc_actions: List[Dict[str, Any]] = []
    # (动作, 起算点, 结束点, 契约时限秒, 说明)
    # ⚠ onsite 不能复用 fo_accept→fo_process（那与 process 完全同值，实测踩过：
    #   两条记录都是 8.88h/2325 条，纯重复）。现场作业要按 WO 的
    #   到场 → 处理完成 两个真实步骤算，没有 WO 就不产出这一条。
    _ACT_SPECS = (
        ("accept",     "FO Accept 接单",  "tt_create",    "fo_accept",
         STAGE_THRESHOLDS.get("fo_accept"), "TT 建单后应尽快被接单"),
        ("process",    "FO Process 填报", "fo_accept",    "fo_process",
         STAGE_THRESHOLDS.get("fo_process"), "接单后应在时限内完成填报"),
    )
    for akey, alabel, a_from, a_to, limit_s, adesc in _ACT_SPECS:
        _a, _b = _t_of(a_from), _t_of(a_to)
        _wait = _gap_seconds(_a, _b)
        if _wait is None:
            continue
        noc_actions.append({
            "key": akey,
            "label": alabel,
            "from": _a.strftime("%Y-%m-%d %H:%M:%S") if _a else None,
            "to": _b.strftime("%Y-%m-%d %H:%M:%S") if _b else None,
            "wait_s": _wait,
            "threshold_s": limit_s,
            "over_threshold": bool(limit_s is not None and _wait > limit_s),
            "note": adesc,
        })

    # WO 侧的人工等待与现场作业：只有真存在 WO 时才看得到
    if wo_timeline:
        _wg = wo_timeline.get("gaps") or {}
        _aw = _wg.get("accept_wait_s")
        if _aw is not None:
            noc_actions.append({
                "key": "wo_accept_wait",
                "label": "WO 建单 → FE 接单",
                "from": None,
                "to": None,
                "wait_s": _aw,
                "threshold_s": None,
                "over_threshold": False,
                "note": "现场工单建好后多久才有人接手；偏大说明派单后无人响应",
            })
        _ons = _wg.get("onsite_s")
        if _ons is not None:
            noc_actions.append({
                "key": "onsite",
                "label": "现场作业（到场 → 处理完成）",
                "from": None,
                "to": None,
                "wait_s": _ons,
                "threshold_s": None,
                "over_threshold": False,
                "note": "只有存在 WO 且有到场/处理时间戳时才有值",
            })

    return {
        "total_seconds": total,
        "window": {
            "start": _t_start.strftime("%Y-%m-%d %H:%M:%S") if _t_start else None,
            "end": _t_end.strftime("%Y-%m-%d %H:%M:%S") if _t_end else None,
        },
        "segments": segments,
        "segments_sum_s": seg_sum,
        "unaccounted_s": unaccounted,
        "unaccounted_note": unaccounted_note,
        "bottleneck": top,
        "bottleneck_note": (
            f"全流程 {_fmt_h(total)} 中，{_fmt_h(top['seconds'])}（{top['pct']}%）"
            f"花在「{top.get('phase_label') or '—'}」（{top['label']}），"
            f"责任方：{top['owner'] or '-'}"
            + (f"，超出阈值 {_fmt_h(top['over_by_s'])}" if top.get("over_threshold") else "")
        ) if top else "无足够时间戳做归因",
        "over_threshold_count": sum(1 for s in segments if s["over_threshold"]),
        # 阶段归并：NOC 手里 / 现场 / 系统 各占多久
        "phases": phases,
        "phase_sum_s": round(phase_tot, 1),
        "human_actions": noc_actions,
        "human_over_threshold_count": sum(1 for a in noc_actions if a["over_threshold"]),
    }


def _build_sla(t: Dict[str, Any], t_create, t_accept, t_process, t_confirm,
               t_clear) -> Dict[str, Any]:
    """SLA 是否超期 + 超了多少 + 超在哪个动作上。

    口径：eflow_tt.sla_deadline 是系统给的期限（= 告警发生 + sla_time），
    sla_status 是系统判定（Pass/Failed），sla_remain_time 是结余（负数即超期）。
    这里额外回答"超期是谁造成的"——通常是"接单后长期无动作"。
    """
    deadline = _parse_dt(t.get("sla_deadline"))
    finished = t_confirm or _parse_dt(t.get("last_modified_time"))
    status = (t.get("sla_status") or "").strip() or None
    is_breached = (status or "").lower() == "failed"

    # 超期时长：以系统给的 sla_remain_time 为准（它是 eFlow 自己的口径）；
    # 只有它缺失时才用 deadline 与关单时间反算，并注明这是推算值。
    over_s = None
    over_source = None
    remain_s = _parse_sla_duration(t.get("sla_remain_time"))
    if remain_s is not None and remain_s < 0:
        over_s = -remain_s
        over_source = "eflow_tt.sla_remain_time"
    elif deadline and finished:
        od = _gap_seconds(deadline, finished)
        if od is not None and od > 0:
            over_s = od
            over_source = "按 sla_deadline 与关单时间推算"

    # 超期归因：Accept 之后到 Process 之间的等待，通常吃掉全部 SLA 余量
    wait_s = _gap_seconds(t_accept, t_process)
    return {
        "status": status,
        "is_breached": is_breached,
        "total_s": _parse_sla_duration(t.get("sla_time")),
        "total_text": t.get("sla_time"),
        "deadline": t.get("sla_deadline"),
        "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S") if finished else None,
        "over_seconds": over_s,
        "over_source": over_source,
        "over_text": (t.get("sla_remain_time") or "").strip() or None,
        "wait_in_hand_s": wait_s,
        "cause": (
            f"接单后到提交共 {_fmt_h(wait_s)}，SLA 期限 {t.get('sla_deadline') or '-'} 之内无人推进，"
            f"最终超期 {_fmt_h(over_s)}"
            if (is_breached and wait_s is not None and over_s)
            else ("SLA 已超期" if is_breached else "SLA 正常达成")
        ),
    }


def _parse_sla_duration(val) -> Optional[int]:
    """解析 eFlow 的 `0d8h0m` / `2d0h0m` 形式时长 → 秒。

    注意：三段的顺序固定是 d/h/m，且**可能缺段**（如 `8h0m`、`30m`）。
    因此不能直接用 group 位置硬取，要按"哪个单位匹配上了"来取。
    """
    if not val:
        return None
    m = re.match(r"^\s*(-?)\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*$",
                 str(val).strip())
    if not m or not any(m.group(i) for i in (2, 3, 4)):
        return None
    sign = -1 if m.group(1) else 1
    d = int(m.group(2)) if m.group(2) else 0
    h = int(m.group(3)) if m.group(3) else 0
    mi = int(m.group(4)) if m.group(4) else 0
    return sign * (d * 86400 + h * 3600 + mi * 60)


def _build_people(t: Dict[str, Any], timeline: List[Dict[str, Any]],
                  wo_record: Optional[Dict[str, Any]], create_by: str,
                  accept_by: str, process_by: str, confirm_by: str) -> Dict[str, Any]:
    """把每个动作的责任人汇总成"人"的视图，方便复盘直接点名。

    TT 单信息区必须能看到人：谁建的、谁接的、谁处理的、谁关的、当前在谁手里。
    """
    def _node(key):
        return next((n for n in timeline if n["key"] == key), None)

    wo_people: List[Dict[str, Any]] = []
    if wo_record:
        for f, label in (("accept_detail", "WO 接单"),
                         ("start_trip_detail", "出发"),
                         ("arrive_site_detail", "到场"),
                         ("process_detail", "现场处理"),
                         ("leave_site_detail", "离场"),
                         ("confirm_detail", "WO 确认")):
            raw = wo_record.get(f)
            # start_trip / arrive_site / leave_site 是 JSON 数组；其余是文本格式。
            # 两条解析路径都要走，否则实测 9,950 条现场动作会被整段漏掉。
            op, ts = _parse_wo_json_step(raw)
            if not (op or ts):
                op, ts = _parse_operator(raw or "")
            if op or ts:
                wo_people.append({"step": label, "operator": op or None,
                                  "time": ts or None, "source": f"eflow_wo.{f}"})

    # 建单人是否机器人：creator 可能是 'assign_rule'，也可能被拼成
    # 'assign_rule(assign_rule)'（_parse_operator 的结果），两种都要认。
    _creator_raw = (create_by or t.get("creator") or "")
    _AUTO_CREATORS = ("assign_rule", "fe_robot", "auto_robot", "system")
    creator_is_auto = any(a in _creator_raw.lower() for a in _AUTO_CREATORS)

    return {
        "creator": create_by or t.get("creator"),
        "creator_kind": "系统自动" if creator_is_auto else "人工",
        "fo_acceptor": accept_by or None,
        "fo_processer": process_by or None,
        "confirmer": confirm_by or None,
        "last_processer": t.get("last_processer"),
        "last_processer_group": (t.get("last_processer_group") or "").replace("\n", " ").strip() or None,
        # WO 侧的人（现场动作责任人）：有 WO 才有值，无 WO 为空列表
        "wo_no": t.get("wo_no"),
        "wo_creator": (wo_record or {}).get("creator"),
        "wo_creator_kind": (
            "系统自动" if str((wo_record or {}).get("creator") or "").lower()
            in ("fe_robot", "auto_robot", "system", "assign_rule")
            else ("人工" if (wo_record or {}).get("creator") else None)
        ),
        "wo_current_handler": (wo_record or {}).get("current_handler"),
        "wo_people": wo_people,
        # 逐动作责任人（时间轴上每个"实际做的动作"对应的人）
        "by_action": [
            {"action": n["label"], "operator": n.get("operator") or None,
             "time": n["time"], "actor": n["actor"], "done": n["time_present"],
             "evidence": n.get("evidence")}
            for n in timeline
        ],
    }


def _detail_ts(detail) -> Optional[datetime]:
    """从 *_detail 文本里取 Operation Time。"""
    m = re.search(r"Operation Time:([0-9\-: T]+)", str(detail or ""))
    if not m:
        return None
    return _parse_dt(m.group(1).strip())


def _parse_wo_json_step(raw) -> Tuple[str, str]:
    """解析 WO 的 JSON 数组型明细（start_trip / arrive_site / leave_site）。

    这些字段**不是** `Operation Time:` 文本，而是 JSON 数组：
    ``[{"opname":"Start Trip","operator":"FE_FE_133","opertime":...,"contactway":"231****65"}]``
    直接套 `_parse_operator` 会得到空值——实测 9,950 条 start_trip 全被漏掉。
    返回 (operator, time_str)；解析不出来就是空串。
    """
    if not raw:
        return "", ""
    s = str(raw).strip()
    if not s or s == "[]":
        return "", ""
    try:
        arr = json.loads(s)
    except Exception:
        # 少数记录可能是文本格式，回落到既有解析器
        return _parse_operator(s)
    if not isinstance(arr, list) or not arr:
        return "", ""
    item = arr[-1] if isinstance(arr[-1], dict) else {}
    op = str(item.get("operator") or "").strip()          # 形如 FE_FE_133（登录名）
    # candidateoperator 里带可读姓名，优先用它做展示（否则报告上只有工号，无法点名）
    name = ""
    try:
        cand = json.loads(str(item.get("candidateoperator") or "[]"))
        if isinstance(cand, list) and cand and isinstance(cand[0], dict):
            name = str(cand[0].get("name") or "").strip()
    except Exception:
        name = ""
    display = f"{name}({op})" if (name and op) else (op or name)
    ts = ""
    for k in ("operationtime", "operatetime", "opertime", "opTime", "time"):
        if item.get(k):
            ts = _norm_wo_time(item[k])
            if ts:
                break
    return display, ts


def _norm_wo_time(val) -> str:
    """WO JSON 明细里的时间可能是 epoch 毫秒、秒，或已格式化的字符串。"""
    if val in (None, ""):
        return ""
    s = str(val).strip()
    if re.fullmatch(r"\d{10,13}", s):
        try:
            n = int(s)
            if n < 10_000_000_000:
                n *= 1000
            return datetime.fromtimestamp(n / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""
    dt = _parse_dt(s)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _ms_to_str(val) -> Optional[str]:
    """history_alarm 的 alarmraisedtime/alarmclearedtime 是 epoch 毫秒。"""
    if val in (None, ""):
        return None
    try:
        n = int(float(val))
        # 兼容秒级
        if n < 10_000_000_000:
            n *= 1000
        return datetime.fromtimestamp(n / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(val)


def _fmt_h(sec: Optional[int]) -> str:
    """秒 → 人读时长（用于偏离说明，中英混排场景下保持中性写法）。"""
    if sec is None:
        return "-"
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec / 60:.0f}min"
    return f"{sec / 3600:.2f}h"


# ---------- WO（现场工单）生命周期时间轴 ----------
# 为什么需要它：单看 TT 的「FO 接单 → 提交关单」只是一个总时长，
# 无法回答"NOC/现场人员及时不及时"。WO 自己有完整生命周期：
#     建单 → FE 接单 → 出发 → 到场 → 处理 → 关单
# 把这几跳拆开，才能看到"工单建好后压了多久才有人接""路上花了多久"。
#
# 时间口径（实测确认，2026-09-23）：
#   - eflow_wo.created_time 与 eflow_tt.created_time 同时区（同一单相差约 2 秒），
#     因此**可以直接与 WO 的 *_detail / epoch 明细相减**。
#   - start_trip/arrive_site/leave_site 是 JSON 数组，operationtime 是 **epoch 毫秒**；
#     accept/process/confirm 是 "Operation Time:YYYY-M-D HH:MM:SS" 文本。
#   - 空数组 "[]" 表示该步未发生，不能当成"耗时 0"。

# WO 生命周期的跳（key, 标签, 取值来源）
_WO_STAGE_SPECS = (
    ("wo_create",    "工单建单",   "created_time"),
    ("wo_accept",    "FE 接单",    "accept_detail"),
    ("wo_start_trip", "出发",      "start_trip_detail"),
    ("wo_arrive",    "到场",      "arrive_site_detail"),
    ("wo_process",   "处理完成",   "process_detail"),
    ("wo_confirm",   "工单关单",   "confirm_detail"),
    ("wo_leave",     "离场",      "leave_site_detail"),
)


def _wo_stage_time(wo: Dict[str, Any], field: str) -> Optional[datetime]:
    """从 WO 记录的某个字段取时间点（兼容文本式与 JSON 毫秒式）。"""
    raw = wo.get(field)
    if field == "created_time":
        return _parse_dt(raw)
    if raw in (None, "", "[]"):
        return None
    s = str(raw).strip()
    # JSON 数组型（start_trip / arrive_site / leave_site）
    if s.startswith("["):
        _op, ts = _parse_wo_json_step(s)
        return _parse_dt(ts) if ts else None
    # 文本型（accept / process / confirm / closed）
    return _detail_ts(s)


def _wo_stage_operator(wo: Dict[str, Any], field: str) -> str:
    """从 WO 记录的某个字段取操作人（显示用）。"""
    raw = wo.get(field)
    if raw in (None, "", "[]"):
        return ""
    s = str(raw).strip()
    if s.startswith("["):
        op, _ts = _parse_wo_json_step(s)
        return op or ""
    op, _ts = _parse_operator(s)
    return op or ""


def build_wo_timeline(wo: Optional[Dict[str, Any]],
                      tt_accept: Optional[datetime] = None,
                      tt_process: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """把 WO 的生命周期拆成逐跳耗时，用于回答"现场处置及不及时"。

    返回结构：
      stages:   逐跳 [{key,label,time,time_present,operator,source,gap_from_prev_s}]
      gaps:     {accept_wait_s, trip_s, on_site_s, ...} 关键间隔（秒）
      summary:  人读结论，例如"工单建好后 7.53h 才有人接单"
      wo_span_s: 建单 → 关单（或最后一步）总跨度

    ``tt_accept`` / ``tt_process`` 是 TT 侧的接单与提交时间，用来对比
    "TT 提交了但 WO 还没到场"这类脱节情况；缺失则不参与对比。
    """
    if not wo:
        return None

    stages: List[Dict[str, Any]] = []
    for key, label, field in _WO_STAGE_SPECS:
        dt = _wo_stage_time(wo, field)
        stages.append({
            "key": key,
            "label": label,
            "time": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None,
            "time_present": dt is not None,
            "operator": _wo_stage_operator(wo, field),
            "source": f"eflow_wo.{field}",
            "_dt": dt,
        })

    # 按时间排序？不排 —— 保持流程顺序，让"越序"（如先到场后出发）自然可见。
    # gap 用"上一个有时间戳的跳"计算，缺失跳不参与。
    prev_dt: Optional[datetime] = None
    for st in stages:
        dt = st.pop("_dt")
        if dt is None:
            st["gap_from_prev_s"] = None
            continue
        st["gap_from_prev_s"] = _gap_seconds(prev_dt, dt)
        prev_dt = dt

    def _g(a_key: str, b_key: str) -> Optional[int]:
        a = next((s for s in stages if s["key"] == a_key and s["time"]), None)
        b = next((s for s in stages if s["key"] == b_key and s["time"]), None)
        if not (a and b):
            return None
        return _gap_seconds(_parse_dt(a["time"]), _parse_dt(b["time"]))

    create_dt = _wo_stage_time(wo, "created_time")
    accept_dt = _wo_stage_time(wo, "accept_detail")
    start_dt = _wo_stage_time(wo, "start_trip_detail")
    arrive_dt = _wo_stage_time(wo, "arrive_site_detail")
    process_dt = _wo_stage_time(wo, "process_detail")
    confirm_dt = _wo_stage_time(wo, "confirm_detail")
    leave_dt = _wo_stage_time(wo, "leave_site_detail")

    gaps = {
        # 工单建好后多久有人接 —— 最直接的"及时性"指标
        "accept_wait_s": _gap_seconds(create_dt, accept_dt),
        # 接单后多久出发
        "start_trip_s": _gap_seconds(accept_dt, start_dt),
        # 出发到到场（在路上）
        "travel_s": _gap_seconds(start_dt, arrive_dt),
        # 到场到处理完成（现场作业）
        "onsite_s": _gap_seconds(arrive_dt, process_dt),
        # 处理完成到工单关单
        "close_s": _gap_seconds(process_dt, confirm_dt),
        # 工单总跨度
        "total_s": _gap_seconds(create_dt, confirm_dt or leave_dt or process_dt),
    }

    # 声明式字段 travel_time（形如 "0d0h2m"）作为交叉验证
    travel_declared = _parse_sla_duration(wo.get("travel_time"))

    # TT 与 WO 的脱节：TT 已提交关单，但 WO 还没到场
    desync = None
    if tt_process and arrive_dt and _gap_seconds(arrive_dt, tt_process) is not None:
        if tt_process < arrive_dt:
            desync = "TT 已提交关单，但 WO 记录显示现场尚未到场"
    if tt_accept and accept_dt and _gap_seconds(tt_accept, accept_dt) is not None:
        if accept_dt < tt_accept:
            desync = desync or "WO 接单早于 TT 接单（TT 侧接单时间晚于现场已接单）"

    # 人读结论
    parts: List[str] = []
    if gaps["accept_wait_s"] is not None:
        parts.append(f"工单建好后 {_fmt_h(gaps['accept_wait_s'])} 才有人接单")
    if gaps["start_trip_s"] is not None:
        parts.append(f"接单到出发 {_fmt_h(gaps['start_trip_s'])}")
    if gaps["travel_s"] is not None:
        parts.append(f"在途 {_fmt_h(gaps['travel_s'])}")
    if gaps["onsite_s"] is not None:
        parts.append(f"到场到处理完成 {_fmt_h(gaps['onsite_s'])}")
    if gaps["close_s"] is not None:
        parts.append(f"处理完成到关单 {_fmt_h(gaps['close_s'])}")
    summary = "；".join(parts) if parts else None

    return {
        "wo_no": str(wo.get("wo_no") or "").strip() or None,
        "creator": str(wo.get("creator") or "").strip() or None,
        "status": str(wo.get("status") or "").strip() or None,
        "current_handler": str(wo.get("current_handler") or "").strip() or None,
        "stages": stages,
        "gaps": gaps,
        "travel_declared_s": travel_declared,
        "travel_mismatch": (
            travel_declared is not None and gaps["travel_s"] is not None
            and abs(travel_declared - gaps["travel_s"]) > 600
        ),
        "summary": summary,
        "desync": desync,
        "stage_present_count": sum(1 for s in stages if s["time_present"]),
    }


# ========================= NOC 操作人分析 =========================
# 设计要点（2026-09-23 下钻增强）：
#   1) 统计口径统一为 eflow_tt.alarm_occur_time（故障发生时间），
#      与「本月处理了多少单」的业务直觉一致；原 last_modified_time 口径会把
#      上月发生、本月才闭环的单算进本月。
#   2) 三层下钻全部由后端按同一份 WHERE 条件重查，保证「表格数字 = 下钻行数」：
#        NOC 行 → TT 明细（build_noc_tt_drilldown）
#        NOC 行 → 异常站点聚合（build_noc_site_drilldown）
#        TT 行  → 告警链路 / 根因一致性审计（复用 _fetch_alarm_chain / _infer_fault_domain）
#   3) 所有聚合都复用本模块既有的 _calc_durations / _infer_fault_domain，
#      避免出现「概览说错位、审计说没错位」的第二套判定逻辑。

# 夜班时段：Accept 操作时间落在 [22:00, 06:00) 视为夜班单（与前端展示口径一致）
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6

# 下钻切片 → 前端表格列的 dataIndex（顺序即列顺序）
NOC_DRILL_SLICES = ("all", "mismatch", "night", "sla_fail", "slow")


def _month_bounds(month: Optional[str]) -> Tuple[str, str, str]:
    """把 YYYY-MM 归一化为半开区间 [start_ts, end_ts)，并回传归一化后的 month。"""
    today = datetime.now()
    if not month or not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", month):
        month = f"{today.year:04d}-{today.month:02d}"
    year, mon = int(month[:4]), int(month[5:7])
    end_year, end_month = (year + 1, 1) if mon == 12 else (year, mon + 1)
    return (
        f"{year:04d}-{mon:02d}-01 00:00:00",
        f"{end_year:04d}-{end_month:02d}-01 00:00:00",
        month,
    )


def _parse_accept_time(fo_accept_detail) -> Optional[datetime]:
    """从 fo_accept_detail 文本里取 Accept 操作时间。"""
    m = re.search(r"Operation Time:([0-9\-: T]+)", str(fo_accept_detail or ""))
    if not m:
        return None
    return _parse_dt(m.group(1).strip())


def _is_night_accept(fo_accept_detail) -> bool:
    """Accept 时间是否落在夜班时段（22:00–06:00）。"""
    t = _parse_accept_time(fo_accept_detail)
    if not t:
        return False
    return t.hour >= NIGHT_START_HOUR or t.hour < NIGHT_END_HOUR


def _mismatch_of(tt_row: Dict[str, Any]) -> Tuple[bool, str]:
    """判定单张 TT 是否存在根因错位。

    复用模块既有口径：NOC 填报 root_cause vs 系统 alarm_reason_type / 告警码语义。
    返回 (是否错位, 错位类型)；错位类型取 'POWER<-TRM' / '其它' / ''（未错位）。

    与概览保持一致的三条排除项（NOC 填报本身不构成"根因判断"的豁免值）：
    Auto-recovery / Uknown / Force Majeure / Planned work 不计入错位。
    """
    rc = (tt_row.get("root_cause") or "").strip().upper()
    sys_rt = (tt_row.get("alarm_reason_type") or "").strip().upper()

    # 无告警链路语义时，用告警码静态语义表兜底（与 _infer_fault_domain 同源）
    if not sys_rt:
        sem = ALARM_CODE_SEMANTICS.get(_norm_alarm_id(tt_row.get("alarm_code")))
        sys_rt = ((sem or {}).get("reason_type") or "").strip().upper()

    if not rc:
        return False, ""
    if rc == "POWER" and sys_rt == "TRM":
        return True, "POWER<-TRM"
    if sys_rt and sys_rt != rc and rc not in ("Auto-recovery", "Uknown", "Force Majeure", "Planned work"):
        return True, "其它"
    return False, ""


def _noc_base_where(noc_filter: Optional[str]) -> Tuple[str, List[Any]]:
    """下钻与概览共用的基础过滤：有处理人 + 时间字段非空 +（可选）按人模糊匹配。"""
    clause = ""
    params: List[Any] = []
    if noc_filter:
        clause = " AND t.last_processer LIKE ?"
        params.append(f"%{noc_filter}%")
    return clause, params


def build_noc_analyst_report(
    month: Optional[str] = None,
    limit: int = 1000,
    noc_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """NOC 操作人分析报告（参考 FME 页面结构）。

    输入：
      - month: YYYY-MM（默认当月）
      - limit: 单人样本上限
      - noc_filter: 仅看某 NOC 操作人（可模糊匹配）

    输出：
      - meta: month/limit/扫描量/使用的口径字段/夜班时段
      - summary: NOC 总数 / 处理总数 / 平均错位率 / 平均处理时长 / SLA Pass 率
      - rows: 每位 NOC 一行（含错位率、各阶段平均时长、夜班单占比、SLA 率等）
      - red_flags: 关键告警（NOC 错位率 > 30% / 平均处理 > 12h / SLA Fail > 50%）
    """
    start_ts, end_ts, month = _month_bounds(month)

    with get_raw_connection() as conn:
        noc_clause, extra = _noc_base_where(noc_filter)
        params: List[Any] = [start_ts, end_ts, *extra]

        # 口径：alarm_occur_time（故障发生时间）落在本月
        rows = conn.execute(
            f"""SELECT t.tt_no, t.last_processer, t.last_processer_group,
                       t.alarm_code, t.alarm_id, t.site_id, t.site_name,
                       t.ticket_severity, t.root_cause, t.sub_root_cause,
                       t.alarm_reason_type, t.fo_accept_detail,
                       t.fo_process_detail, t.confirm_detail, t.create_detail,
                       t.status, t.sla_status, t.alarm_occur_time, t.alarm_clear_time,
                       t.last_modified_time
                FROM eflow_tt t
                WHERE t.last_processer IS NOT NULL AND t.last_processer <> ''
                  AND t.alarm_occur_time IS NOT NULL AND t.alarm_occur_time <> ''
                  AND t.alarm_occur_time >= ? AND t.alarm_occur_time < ?
                  {noc_clause}
                ORDER BY t.alarm_occur_time DESC
                LIMIT ?""",
            (*params, limit),
        ).fetchall()

        # 按 NOC 分组聚合
        per_noc: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            d = dict(r)
            noc = d["last_processer"]
            group = d.get("last_processer_group") or ""
            cur = per_noc.setdefault(noc, {
                "noc_name": noc,
                "group": group,
                "total": 0,
                "with_root_cause": 0,
                "mismatch_power_trm": 0,
                "mismatch_other": 0,
                "duration_sum_s": 0,
                "duration_count": 0,
                "night_total": 0,
                "sla_pass": 0,
                "sla_fail": 0,
                "sla_total": 0,
                "tt_sample": [],
            })

            cur["total"] += 1

            # 错位检测：统一走 _mismatch_of（与下钻切片同源）
            if (d.get("root_cause") or "").strip():
                cur["with_root_cause"] += 1
            is_mis, kind = _mismatch_of(d)
            if is_mis:
                if kind == "POWER<-TRM":
                    cur["mismatch_power_trm"] += 1
                else:
                    cur["mismatch_other"] += 1

            # 阶段时长
            durs = _calc_durations(d)
            tot = durs.get("total_seconds")
            if tot is not None and tot < 7 * 86400:  # 过滤异常值（>7 天视为误报）
                cur["duration_sum_s"] += tot
                cur["duration_count"] += 1

            # 夜班：Accept 时间在 22:00 - 06:00
            if _is_night_accept(d.get("fo_accept_detail")):
                cur["night_total"] += 1

            # SLA
            sla = (d.get("sla_status") or "").strip()
            if sla in ("Pass", "Failed"):
                cur["sla_total"] += 1
                if sla == "Pass":
                    cur["sla_pass"] += 1
                else:
                    cur["sla_fail"] += 1

            # 留 5 条样本便于下钻
            if len(cur["tt_sample"]) < 5:
                cur["tt_sample"].append({
                    "tt_no": d["tt_no"],
                    "site_name": d.get("site_name"),
                    "ticket_severity": d.get("ticket_severity"),
                    "root_cause": d.get("root_cause"),
                    "alarm_reason_type": d.get("alarm_reason_type"),
                    "sla_status": d.get("sla_status"),
                })

        rows_out = []
        for noc, c in per_noc.items():
            total = c["total"]
            mismatch = c["mismatch_power_trm"] + c["mismatch_other"]
            mismatch_pct = (100.0 * mismatch / c["with_root_cause"]) if c["with_root_cause"] else None
            avg_dur_h = (c["duration_sum_s"] / c["duration_count"] / 3600.0) if c["duration_count"] else None
            night_pct = (100.0 * c["night_total"] / total) if total else None
            sla_rate = (100.0 * c["sla_pass"] / c["sla_total"]) if c["sla_total"] else None
            sla_fail_pct = (100.0 * c["sla_fail"] / c["sla_total"]) if c["sla_total"] else None
            rows_out.append({
                "noc_name": noc,
                "group": c["group"],
                "total": total,
                "with_root_cause": c["with_root_cause"],
                "mismatch_count": mismatch,
                "mismatch_power_trm": c["mismatch_power_trm"],
                "mismatch_other": c["mismatch_other"],
                "mismatch_pct": round(mismatch_pct, 1) if mismatch_pct is not None else None,
                "avg_duration_h": round(avg_dur_h, 1) if avg_dur_h is not None else None,
                "night_total": c["night_total"],
                "night_pct": round(night_pct, 1) if night_pct is not None else None,
                "sla_pass": c["sla_pass"],
                "sla_fail": c["sla_fail"],
                "sla_total": c["sla_total"],
                "sla_pass_rate_pct": round(sla_rate, 1) if sla_rate is not None else None,
                "sla_fail_pct": round(sla_fail_pct, 1) if sla_fail_pct is not None else None,
                "tt_sample": c["tt_sample"],
            })

        rows_out.sort(key=lambda x: (x["mismatch_pct"] or 0, -(x["total"])), reverse=True)

        # summary
        n = len(rows_out)
        total_handled = sum(r["total"] for r in rows_out)
        avg_mismatch = (
            sum(r["mismatch_pct"] or 0 for r in rows_out if r["mismatch_pct"] is not None)
            / max(1, sum(1 for r in rows_out if r["mismatch_pct"] is not None))
        )
        avg_dur = (
            sum(r["avg_duration_h"] or 0 for r in rows_out if r["avg_duration_h"] is not None)
            / max(1, sum(1 for r in rows_out if r["avg_duration_h"] is not None))
        )
        overall_sla = (
            sum(r["sla_pass"] for r in rows_out)
            / max(1, sum(r["sla_total"] for r in rows_out))
        ) * 100 if sum(r["sla_total"] for r in rows_out) else None

        # 红旗
        red_flags = []
        for r in rows_out:
            reasons = []
            if (r["mismatch_pct"] or 0) >= 30:
                reasons.append(f"根因错位率 {r['mismatch_pct']}%（≥30%）")
            if (r["avg_duration_h"] or 0) >= 12:
                reasons.append(f"平均处理 {r['avg_duration_h']}h（≥12h）")
            if (r["sla_fail_pct"] or 0) >= 50:
                reasons.append(f"SLA Fail 率 {r['sla_fail_pct']}%（≥50%）")
            if reasons:
                red_flags.append({"noc_name": r["noc_name"], "reasons": reasons,
                                  "total": r["total"], "mismatch_pct": r["mismatch_pct"]})

    return {
        "meta": {
            "month": month,
            "limit": limit,
            "noc_filter": noc_filter,
            "scanned": len(rows),
            "time_field": "alarm_occur_time",
            "night_window": f"{NIGHT_START_HOUR:02d}:00-{NIGHT_END_HOUR:02d}:00",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "summary": {
            "noc_count": n,
            "total_handled": total_handled,
            "avg_mismatch_pct": round(avg_mismatch, 1) if n else None,
            "avg_duration_h": round(avg_dur, 1) if n else None,
            "overall_sla_pass_rate_pct": round(overall_sla, 1) if overall_sla is not None else None,
        },
        "rows": rows_out,
        "red_flags": red_flags,
    }


# ---------- 下钻（NOC → TT 明细） ----------

# 切片 → 前端列定义（key 即 dataIndex；zh/en 双语文案由前端 i18n 决定，这里只给列序）
_NOC_TT_DRILL_COLUMNS = [
    "tt_no", "site_name", "ticket_severity", "alarm_occur_time",
    "maintain_duration_h", "root_cause", "system_reason_type",
    "mismatch_type", "accept_time", "is_night", "sla_status", "status",
]


def build_noc_tt_drilldown(
    noc: str,
    month: Optional[str] = None,
    slice_: str = "all",
    limit: int = 20000,
) -> Dict[str, Any]:
    """某位 NOC 的 TT 明细下钻。

    切片（slice_）：
      - all      : 本月该 NOC 处理的全部 TT
      - mismatch : 根因错位（POWER<-TRM 或其它）
      - night    : 夜班单（Accept 落在 22:00–06:00）
      - sla_fail : SLA = Failed
      - slow     : 处理时长 ≥ 12h

    关键约束：WHERE 条件与 build_noc_analyst_report 完全一致（同一时间字段、
    同一 last_processer 精确匹配），因此下钻行数与表格数字天然对齐。
    切片在 Python 侧过滤 —— 错位/夜班依赖文本解析，无法下推到 SQL。
    """
    start_ts, end_ts, month = _month_bounds(month)
    slice_ = (slice_ or "all").strip().lower()
    if slice_ not in NOC_DRILL_SLICES:
        slice_ = "all"
    noc = (noc or "").strip()

    with get_raw_connection() as conn:
        rows = conn.execute(
            """SELECT t.tt_no, t.last_processer, t.last_processer_group,
                      t.alarm_code, t.site_id, t.site_name, t.ticket_severity,
                      t.root_cause, t.sub_root_cause, t.alarm_reason_type,
                      t.create_detail, t.fo_accept_detail, t.fo_process_detail,
                      t.confirm_detail, t.status, t.sla_status,
                      t.alarm_occur_time, t.alarm_clear_time, t.last_modified_time
               FROM eflow_tt t
               WHERE t.last_processer = ?
                 AND t.alarm_occur_time IS NOT NULL AND t.alarm_occur_time <> ''
                 AND t.alarm_occur_time >= ? AND t.alarm_occur_time < ?
               ORDER BY t.alarm_occur_time DESC
               LIMIT ?""",
            (noc, start_ts, end_ts, limit),
        ).fetchall()
        conn.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        durs = _calc_durations(d)
        tot_s = durs.get("total_seconds")
        dur_h = round(tot_s / 3600.0, 1) if (tot_s is not None and tot_s < 7 * 86400) else None
        is_mis, mis_kind = _mismatch_of(d)
        acc = _parse_accept_time(d.get("fo_accept_detail"))
        night = _is_night_accept(d.get("fo_accept_detail"))
        sla = (d.get("sla_status") or "").strip()
        sys_rt = (d.get("alarm_reason_type") or "").strip()
        if not sys_rt:
            sem = ALARM_CODE_SEMANTICS.get(_norm_alarm_id(d.get("alarm_code")))
            sys_rt = (sem or {}).get("reason_type") or ""

        rec = {
            "tt_no": d.get("tt_no"),
            "site_id": d.get("site_id"),
            "site_name": d.get("site_name"),
            "ticket_severity": d.get("ticket_severity"),
            "alarm_code": d.get("alarm_code"),
            "alarm_occur_time": d.get("alarm_occur_time"),
            "alarm_clear_time": d.get("alarm_clear_time"),
            "maintain_duration_h": dur_h,
            "root_cause": d.get("root_cause"),
            "sub_root_cause": d.get("sub_root_cause"),
            "system_reason_type": sys_rt or None,
            "mismatch_type": mis_kind if is_mis else None,
            "accept_time": acc.strftime("%Y-%m-%d %H:%M:%S") if acc else None,
            "is_night": bool(night),
            "sla_status": sla or None,
            "status": d.get("status"),
            "last_modified_time": d.get("last_modified_time"),
        }

        # 切片过滤
        if slice_ == "mismatch" and not is_mis:
            continue
        if slice_ == "night" and not night:
            continue
        if slice_ == "sla_fail" and sla != "Failed":
            continue
        if slice_ == "slow" and not (dur_h is not None and dur_h >= 12):
            continue
        out.append(rec)

    return {
        "meta": {
            "noc": noc,
            "month": month,
            "slice": slice_,
            "time_field": "alarm_occur_time",
            # 该人本月总量（切片前），供前端展示"x / total"上下文，避免误读为数据缺失
            "noc_total_in_month": len(rows),
            "matched": len(out),
            "limit": limit,
            "truncated": len(rows) >= limit,
        },
        "columns": list(_NOC_TT_DRILL_COLUMNS),
        "rows": out,
    }


# ---------- 下钻（NOC → 异常站点聚合） ----------

def build_noc_site_drilldown(
    noc: str,
    month: Optional[str] = None,
    only_abnormal: bool = True,
    limit: int = 20000,
) -> Dict[str, Any]:
    """某位 NOC 名下按站点聚合的异常视图。

    聚合维度：站点（site_id）。用于回答"这位 NOC 反复出问题的站点是哪几个"，
    是从"人"下钻到"站点"的关键一层。

    only_abnormal=True 时只保留至少命中一个异常的站点：
      - 存在根因错位，或
      - 存在 SLA Failed，或
      - 存在处理时长 ≥ 12h

    注意：limit 是该人本月的取样上限，必须显著大于单人月单量（实测单人月峰值约
    2000 单）。若被截断，站点聚合的 total 会小于概览 total，出现"同一月份两个
    数字对不上"的误导；因此默认给到 20000，并在 meta.truncated 中显式标注。
    """
    start_ts, end_ts, month = _month_bounds(month)
    noc = (noc or "").strip()

    with get_raw_connection() as conn:
        rows = conn.execute(
            """SELECT t.tt_no, t.site_id, t.site_name, t.alarm_code,
                      t.ticket_severity, t.root_cause, t.alarm_reason_type,
                      t.create_detail, t.fo_accept_detail, t.confirm_detail,
                      t.status, t.sla_status, t.alarm_occur_time
               FROM eflow_tt t
               WHERE t.last_processer = ?
                 AND t.alarm_occur_time IS NOT NULL AND t.alarm_occur_time <> ''
                 AND t.alarm_occur_time >= ? AND t.alarm_occur_time < ?
               ORDER BY t.alarm_occur_time DESC
               LIMIT ?""",
            (noc, start_ts, end_ts, limit),
        ).fetchall()
        conn.close()

    per_site: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        key = str(d.get("site_id") or d.get("site_name") or "UNKNOWN")
        cur = per_site.setdefault(key, {
            "site_id": d.get("site_id"),
            "site_name": d.get("site_name"),
            "total": 0,
            "mismatch_count": 0,
            "sla_fail": 0,
            "slow_count": 0,
            "night_count": 0,
            "dur_sum_s": 0,
            "dur_count": 0,
            "last_occur": None,
            "root_causes": {},
            "tt_nos": [],
        })
        cur["total"] += 1
        cur["tt_nos"].append(d.get("tt_no"))

        is_mis, _ = _mismatch_of(d)
        if is_mis:
            cur["mismatch_count"] += 1

        if (d.get("sla_status") or "").strip() == "Failed":
            cur["sla_fail"] += 1

        durs = _calc_durations(d)
        tot_s = durs.get("total_seconds")
        if tot_s is not None and tot_s < 7 * 86400:
            cur["dur_sum_s"] += tot_s
            cur["dur_count"] += 1
            if tot_s >= 12 * 3600:
                cur["slow_count"] += 1

        if _is_night_accept(d.get("fo_accept_detail")):
            cur["night_count"] += 1

        occ = d.get("alarm_occur_time")
        if occ and (cur["last_occur"] is None or str(occ) > str(cur["last_occur"])):
            cur["last_occur"] = occ

        rc = (d.get("root_cause") or "未填报").strip() or "未填报"
        cur["root_causes"][rc] = cur["root_causes"].get(rc, 0) + 1

    out: List[Dict[str, Any]] = []
    for key, c in per_site.items():
        avg_h = (c["dur_sum_s"] / c["dur_count"] / 3600.0) if c["dur_count"] else None
        has_abnormal = bool(c["mismatch_count"] or c["sla_fail"] or c["slow_count"])
        if only_abnormal and not has_abnormal:
            continue
        # 站点最高频根因（便于一眼看出该站反复出什么问题）
        top_rc = max(c["root_causes"].items(), key=lambda kv: kv[1])[0] if c["root_causes"] else None
        out.append({
            "site_id": c["site_id"],
            "site_name": c["site_name"],
            "total": c["total"],
            "mismatch_count": c["mismatch_count"],
            "sla_fail": c["sla_fail"],
            "slow_count": c["slow_count"],
            "night_count": c["night_count"],
            "avg_duration_h": round(avg_h, 1) if avg_h is not None else None,
            "top_root_cause": top_rc,
            "last_occur": c["last_occur"],
            "abnormal": has_abnormal,
            "tt_nos": c["tt_nos"][:50],
        })

    # 排序：异常重的靠前（错位 + SLA Fail + 慢单 加权），再按总量
    out.sort(key=lambda x: (
        -(x["mismatch_count"] * 2 + x["sla_fail"] * 2 + x["slow_count"]),
        -x["total"],
        str(x["site_name"] or ""),
    ))

    return {
        "meta": {
            "noc": noc,
            "month": month,
            "only_abnormal": only_abnormal,
            "scanned": len(rows),
            "site_count": len(out),
            "truncated": len(rows) >= limit,
        },
        "columns": [
            "site_name", "total", "mismatch_count", "sla_fail",
            "slow_count", "night_count", "avg_duration_h", "top_root_cause", "last_occur",
        ],
        "rows": out,
    }


# ---------- 下钻（单 TT → 告警链路 + 根因一致性审计） ----------

def build_noc_tt_detail(tt_no: str, noc: Optional[str] = None) -> Dict[str, Any]:
    """单张 TT 的下钻明细：告警链路 + 系统判定根因 vs NOC 填报根因。

    这是 NOC 分析页的最底层 —— 从"这个人"一路下钻到"这一单到底发生了什么"。
    权威依据链：history_alarm 告警链路 > eflow_tt.alarm_reason_type > NOC 人工填报。
    """
    tt_no = (tt_no or "").strip()
    with get_raw_connection() as conn:
        row = conn.execute(
            """SELECT tt_no, site_id, site_name, alarm_code, alarm_id, ticket_severity,
                      alarm_severity, status, root_cause, sub_root_cause, root_cause_description,
                      alarm_reason_type, last_processer, last_processer_group,
                      alarm_occur_time, alarm_clear_time, last_modified_time,
                      create_detail, fo_accept_detail, fo_process_detail, confirm_detail
               FROM eflow_tt WHERE tt_no = ?""",
            (tt_no,),
        ).fetchone()
        if not row:
            conn.close()
            return {"tt_no": tt_no, "found": False, "message": "未找到该工单"}

        t = dict(row)
        # 复用既有三级告警链路策略（exact / site_fallback / site_reason_fallback / none）
        alarm_rows, linkage = _fetch_alarm_chain(
            conn, tt_no, t.get("alarm_id"), t.get("site_id"),
            t.get("alarm_code"), t.get("alarm_reason_type"),
        )
        conn.close()

    # ---- 阶段时长 ----
    durs = _calc_durations(t)
    dur_h = None
    if durs.get("total_seconds") is not None and durs["total_seconds"] < 7 * 86400:
        dur_h = round(durs["total_seconds"] / 3600.0, 1)

    # ---- NOC 填报层 ----
    filed_by, filed_at = _parse_operator(t.get("fo_process_detail"))
    noc_filled = {
        "root_cause": t.get("root_cause"),
        "sub_root_cause": t.get("sub_root_cause"),
        "root_cause_description": t.get("root_cause_description"),
        "filed_by": filed_by or t.get("last_processer"),
        "filed_at": filed_at or t.get("last_modified_time"),
    }

    # ---- 告警链路明细 ----
    chain: List[Dict[str, Any]] = []
    for r in alarm_rows:
        d = dict(r)
        dom, basis = _infer_fault_domain(d.get("codename"), d.get("reason_type"), d.get("alarmcode"))
        chain.append({
            "alarmcode": d.get("alarmcode"),
            "codename": d.get("codename"),
            "reason_type": d.get("reason_type"),
            "alarm_source": d.get("alarm_source"),
            "restypename": d.get("restypename"),
            "alarmkey": d.get("alarmkey"),
            "fault_domain": dom,
            "basis": basis,
            "family": _alarm_family(d.get("alarmcode"), d.get("codename"), d.get("reason_type")),
        })

    # ---- 系统判定层（优先取能推断出故障域的一条）----
    system_judged = None
    if chain:
        best = next((c for c in chain if c["fault_domain"] != "UNKNOWN"), chain[0])
        system_judged = {
            "fault_domain": best["fault_domain"],
            "basis": best["basis"],
            "alarmcode": best["alarmcode"],
            "codename": best["codename"],
            "reason_type": best["reason_type"],
            "linkage": linkage,
            "alarm_count": len(chain),
            "distinct_codes": sorted({str(c["alarmcode"]) for c in chain}),
            "distinct_names": sorted({str(c["codename"]) for c in chain}),
        }
    elif t.get("alarm_reason_type"):
        system_judged = {
            "fault_domain": t.get("alarm_reason_type"),
            "basis": "eflow_tt.alarm_reason_type（系统字段，无告警链路佐证）",
            "alarmcode": t.get("alarm_code"),
            "codename": None,
            "reason_type": t.get("alarm_reason_type"),
            "linkage": linkage,
            "alarm_count": 0,
        }

    # ---- 一致性判定（与本模块 _mismatch_of 同源，避免两套结论）----
    is_mis, mis_kind = _mismatch_of(t)
    consistency: Optional[bool]
    note: str
    confidence = "low"
    if system_judged and system_judged.get("fault_domain") in ("POWER", "TRM", "OTHER"):
        confidence = ("high" if linkage == "exact"
                      else "medium" if linkage in ("site_fallback", "site_reason_fallback")
                      else "low")
    if is_mis:
        consistency = False
        note = ("NOC 填报 %s，但告警链路/系统语义指向 %s，判定为根因错位（%s）。"
                % (t.get("root_cause") or "空", (system_judged or {}).get("fault_domain") or "UNKNOWN", mis_kind))
    elif not (t.get("root_cause") or "").strip():
        consistency = None
        note = "NOC 未填报根因（root_cause 为空），无法比对。"
    elif not system_judged:
        consistency = None
        note = "缺少可用告警链路，无法比对（告警可能已滚出 history_alarm 窗口）。"
    else:
        consistency = True
        note = "NOC 填报根因与告警链路一致。"

    accept_t = _parse_accept_time(t.get("fo_accept_detail"))

    return {
        "tt_no": tt_no,
        "found": True,
        "noc": noc or t.get("last_processer"),
        "site": {"site_id": t.get("site_id"), "site_name": t.get("site_name")},
        "ticket": {
            "ticket_severity": t.get("ticket_severity"),
            "alarm_severity": t.get("alarm_severity"),
            "alarm_code": t.get("alarm_code"),
            "status": t.get("status"),
            "sla_status": t.get("sla_status"),
            "alarm_occur_time": t.get("alarm_occur_time"),
            "alarm_clear_time": t.get("alarm_clear_time"),
            "accept_time": accept_t.strftime("%Y-%m-%d %H:%M:%S") if accept_t else None,
            "is_night": _is_night_accept(t.get("fo_accept_detail")),
            "maintain_duration_h": dur_h,
            "durations": durs,
        },
        "noc_filled": noc_filled,
        "system_judged": system_judged,
        "alarm_chain": chain,
        "consistency": consistency,
        "mismatch_type": mis_kind if is_mis else "",
        "confidence": confidence,
        "note": note,
    }


# ==================== 里程碑时间轴批量聚：时间都花哪了 ====================
# 背景（2026-09-23）：单张 TT 的 `build_tt_timeline` 已经能给出
# 「里程碑时间轴 / 应做·实做 / 偏离清单 / 时间归因」，但那是**单看一单**。
# 本次新增的是**管理视角的批量聚合**：把本月全部 TT 的时间轴合起来算，
# 回答"时间到底浪费在哪个环节、哪些人、哪些动作没做"。
#
# 设计要点：
#   1) 逐单复用 `build_tt_timeline`，**不重写一套判定**，避免两条结论打架。
#   2) 聚合只做统计（percentile / 计数 / 求和），不改判任何单子的结论。
#   3) 结果按 month 落磁盘缓存（月份收口后数据不再变），避免每次进页重算
#      —— 全量约 2000+ 单，每单都要解析 *_detail 文本，重算要数十秒。
#   4) 缓存文件不含任何凭据；仅本模块读写的 JSON。

import os as _os
import statistics as _statistics
from pathlib import Path as _Path

# 缓存目录：backend/data/tt_timeline_cache（运行时可重建，已随 backend/data 忽略）
_TIMELINE_CACHE_DIR = _Path(__file__).resolve().parents[2] / "data" / "tt_timeline_cache"
# 缓存版本号：聚合口径变更时必须 +1，否则旧缓存会被当成新口径数据读出
_TIMELINE_CACHE_VERSION = 5


def _timeline_cache_path(month: str) -> _Path:
    return _TIMELINE_CACHE_DIR / f"noc_timeline_{month}_v{_TIMELINE_CACHE_VERSION}.json"


def _pct(sorted_vals: List[float], q: float) -> Optional[float]:
    """取分位数（q=0.5 即中位数）。列表须已升序；空列表返回 None。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _stat_block(vals: List[float]) -> Dict[str, Any]:
    """一组秒数 → 计数/均值/P50/P90/最大。全部转成秒，前端自行格式化。"""
    if not vals:
        return {"count": 0, "avg_s": None, "p50_s": None, "p90_s": None, "max_s": None}
    s = sorted(vals)
    return {
        "count": len(s),
        "avg_s": round(sum(s) / len(s), 1),
        "p50_s": round(_pct(s, 0.5) or 0, 1),
        "p90_s": round(_pct(s, 0.9) or 0, 1),
        "max_s": round(s[-1], 1),
    }


def build_noc_timeline_agg(
    month: Optional[str] = None,
    limit: int = 20000,
    noc_filter: Optional[str] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """本月全部 TT 的「里程碑时间轴」批量聚合 —— 时间都花哪了 + 动作偏离。

    输入：
      - month: YYYY-MM（默认当月）
      - limit: 取样上限（必须显著大于单人月单量，防止静默截断）
      - noc_filter: 只看某个 NOC 操作人（精确匹配 last_processer，与下钻同源）
      - use_cache: 是否使用磁盘缓存（默认使用；口径变更时改版本号）

    输出（全部为纯统计，可回溯到单 TT 详情）：
      - meta: 口径字段 / 月份 / 扫描量 / 覆盖单量 / 缓存命中情况 / 阈值
      - stage_stats:   每个里程碑的耗时分布（P50/P90/最大）→ "哪一跳最慢"
      - segment_stats: 时间归因分段（告警→建单→接单→提交→关单）占比 → "时间花在谁手里"
      - bottleneck_rank: 瓶颈环节排行（按平均耗时降序）
      - deviation_stats: 偏离类型分布（kind × severity 计数）
      - missing_stats:  契约缺失动作排行（哪个必需动作最常没做）
      - wo_stats:       WO 派单情况 + **应派未派清单**（本次重点）
      - noc_stats:      按 NOC 归因（每人的平均总历时/瓶颈段/偏离数/未派WO数）
      - tickets:        逐单精简结果（供表格与下钻；含 tt_no 可再下钻）
    """
    import time as _time

    start_ts, end_ts, month = _month_bounds(month)
    cache_file = _timeline_cache_path(month)

    # noc_filter 参与缓存键：不同筛选不能共用同一份缓存
    filtered = bool(noc_filter and noc_filter.strip())
    if use_cache and not filtered and cache_file.exists():
        try:
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
            # 版本/口径自校验：文件名带版本号，但人工改过口径却忘了升版本时，
            # 仍可能出现"结构性过期"（缺新字段）。这里校验必需键，缺则重算，
            # 避免把旧口径数据当成新口径展示 —— 这类静默错误比慢更危险。
            _required = ("stage_stats", "segment_stats", "deviation_stats",
                         "missing_stats", "wo_stats", "noc_stats", "tickets",
                         "wo_gap_stats", "human_action_stats", "phase_stats")
            _missing_keys = [k for k in _required if k not in raw]
            if _missing_keys:
                logger.warning("[noc_timeline] 缓存缺少键 %s，改为重算", _missing_keys)
            else:
                raw.setdefault("meta", {})["cache_hit"] = True
                raw["meta"]["cache_file"] = str(cache_file.name)
                return raw
        except Exception:
            logger.warning("[noc_timeline] 缓存读取失败，改为重算: %s", cache_file, exc_info=True)

    t0 = _time.time()

    with get_raw_connection() as conn:
        noc_clause, extra = _noc_base_where(None)
        # 与概览端点**完全一致**的 WHERE（AGENTS.md 3.1b 铁律）：
        # 同一 alarm_occur_time 月窗口 + last_processer 非空
        rows = conn.execute(
            f"""SELECT t.tt_no
                FROM eflow_tt t
                WHERE t.last_processer IS NOT NULL AND t.last_processer <> ''
                  AND t.alarm_occur_time IS NOT NULL AND t.alarm_occur_time <> ''
                  AND t.alarm_occur_time >= ? AND t.alarm_occur_time < ?
                  {noc_clause}
                ORDER BY t.alarm_occur_time DESC
                LIMIT ?""",
            (start_ts, end_ts, *extra, limit),
        ).fetchall()
        tt_nos = [(dict(r).get("tt_no") or "").strip() for r in rows]
        tt_nos = [x for x in tt_nos if x]

        # 概览同口径的总量，用于暴露截断
        total_in_month = conn.execute(
            """SELECT COUNT(*) AS c FROM eflow_tt t
               WHERE t.last_processer IS NOT NULL AND t.last_processer <> ''
                 AND t.alarm_occur_time IS NOT NULL AND t.alarm_occur_time <> ''
                 AND t.alarm_occur_time >= ? AND t.alarm_occur_time < ?""",
            (start_ts, end_ts),
        ).fetchone()
        total_in_month = int(dict(total_in_month).get("c") or 0) if total_in_month else 0

    # ---------- 逐单解析 ----------
    stage_secs: Dict[str, List[float]] = {}
    seg_secs: Dict[str, List[float]] = {}
    seg_labels: Dict[str, str] = {}
    dev_counter: Dict[str, Dict[str, Any]] = {}
    missing_counter: Dict[str, Dict[str, Any]] = {}
    wo_expected = 0
    wo_dispatched = 0
    no_wo_rows: List[Dict[str, Any]] = []
    over_threshold: Dict[str, int] = {}
    tickets: List[Dict[str, Any]] = []
    per_noc: Dict[str, Dict[str, Any]] = {}
    # WO 生命周期各跳耗时（用于"现场处置及不及时"的月度分布）
    wo_stage_secs: Dict[str, List[float]] = {}
    wo_gap_secs: Dict[str, List[float]] = {}
    wo_gap_labels: Dict[str, str] = {}
    wo_stage_labels: Dict[str, str] = {}
    wo_with_timeline = 0
    # 阶段归并累计（NOC 手里 / 现场 / 系统 各占多久）
    phase_secs: Dict[str, List[float]] = {}
    phase_labels2: Dict[str, str] = {}
    # 人工动作等待时长（NOC 及时性）
    human_act_secs: Dict[str, List[float]] = {}
    human_act_labels: Dict[str, str] = {}
    human_act_limits: Dict[str, Optional[int]] = {}
    human_act_over: Dict[str, int] = {}
    parsed = 0
    parse_failed = 0

    for tt_no in tt_nos:
        try:
            rep = build_tt_timeline(tt_no)
        except Exception:
            parse_failed += 1
            logger.warning("[noc_timeline] 解析失败 %s", tt_no, exc_info=True)
            continue
        if not rep.get("found"):
            parse_failed += 1
            continue
        parsed += 1

        tl = rep.get("timeline") or []
        meta = rep.get("meta") or {}
        tsc = rep.get("time_spent") or {}
        devs = rep.get("deviations") or []
        miss = rep.get("missing_actions") or []
        t = rep.get("ticket") or {}

        # ---- NOC 归属 ----
        # ⚠ 不能用 eflow_tt.last_processer：那是**最后处理人**（多为 FE 关单人），
        # 实测本月 2295 单里有 2016 单落在 FE Robot(fe_robot)，若按它归因，
        # 整张"NOC 分析"表会变成"FE 分析表"，完全跑偏。
        # NOC 的正确归属是 **Accept（接单）/ Process（填报）这两跳的操作人**，
        # 与时间轴上 fo_accept / fo_process 节点的 operator 同源。
        noc_name = ""
        for n in tl:
            if n.get("key") in ("fo_accept", "fo_process") and (n.get("operator") or "").strip():
                noc_name = n["operator"].strip()
                break
        if not noc_name:
            _people = rep.get("people") or {}
            noc_name = (_people.get("fo_acceptor") or _people.get("fo_processer") or "-").strip() or "-"

        cur = per_noc.setdefault(noc_name, {
            "noc_name": noc_name,
            "total": 0,
            "total_seconds_sum": 0.0,
            "total_seconds_count": 0,
            "deviation_count": 0,
            "critical_count": 0,
            "no_wo_count": 0,
            "missing_count": 0,
            "worst_segment": None,
            "worst_segment_s": 0.0,
        })
        cur["total"] += 1

        total_s = meta.get("total_seconds")
        if isinstance(total_s, (int, float)) and total_s >= 0:
            cur["total_seconds_sum"] += float(total_s)
            cur["total_seconds_count"] += 1

        # 里程碑跳间隔
        for n in tl:
            gap = n.get("gap_from_prev_s")
            if isinstance(gap, (int, float)) and gap >= 0:
                stage_secs.setdefault(n.get("key") or "?", []).append(float(gap))

        # 时间归因分段（谁手里花的）
        for s in tsc.get("segments") or []:
            k = s.get("key") or "?"
            seg_labels[k] = s.get("label") or k
            sec = s.get("seconds")
            if isinstance(sec, (int, float)) and sec >= 0:
                seg_secs.setdefault(k, []).append(float(sec))
                if cur["worst_segment_s"] < float(sec):
                    cur["worst_segment_s"] = float(sec)
                    cur["worst_segment"] = seg_labels[k]
            if s.get("over_threshold"):
                over_threshold[k] = over_threshold.get(k, 0) + 1

        # 偏离
        cur["deviation_count"] += len(devs)
        for d in devs:
            code = d.get("code") or "?"
            e = dev_counter.setdefault(code, {
                "code": code,
                "kind": d.get("kind"),
                "severity": d.get("severity"),
                "label": d.get("label"),
                "count": 0,
                "sample_tts": [],
            })
            e["count"] += 1
            # 留 15 条样本便于下钻：5 条时高发偏离（如根因错位 1289 单）几乎全是
            # 同一批人/同一站点，看不出分布，用户会以为"样本就这些"。
            if len(e["sample_tts"]) < 15:
                e["sample_tts"].append(tt_no)
            if d.get("severity") == "critical":
                cur["critical_count"] += 1

        # 缺失动作
        cur["missing_count"] += len(miss)
        for m in miss:
            k = m.get("key") or "?"
            e = missing_counter.setdefault(k, {
                "key": k, "label": m.get("label"), "actor": m.get("actor"),
                "count": 0, "sample_tts": [],
            })
            e["count"] += 1
            if len(e["sample_tts"]) < 5:
                e["sample_tts"].append(tt_no)

        # WO 派单（本次重点）
        # ⚠ build_tt_timeline 的 `wo` 块恒为 None（未组装），WO 号实际在
        # dispatch_path.wo_no；时间轴上 wo_dispatch 跳是否有点也是同一事实。
        dp = rep.get("dispatch_path") or {}
        wo_no = (dp.get("wo_no") or "").strip()
        wo_node = next((n for n in tl if n.get("key") == "wo_dispatch"), None)
        has_wo = bool(wo_no) or bool((wo_node or {}).get("time_present"))
        # "应派"判据与偏离 4 完全同源：直接看是否命中 no_wo_for_critical_outage
        codes = {d.get("code") for d in devs}
        should_wo = "no_wo_for_critical_outage" in codes
        if should_wo:
            wo_expected += 1
            cur["no_wo_count"] += 1
            no_wo_rows.append({
                "tt_no": tt_no,
                "noc_name": noc_name,
                "site_name": (rep.get("site") or {}).get("site_name"),
                "site_id": (rep.get("site") or {}).get("site_id"),
                "alarm_code": t.get("alarm_code"),
                "ticket_severity": t.get("ticket_severity"),
                "alarm_occur_time": t.get("alarm_occur_time"),
                "alarm_clear_time": t.get("alarm_clear_time"),
                "total_seconds": total_s,
                "filed_root_cause": (rep.get("noc_filled") or {}).get("root_cause"),
                "dispatch_category": dp.get("category"),
                "bottleneck": (tsc.get("bottleneck") or {}).get("label"),
                "bottleneck_seconds": (tsc.get("bottleneck") or {}).get("seconds"),
            })
        if has_wo:
            wo_dispatched += 1

        # ---- WO 生命周期各跳（现场处置及时性）----
        # 只在真有 WO 时统计；缺失跳不进分布（否则会把"没做"混进"做得快"）
        wt = rep.get("wo_timeline") or None
        if wt:
            wo_with_timeline += 1
            for st in wt.get("stages") or []:
                k = st.get("key") or "?"
                wo_stage_labels[k] = st.get("label") or k
                g = st.get("gap_from_prev_s")
                if isinstance(g, (int, float)):
                    wo_stage_secs.setdefault(k, []).append(float(g))
            for gk, gv in (wt.get("gaps") or {}).items():
                if isinstance(gv, (int, float)) and gv >= 0:
                    wo_gap_secs.setdefault(gk, []).append(float(gv))
            wo_gap_labels.update({
                "accept_wait_s": "WO 建单 → FE 接单",
                "start_trip_s": "FE 接单 → 出发",
                "travel_s": "出发 → 到场（在途）",
                "onsite_s": "到场 → 处理完成（现场作业）",
                "close_s": "处理完成 → 工单关单",
                "total_s": "WO 建单 → 关单（总跨度）",
            })

        # ---- 阶段归并 ----
        for ph in tsc.get("phases") or []:
            pk = ph.get("phase") or "?"
            phase_labels2[pk] = ph.get("phase_label") or pk
            pv = ph.get("seconds")
            if isinstance(pv, (int, float)) and pv >= 0:
                phase_secs.setdefault(pk, []).append(float(pv))

        # ---- 人工动作等待（NOC 及时性）----
        for a in tsc.get("human_actions") or []:
            k = a.get("key") or "?"
            w = a.get("wait_s")
            if not isinstance(w, (int, float)) or w < 0:
                continue
            human_act_labels[k] = a.get("label") or k
            human_act_limits[k] = a.get("threshold_s")
            human_act_secs.setdefault(k, []).append(float(w))
            if a.get("over_threshold"):
                human_act_over[k] = human_act_over.get(k, 0) + 1

        # 逐单精简结果（供表格/下钻）
        tickets.append({
            "tt_no": tt_no,
            "noc_name": noc_name,
            "site_name": (rep.get("site") or {}).get("site_name"),
            "ticket_severity": t.get("ticket_severity"),
            "alarm_occur_time": t.get("alarm_occur_time"),
            "total_seconds": total_s,
            "done_count": meta.get("done_count"),
            "stage_count": meta.get("stage_count"),
            "missing_count": len(miss),
            "deviation_count": len(devs),
            "max_severity": meta.get("max_severity"),
            "has_wo": has_wo,
            "should_wo": should_wo,
            "bottleneck": (tsc.get("bottleneck") or {}).get("label"),
            "bottleneck_seconds": (tsc.get("bottleneck") or {}).get("seconds"),
            "bottleneck_owner": (tsc.get("bottleneck") or {}).get("owner"),
            "over_threshold_count": tsc.get("over_threshold_count"),
        })

    # ---------- 汇总 ----------
    # 里程碑：按契约顺序输出，保证前端行序稳定
    stage_stats = []
    for st in STAGE_CONTRACT:
        k = st["key"]
        vals = stage_secs.get(k) or []
        blk = _stat_block(vals)
        blk.update({
            "key": k,
            "label": st["label"],
            "actor": st["actor"],
            "expected": st["expected"],
            "threshold_s": STAGE_THRESHOLDS.get(k),
        })
        stage_stats.append(blk)

    segment_stats = []
    total_all = sum(sum(v) for v in seg_secs.values())
    for k, vals in seg_secs.items():
        blk = _stat_block(vals)
        ssum = sum(vals)
        blk.update({
            "key": k,
            "label": seg_labels.get(k, k),
            "sum_s": round(ssum, 1),
            "pct": round(100.0 * ssum / total_all, 1) if total_all else None,
            "over_threshold_count": over_threshold.get(k, 0),
            "threshold_s": STAGE_THRESHOLDS.get(
                {"detect": "tt_create", "assign": "fo_accept",
                 "handle": "fo_process", "close": "confirm"}.get(k) or "", None),
        })
        segment_stats.append(blk)
    segment_stats.sort(key=lambda x: -(x.get("sum_s") or 0))

    deviation_stats = sorted(dev_counter.values(), key=lambda x: -x["count"])
    missing_stats = sorted(missing_counter.values(), key=lambda x: -x["count"])

    # ---------- WO 生命周期分布（现场处置及时性）----------
    # 顺序固定为业务顺序，不按耗时排序 —— 读的人要按流程看"哪一跳卡住"
    _WO_GAP_ORDER = ("accept_wait_s", "start_trip_s", "travel_s", "onsite_s",
                     "close_s", "total_s")
    wo_gap_stats = []
    for gk in _WO_GAP_ORDER:
        vals = wo_gap_secs.get(gk)
        if not vals:
            continue
        blk = _stat_block(vals)
        blk.update({
            "key": gk,
            "label": wo_gap_labels.get(gk, gk),
            "sum_s": round(sum(vals), 1),
        })
        wo_gap_stats.append(blk)

    wo_stage_stats = []
    for st in _WO_STAGE_SPECS:
        k = st[0]
        vals = wo_stage_secs.get(k)
        if not vals:
            continue
        blk = _stat_block(vals)
        blk.update({"key": k, "label": st[1]})
        wo_stage_stats.append(blk)

    # ---------- 阶段归并汇总 ----------
    _PHASE_ORDER = ("detect", "assign", "dispatch", "onsite_wait", "onsite_work",
                    "clear", "handle", "close", "other")
    _phase_total = sum(sum(v) for v in phase_secs.values())
    phase_stats = []
    for pk in _PHASE_ORDER:
        vals = phase_secs.get(pk)
        if not vals:
            continue
        blk = _stat_block(vals)
        ssum = sum(vals)
        blk.update({
            "phase": pk,
            "phase_label": phase_labels2.get(pk, pk),
            "sum_s": round(ssum, 1),
            "pct": round(100.0 * ssum / _phase_total, 1) if _phase_total else None,
        })
        phase_stats.append(blk)
    phase_stats.sort(key=lambda x: -(x.get("sum_s") or 0))

    # ---------- 人工动作及时性（NOC 侧）----------
    _ACT_ORDER = ("accept", "process", "onsite", "wo_accept_wait")
    human_action_stats = []
    for ak in _ACT_ORDER:
        vals = human_act_secs.get(ak)
        if not vals:
            continue
        blk = _stat_block(vals)
        lim = human_act_limits.get(ak)
        blk.update({
            "key": ak,
            "label": human_act_labels.get(ak, ak),
            "threshold_s": lim,
            "over_threshold_count": human_act_over.get(ak, 0),
            "over_threshold_pct": round(100.0 * human_act_over.get(ak, 0) / len(vals), 1),
        })
        human_action_stats.append(blk)


    # 最多缺 8 条未派 WO 明细（按总历时降序，先看拖最久的）
    no_wo_rows.sort(key=lambda r: -(r.get("total_seconds") or 0))

    # NOC 归因：按未派 WO 数、再按平均总历时降序
    noc_list = []
    for v in per_noc.values():
        cnt = v["total_seconds_count"]
        noc_list.append({
            **v,
            "avg_total_seconds": round(v["total_seconds_sum"] / cnt, 1) if cnt else None,
            "avg_deviation": round(v["deviation_count"] / v["total"], 2) if v["total"] else None,
        })
    noc_list.sort(key=lambda x: (-x["no_wo_count"], -(x["avg_total_seconds"] or 0)))

    elapsed = round(_time.time() - t0, 1)
    truncated = total_in_month > len(tt_nos)

    result: Dict[str, Any] = {
        "meta": {
            "month": month,
            "time_field": "alarm_occur_time",
            "window": {"start": start_ts, "end": end_ts},
            "scanned": len(tt_nos),
            "parsed": parsed,
            "parse_failed": parse_failed,
            "total_in_month": total_in_month,
            "truncated": truncated,
            "limit": limit,
            "noc_filter": noc_filter,
            "expected_stage_count": sum(1 for s in STAGE_CONTRACT if s["expected"]),
            "stage_count": len(STAGE_CONTRACT),
            "thresholds": {k: _fmt_h(v) for k, v in STAGE_THRESHOLDS.items()},
            "elapsed_s": elapsed,
            "cache_hit": False,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": ("时间点与动作全部来自单张 TT 的程序化复盘（build_tt_timeline），"
                     "口径与「TT 复盘报告」完全一致；source 字段可回溯原始 *_detail 文本"),
        },
        "stage_stats": stage_stats,
        "segment_stats": segment_stats,
        "bottleneck_rank": sorted(
            [s for s in segment_stats if s.get("avg_s") is not None],
            key=lambda x: -(x.get("avg_s") or 0),
        ),
        "deviation_stats": deviation_stats,
        "missing_stats": missing_stats,
        "wo_stats": {
            "dispatched": wo_dispatched,
            "should_dispatch": wo_expected,
            "missing_dispatch": len(no_wo_rows),
            "dispatch_rate_pct": (round(100.0 * wo_dispatched / parsed, 1) if parsed else None),
        },
        "no_wo_tickets": no_wo_rows,
        "noc_stats": noc_list,
        "tickets": tickets,
        # 现场处置及时性（WO 生命周期）
        "wo_gap_stats": wo_gap_stats,
        "wo_stage_stats": wo_stage_stats,
        "wo_with_timeline": wo_with_timeline,
        # 阶段归并（NOC 手里 / 现场 / 系统 各占多久）
        "phase_stats": phase_stats,
        # NOC 人工动作及时性
        "human_action_stats": human_action_stats,
    }

    if use_cache and not filtered:
        try:
            _TIMELINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            # 缓存里同样写入真实耗时，便于判断是否需要调 limit
            cache_file.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.warning("[noc_timeline] 缓存写入失败: %s", cache_file, exc_info=True)

    return result
