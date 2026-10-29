# -*- coding: utf-8 -*-
"""5G 站点告警的**特有判定规则**（纯函数，不触网、不碰库）。

## 为什么单独成模块

5G 与 Fiber 的**判定口径主体**共用 `backend/services/eflow_assign/assign_engine.py`
（时间边界、关联三态、派单重试、演练开关），但有**四处 5G 特有**的规则：

1. **小区标识**（`cell` / `cellname`）—— Fiber 没有这个维度；
2. **站点身份**（用于一站多小区去重的分组键）—— 5G 的 `site` 已是数字站号；
3. **一站多小区合并分组** —— 与 Fiber 的「纯时间窗跨站合并」口径相反；
4. **本组涵盖的小区列表** —— 通报正文要让人数得出是哪几个小区。

这四条都是**纯函数**（只读入参）→ 单测无需触网；单独成模块也让
`g5_assign_service.py` 保持在 500 行以内（AGENTS.md 第三节第 2 条）。

## 一站多小区为什么必须合并（5G 特有形态）

实测一个 gNB 的多个小区（cell 50/51/52）各自产生一条告警，同一故障会派出一堆
重复单。故按「**同一站点** + 同一时间窗」合并成一个 TT，通报正文列出涵盖的小区。

⚠ 与 Fiber 的差别别搞混：Fiber 断一条光缆 → 链路上**多个不同站点**同时告警 →
按**纯时间窗**跨站点合并（「同一次断纤」）。5G 若也按纯时间窗跨站合并，会把
「两个站点恰好同时退服」误并成一单 —— 那是**两个故障**，合并后现场要跑两个站。
故 5G 的分组键 = 站点身份，时间窗只在**同站点内部**做二次切分。
"""
from typing import Any, Dict, List, Optional

from backend.services.eflow_assign import assign_engine as engine

# 站点/小区字段里的占位值（eFlow 用这些字符串表示「没有值」）
_PLACEHOLDERS = ("empty", "--", "-", "none")


def alarm_cell(alarm: Dict[str, Any]) -> str:
    """告警的小区标识（5G 特有）。

    实测字段：`cell` = `'52'`、`cellname` = `'Liscr-S2'`。
    优先 `cellname`（人可读，通报里直接用），回退 `cell`。
    """
    cname = engine.s(engine.val(alarm.get("cellname")))
    if cname and cname.lower() not in _PLACEHOLDERS:
        return cname
    cid = engine.s(engine.val(alarm.get("cell")))
    if cid and cid.lower() not in _PLACEHOLDERS:
        return cid
    return ""


def alarm_site_identity(alarm: Dict[str, Any]) -> str:
    """告警的**站点身份**（用于一站多小区去重的分组键）。

    ⚠ 不能只用 `sitename`：同一站点名在不同告警里可能大小写/空格不同，
    且 `sitename` 可能是 `--`。故优先用**数字站点 ID**（5G 的 `site` 已是数字，
    实测 `4162`），没有才回退站点名。

    返回空串表示「站点信息不足」→ 该告警不参与合并（各自成一组）：
    无法判断时宁可多派一单，也不把来路不明的告警并进别人的 TT。
    """
    sid = engine.s(engine.val(alarm.get("site_id"))) or engine.s(engine.val(alarm.get("site")))
    if sid.isdigit():
        return "id:" + sid
    name = engine.s(engine.val(alarm.get("site_name"))) or engine.s(engine.val(alarm.get("sitename")))
    if name and name.lower() not in ("--", "-", "empty", "none") and not engine.is_uuid(name):
        return "name:" + name.lower()
    return ""


def group_by_site_occurrence(alarms: List[Dict[str, Any]], window_ms: int
                             ) -> Dict[str, Dict[str, Any]]:
    """按「**同一站点** + 升起时间窗」把告警聚类成「同一次站点故障」组。

    **分组规则**：先按站点身份分桶；桶内按升起时间升序，与桶内**第一条**的
    时间差 ≤ `window_ms` 则并入，否则开新组（与 Fiber 同口径：与第一条比，
    不是与上一条比，保证组跨度不超过窗口）。

    **取不到升起时间或站点信息的告警不参与合并**，各自成一组。

    返回 `{alarm_key: {"root": 组长 key, "members": [...], "site": 站点身份}}`，
    组长 = 组内升起最早的那条。
    """
    groups: Dict[str, Dict[str, Any]] = {}

    def _alone(a: Dict[str, Any], site: str = "") -> None:
        k = engine.alarm_key_of(a)
        groups[k] = {"root": k, "members": [a], "site": site}

    # 先按站点身份分桶
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for a in alarms:
        site = alarm_site_identity(a)
        if not site:
            _alone(a)
            continue
        buckets.setdefault(site, []).append(a)

    # 桶内再按时间窗切分
    for site, items in buckets.items():
        if window_ms <= 0:
            for a in items:
                _alone(a, site)
            continue
        ordered = sorted(items, key=lambda x: (engine.occur_ms(x) is None,
                                               engine.occur_ms(x) or 0,
                                               engine.alarm_key_of(x)))
        bucket: List[Dict[str, Any]] = []
        base_ms: Optional[int] = None

        def _flush(bucket: List[Dict[str, Any]], site: str) -> None:
            if not bucket:
                return
            root_key = engine.alarm_key_of(bucket[0])
            for m in bucket:
                groups[engine.alarm_key_of(m)] = {
                    "root": root_key, "members": list(bucket), "site": site}

        for a in ordered:
            occ = engine.occur_ms(a)
            if occ is None:
                if bucket:
                    _flush(bucket, site)
                    bucket, base_ms = [], None
                _alone(a, site)
                continue
            if base_ms is None or not bucket:
                bucket, base_ms = [a], occ
                continue
            if occ - base_ms <= window_ms:
                bucket.append(a)
                continue
            _flush(bucket, site)
            bucket, base_ms = [a], occ
        _flush(bucket, site)
    return groups


def group_cell_labels(members: List[Dict[str, Any]]) -> List[str]:
    """取一组告警涵盖的小区标识（去重、保序）。

    通报正文要列出「这一单实际涵盖了哪几个小区」—— 否则群里只看到
    「涵盖 3 个小区」却数不出是哪三个。
    """
    out: List[str] = []
    for m in members:
        c = alarm_cell(m)
        if c and c not in out:
            out.append(c)
    return out
