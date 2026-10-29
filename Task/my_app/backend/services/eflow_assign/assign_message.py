# -*- coding: utf-8 -*-
"""eFlow 派单**通报正文**的渲染（纯函数，不触网）。

## 为什么单独成模块（2026-10-29）

`assign_engine.py` 一度 600 行，超出 AGENTS.md 第三节第 2 条的
「新增文件单个不超过 500 行」。渲染与判定是**两件不相干的事**：
判定读告警字段做决策，渲染把决策结果拼成给人看的英文正文。

## 通报格式（需求原文）

TT Title = `SITE ID_Site name_Alarm Code`。TT 的真正标题由 eFlow 自动生成
（`<site>.[<site name>]<告警名>`），接口不接受自定义标题；故群里按需求格式
通报，并附上真实 TT 编号。

⚠ **群通报正文一律英文**（2026-10-27 如意要求「通报默认使用英文」）。
故调用方传入的 `site_note` / `notes` / `extra_lines` 必须已是英文；
中文只留在日志与状态表里。

## 两个附加段（合并派单时必看）

* `impacted` —— 同一次故障里被本 TT 一并覆盖的**其它站点**
  `[(site_id, site_name), ...]`，已去重，**不含**本条自己的站点。
  非空时追加「这一单实际涵盖 N 个站点」，避免群里误以为只坏了这一个站。
* `extra_lines` —— 业务线自有的附加行（如 5G 的小区列表），格式
  `[(标签, 值), ...]`。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.services.eflow_assign.assign_config import norm_code


def _val(v: Any) -> Any:
    """eFlow 告警字段是 {value, displayname, ...} 对象；统一取 value。"""
    if isinstance(v, dict):
        return v.get("value")
    return v


def _s(val_: Any) -> str:
    """转字符串并去空白；None → ''。"""
    return "" if val_ is None else str(val_).strip()


def _occur_ms(alarm: Dict[str, Any]) -> Optional[int]:
    """告警升起时间（毫秒）：优先 `alarmraisedtime`，回退 `servertime`。"""
    raw = _val(alarm.get("alarmraisedtime")) or _val(alarm.get("servertime"))
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def render_message(ctx, alarm: Dict[str, Any],
                   site_id: str, site_name: str,
                   tt_no: str, dry_run: bool,
                   site_note: str = "",
                   notes: Optional[List[str]] = None,
                   impacted: Optional[List[Tuple[str, str]]] = None,
                   extra_lines: Optional[List[Tuple[str, str]]] = None,
                   ) -> str:
    """按需求格式渲染通报：TT Title = SITE ID_Site name_Alarm Code。"""
    code = norm_code(_val(alarm.get("alarmcode")))
    code_name = _s(_val(alarm.get("codename")) or _val(alarm.get("alarm_title")))
    occ = _occur_ms(alarm)
    occ_txt = datetime.fromtimestamp(occ / 1000).strftime("%Y-%m-%d %H:%M:%S") if occ else "-"
    title = f"{site_id}_{site_name}_{code}"
    lines = [ctx.push_title, ""]
    lines.append(f"TT Title : {title}")
    lines.append(f"Site ID  : {site_id}")
    lines.append(f"Site Name: {site_name}")
    lines.append(f"Alarm    : {code} {code_name}".rstrip())
    lines.append(f"Occurred : {occ_txt}")
    me_name = _s(_val(alarm.get("mename")) or _val(alarm.get("site")))
    if me_name:
        lines.append(f"ME       : {me_name}")
    for label, value in (extra_lines or []):
        if value:
            lines.append(f"{label:<8}: {value}")
    if tt_no:
        lines.append(f"TT No.   : {tt_no}")
    lines.append(f"Assigned : {ctx.assign_group}")
    if impacted:
        # 合并派单：说清「这一单实际涵盖多个站点」，否则群里会以为只坏了一个站
        lines.append("")
        lines.append(f"This TT covers {len(impacted) + 1} sites from {ctx.outage_label}:")
        lines.append(f"  - {site_id}/{site_name}  (TT created on this site)")
        for _sid, _sname in impacted:
            # 站点解析失败的成员也要露出来（用站名/ME 名兜底），不能显示成空行 ——
            # 否则群里看到一行空白，反而不知道这一单还涵盖了谁。
            _label = f"{_sid}/{_sname}" if _sid else (_sname or "unknown site")
            lines.append(f"  - {_label}")
    if dry_run:
        lines.append("")
        lines.append("⚠ DRY-RUN: rehearsal only, no TT has been created")
    if site_note:
        lines.append("")
        lines.append(f"⚠ {site_note}")
    for note in notes or []:
        if note:
            lines.append(f"⚠ {note}")
    return "\n".join(lines)


def render_manual_message(ctx, alarm: Dict[str, Any], reason: str,
                          hint_lines: Optional[List[str]] = None) -> str:
    """自动派单失败时的「需人工处理」通报（2026-10-27 业务要求：不能静默漏派）。

    两类失败都会走它：
      1. **站点解析失败** —— 拿不到数字站号，eFlow 对只带 ME 名的 payload 会回
         `manual assign succeed.` 却不建 TT（实测）；
      2. **eFlow 侧 ttstatus 非 0**（ME 未关联站点）—— 仍会尝试派单，但接口回
         succeed 也不建 TT，必须让人去 eFlow 修站点绑定。

    共同点：自动派不了，**但必须让群里看到**，否则等于漏派且无人知晓。
    同一条告警只通知一次，由状态表 `send_status` 抑制（见主流程）。

    ⚠ **群通报正文一律英文**：`reason` / `hint_lines` 必须由调用方传入英文；
    中文原因走 `last_error` 落状态表。
    """
    code = norm_code(_val(alarm.get("alarmcode")))
    code_name = _s(_val(alarm.get("codename")) or _val(alarm.get("alarm_title")))
    occ = _occur_ms(alarm)
    occ_txt = datetime.fromtimestamp(occ / 1000).strftime("%Y-%m-%d %H:%M:%S") if occ else "-"
    me_name = _s(_val(alarm.get("mename")) or _val(alarm.get("site")))

    lines = [ctx.push_title, ""]
    lines.append("⚠ Auto assign failed — manual action required in eFlow")
    lines.append(f"ME       : {me_name or '-'}")
    lines.append(f"Alarm    : {code} {code_name}".rstrip())
    lines.append(f"Occurred : {occ_txt}")
    lines.append(f"Reason   : {reason}")
    lines.append("")
    if hint_lines is None:
        hint_lines = ["Note: no numeric site ID could be resolved from cmdb for this site,",
                      "      so eFlow cannot create a TT automatically.",
                      "      Please fix the cmdb site or assign the TT manually in eFlow."]
    lines.extend(hint_lines)
    return "\n".join(lines)
