# -*- coding: utf-8 -*-
"""让 WhatsApp 知识库跟上 eFlow 规则更新（定时任务调用）。

## 为什么是 my_app 来调 whatsapp-kb-bot

规则采集（`eflow_alarm_rules_collect` / `eflow_TT_rules_check` /
`eflow_push_rules_collect`）都跑在 my_app 里，落盘成
`backend/services/eflow_rules/*.xlsx`。而知识库是 whatsapp-kb-bot 的资产：
它的 `knowledge/*.md` 由 xlsx 导出、索引要靠 `npm run ingest` 重建、新索引
又必须**重启 bot 进程**才会被读进内存。

这三步此前全靠人手，规则更新后没人做，bot 就静默按旧规则回答 ——
2026-09-15 和 2026-10-23 各踩过一次。所以把它挂成任务：采集完就调
`whatsapp-kb-bot/scripts/sync-kb.mjs`，由那个脚本自己判断「这次有没有真的变」。

## 边界

* **不复制规则数据**：本模块只触发，不读 xlsx、不写 knowledge/。
* **失败不抛出**：知识库同步是旁路增强，失败只记录在返回值里，
  不应当让采集任务本身被标记为失败（采集成功是主任务）。
* **幂等**：没变化时 sync-kb.mjs 直接跳过，进程都不重启。
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 知识库同步超时：含给 900 块重算向量（约 30~60s）+ 重启 bot 等握手（最长 60s），
# 留足余量。超时表明显出了问题，不应该无限等待。
_SYNC_TIMEOUT_SEC = int(os.environ.get("WHATSAPP_KB_SYNC_TIMEOUT", "420"))


def _bot_root() -> str:
    """whatsapp-kb-bot 根目录；与任务仓库布局一致（`Task/my_app` 与 `Task/whatsapp-kb-bot` 并排）。

    可用环境变量 `WHATSAPP_KB_DIR` 覆盖（换机器、或 bot 不在仓库布局里时）。
    """
    override = os.environ.get("WHATSAPP_KB_DIR")
    if override:
        return override
    here = os.path.dirname(os.path.abspath(__file__))       # backend/services
    task_dir = os.path.abspath(os.path.join(here, "..", "..", ".."))  # Task/
    return os.path.join(task_dir, "whatsapp-kb-bot")


def sync_knowledge_base(force: bool = False) -> Dict[str, Any]:
    """触发知识库同步，返回结果摘要（**不抛异常**）。"""
    root = _bot_root()
    script = os.path.join(root, "scripts", "sync-kb.mjs")
    if not os.path.isfile(script):
        msg = f"未找到同步脚本：{script}"
        logger.warning("whatsapp 知识库同步跳过 —— %s", msg)
        return {"success": False, "skipped": True, "error": msg}

    node = os.environ.get("NODE_EXE") or "node"
    cmd = [node, script] + (["--force"] if force else [])
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SYNC_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        msg = f"同步超时（>{_SYNC_TIMEOUT_SEC}s）"
        logger.error("whatsapp 知识库同步失败 —— %s", msg)
        return {"success": False, "error": msg, "elapsed_sec": round(time.time() - t0, 1)}
    except OSError as e:
        logger.error("whatsapp 知识库同步启动失败 —— %s", e)
        return {"success": False, "error": f"启动失败：{e}"}

    elapsed = round(time.time() - t0, 1)
    tail = _tail(proc.stdout, proc.stderr)
    if proc.returncode != 0:
        logger.error("whatsapp 知识库同步失败（exit=%s）：%s", proc.returncode, tail)
        return {
            "success": False,
            "error": f"exit={proc.returncode}",
            "output_tail": tail,
            "elapsed_sec": elapsed,
        }

    skipped = "未变化，跳过" in proc.stdout
    logger.info("whatsapp 知识库同步完成（%s，%.1fs）", "无变化" if skipped else "已重建", elapsed)
    return {
        "success": True,
        "skipped": skipped,
        "output_tail": tail,
        "elapsed_sec": elapsed,
    }


def _tail(stdout: str, stderr: str, lines: int = 12) -> str:
    """取输出末尾若干行写入任务日志 —— 避免把几百行向量进度全塞进执行日志。"""
    merged = "\n".join(x for x in (stdout or "", stderr or "") if x).strip()
    if not merged:
        return ""
    return "\n".join(merged.splitlines()[-lines:])


# ---------------------------------------------------------------- #
# 定时任务入口
# ---------------------------------------------------------------- #

def run_whatsapp_kb_sync_after_push_rules() -> Dict[str, Any]:
    """跟在「推单规则收集」之后：规则变了就重建知识库并重启 bot。"""
    return sync_knowledge_base()


def run_whatsapp_kb_sync_after_alarm_rules() -> Dict[str, Any]:
    """跟在「告警规则收集」之后（压缩规则来自这份表）。"""
    return sync_knowledge_base()


def run_whatsapp_kb_sync_after_tt_rules() -> Dict[str, Any]:
    """跟在「TT 规则收集与匹配检查」之后（级别规则来自这份表）。"""
    return sync_knowledge_base()
