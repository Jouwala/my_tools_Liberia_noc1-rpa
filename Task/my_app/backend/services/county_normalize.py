# -*- coding: utf-8 -*-
"""利比里亚县名归一化 —— 把数据源里的**大小写 / 空格 / 拼写**变体收敛到 15 个标准县名。

=========================== 为什么需要它 ===========================

`db/ZTE OLR MS Master Site Database 20261103(Important) (1).xlsx` 的
「Province/County」列（第 7 列）自带脏值，实测 18 种取值里有 3 个是变体：

    'Monsteraddo'   3 行   Montserrado 的拼写错误
    'Rivercess'     3 行   少了空格
    'River cess'    1 行   大小写不一致

同一份 Excel 在 `eflow_site`（另一条同步链路）里是干净的 15 个县 ——
说明这是**人工维护的表格笔误**，不是系统性口径差异。脏值会污染所有按县
统计/筛选的地方（GIS、人员、TT 报表、导出），所以：

  1. 导入时归一化（`normalize_admin_columns`）—— 从源头堵住；
  2. 存量数据另做一次清洗（见 2026-11-04 工作日志）。

=========================== 归一化规则（刻意保守） ===========================

* **紧凑键匹配**：小写 + 去掉所有非字母字符后比对。于是
  `River Cess` / `Rivercess` / `river  cess` 都归到 `River Cess`，
  不需要为每种变体写一条规则。
* **显式别名表**：只收**真正的拼写错误**（紧凑键也匹配不上的），如
  `Monsteraddo` → `Montserrado`。别名必须逐条人工确认，不做模糊匹配
  （编辑距离之类的猜法会把 Grand Bassa / Grand Cape Mount 混掉）。
* **认不出就原样返回**，绝不猜、绝不置空 —— 宁可让脏值显形，也不要
  把站点悄悄归到错误的县。

`LIBERIA_COUNTIES` 复用 `incident_overview_service` 里那份（与 `eflow_site`
实际值逐字一致），避免出现第二份"标准县名"真相源。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.services.incident_overview_service import LIBERIA_COUNTIES

logger = logging.getLogger("county_normalize")

# 紧凑键 -> 标准县名（"River Cess" -> "rivercess"）
_STANDARD_BY_KEY: Dict[str, str] = {
    re.sub(r"[^a-z]", "", c.lower()): c for c in LIBERIA_COUNTIES
}

# 紧凑键也匹配不上的**拼写错误**。新增条目必须是人工核实过的笔误，
# 并在后面注明依据，不要凭"看起来像"往里加。
_SPELLING_ALIASES: Dict[str, str] = {
    "monsteraddo": "Montserrado",   # 2026-11-03 Excel 第 7 列笔误，3 行（eflow_site 均为 Montserrado）
    "monsterrado": "Montserrado",   # 同类笔误的另一种写法（预防性登记）
    "montserrado": "Montserrado",
}

# 可能承载县名的列名（按优先级）。列名先过 clean_column_name，
# 所以这里用归一化后的小写形式。
COUNTY_COLUMNS: Tuple[str, ...] = ("province_county", "province", "county", "state")


def compact_key(value: Any) -> str:
    """归一化比对键：小写 + 去掉所有非字母字符。"""
    return re.sub(r"[^a-z]", "", str(value or "").lower())


def normalize_county(value: Any) -> str:
    """县名 -> 标准写法；空值、认不出的值原样返回（去首尾空白）。"""
    raw = str(value if value is not None else "").strip()
    if not raw:
        return raw
    key = compact_key(raw)
    hit = _SPELLING_ALIASES.get(key) or _STANDARD_BY_KEY.get(key)
    return hit or raw


def audit_counties(values: Iterable[Any]) -> List[Tuple[str, str, int]]:
    """审计用：返回 [(原值, 标准值, 出现次数)]，只列**会被改动**的取值。"""
    counts: Dict[str, int] = {}
    for v in values:
        raw = str(v if v is not None else "")
        counts[raw] = counts.get(raw, 0) + 1
    out: List[Tuple[str, str, int]] = []
    for raw, n in counts.items():
        norm = normalize_county(raw)
        if norm != raw.strip():
            out.append((raw, norm, n))
    return sorted(out, key=lambda x: (-x[2], x[0]))


def normalize_admin_columns(df, columns: Optional[Iterable[str]] = None) -> Dict[str, List[Tuple[str, str, int]]]:
    """就地归一化 DataFrame 里的行政区列，返回 {列名: 审计结果}。

    只在**导入写库前**调用；`columns` 缺省时按 `COUNTY_COLUMNS` 自动发现。
    改动会打 WARNING 日志（带原值 -> 新值 -> 行数），因为"数据被自动改过"
    这件事必须留痕，不能静默。
    """
    found: Dict[str, List[Tuple[str, str, int]]] = {}
    targets = list(columns) if columns else [
        c for c in df.columns if str(c).strip().lower() in COUNTY_COLUMNS
    ]
    for col in targets:
        if col not in df.columns:
            continue
        audit = audit_counties(df[col].tolist())
        if not audit:
            continue
        df[col] = df[col].map(normalize_county)
        found[col] = audit
        for raw, norm, n in audit:
            logger.warning("[county_normalize] 列 %s: %r -> %r（%d 行）", col, raw, norm, n)
    return found


__all__ = [
    "LIBERIA_COUNTIES", "COUNTY_COLUMNS",
    "compact_key", "normalize_county", "audit_counties", "normalize_admin_columns",
]
