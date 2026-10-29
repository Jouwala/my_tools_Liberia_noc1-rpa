# -*- coding: utf-8 -*-
"""5G 站点告警的**拉取与静默失效审计**。

## 主路径：服务端按码过滤（实测 21 条 / 0.03s）

eFlow 的 `alarmcodeconds` 必须是 `[{restype, alarmcode}, ...]` 的**笛卡尔积**。
**只给 alarmcode 会返回 HTTP 499**（实测），通配 restype 不被支持
（`zte.ran.*` → 0 条），故只能穷举具体 restype。

## 审计路径：定期全量对账（默认每 60 分钟）

目的：发现「全量里有、过滤里没有」的目标码 → 说明该码的真实 restype
没被配进候选 → **静默失效**（任务永远收不到它且无任何报错）。
实测全量 6752 条 / 4.45s，60 分钟一次可忽略。

诊断信息含 `filtered` / `audit_ran` / `missed_codes` / `missed_samples`，
供主循环写 warnings。
"""
import logging
from typing import Any, Dict, List, Set, Tuple

from backend.services.eflow_assign import assign_engine as engine
from backend.services.eflow_assign import eflow_assign_client as client
from backend.services.eflow_assign.assign_config import norm_code

logger = logging.getLogger("eflow_5g_fetch")

# 上次全量审计时间（模块级；worker 重启后重置 → 重启后多审计一次，无害）
_LAST_AUDIT_TS = 0.0


def fetch_target_alarms(codes: Set[str], correlation_codes: Set[str],
                        restypes: List[str], now: float,
                        fallback_full_scan: bool = True,
                        audit_interval_minutes: int = 60,
                        ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """拉取目标告警 + 关联告警 → (目标告警, 拉取诊断信息)。"""
    diag: Dict[str, Any] = {
        "filtered": 0, "audit_ran": False, "missed_codes": [],
        "missed_samples": [], "mode": "server_filter",
    }
    # 目标码 + 关联码一起拉（关联判定需要看到 99933）
    want_codes = sorted(codes | correlation_codes)
    rows = client.fetch_active_alarms_by_codes(want_codes, restypes)
    diag["filtered"] = len(rows)

    target_rows = [r for r in rows
                   if norm_code(engine.val(r.get("alarmcode"))) in codes]
    corr_rows = [r for r in rows
                 if norm_code(engine.val(r.get("alarmcode"))) in correlation_codes]

    # ---- 定期全量审计 ----
    global _LAST_AUDIT_TS
    interval_s = max(1, int(audit_interval_minutes)) * 60
    if fallback_full_scan and (now - _LAST_AUDIT_TS) >= interval_s:
        try:
            full = client.fetch_active_alarms()
            _LAST_AUDIT_TS = now
            diag["audit_ran"] = True
            full_target = [r for r in full
                           if norm_code(engine.val(r.get("alarmcode"))) in codes]
            full_corr = [r for r in full
                         if norm_code(engine.val(r.get("alarmcode"))) in correlation_codes]
            # 全量里有、过滤里没有的目标码 → restype 配漏了
            got_codes = {norm_code(engine.val(r.get("alarmcode"))) for r in target_rows}
            missed = sorted(codes - got_codes)
            # 只在「全量里确实存在该码」时才算漏配（否则只是当前没有实例）
            full_codes = {norm_code(engine.val(r.get("alarmcode"))) for r in full_target}
            real_missed = [c for c in missed if c in full_codes]
            if real_missed:
                diag["missed_codes"] = real_missed
                samples = []
                for r in full_target:
                    c = norm_code(engine.val(r.get("alarmcode")))
                    if c in real_missed and len(samples) < 5:
                        samples.append({
                            "alarm_code": c,
                            "restype": engine.s(engine.val(r.get("restype"))),
                            "moc": engine.s(engine.val(r.get("moc"))),
                            "site": engine.s(engine.val(r.get("site"))),
                        })
                diag["missed_samples"] = samples
                logger.error(
                    "[5G] ⚠ 全量审计发现 %d 个目标码被 restype 配置漏掉：%s。"
                    "这些码在实时告警里存在，但按码过滤拉不到 → 请把它们的 restype "
                    "加进「任务配置」的 restypes 字段",
                    len(real_missed), ", ".join(real_missed))
            # 全量里有关联码、过滤里没有 → 关联判定会漏判（比漏派更隐蔽）
            got_corr = {norm_code(engine.val(r.get("alarmcode"))) for r in corr_rows}
            corr_missed = sorted(correlation_codes - got_corr)
            full_corr_codes = {norm_code(engine.val(r.get("alarmcode"))) for r in full_corr}
            corr_real = [c for c in corr_missed if c in full_corr_codes]
            if corr_real:
                diag["missed_codes"] = sorted(set(diag["missed_codes"]) | set(corr_real))
                logger.error(
                    "[5G] ⚠ 全量审计发现关联码 %s 被 restype 配置漏掉 → 关联判定会漏判",
                    ", ".join(corr_real))
            # 审计结果里的行补进集合（确保关联判定与派单判定看到完整数据）
            seen = {engine.alarm_key_of(r) for r in rows}
            for r in full_target + full_corr:
                if engine.alarm_key_of(r) not in seen:
                    rows.append(r)
                    seen.add(engine.alarm_key_of(r))
            target_rows = [r for r in rows
                           if norm_code(engine.val(r.get("alarmcode"))) in codes]
            corr_rows = [r for r in rows
                         if norm_code(engine.val(r.get("alarmcode"))) in correlation_codes]
        except Exception as e:  # noqa: BLE001
            logger.warning("[5G] 全量审计失败（忽略，不影响派单）: %s", e)

    return target_rows, {"diag": diag, "all_rows": rows, "corr_rows": corr_rows}
