# -*- coding: utf-8 -*-
"""5G 派单的**通报正文渲染**（纯函数，不触网）。

## 为什么单独成模块

渲染口径（含 5G 特有的 **Cells** 行）与 Fiber 共用 `assign_engine.render_message`，
但 5G 要多一行「本单涵盖哪几个小区」—— 一站多小区合并后，群里的同事必须
一眼看出这一单到底覆盖了几个小区、是哪几个，否则要去查 eFlow 才知道。

正文**一律英文**（沿用 Fiber 的 2026-10-27 如意要求：通报默认使用英文）：
`site_note` / `notes` 必须由调用方传入英文；中文只留在日志与状态表里。
"""
from typing import Any, Dict, List, Optional, Tuple

from backend.services.eflow_assign import assign_engine as engine


def build_message(ctx: engine.AssignContext,
                  alarm: Dict[str, Any], site_id: str, site_name: str,
                  tt_no: str, dry_run: bool,
                  cells: Optional[List[str]] = None,
                  site_note: str = "",
                  notes: Optional[List[str]] = None) -> str:
    """渲染 5G 派单通报。

    格式与 Fiber 一致（TT Title = SITE ID_Site name_Alarm Code），
    另加 **Cells** 行（5G 一站多小区，必须让人看清涵盖哪几个小区）。
    """
    cell_list = list(cells or [])
    extra: List[Tuple[str, str]] = []
    if cell_list:
        extra.append(("Cells", ", ".join(cell_list)))
    text = engine.render_message(ctx, alarm, site_id, site_name, tt_no, dry_run,
                                 site_note=site_note, notes=notes, extra_lines=extra)
    if len(cell_list) > 1:
        # 多小区时补一句，明确「这一单覆盖了几个小区」
        text += f"\nThis TT covers {len(cell_list)} cells on the same site: " \
                + ", ".join(cell_list)
    return text


def build_manual_message(ctx: engine.AssignContext, alarm: Dict[str, Any],
                         reason: str,
                         hint_lines: Optional[List[str]] = None) -> str:
    """自动派单失败时的「需人工处理」通报（不能静默漏派）。"""
    return engine.render_manual_message(ctx, alarm, reason, hint_lines=hint_lines)
