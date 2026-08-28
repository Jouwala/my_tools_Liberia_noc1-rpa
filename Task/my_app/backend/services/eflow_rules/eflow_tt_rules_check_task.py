# -*- coding: utf-8 -*-
"""eFlow TT 规则收集 + 匹配检查 —— 定时任务入口（每天 04:20）

完整流程（全部在本任务内完成）：
  1. 从 eFlow API 拉取激活的 TT Update Severity Rule → eflow_TT_rules.xlsx
     （子进程运行 eflow_TT_Rule_Collector.py，隔离其 os.chdir / logging 副作用；
       收集失败则降级使用已有规则文件继续检查，不中断整个任务）
  2. 用最新规则对最新 1000 条 eflow_tt 记录做匹配与级别矫正
     → eflow_tt_severity_correction.xlsx + MATCHING_REPORT.md
  3. 摘要落盘 eflow_tt_rules_check_latest.json，供 Email Reports 页 eflow_tt_rules_check 页签展示

注册见 backend/task_registry.py 的 TASK_SPECS（task_id=eflow_tt_rules_check, cron=20 4 * * *）。
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
COLLECTOR_SCRIPT = _RULES_DIR / "eflow_TT_Rule_Collector.py"
RULES_XLSX = _RULES_DIR / "eflow_TT_rules.xlsx"
SUMMARY_JSON = _RULES_DIR / "eflow_tt_rules_check_latest.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def _refresh_rules() -> dict:
    """子进程运行规则收集器，刷新 eflow_TT_rules.xlsx。best-effort：失败不抛。

    超时可由环境变量 EFLOW_RULES_COLLECT_TIMEOUT（秒）覆盖，默认 180。
    eFlow 不可达时 login() 可能长时间挂起，超时后降级使用已有规则文件继续检查。
    """
    if not COLLECTOR_SCRIPT.is_file():
        return {"success": False, "error": "收集器脚本不存在", "rules_file_exists": RULES_XLSX.exists()}
    timeout = 180
    try:
        timeout = max(30, int(os.environ.get("EFLOW_RULES_COLLECT_TIMEOUT", "180")))
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
        ok = proc.returncode == 0
        return {
            "success": ok,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "rules_file": str(RULES_XLSX),
            "rules_file_exists": RULES_XLSX.exists(),
        }
    except subprocess.TimeoutExpired:
        logger.warning(f"规则收集子进程超时（{timeout}s），降级使用已有规则文件")
        return {
            "success": False,
            "error": f"collector timeout after {timeout}s",
            "rules_file_exists": RULES_XLSX.exists(),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"规则收集子进程异常: {e}")
        return {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "rules_file_exists": RULES_XLSX.exists(),
        }


def _rules_count() -> int | None:
    """读取规则 Excel 行数（规则条数）。"""
    try:
        import pandas as pd
        return int(len(pd.read_excel(RULES_XLSX)))
    except Exception:
        return None


def run_eflow_tt_rules_check(limit: int = 1000) -> dict:
    """定时任务函数：取规则 → 匹配检查 → 落盘摘要。

    返回可序列化摘要。规则收集失败时降级用已有规则继续检查（摘要中 rules_collected.success=False）。
    """
    logger.info("eflow_tt_rules_check 开始：刷新规则 + 检查最新 %s 条 eflow_tt", limit)
    t0 = time.perf_counter()

    # Step 1: 从 eFlow 获取最新规则
    rules_collected = _refresh_rules()
    if not rules_collected.get("success"):
        logger.warning("规则收集失败，降级使用已有规则文件继续检查")
    rules_count = _rules_count()

    # Step 2: 匹配检查（用最新/已有规则）
    summary: dict
    try:
        from backend.services.eflow_rules.eflow_rules_matcher import run as _run_match
        summary = _run_match(limit=limit)
    except Exception as e:  # noqa: BLE001
        logger.exception("eflow_tt_rules_check 匹配阶段失败")
        summary = {
            "success": False,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "limit": limit,
            "error": f"{type(e).__name__}: {e}",
        }
        summary["rules_collected"] = rules_collected
        summary["rules_count"] = rules_count
        summary["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
        try:
            _atomic_write_json(SUMMARY_JSON, summary)
        except Exception:  # noqa: BLE001
            logger.warning("eflow_tt_rules_check 失败摘要落盘失败")
        return summary

    # Step 3: 合并规则收集信息并落盘
    summary["rules_collected"] = rules_collected
    summary["rules_count"] = rules_count
    summary["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
    try:
        _atomic_write_json(SUMMARY_JSON, summary)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"eflow_tt_rules_check 摘要落盘失败: {e}")

    logger.info(
        "eflow_tt_rules_check 完成：rules=%s total=%s matched=%s changed=%s",
        rules_count, summary.get("total"), summary.get("matched"), summary.get("changed"),
    )
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = run_eflow_tt_rules_check(limit=1000)
    print(json.dumps(r, ensure_ascii=False, indent=2))
