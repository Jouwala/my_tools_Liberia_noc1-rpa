"""TT 告警 WhatsApp 消息渲染（纯函数，不碰 DB / 网络 / 环境）。

从 `tt_alarm_whatsapp_service` 拆出，职责单一：**把一行 eflow_tt 变成一段文本**。
拆出的理由有两个，都不是为了好看：
  1. 本模块是纯函数，可脱离数据库单测（`tests/test_tt_alarm_whatsapp_service.py`
     的渲染断言全部打在这里）；
  2. 渲染规则的微调（改文案、加字段）频率远高于取数与调度，独立后改动面收敛。
     （拆出时主服务 611 代码行，已越过 `AGENTS.md` 三.2 的 500 行上限。）

渲染格式以需求样例单 TT202609270103 为基准，逐行对照（在样例基础上补了
`Occurred:` 行 —— 告警发生时间是本消息最关键的元素，见 build_tt_message 内注释）：

    TT202609270103 · Ganta 4(4530) | Nimba | Site type NORMAL | Site subtype REGULAR
    Occurred: 2026-09-27 01:03
    Title: 4530.[Ganta 4]Complete site down (CSD)
    Alarm: 9920(Critical) | RAN | Communication Alarm
    Alarm object: BSC1(1)/Ganta 4 | 10.17.17.129/129.0.1.1 | 2G SITE DOWN
    Impact: 2G,3G,4G outage | site outage | 1 site(s) down | VIP Yes
    Severity: P1

**取值一律「取不到给 —，不得给 0」**（`AGENTS.md` 三.6）。
"""
from typing import Any, Dict, List

__all__ = ["s", "dash", "norm_alarm_code", "split_multi", "build_tt_message",
           "reminder_banner"]


def s(val: Any) -> str:
    """None / NaN / 空串 → ''；其余转字符串并去首尾空白。"""
    if val is None:
        return ""
    text = str(val).strip()
    return "" if text.lower() in ("none", "nan", "nat") else text


def dash(val: Any) -> str:
    """渲染用：空值一律给 '—'（取不到值不显示成 0）。"""
    return s(val) or "—"


def norm_alarm_code(val: Any) -> str:
    """归一化告警码：去掉浮点文本尾巴（'99933.0' → '99933'），去空白。

    `eflow_tt.alarm_code` 经同步链路后常被读成浮点文本，库里 `'99933'`（2159 行）
    与 `'99933.0'`（16599 行）**并存**，故判等前必须归一化。
    语义与 `backend/services/tt_postmortem/__init__.py:85` 的 `_norm_alarm_id` 一致。
    """
    text = s(val)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def split_multi(val: Any) -> List[str]:
    """多值字段 → 列表（源字段用 ';' + 换行分隔，如 'BSC1(1);\\nGanta 4'）。"""
    text = s(val)
    if not text:
        return []
    parts = [p.strip() for p in text.replace("\n", ";").split(";")]
    return [p for p in parts if p]


def _first(val: Any) -> str:
    """多值字段取第一项。"""
    parts = split_multi(val)
    return parts[0] if parts else ""


