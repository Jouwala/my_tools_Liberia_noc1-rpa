# -*- coding: utf-8 -*-
"""eFlow 推单规则批量检查 —— 定时任务入口（每周一次）

为什么要做成定时任务：规则改了以后「派单会怎么变」要能**跨周对比**，
单次运行只能看到当下的规则 vs 实际结果。每周留存一份快照，
页面就能选两次运行对比，看清规则变更前后逐单判定的差异。

流程：
  1. 先用 eFlow 最新的推单规则刷新 eflow_push_rules.xlsx
     （子进程跑 eflow_Push_Rule_Collector，失败则降级用已有文件继续检查）
  2. 对与 `eflow_tt_rules_check` 同一批样本（created_time 最新 1000 条、alarm_code 非空）
     套用 FOAccept 推单规则，逐单给出规则判定 / 实际派单 / 一致性分类
  3. 导出 eflow_push_rules_check.xlsx（All_TT_Records + Rule_Hits）
  4. 摘要落盘 eflow_push_rules_check_latest.json，并在 push_rules_snapshots/ 留一份周快照

注册见 backend/task_registry.py 的 TASK_SPECS
（task_id=eflow_push_rules_check，cron=`10 5 * * 2`，即每周二 05:10 ——
排在周一 23:59 的推单规则收集之后，保证对比的是刚收集到的最新规则）。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).resolve().parent
COLLECTOR_SCRIPT = _RULES_DIR / "eflow_Push_Rule_Collector.py"
PUSH_RULES_XLSX = _RULES_DIR / "eflow_push_rules.xlsx"
SUMMARY_JSON = _RULES_DIR / "eflow_push_rules_check_latest.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def _refresh_push_rules() -> dict:
    """子进程运行推单规则收集器刷新 xlsx。best-effort：失败不抛，降级用已有文件。

    eFlow 不可达时 collector 内的 login() 可能长时间挂起，超时后降级继续检查。
    超时可由环境变量 EFLOW_PUSH_RULES_COLLECT_TIMEOUT（秒）覆盖，默认 300。
    """
    if not COLLECTOR_SCRIPT.is_file():
        return {"success": False, "error": "收集器脚本不存在",
                "rules_file_exists": PUSH_RULES_XLSX.exists()}
    timeout = 300
    try:
        timeout = max(30, int(os.environ.get("EFLOW_PUSH_RULES_COLLECT_TIMEOUT", "300")))
    except ValueError:
        pass
    try:
        proc = subprocess.run(
            [sys.executable, str(COLLECTOR_SCRIPT)],
            cwd=str(_RULES_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "rules_file": str(PUSH_RULES_XLSX),
            "rules_file_exists": PUSH_RULES_XLSX.exists(),
        }
    except subprocess.TimeoutExpired:
        logger.warning(f"推单规则收集超时（{timeout}s），降级使用已有规则文件")
        return {"success": False, "error": f"collector timeout after {timeout}s",
                "rules_file_exists": PUSH_RULES_XLSX.exists()}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"推单规则收集异常: {e}")
        return {"success": False, "error": f"{type(e).__name__}: {e}",
                "rules_file_exists": PUSH_RULES_XLSX.exists()}


def run_eflow_push_rules_check(limit: int = 1000) -> dict:
    """定时任务函数：刷新推单规则 → 批量评估 → 落盘摘要 + 周快照。"""
    logger.info("eflow_push_rules_check 开始：刷新推单规则 + 检查最新 %s 条 eflow_tt", limit)
    t0 = time.perf_counter()

    rules_collected = _refresh_push_rules()
    if not rules_collected.get("success"):
        logger.warning("推单规则收集失败，降级使用已有规则文件继续检查")

    try:
        from backend.services.eflow_rules.eflow_push_rules_checker import check_all
        summary = check_all(limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.exception("eflow_push_rules_check 评估阶段失败")
        summary = {
            "success": False,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "limit": limit,
            "error": f"{type(e).__name__}: {e}",
        }

    summary["rules_collected"] = rules_collected
    summary["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
    try:
        _atomic_write_json(SUMMARY_JSON, summary)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"eflow_push_rules_check 摘要落盘失败: {e}")

    logger.info(
        "eflow_push_rules_check 完成：total=%s correct=%s mismatch=%s undecidable=%s unmatched=%s",
        summary.get("total"),
        (summary.get("counts") or {}).get("correct"),
        (summary.get("counts") or {}).get("mismatch"),
        (summary.get("counts") or {}).get("undecidable"),
        (summary.get("counts") or {}).get("unmatched"),
    )
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = run_eflow_push_rules_check(limit=1000)
    print(json.dumps({k: v for k, v in r.items() if k != "rule_breakdown"},
                     ensure_ascii=False, indent=2))
