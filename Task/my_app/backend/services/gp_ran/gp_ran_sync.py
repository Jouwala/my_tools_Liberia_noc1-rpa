"""gp_ran 定时任务：滚动取最近 N 天的 VoLTE / N78 用户身份（IMSI）清单。

任务 `gp_ran_user_sync` 的入口（worker 懒加载调用，无参数）。

口径与实测依据见同目录 README.md，几条硬事实：
* 数仓落库延迟约 **10 小时**（2026-10-19 实测：当时最新记录 05:44 UTC，本机已 16:06 UTC），
  所以 cron 排在 11:40 UTC —— 那时「上一个 UTC 自然日」才完整。
* 窗口按 **UTC 自然日左闭右开**：`[今天-N, 今天)`，只含已完整的日子，
  不含仍在累积的今天（否则数字每天在动，看板无法对账）。
* 清单是 **IMSI 不是 MSISDN**，且 85% 的明细行 D023 为空 —— 已在 SQL 里排掉。
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# 本机 stdout 默认 cp1252，打印中文会抛 UnicodeEncodeError（.qoder/rules/shell_safe.md §2）。
# worker 把任务日志重定向到文件时同样会踩，所以放在模块导入期而不是 __main__ 里。
# 同 backend/services/get_sp_table.py:54-58 的做法。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from . import gp_ran_store as store  # noqa: E402
from .gp_ran_client import (  # noqa: E402
    GpRanClient, GpRanError, GpRanUnavailable, sql_n78_users, sql_volte_users,
)

logger = logging.getLogger("gp_ran.sync")

DEFAULT_DAYS = 7
KINDS = {                      # kind -> (中文名, SQL 生成器)
    "volte": ("VoLTE", sql_volte_users),
    "n78": ("N78 频段", sql_n78_users),
}
# 本次 users 低于历史中位数的这个比例就判定为上游缺数（数仓忠实反映上游，不代表真没人用）
SHORTFALL_RATIO = 0.5
EPOCH_2000 = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _window(days: int) -> tuple[str, str]:
    """最近 N 个**完整** UTC 日：[今天-N, 今天)。"""
    today = datetime.now(timezone.utc).date()
    return ((today - timedelta(days=days)).isoformat(), today.isoformat())


def _resolve_days(days: Optional[int] = None) -> int:
    """窗口天数：显式参数 > 环境变量 GP_RAN_WINDOW_DAYS > 默认 7。

    只有 `None` 才算「没传」（写成 `if days` 会让 days=0 悄悄回落到 7，
    而 days=-5 却被夹到 1 —— 两个相邻输入行为不一致，测试 test_resolve_days_clamps 守住这里）。
    """
    raw = days if days is not None else os.environ.get("GP_RAN_WINDOW_DAYS")
    try:
        val = int(raw) if raw not in (None, "") else DEFAULT_DAYS
    except (TypeError, ValueError):
        val = DEFAULT_DAYS
    return min(max(val, 1), 60)          # 最早分区只到约 62 天前，超了必然取到空


def _epoch_to_iso(epoch: Any) -> str:
    try:
        return (EPOCH_2000 + timedelta(seconds=int(float(epoch)))).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError):
        return ""


def _window_stats(client: GpRanClient, start: str, end: str) -> tuple[Optional[int], str]:
    """窗口内的明细行数与最大记录时间（数仓上游体检，与 kind 无关）。"""
    sql = ("SELECT count(*) AS rows, max(A.D027) AS last_epoch FROM L_T216 A "
           f"WHERE A.D027 >= EXTRACT(EPOCH FROM ('{start}'::TIMESTAMP - "
           f"TIMESTAMP '2000-01-01 00:00:00')) "
           f"AND A.D027 < EXTRACT(EPOCH FROM ('{end}'::TIMESTAMP - "
           f"TIMESTAMP '2000-01-01 00:00:00'))")
    out = client.exec_sql(sql).strip().splitlines()
    if not out:
        return None, ""
    parts = out[-1].split(",")
    rows = int(parts[0]) if parts and parts[0].strip().lstrip("-").isdigit() else None
    return rows, _epoch_to_iso(parts[1] if len(parts) > 1 else "")


def _write_csv(text: str, dest: Path) -> int:
    """先写 .part 再原子替换，避免半截文件被当成一次完整产物下载走。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.part"
    tmp.write_text(text, encoding="utf-8-sig", newline="")
    tmp.replace(dest)
    return max(text.count("\n") - 1, 0)


