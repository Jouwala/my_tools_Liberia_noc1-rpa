# -*- coding: utf-8 -*-
"""eFlow 全流程查询（eFlow Process Flow）
=========================================
用户输入**告警**（alarm_id / aid / 告警码）或 **TT 单号**，输出该单在 eFlow 里的
**全流程图**：规则驱动的状态机（应该怎么走）+ 该单实际走过的路径（实际走到哪、卡在哪）。

设计原则：**不产生第二套判定**
------------------------------
* 规则目录：复用 `backend.services.tt_postmortem._load_rule_catalog()` /
  `_load_push_rules()` / `_detect_ocrule_columns()` / `_qcol()`
  —— 与「NOC 分析（noc_analyst）」「单 TT 复盘报告」同源，避免"流程图说 A、复盘说 B"。
* 实际路径：复用 `build_tt_timeline()` 的里程碑口径（alarm_occur → create → accept →
  process → confirm → closed）与 `_infer_dispatch_path()` 的派单成因判定。
* 关联链路：`eflow_tt.wo_no` = `eflow_wo.wo_no`（实测 13385 条命中）；
  告警经 `realtime_alarm.tt_id` / `history_alarm.tt_id` 指回 TT。

流程节点（state machine）
-------------------------
eFlow TT 的生命周期由 `operation_type` 字段承载（取值实测见下），
规则表 `ocrule_details` 的 `triggerStep` 指明**哪个步骤由哪条规则接管**：

    告警 → TT 建单 → autoDispatch → FOAccept / BOAccept
         → FOProcess / BOProcess / ThirdAccept / ThirdProcess → Confirm → Closed

对外接口
--------
* `query_flow(keyword, lang)`   → dict，见 docstring（告警或 TT 单号均可）
* `build_flow_graph(...)`       → 规则状态机 + 实际路径高亮（节点/边）
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 状态机定义：eFlow TT 全流程的规范节点
# ---------------------------------------------------------------------------
# key            : 节点唯一标识（前端 ECharts 节点 id）
# label_zh/en    : 展示名
# trigger_steps  : 该节点在 ocrule_details.triggerStep 里对应的取值
#                  （用于把规则挂到节点上；同名步骤有多个变体故用列表）
# stage          : 泳道分组，用于图的分层排布
_FLOW_NODES: List[Dict[str, Any]] = [
    {
        "key": "alarm",
        "label_zh": "告警发生",
        "label_en": "Alarm Raised",
        "stage": "upstream",
        "trigger_steps": [],
    },
    {
        "key": "create",
        "label_zh": "TT 建单",
        "label_en": "TT Created",
        "stage": "create",
        "trigger_steps": ["ticketSeverity_autoCreateTT", "GroupDefault_Create"],
    },
    {
        "key": "autoDispatch",
        "label_zh": "自动派单",
        "label_en": "Auto Dispatch",
        "stage": "dispatch",
        "trigger_steps": ["autoDispatch"],
    },
    {
        "key": "FOAccept",
        "label_zh": "FO 接单",
        "label_en": "FO Accept",
        "stage": "fo",
        "trigger_steps": ["FOAccept", "CustomTitle_FOAccept", "GroupConfig_FOAccept"],
    },
    {
        "key": "FOProcess",
        "label_zh": "FO 处理",
        "label_en": "FO Process",
        "stage": "fo",
        "trigger_steps": ["FOProcess", "GroupConfig_FOProcess", "GroupDefault_FOProcess"],
    },
    {
        "key": "BOAccept",
        "label_zh": "BO 接单",
        "label_en": "BO Accept",
        "stage": "bo",
        "trigger_steps": ["BOAccept", "CustomTitle_BOAccept", "GroupConfig_BOAccept"],
    },
    {
        "key": "BOProcess",
        "label_zh": "BO 处理",
        "label_en": "BO Process",
        "stage": "bo",
        "trigger_steps": ["BOProcess", "GroupConfig_BOProcess", "GroupDefault_BOProcess"],
    },
    {
        "key": "ThirdAccept",
        "label_zh": "第三方接单",
        "label_en": "3rd Party Accept",
        "stage": "third",
        "trigger_steps": ["ThirdAccept", "GroupConfig_ThirdAccept", "GroupDefault_ThirdAccept"],
    },
    {
        "key": "ThirdProcess",
        "label_zh": "第三方处理",
        "label_en": "3rd Party Process",
        "stage": "third",
        "trigger_steps": ["ThirdProcess", "GroupConfig_ThirdProcess", "GroupDefault_ThirdProcess"],
    },
    {
        "key": "Confirm",
        "label_zh": "确认",
        "label_en": "Confirm",
        "stage": "confirm",
        "trigger_steps": ["Confirm", "GroupConfig_Confirm"],
    },
    {
        "key": "Closed",
        "label_zh": "关单",
        "label_en": "Closed",
        "stage": "closed",
        "trigger_steps": [],
    },
]

# 规范流程的连线（规则未显式给出「推送路径」时的兜底主干）
_FLOW_EDGES: List[Tuple[str, str]] = [
    ("alarm", "create"),
    ("create", "autoDispatch"),
    ("autoDispatch", "FOAccept"),
    ("autoDispatch", "BOAccept"),
    ("FOAccept", "FOProcess"),
    ("BOAccept", "BOProcess"),
    ("FOProcess", "ThirdAccept"),
    ("ThirdAccept", "ThirdProcess"),
    ("FOProcess", "Confirm"),
    ("BOProcess", "Confirm"),
    ("ThirdProcess", "Confirm"),
    ("Confirm", "Closed"),
]

# WO（工单）子流程节点：TT 派生出 WO 后，WO 有自己的现场流程
_WO_NODES: List[Dict[str, Any]] = [
    {"key": "wo_create", "label_zh": "WO 建单", "label_en": "WO Created", "stage": "wo",
     "trigger_steps": []},
    {"key": "wo_accept", "label_zh": "WO 接单", "label_en": "WO Accept", "stage": "wo",
     "trigger_steps": ["GroupConfig_Accept"]},
    {"key": "wo_process", "label_zh": "WO 处理", "label_en": "WO Process", "stage": "wo",
     "trigger_steps": ["GroupConfig_Process"]},
    {"key": "wo_confirm", "label_zh": "WO 确认", "label_en": "WO Confirm", "stage": "wo",
     "trigger_steps": ["GroupConfig_Confirm"]},
    {"key": "wo_closed", "label_zh": "WO 关单", "label_en": "WO Closed", "stage": "wo",
     "trigger_steps": []},
]

# eFlow 规则类型 → 规则在流程里扮演的角色（用于图例与节点说明）
_RULE_ROLE: Dict[str, Dict[str, str]] = {
    "ttLevelRule": {"zh": "定级（决定 P1~P4）", "en": "Severity (P1-P4)"},
    "ttDispatchRule": {"zh": "自动派单", "en": "Auto dispatch"},
    "ttPushOrderRule": {"zh": "推单（下一步流转）", "en": "Push order (next step)"},
    "ttGroupConfigRule": {"zh": "处理组配置", "en": "Handler group config"},
    "ttGroupDefaultRule": {"zh": "兜底处理组", "en": "Default handler group"},
    "ttAutoCloseRule": {"zh": "自动关单", "en": "Auto close"},
    "ttCustomTitleRule": {"zh": "定制单据标题", "en": "Custom title"},
    "woGroupConfigRule": {"zh": "WO 处理组配置", "en": "WO handler group"},
    "woGroupDefaultRule": {"zh": "WO 兜底处理组", "en": "WO default group"},
    "woPushOrderRule": {"zh": "WO 推单", "en": "WO push order"},
    "woAutoCloseRule": {"zh": "WO 自动关单", "en": "WO auto close"},
}

_TT_RE = re.compile(r"^TT\d{6,}$", re.I)


def _s(v: Any) -> str:
    """NaN / None / 'nan' → 空串（与 tt_batch_severity._s 同口径）。"""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat", "null", "empty") else s


def _norm_code(v: Any) -> str:
    """告警码归一：去掉浮点尾巴（'99933.0' → '99933'）。"""
    s = _s(v)
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _norm_alarm_id(v: Any) -> str:
    """告警 id 归一（PG 里 alarm_id 常为 '1764213625912.0'）。"""
    s = _s(v)
    if s.endswith(".0"):
        s = s[:-2]
    return s


# ---------------------------------------------------------------------------
# 规则目录（复用 tt_postmortem 的实现，绝不另写一套列名适配）
# ---------------------------------------------------------------------------
def _load_rules(conn) -> List[Dict[str, Any]]:
    """读取 ocrule_details 里 TT/WO 相关的**全部**规则。

    为什么不用 `tt_postmortem._load_rule_catalog()`：
    后者是「派单归因」专用，只取 ttPushOrderRule / ttDispatchRule /
    ttGroupConfigRule / ttGroupDefaultRule 四类、且不返回 `推送路径` 与 `工单类型`
    —— 而流程图恰恰需要**全部 11 类** TT/WO 规则（定级/自动关闭/定制标题…）
    以及 `推送路径`（形如 `FOAccept,2>FOProcess,8>FOProcess`）来画边。

    但**列名适配逻辑必须同源**：这里复用它的 `_detect_ocrule_columns()` 与
    `_qcol()`，避免 PG(camelCase) / SQLite(小写) 两套列名各写一份适配
    （`_qcol` 的注释里记录了 PG 折叠标识符导致规则查询静默失败的踩坑历史）。
    """
    try:
        from backend.services.tt_postmortem import _detect_ocrule_columns, _qcol
    except Exception:
        logger.warning("[eflow_flow] 无法导入 tt_postmortem 列适配器", exc_info=True)
        return []

    cols = _detect_ocrule_columns(conn)
    available = cols.get("_columns") or set()
    if not available:
        return []

    # canonical -> 候选真实列名（两方言兼容）
    wanted = [
        ("id", ("ID", "id", "Rule Id", "rule_id")),
        ("rule_name", ("ruleName", "Rule Name", "rule_name")),
        ("rule_type", ("ruleType", "Rule Type", "rule_type")),
        ("wo_type", ("woType", "WO Type", "wo_type", "工单类型")),
        ("trigger_step", ("triggerStep", "Trigger Step", "trigger_step", "触发步骤")),
        ("status", ("status", "Status", "状态")),
        ("priority", ("rulePriority", "Rule Priority", "rule_priority", "优先级")),
        ("handler_name", ("targetHandlerName", "Target Handler Name", "目标处理人")),
        ("description", ("description", "Description", "描述")),
        ("update_time", ("updateTime", "Update Time", "update_time")),
        ("push_path", ("推送路径", "pushPath", "push_path", "Push Path")),
    ]
    select_fields: List[str] = []
    for canonical, candidates in wanted:
        c = next((x for x in candidates if x in available), None)
        if c:
            select_fields.append(f"{_qcol(c)} AS {canonical}")

    if not select_fields or not any(f.endswith("AS rule_type") for f in select_fields):
        return []

    sql = f"SELECT {', '.join(select_fields)} FROM ocrule_details"
    try:
        rows = conn.execute(sql).fetchall()
    except Exception:
        logger.warning("[eflow_flow] ocrule_details 查询失败: %s", sql, exc_info=True)
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        rt = _s(d.get("rule_type"))
        out.append({
            "id": _s(d.get("id")),
            "name": _s(d.get("rule_name")),
            "rule_type": rt,
            "role_zh": _RULE_ROLE.get(rt, {}).get("zh", rt),
            "role_en": _RULE_ROLE.get(rt, {}).get("en", rt),
            "wo_type": _s(d.get("wo_type")),
            "trigger_step": _s(d.get("trigger_step")),
            "status": _s(d.get("status")),
            "priority": _s(d.get("priority")),
            "handler": _s(d.get("handler_name")),
            "description": _s(d.get("description")),
            "update_time": _s(d.get("update_time")),
            "push_path": _s(d.get("push_path")),
        })
    return out


# ---------------------------------------------------------------------------
# 定位：告警 → TT，或 TT → 自身
# ---------------------------------------------------------------------------
def _find_tt_by_alarm(conn, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    """按告警 id / aid / 告警码定位 TT。

    优先用告警表的 tt_id 直连；查不到再退回 eflow_tt.alarm_id / alarm_code 匹配。

    ⚠ 关键坑（实测）：`eflow_tt.alarm_id` 存的是**浮点文本** `'1764213625912.0'`，
    而告警表的 `id` 是整数 `1764213625912`。直接
    `CAST(id AS TEXT) = '1764213625912.0'` 永远为 0 行。
    因此两侧都做「去浮点尾巴」归一后比较（不依赖方言的 CAST 行为）。
    """
    kw = _norm_alarm_id(keyword)
    if not kw:
        return []
    hits: List[Dict[str, Any]] = []

    # ① 告警表（realtime 优先，其次 history）里的 tt_id
    for tbl in ("realtime_alarm", "history_alarm"):
        try:
            rows = conn.execute(
                f"SELECT tt_id, aid, id, alarmcode, site_name, alarmraisedtime "
                f"FROM {tbl} "
                f"WHERE (CAST(aid AS TEXT) = ? OR CAST(id AS TEXT) = ? OR CAST(alarmcode AS TEXT) = ?) "
                f"LIMIT ?",
                (kw, kw, kw, limit),
            ).fetchall()
            for r in rows:
                d = dict(r)
                tt = _s(d.get("tt_id"))
                # tt_id 实测存在字面量 'empty' 脏值，必须排除
                if tt and tt.lower() not in ("empty", "-", "none"):
                    hits.append({
                        "tt_no": tt,
                        "via": f"{tbl}.tt_id",
                        "alarm_id": _norm_alarm_id(d.get("id")),
                        "site_name": _s(d.get("site_name")),
                    })
        except Exception:
            logger.debug("[eflow_flow] 告警表 %s 查询失败", tbl, exc_info=True)
        if hits:
            break

    # ② 退回 eflow_tt 自身字段（两侧归一后比较）
    if not hits:
        try:
            rows = conn.execute(
                "SELECT tt_no, alarm_id, alarm_code, site_name, status, operation_type "
                "FROM eflow_tt "
                "WHERE alarm_id IS NOT NULL AND alarm_id <> '' "
                "ORDER BY created_time DESC LIMIT 2000"
            ).fetchall()
            for r in rows:
                d = dict(r)
                if (_norm_alarm_id(d.get("alarm_id")) == kw
                        or _norm_code(d.get("alarm_code")) == kw):
                    hits.append({
                        "tt_no": _s(d.get("tt_no")),
                        "via": "eflow_tt.alarm_id/alarm_code",
                        "alarm_id": _norm_alarm_id(d.get("alarm_id")),
                        "site_name": _s(d.get("site_name")),
                    })
                    if len(hits) >= limit:
                        break
        except Exception:
            logger.warning("[eflow_flow] eflow_tt 按告警查询失败", exc_info=True)

    # 去重（同一 TT 可能多条重复告警）
    seen: set = set()
    uniq: List[Dict[str, Any]] = []
    for h in hits:
        if h["tt_no"] in seen:
            continue
        seen.add(h["tt_no"])
        uniq.append(h)
    return uniq


def _find_by_alarm_code(conn, code: str, limit: int = 50) -> List[Dict[str, Any]]:
    """按告警码找最近的 TT（用户只给一个码时用）。"""
    code = _norm_code(code)
    if not code:
        return []
    try:
        rows = conn.execute(
            "SELECT tt_no, alarm_code, alarm_id, site_name, status, operation_type, "
            "       created_time, ticket_severity "
            "FROM eflow_tt WHERE CAST(alarm_code AS TEXT) = ? "
            "ORDER BY created_time DESC LIMIT ?",
            (code, limit),
        ).fetchall()
    except Exception:
        logger.warning("[eflow_flow] 按告警码查询失败", exc_info=True)
        return []
    return [{
        "tt_no": _s(dict(r).get("tt_no")),
        "alarm_code": _norm_code(dict(r).get("alarm_code")),
        "alarm_id": _norm_alarm_id(dict(r).get("alarm_id")),
        "site_name": _s(dict(r).get("site_name")),
        "status": _s(dict(r).get("status")),
        "operation_type": _s(dict(r).get("operation_type")),
        "created_time": _s(dict(r).get("created_time")),
        "ticket_severity": _s(dict(r).get("ticket_severity")),
    } for r in rows]


# ---------------------------------------------------------------------------
# 单 TT 的流程状态
# ---------------------------------------------------------------------------
def _tt_flow_state(conn, tt_no: str) -> Optional[Dict[str, Any]]:
    """取单 TT 的流程相关字段 + 关联 WO + 关联告警。"""
    try:
        row = conn.execute(
            "SELECT tt_no, wo_no, status, operation_type, ticket_severity, alarm_code, "
            "       alarm_id, alarm_type, alarm_severity, site_name, site_id, "
            "       current_handler, creator, ticket_type, domain, ne_name, moc, "
            "       alarm_occur_time, alarm_clear_time, created_time, last_modified_time, "
            "       actual_completion_time, fault_recovery_time, fault_duration_time, "
            "       sla_status, sla_deadline, root_cause, root_cause_description, "
            "       process_description, description, title, down_site_count, "
            "       fo_accept_detail, fo_process_detail, confirm_detail, "
            "       create_detail, closed_detail "
            "FROM eflow_tt WHERE tt_no = ?",
            (tt_no,),
        ).fetchone()
    except Exception:
        logger.warning("[eflow_flow] 读取 TT %s 失败", tt_no, exc_info=True)
        return None
    if not row:
        return None

    t = dict(row)

    # 关联 WO（子流程）
    wo: Optional[Dict[str, Any]] = None
    if _s(t.get("wo_no")):
        try:
            w = conn.execute(
                "SELECT wo_no, tt_no, status, operation_step, current_handler, creator, "
                "       created_time, last_modified_time, actual_finish_time, "
                "       accept_detail, start_trip_detail, arrive_site_detail, "
                "       leave_site_detail, process_detail, confirm_detail, closed_detail "
                "FROM eflow_wo WHERE wo_no = ?",
                (_s(t["wo_no"]),),
            ).fetchone()
            if w:
                wo = dict(w)
        except Exception:
            logger.debug("[eflow_flow] 读取 WO 失败", exc_info=True)

    # 关联告警（该 TT 由哪些告警触发）
    # 两条路径都要走：
    #   ① 告警表 tt_id 直接指回 TT（realtime 表只有 30 行有值，history 表较全）；
    #   ② 用 TT 自己的 alarm_id 与告警表 id/aid 归一后比对（tt_id 为 'empty' 脏值时靠这条）。
    #
    # ⚠ 关键坑（实测）：realtime_alarm(149 列) 与 history_alarm(173 列) **列集不同**——
    #   `alarmclearedtime` 只在 history 有、`clearstatename` 只在 realtime 有。
    #   给两表用同一条 SELECT 会抛 UndefinedColumn，被 except 吞掉后表现为
    #   「关联告警永远是 0 条」。因此这里只选**两表都存在**的列。
    alarms: List[Dict[str, Any]] = []
    tt_no_v = _s(tt_no)
    wanted_alarm_id = _norm_alarm_id(t.get("alarm_id"))

    # 两表交集列（探针实测）
    _COMMON_COLS = ("id, aid, alarmcode, site_name, alarmraisedtime, "
                    "perceivedseverityname, alarm_title, alarmtypename, codename, "
                    "reason_type, neip, mename")

    def _collect(tbl: str, rows) -> None:
        for r in rows:
            d = dict(r)
            alarms.append({
                "table": tbl,
                "id": _norm_alarm_id(d.get("id")),
                "aid": _s(d.get("aid")),
                "alarm_code": _norm_code(d.get("alarmcode")),
                "site_name": _s(d.get("site_name")),
                "raised": _s(d.get("alarmraisedtime")),
                "severity": _s(d.get("perceivedseverityname")),
                "title": _s(d.get("alarm_title")),
                "alarm_type_name": _s(d.get("alarmtypename")),
                "codename": _s(d.get("codename")),
                "reason_type": _s(d.get("reason_type")),
                "ne_ip": _s(d.get("neip")),
                "ne_name": _s(d.get("mename")),
            })

    for tbl in ("realtime_alarm", "history_alarm"):
        try:
            rows = conn.execute(
                f"SELECT {_COMMON_COLS} FROM {tbl} WHERE tt_id = ? LIMIT 20",
                (tt_no_v,),
            ).fetchall()
            _collect(tbl, rows)
        except Exception:
            logger.warning("[eflow_flow] 读取 %s 关联告警失败", tbl, exc_info=True)

    # ② 若靠 tt_id 一条都没拿到，用 alarm_id 归一比对补
    if not alarms and wanted_alarm_id:
        for tbl in ("realtime_alarm", "history_alarm"):
            try:
                rows = conn.execute(
                    f"SELECT {_COMMON_COLS} FROM {tbl} "
                    f"WHERE REPLACE(CAST(id AS TEXT), '.0', '') = ? "
                    f"   OR REPLACE(CAST(aid AS TEXT), '.0', '') = ? LIMIT 20",
                    (wanted_alarm_id, wanted_alarm_id),
                ).fetchall()
                _collect(tbl, rows)
            except Exception:
                logger.warning("[eflow_flow] 按 alarm_id 读取 %s 失败", tbl, exc_info=True)
            if alarms:
                break

    return {"tt": t, "wo": wo, "alarms": alarms}


def _match_step(raw: str) -> Optional[str]:
    """把 operation_type / status 的原始取值映射到规范节点 key。

    实测取值形如：
        'FOProcess(WO RCA to FO Confirm)' → FOProcess
        'Waiting for FO Process'          → FOProcess
        'Closed'                          → Closed
        'ThirdAccept'                     → ThirdAccept
    """
    v = _s(raw)
    if not v:
        return None
    if v.lower().startswith("closed"):
        return "Closed"
    # 去掉 "Waiting for " 前缀与括号里的补充说明，取主步骤
    core = re.sub(r"^waiting\s+for\s+", "", v, flags=re.I)
    core = core.split("(")[0].strip()
    # 去空格后与节点 key 做不区分大小写匹配
    compact = re.sub(r"\s+", "", core).lower()
    for n in _FLOW_NODES:
        if n["key"].lower() == compact:
            return n["key"]
    # FO Process / BO Process 这类带空格的
    for n in _FLOW_NODES:
        if n["key"].lower() == compact.replace("process", "process"):
            return n["key"]
    return None


def _match_wo_step(raw: str) -> Optional[str]:
    """WO 的 operation_step → WO 子流程节点 key。"""
    v = _s(raw)
    if not v:
        return None
    compact = re.sub(r"\s+", "", v).lower()
    mapping = {
        "accept": "wo_accept",
        "accepted": "wo_accept",
        "process": "wo_process",
        "confirm": "wo_confirm",
        "closed": "wo_closed",
        "starttrip": "wo_process",
        "arrivesite": "wo_process",
        "leavesite": "wo_process",
        "bonpoprocess": "wo_process",
    }
    return mapping.get(compact)


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------
def build_flow_graph(lang: str = "zh") -> Dict[str, Any]:
    """返回**规则驱动**的流程骨架（不含具体单子）。

    节点来自 `_FLOW_NODES`，并挂上 ocrule_details 里 triggerStep 对应的规则；
    边优先取规则「推送路径」的显式定义，缺失时用主干兜底。
    """
    rules: List[Dict[str, Any]] = []
    try:
        with get_raw_connection() as conn:
            rules = _load_rules(conn)
    except Exception:
        logger.warning("[eflow_flow] 读取规则失败", exc_info=True)

    # triggerStep → 规则列表
    by_step: Dict[str, List[Dict[str, Any]]] = {}
    for r in rules:
        step = r["trigger_step"]
        if not step:
            continue
        by_step.setdefault(step, []).append(r)

    nodes: List[Dict[str, Any]] = []
    for n in _FLOW_NODES + _WO_NODES:
        # 节点属于哪张工单：WO 子流程节点只挂 eflow-wo 的规则，TT 节点只挂 eflow-tt 的规则。
        # 不区分会把 `TT_confirm`（eflow-tt）挂到 wo_confirm 上 —— 两者 triggerStep
        # 同名（Confirm）但工单类型不同，混挂会让「这一步归谁管」失真。
        is_wo_node = n["key"].startswith("wo_") or n["stage"] == "wo"
        want_wo_type = "eflow-wo" if is_wo_node else "eflow-tt"

        attached: List[Dict[str, Any]] = []
        for step in n["trigger_steps"]:
            for r in by_step.get(step, []):
                if r["wo_type"] != want_wo_type:
                    continue
                attached.append(r)
        # 去重（同一规则可能命中多个 triggerStep 变体）
        seen: set = set()
        uniq: List[Dict[str, Any]] = []
        for r in attached:
            k = (r["name"], r["rule_type"], r["trigger_step"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        nodes.append({
            "id": n["key"],
            "label": n["label_zh"] if lang == "zh" else n["label_en"],
            "stage": n["stage"],
            "rules": sorted(uniq, key=lambda x: (x["rule_type"], x["priority"])),
            "rule_count": len(uniq),
            "active_rule_count": sum(1 for x in uniq if x["status"] == "ACTIVE"),
        })

    # 边：主干 + 规则「推送路径」里显式声明的流转
    edges: List[Dict[str, Any]] = []
    seen_e: set = set()

    def _add_edge(src: str, dst: str, kind: str, rule: Optional[Dict[str, Any]] = None):
        if src == dst:
            return
        k = (src, dst)
        if k in seen_e:
            # 已存在则仅补充规则来源
            if rule:
                for e in edges:
                    if (e["from"], e["to"]) == k:
                        if rule["name"] not in e["rule_names"]:
                            e["rule_names"].append(rule["name"])
            return
        seen_e.add(k)
        edges.append({
            "from": src,
            "to": dst,
            "kind": kind,
            "rule_names": [rule["name"]] if rule else [],
        })

    node_ids = {n["id"] for n in nodes}
    for a, b in _FLOW_EDGES:
        _add_edge(a, b, "main")

    # 规则推送路径解析：形如 "FOAccept,2>FOProcess,8>FOProcess"
    for r in rules:
        path = r.get("push_path") or ""
        if not path:
            continue
        parts = [p.strip() for p in re.split(r">", path) if p.strip()]
        step_names: List[str] = []
        for p in parts:
            # 去掉 "FOAccept,2" 里的优先级尾数
            name = p.split(",")[0].strip()
            if name:
                step_names.append(name)
        for i in range(len(step_names) - 1):
            src = _step_to_node(step_names[i])
            dst = _step_to_node(step_names[i + 1])
            if src and dst and src in node_ids and dst in node_ids:
                _add_edge(src, dst, "rule", r)

    return {"nodes": nodes, "edges": edges, "rules_total": len(rules)}


def _step_to_node(step: str) -> Optional[str]:
    """triggerStep / 推送路径里的步骤名 → 规范节点 key。"""
    s = _s(step)
    if not s:
        return None
    low = s.lower()
    for n in _FLOW_NODES + _WO_NODES:
        if n["key"].lower() == low:
            return n["key"]
    # 规则里常见的带前缀写法
    for prefix, key in (
        ("groupconfig_", None), ("groupdefault_", None), ("customtitle_", None),
    ):
        if low.startswith(prefix):
            tail = s[len(prefix):]
            for n in _FLOW_NODES + _WO_NODES:
                if n["key"].lower() == tail.lower():
                    return n["key"]
    return None


def _actual_path(tt_state: Dict[str, Any], lang: str) -> Dict[str, Any]:
    """由该 TT 的实际数据推导「实际走过的节点」与「当前所处节点」。"""
    t = tt_state["tt"]
    wo = tt_state["wo"]
    alarms = tt_state["alarms"]

    reached: List[Dict[str, Any]] = []
    order = [n["key"] for n in _FLOW_NODES]

    def _mark(key: str, ts: str = "", by: str = "", note_zh: str = "", note_en: str = ""):
        if key not in order:
            return
        reached.append({
            "id": key,
            "ts": ts,
            "by": by,
            "note_zh": note_zh,
            "note_en": note_en,
        })

    # ① 告警发生
    _mark("alarm",
          ts=_s(t.get("alarm_occur_time")) or _s(t.get("alarm_server_time")),
          by=_s(t.get("moc")) or _s(t.get("ne_name")),
          note_zh="告警产生并上报 eFlow",
          note_en="Alarm raised and reported to eFlow")

    # ② 建单
    _mark("create", ts=_s(t.get("created_time")), by=_s(t.get("creator")),
          note_zh="按 TT Level Rule 定级后建单",
          note_en="TT created after severity rule applied")

    # ③ WO 子流程（若已派生）：挂一条边到 FO 接单/处理，说明现场侧已展开
    if wo:
        _mark("FOAccept" if not _s(t.get("fo_accept_detail")) else "FOProcess",
              ts=_s(wo.get("created_time")), by=_s(wo.get("creator")),
              note_zh=f"已派生 WO {_s(wo.get('wo_no'))}（现场工单）",
              note_en=f"WO {_s(wo.get('wo_no'))} derived (field work order)")

    # ④ 按实际发生的明细字段打点（与 tt_postmortem 的里程碑口径一致）
    detail_marks = [
        ("FOAccept", t.get("fo_accept_detail"), "FO 接单", "FO accepted"),
        ("FOProcess", t.get("fo_process_detail"), "FO 处理", "FO processed"),
        ("Confirm", t.get("confirm_detail"), "确认", "Confirmed"),
    ]
    for key, detail, zh, en in detail_marks:
        txt = _s(detail)
        if not txt:
            continue
        ts = ""
        m = re.search(r"(20\d{2}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2})", txt)
        if m:
            ts = m.group(1)
        by = ""
        m2 = re.search(r"(?:By|Operator|处理人|Assign To)[:：]\s*([^\s,;]+)", txt)
        if m2:
            by = m2.group(1)
        if not any(x["id"] == key for x in reached):
            _mark(key, ts=ts, by=by, note_zh=zh, note_en=en)
        else:
            # 已在 reached（如 WO 派生时占位）则补上时间与处理人
            for x in reached:
                if x["id"] == key:
                    x["ts"] = x["ts"] or ts
                    x["by"] = x["by"] or by
                    break

    # ⑤ 当前所处节点（operation_type 是 eFlow 的实际步骤字段）
    current = _match_step(t.get("operation_type")) or _match_step(t.get("status"))
    if current and not any(x["id"] == current for x in reached):
        _mark(current, ts=_s(t.get("last_modified_time")),
              by=_s(t.get("current_handler")),
              note_zh="当前所处步骤（来自 operation_type）",
              note_en="Current step (from operation_type)")

    # ⑥ 关单
    if _s(t.get("actual_completion_time")) or (current == "Closed"):
        if not any(x["id"] == "Closed" for x in reached):
            _mark("Closed", ts=_s(t.get("actual_completion_time")),
                  note_zh="工单已关闭", note_en="Ticket closed")

    # 按规范顺序排序，保证「流程感」
    idx = {k: i for i, k in enumerate(order)}
    reached.sort(key=lambda x: idx.get(x["id"], 999))
    reached_ids = [x["id"] for x in reached]

    # 实际走过的边
    actual_edges = []
    for i in range(len(reached_ids) - 1):
        actual_edges.append({"from": reached_ids[i], "to": reached_ids[i + 1]})

    return {
        "reached": reached,
        "reached_ids": reached_ids,
        "current": current,
        "actual_edges": actual_edges,
    }


def _wo_path(tt_state: Dict[str, Any]) -> Dict[str, Any]:
    """WO 子流程的实际状态。"""
    wo = tt_state["wo"]
    if not wo:
        return {"present": False, "reached_ids": [], "current": None, "steps": []}

    reached: List[str] = ["wo_create"]
    cur = _match_wo_step(wo.get("operation_step")) or _match_wo_step(wo.get("status"))
    order = [n["key"] for n in _WO_NODES]
    if cur and cur in order:
        i = order.index(cur)
        for k in order[: i + 1]:
            if k not in reached:
                reached.append(k)
    reached = [k for k in order if k in reached]

    detail_steps = []
    for key, label in (("accept_detail", "wo_accept"), ("process_detail", "wo_process"),
                       ("confirm_detail", "wo_confirm"), ("closed_detail", "wo_closed")):
        txt = _s(wo.get(key))
        if txt:
            ts = ""
            m = re.search(r"(20\d{2}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2})", txt)
            if m:
                ts = m.group(1)
            detail_steps.append({"key": label, "ts": ts, "detail": txt[:300]})

    return {
        "present": True,
        "reached_ids": reached,
        "current": cur,
        "steps": detail_steps,
        "wo_no": _s(wo.get("wo_no")),
        "status": _s(wo.get("status")),
        "operation_step": _s(wo.get("operation_step")),
        "current_handler": _s(wo.get("current_handler")),
        "created_time": _s(wo.get("created_time")),
        "actual_finish_time": _s(wo.get("actual_finish_time")),
    }


def query_flow(keyword: str, lang: str = "zh") -> Dict[str, Any]:
    """主入口：按告警或 TT 单号查询全流程。

    参数
    ----
    keyword : TT 单号（TT202609230060）/ 告警 id（1764213625912）/ 告警码（99933）
    lang    : 'zh' | 'en'

    返回
    ----
    {
      "found": bool,
      "query": str,
      "query_type": "tt" | "alarm" | "alarm_code" | "unknown",
      "graph": {...规则骨架（节点/边）...},
      "tt": {...}, "wo": {...}, "alarms": [...],
      "reached_ids": [...], "actual_edges": [...], "current": "FOProcess",
      "wo_path": {...},
      "rule_hits": [...命中该单的规则（挂在实际所在节点）...],
      "candidates": [...若未唯一命中，给出候选单号...],
      "message": "..."
    }
    """
    kw = _s(keyword)
    graph = build_flow_graph(lang=lang)
    if not kw:
        return {
            "found": False, "query": kw, "query_type": "unknown",
            "graph": graph, "message": "请输入 TT 单号或告警 ID/告警码",
            "message_en": "Enter a TT number or alarm ID/code",
        }

    with get_raw_connection() as conn:
        query_type = "unknown"
        tt_no = ""
        via = ""
        candidates: List[Dict[str, Any]] = []

        if _TT_RE.match(kw):
            query_type = "tt"
            tt_no = kw.upper()
        else:
            hits = _find_tt_by_alarm(conn, kw)
            if hits:
                query_type = "alarm"
                tt_no = hits[0]["tt_no"]
                via = hits[0].get("via", "")
                if len(hits) > 1:
                    candidates = hits[1:]
            else:
                # 当作告警码
                cands = _find_by_alarm_code(conn, kw)
                if cands:
                    query_type = "alarm_code"
                    candidates = cands
                    tt_no = cands[0]["tt_no"]

        if not tt_no:
            return {
                "found": False, "query": kw, "query_type": query_type,
                "graph": graph,
                "message": f"未找到与「{kw}」关联的 TT 工单",
                "message_en": f"No TT ticket found for \"{kw}\"",
            }

        state = _tt_flow_state(conn, tt_no)

    if not state:
        return {
            "found": False, "query": kw, "query_type": query_type,
            "graph": graph,
            "message": f"TT {tt_no} 不在本地库中（可能尚未同步）",
            "message_en": f"TT {tt_no} is not in the local mirror yet",
        }

    path = _actual_path(state, lang)
    wo_path = _wo_path(state)

    # 命中该单的规则：按当前所在节点与告警码/定级给出
    t = state["tt"]
    cur = path["current"]
    rule_hits: List[Dict[str, Any]] = []
    for n in graph["nodes"]:
        if n["id"] == cur:
            for r in n["rules"]:
                rule_hits.append({**r, "node": n["id"], "reason_zh": "当前步骤由该规则接管",
                                  "reason_en": "Rule governing the current step"})
    # 定级规则（决定 P1~P4）始终相关
    for n in graph["nodes"]:
        if n["id"] == "create":
            for r in n["rules"]:
                if r["rule_type"] == "ttLevelRule":
                    rule_hits.append({**r, "node": "create",
                                      "reason_zh": "建单定级规则",
                                      "reason_en": "Severity rule applied at creation"})

    seen_r: set = set()
    uniq_hits: List[Dict[str, Any]] = []
    for r in rule_hits:
        k = (r["name"], r["node"])
        if k in seen_r:
            continue
        seen_r.add(k)
        uniq_hits.append(r)

    tt_out = {
        "tt_no": _s(t.get("tt_no")),
        "wo_no": _s(t.get("wo_no")),
        "status": _s(t.get("status")),
        "operation_type": _s(t.get("operation_type")),
        "ticket_severity": _s(t.get("ticket_severity")),
        "alarm_code": _norm_code(t.get("alarm_code")),
        "alarm_id": _norm_alarm_id(t.get("alarm_id")),
        "alarm_type": _s(t.get("alarm_type")),
        "alarm_severity": _s(t.get("alarm_severity")),
        "site_name": _s(t.get("site_name")),
        "current_handler": _s(t.get("current_handler")),
        "creator": _s(t.get("creator")),
        "domain": _s(t.get("domain")),
        "ne_name": _s(t.get("ne_name")),
        "title": _s(t.get("title")),
        "created_time": _s(t.get("created_time")),
        "last_modified_time": _s(t.get("last_modified_time")),
        "alarm_occur_time": _s(t.get("alarm_occur_time")),
        "alarm_clear_time": _s(t.get("alarm_clear_time")),
        "actual_completion_time": _s(t.get("actual_completion_time")),
        "fault_duration_time": _s(t.get("fault_duration_time")),
        "sla_status": _s(t.get("sla_status")),
        "root_cause": _s(t.get("root_cause")),
        "root_cause_description": _s(t.get("root_cause_description")),
        "down_site_count": _s(t.get("down_site_count")),
        "description": _s(t.get("description"))[:1000],
    }

    return {
        "found": True,
        "query": kw,
        "query_type": query_type,
        "via": via,
        "graph": graph,
        "tt": tt_out,
        "wo": state["wo"] and {
            "wo_no": _s(state["wo"].get("wo_no")),
            "status": _s(state["wo"].get("status")),
            "operation_step": _s(state["wo"].get("operation_step")),
            "current_handler": _s(state["wo"].get("current_handler")),
            "creator": _s(state["wo"].get("creator")),
            "created_time": _s(state["wo"].get("created_time")),
            "actual_finish_time": _s(state["wo"].get("actual_finish_time")),
        },
        "alarms": state["alarms"],
        "reached": path["reached"],
        "reached_ids": path["reached_ids"],
        "actual_edges": path["actual_edges"],
        "current": path["current"],
        "wo_path": wo_path,
        "rule_hits": uniq_hits,
        "candidates": candidates,
        "message": "",
        "message_en": "",
    }
