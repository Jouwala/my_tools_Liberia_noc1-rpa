"""TT 告警 WhatsApp 消息渲染（纯函数，不碰 DB / 网络 / 环境）。

从 `tt_alarm_whatsapp_service` 拆出，职责单一：**把一行 eflow_tt 变成一段文本**。
拆出的理由有两个，都不是为了好看：
  1. 本模块是纯函数，可脱离数据库单测（`tests/test_tt_alarm_whatsapp_service.py`
     的渲染断言全部打在这里）；
  2. 渲染规则的微调（改文案、加字段）频率远高于取数与调度，独立后改动面收敛。
     （拆出时主服务 611 代码行，已越过 `AGENTS.md` 三.2 的 500 行上限。）

渲染格式以需求样例单 TT202609270103 为基准，逐行对照：

    TT202609270103 · Ganta 4(4530) | Nimba | Site type NORMAL | Site subtype REGULAR
    Title: 4530.[Ganta 4]Complete site down (CSD)
    Alarm: 9920(Critical) | RAN | Communication Alarm
    Alarm object: BSC1(1)/Ganta 4 | 10.17.17.129/129.0.1.1 | 2G SITE DOWN
    Impact: 2G,3G,4G outage | site outage | 1 site(s) down | VIP Yes
    Severity: P1 (matches rule)

**取值一律「取不到给 —，不得给 0」**（`AGENTS.md` 三.6）。
"""
from typing import Any, Dict, List

__all__ = ["s", "dash", "norm_alarm_code", "split_multi", "build_tt_message"]


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

    `row` 可直接用 `fetch_candidate_tts` 返回的行（含预处理好的 `_alarm_code_norm`），
    也可用任意同名字典 —— 缺失键按空值处理，不会抛 KeyError。
    """
    # ---- 第 1 行：单号 · 站名(站号) | 区域 | 站点类型 | 站点子类型 ----
    line1 = (f"{dash(row.get('tt_no'))} · {dash(row.get('site_name'))}"
             f"({dash(row.get('site_id') or row.get('asset_id'))}) | "
             f"{dash(row.get('region_level1'))} | "
             f"Site type {dash(row.get('site_type'))} | "
             f"Site subtype {dash(row.get('site_information'))}")

    # ---- 第 2 行：标题 ----
    line2 = f"Title: {s(row.get('title')) or s(row.get('description')) or '—'}"

    # ---- 第 3 行：告警码(级别) | 域 | 告警类型 ----
    code = row.get("_alarm_code_norm")
    if code is None:
        code = norm_alarm_code(row.get("alarm_code"))
    alarm_sev = s(row.get("alarm_severity"))
    alarm_type = s(row.get("alarm_type")) or s(row.get("alarm_category"))
    alarm_head = f"Alarm: {code or '—'}({alarm_sev or '—'})"
    alarm_rest = " | ".join(x for x in (s(row.get("domain")), alarm_type) if x)
    line3 = f"{alarm_head} | {alarm_rest}" if alarm_rest else alarm_head

    # ---- 第 4 行：告警对象 ----
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
    line4 = "Alarm object: " + (" | ".join(obj_groups) if obj_groups else "—")

    # ---- 第 5 行：影响面 ----
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
    line5 = "Impact: " + (" | ".join(impact_parts) if impact_parts else "—")

    # ---- 第 6 行：级别 ----
    line6 = f"Severity: {dash(row.get('ticket_severity'))} (matches rule)"

    return "\n".join([line1, line2, line3, line4, line5, line6])