def run_gp_ran_user_sync(days: Optional[int] = None) -> Dict[str, Any]:
    """取最近 N 天的 VoLTE / N78 IMSI 清单，落 CSV + 运行记录。返回任务结果字典。"""
    t_all = time.time()
    days_n = _resolve_days(days)
    start, end = _window(days_n)
    store.init_store()
    result: Dict[str, Any] = {
        "success": True,
        "message": "",
        "window_start": start,
        "window_end": end,
        "days": days_n,
        "kinds": {},
        "warnings": [],
    }
    print(f"[gp_ran] 窗口 {start} ~ {end}（{days_n} 个完整 UTC 日，不含当天）")

    rows_scanned: Optional[int] = None
    data_last = ""
    try:
        with GpRanClient() as client:
            # 先拿窗口体检值：它和 kind 无关，且要写进下面每条运行记录里
            try:
                rows_scanned, data_last = _window_stats(client, start, end)
                result["rows_scanned"] = rows_scanned
                result["data_last"] = data_last
                print(f"[gp_ran] 窗口明细 {rows_scanned} 行，最新记录 {data_last}")
            except (GpRanError, GpRanUnavailable) as exc:
                print(f"[gp_ran] 窗口体检查询失败（不影响清单）: {exc}")

            for kind, (label, builder) in KINDS.items():
                sql = builder(start, end)
                dest = store.DATA_DIR / f"{kind}_{start}_{end}.csv"
                t0 = time.time()
                try:
                    text = client.query_csv(sql)
                    users = _write_csv(text, dest)
                    result["kinds"][kind] = {
                        "label": label, "users": users, "csv": str(dest),
                        "bytes": dest.stat().st_size, "seconds": round(time.time() - t0, 1),
                        "status": "ok",
                    }
                    store.record_run(kind=kind, window_start=start, window_end=end,
                                     users=users, csv_path=str(dest),
                                     csv_bytes=dest.stat().st_size,
                                     seconds=time.time() - t0, status="ok",
                                     rows_scanned=rows_scanned, data_last=data_last)
                    print(f"[gp_ran] {label}: {users} 个 IMSI → {dest.name} "
                          f"（{dest.stat().st_size / 1048576:.1f} MB, {time.time() - t0:.1f}s）")
                except (GpRanError, GpRanUnavailable) as exc:
                    result["kinds"][kind] = {"label": label, "status": "error",
                                             "detail": str(exc)[:300]}
                    store.record_run(kind=kind, window_start=start, window_end=end,
                                     users=0, status="error", detail=str(exc)[:500],
                                     rows_scanned=rows_scanned, data_last=data_last)
                    result["success"] = False
                    print(f"[gp_ran] {label} 取数失败: {exc}")
    except (GpRanUnavailable, GpRanError) as exc:
        result["success"] = False
        result["message"] = f"Greenplum 链路失败：{exc}"
        print(f"[gp_ran] {result['message']}")
        return _finish(result, t_all)

    # 缺数体检：本次数量与历史中位数比，掉太多说明上游缺数而不是真没人用
    for kind, info in result["kinds"].items():
        if info.get("status") != "ok":
            continue
        med = store.median_users(kind, end)
        if med and info["users"] < med * SHORTFALL_RATIO:
            warn = (f"{KINDS[kind][0]} 本次 {info['users']} 个 IMSI，低于近 8 次中位数 {med} 的 "
                    f"{SHORTFALL_RATIO:.0%}（{info['users'] / med:.1%}）—— "
                    f"多半是数仓上游缺数，不是真实用户减少")
            result["warnings"].append(warn)
            print(f"[gp_ran][警告] {warn}")

    if result["success"]:
        ok_txt = "，".join(f"{KINDS[k][0]} {v['users']}" for k, v in result["kinds"].items())
        result["message"] = f"gp_ran {days_n} 天清单完成：{ok_txt}（窗口 {start}~{end}）"
    return _finish(result, t_all)


def _finish(result: Dict[str, Any], t_all: float) -> Dict[str, Any]:
    """收尾：CSV 保留期清理 + 总耗时（本项目要求全程可见运行时长）。"""
    try:
        purge = store.purge_files()
        if purge.get("deleted"):
            result["purged"] = purge
            print(f"[gp_ran] 保留期清理：删除 {purge['deleted']} 个旧 CSV，保留 {purge['kept']} 个")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[gp_ran] 清理旧 CSV 失败（不影响本次结果）: %s", exc)
    result["seconds"] = round(time.time() - t_all, 1)
    print(f"[gp_ran] 总耗时 {result['seconds']}s")
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run_gp_ran_user_sync(), ensure_ascii=False, indent=2))