def build_tt_message(row: Dict[str, Any]) -> str:
    """把一行 eflow_tt 渲染成 WhatsApp 文本消息（纯函数）。

    `row` 可用实时查单行（`eflow_data_mapper.fetch_tt_live_batch` 的归一化行）、
    本地镜像行或任意同名字典 —— 缺失键按空值处理，不会抛 KeyError。
    """
    # ---- 第 1 行：单号 · 站名(站号) | 区域 | 站点类型 | 站点子类型 ----
    line1 = (f"{dash(row.get('tt_no'))} · {dash(row.get('site_name'))}"
             f"({dash(row.get('site_id') or row.get('asset_id'))}) | "
             f"{dash(row.get('region_level1'))} | "
             f"Site type {dash(row.get('site_type'))} | "
             f"Site subtype {dash(row.get('site_information'))}")

    # ---- 第 2 行：告警发生时间 ----
    # 这是告警消息最关键的元素之一（"发生多久了"），降级模板里绝不能缺 ——
    # 降级在这个任务里不是异常路径而是常态（引擎超时/镜像滞后），缺时间会把
    # 值班群晾在"不知道这条告警是刚发生还是三天前的"的状态里。
    line2 = f"Occurred: {dash(row.get('alarm_occur_time'))}"

    # ---- 第 3 行：标题 ----
    line3 = f"Title: {s(row.get('title')) or s(row.get('description')) or '—'}"

    # ---- 第 4 行：告警码(级别) | 域 | 告警类型 ----
    code = row.get("_alarm_code_norm")
    if code is None:
        code = norm_alarm_code(row.get("alarm_code"))
    alarm_sev = s(row.get("alarm_severity"))
    alarm_type = s(row.get("alarm_type")) or s(row.get("alarm_category"))
    # ⚠️ 2026-10-08：把 `alarm_description`（eFlow 的告警码中文名/codename，如
    # "MW LINK DOWN" / "3G SITE DOWN"）拼在 `Alarm:` 行 `domain | alarm_type` 段。
    # 之前 `build_tt_message` 只在 `sub_alarm_name` 兜底位用它（line 117）——
    # 这位置**只是子告警名兜底**，子告警名一旦非空，codename 就被挤掉。
    # 期望格式：`Alarm: 9995(Critical) | codename: MW LINK DOWN | Communication Alarm`。
    # 缺值时不输出 codename 段（与 domain/alarm_type 同语义）。
    codename = s(row.get("alarm_description"))
    alarm_head = f"Alarm: {code or '—'}({alarm_sev or '—'})"
    rest_parts = []
    if codename:
        rest_parts.append(f"codename: {codename}")
    rest_parts.extend(x for x in (s(row.get("domain")), alarm_type) if x)
    alarm_rest = " | ".join(rest_parts)
    line4 = f"{alarm_head} | {alarm_rest}" if alarm_rest else alarm_head

    # ---- 第 5 行：告警对象 ----
    #
    # 格式对照样例 `BSC1(1)/Ganta 4 | 10.17.17.129/129.0.1.1 | 2G SITE DOWN`：
    # **所有网元名用 `/` 连成一组，所有 IP 用 `/` 连成一组**，两组之间用 ` | `，
    # 再与子告警名用 ` | ` 相连。注意不是按下标 zip 成
    # `BSC1(1)/10.17.17.129/Ganta 4/129.0.1.1`（那会把名与 IP 交错，与样例不符）。
    #
    # ⚠️ 实测（2026-09-28）：`sub_alarm_*` 三个字段在**近期单**上填充率 >95%
    # （近 30 天 4462 单里空 202~505），但在**历史遗留的未清除老单**上**全为空**
    # （16 张未清除 P1 单，16 张都空）。只取 sub_alarm_* 会让老单渲染成
    # "Alarm object: —"，故兜底：网元名 → ne_name；子告警名 → specific_problem
    # → alarm_description。
    ne_names = split_multi(row.get("sub_alarm_ne_name")) or split_multi(row.get("ne_name"))
    ne_ips = split_multi(row.get("sub_alarm_ne_ip"))
    sub_alarm = (_first(row.get("sub_alarm_name"))
                 or s(row.get("specific_problem"))
                 or s(row.get("alarm_description")))
    obj_groups: List[str] = []
    if ne_names:
        obj_groups.append("/".join(ne_names))
    if ne_ips:
        obj_groups.append("/".join(ne_ips))
    if not obj_groups and sub_alarm:
        # 网元名与 IP 都缺（历史老单常见）时，至少给出子告警名
        obj_groups.append(sub_alarm)
        sub_alarm = ""
    if sub_alarm:
        obj_groups.append(sub_alarm)
    line5 = "Alarm object: " + (" | ".join(obj_groups) if obj_groups else "—")

    # ---- 第 6 行：影响面 ----
    #
    # ⚠️ 两个已实测的坑（2026-09-28 全表核对）：
    #   1) `down_site_count` 的 '0' 是**有效值**（全表 27254 行为 '0'），不是缺数据；
    #      样例 TT202609270103 为 '1'。故只有「> 0」才输出 "N site(s) down" ——
    #      取到 0 时输出 "0 site(s) down" 是把「无断站」说成「有 0 个断站」。
    #   2) `site_outage` 是 'Yes'/'No' 文本，只有 'Yes' 才算断站。未清除的 P1 老单
    #      实测存在 site_outage='No' + down_site_count='0' 的组合；若写成
    #      `site_outage=='yes' or down_site_count`，'0' 会被当假值、'No' 会被当断站，
    #      两条都错。
    impact_parts: List[str] = []
    impacted = s(row.get("impacted_service"))
    if impacted:
        impact_parts.append(f"{impacted} outage")
    if s(row.get("site_outage")).lower() == "yes":
        impact_parts.append("site outage")
    try:
        cnt = int(float(s(row.get("down_site_count")) or 0))
    except ValueError:
        cnt = 0
    if cnt > 0:
        impact_parts.append(f"{cnt} site(s) down")
    vip = s(row.get("vip_site"))
    if vip:
        impact_parts.append(f"VIP {vip}")
    line6 = "Impact: " + (" | ".join(impact_parts) if impact_parts else "—")

    # ---- 第 7 行：级别 ----
    # 只报级别，不写 "(matches rule)"：本模板是**降级路径**，此时规则引擎
    # 根本没跑过（完整引擎的输出才带派单依据/规则判定），写 matches 是谎报。
    line7 = f"Severity: {dash(row.get('ticket_severity'))}"

    return "\n".join([line1, line2, line3, line4, line5, line6, line7])


def reminder_banner(reminder_no: int, open_minutes: int, stale_minutes: int) -> str:
    """重报横幅：让值班一眼分清「首推」与「第 N 次提醒仍未解决」。

    重报消息的正文与首推几乎相同（同一单的同一份渲染），没有横幅时群里
    无法区分新告警和旧提醒。三个数字的口径（由调用方保证）：
      * reminder_no —— 本次是第几次发送（已成功发送次数 + 1）；
      * open_minutes —— 告警发生至今（alarm_occur_time 到 now）；
      * stale_minutes —— 距最近一次工单更新（last_modified_time 到 now）。
    首推（reminder_no <= 1）应返回空串，调用方不拼横幅。
    """
    total = max(0, int(open_minutes))
    hours, mins = divmod(total, 60)
    open_txt = f"{hours}h{mins:02d}m" if hours else f"{mins}m"
    stale = max(0, int(stale_minutes))
    return (f"⚠️ REMINDER #{int(reminder_no)} · open {open_txt}"
            f" · no update for {stale}m")
