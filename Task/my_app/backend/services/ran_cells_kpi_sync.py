# -*- coding: utf-8 -*-
r"""RAN 2G/3G/4G Cells KPI 每日同步任务。

职责（两步）：
  1) 从 RAN_UME 拉取「小区级」可用率数据 → 复用 backend.services.ran_cell_availability_sync
     的既有获取方法（FDD/UMTS/GSM/TDD 4 模板，1 天粒度），UPSERT 写入
     data/ran_kpi_avalability_1day.sqlite3（与既有 cell_availability_sync 任务同一份原始库）。
  2) 按 Cells KPI 口径聚合当月每日指标（Total / Meeting / Below / Blank / % / Availability），
     物化写入 data/ran_cells_kpi.sqlite3 的 cells_kpi_daily 表，**只保留当月数据**。

看板读取顺序：物化库 → （缺失时）实时聚合原始库。

作为 my_app 定时任务注册：task_id = cells_kpi_sync（每天 04:50，紧跟小区可用性同步之后）。
"""
import json
import logging
import time
from datetime import datetime

from backend.services import ran_cells_kpi_service as kpi
from backend.services import ran_cell_availability_sync as avail

logger = logging.getLogger(__name__)


def _is_month_start_pending(month: str, today: datetime = None) -> bool:
    """本月的空窗是否属于「月初本就无数据可算」这种**预期**情况。

    ## 背景（2026-10-01 事故）

    本任务每天 04:50 跑，物化 `current_month()`。

    **根因不是「数据延迟」，而是天粒度数据的固有性质**：小区可用率是**按天**统计的，
    一行代表「某个小区在某个自然日」的表现，靠 `Begin Time` 归属该自然日
    （已实测 `End Time - 1day == Begin Time`，360 万行全等，故 Begin 就是所覆盖的那一天）。
    **一天没过完，就算不出这一天的数据**，所以任何时刻能取到的最新一天，
    必然是昨天 —— 这不是上游慢了，是「今天」这个数据点此刻还不存在。

    于是在**每月 1 号** 04:50 运行时，本月（10 月）窗口内**必然一行都没有**：
    窗口要找「10/1 这一天」，而 10/1 还没过完。旧代码把这个空窗当成失败
    （`success = rows > 0`），导致每月 1 号稳定报失败并触发微信 + 邮件告警 ——
    这是**误报**，不是真故障，但它会让真正的故障淹没在噪声里。

    > 用「延迟」来描述这件事会误导人：听起来像「上游没及时发，等等就好」，
    > 从而有人会去加长重试或改窗口。实际是当天的数**在当天根本不存在**，
    > 重试多少次都一样 —— 必须靠判据识别，而不是靠等待。

    判据（必须同时满足，避免把真故障误判成预期）：
      1. `month` 是**当前自然月**（历史月份为空是真故障，不能放过）；
      2. 今天是**该月 1 号**（只有这一天，本月窗口才可能存在"当天尚未结束"的必然空窗）。

    月初之后的任何一天若仍为空，按真故障处理 —— 那时每一天都已过完，空就是漏采。
    """
    now = today or datetime.now()
    cur_month = f"{now.year}-{now.month:02d}"
    return month == cur_month and now.day == 1


def run_cells_kpi_sync(window_days: int = 2, fetch_raw: bool = True,
                       do_upload: bool = False, month: str = None) -> dict:
    """my_app 定时任务入口。

    Args:
        window_days: 从 RAN_UME 拉取的窗口天数（默认 2 天，覆盖昨天+今天）。
        fetch_raw:   是否先拉取原始小区可用率数据（复用既有 UME 获取方法）。
        do_upload:   拉取后是否 FTP 上传原始库（默认否——由 cell_availability_sync 负责）。
        month:       物化的统计月份 YYYY-MM，默认当月。

    Returns:
        dict: {success, month, fetch, materialize, errors, elapsed_seconds}
              `month_pending=True` 表示月初的正常空窗（本月第一天尚未结束，
              天粒度数据此刻算不出），此时 `success=True` 且 `errors` 为空 —— 它不是失败。
    """
    t0 = time.time()
    month = month or kpi.current_month()
    result = {
        "success": False,
        "month": month,
        "fetch": None,
        "materialize": None,
        "errors": [],
        "elapsed_seconds": 0,
    }

    # ---------- 1) 从 RAN_UME 获取小区数据 ----------
    if fetch_raw:
        try:
            fetch_res = avail.run_cell_availability_sync(
                window_days=window_days, do_upload=do_upload)
            result["fetch"] = {
                "success": fetch_res.get("success"),
                "rows": fetch_res.get("rows"),
                "tables": fetch_res.get("tables"),
                "errors": fetch_res.get("errors"),
            }
            if not fetch_res.get("success"):
                result["errors"].append(
                    "RAN_UME 小区数据拉取未完全成功: %s" % (fetch_res.get("errors") or ""))
        except Exception as e:  # 拉取失败仍尝试用现有原始库物化
            logger.exception("[CELLS-KPI] 拉取原始数据失败: %s", e)
            result["errors"].append(f"拉取原始数据异常: {e}")
    else:
        logger.info("[CELLS-KPI] 跳过 RAN_UME 拉取（fetch_raw=False），直接使用现有原始库")

    # ---------- 2) 聚合 + 物化（只保留当月） ----------
    try:
        mat = kpi.write_month_to_db(month)
        result["materialize"] = mat
        if not mat.get("rows"):
            if _is_month_start_pending(month):
                # 月初窗口：本月第一天还没过完，算不出这一天的天粒度数据，
                # 故本月必然为空。属**预期**而非故障，详见 _is_month_start_pending。
                result["month_pending"] = True
                result["message"] = (
                    f"{month} 月初：本月第一天尚未结束，天粒度数据此刻还无法算出，"
                    f"本轮无可物化数据 —— 属预期，非故障（次日凌晨起本任务会正常产出）")
                logger.info("[CELLS-KPI] %s", result["message"])
            else:
                result["errors"].append(f"{month} 无有效小区数据，物化 0 行")
    except Exception as e:
        logger.exception("[CELLS-KPI] 物化失败: %s", e)
        result["errors"].append(f"物化失败: {e}")

    # 成功判据：物化出数据 **或** 月初的正常空窗期（后者不算失败）。
    # 旧写法只看 rows>0，导致每月 1 号必然报失败并触发微信/邮件告警（2026-10-01 事故）。
    result["success"] = bool((result["materialize"] or {}).get("rows", 0) > 0
                             or result.get("month_pending"))
    result["elapsed_seconds"] = round(time.time() - t0, 2)
    logger.info("[CELLS-KPI] 完成 month=%s rows=%s %.2fs success=%s errors=%s",
                month, (result["materialize"] or {}).get("rows"),
                result["elapsed_seconds"], result["success"], result["errors"])
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAN 2G/3G/4G Cells KPI 每日同步")
    parser.add_argument("--window-days", type=int, default=2, help="RAN_UME 拉取窗口天数")
    parser.add_argument("--no-fetch", action="store_true", help="不拉取原始数据，只用现有库物化")
    parser.add_argument("--upload", action="store_true", help="拉取后 FTP 上传原始库")
    parser.add_argument("--month", default=None, help="统计月份 YYYY-MM（默认当月）")
    args = parser.parse_args()

    res = run_cells_kpi_sync(window_days=args.window_days, fetch_raw=not args.no_fetch,
                             do_upload=args.upload, month=args.month)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
