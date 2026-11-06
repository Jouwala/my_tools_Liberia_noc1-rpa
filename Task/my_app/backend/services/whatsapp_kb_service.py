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
import tempfile
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 知识库同步超时：含给 900 块重算向量（约 30~60s）+ 重启 bot 等握手（最长 60s），
# 留足余量。超时表明显出了问题，不应该无限等待。
_SYNC_TIMEOUT_SEC = int(os.environ.get("WHATSAPP_KB_SYNC_TIMEOUT", "420"))

# 临时输出文件的前缀与保留时长（见 _prune_stale_temp）。
_TEMP_PREFIX = "whatsapp_kb_sync_"
_TEMP_KEEP_SEC = 3600


def _prune_stale_temp() -> None:
    """尽力清掉以前几轮同步留下的临时输出文件。

    ## 为什么会有残留（2026-11-06 实测）

    stdout/stderr 落的是 `NamedTemporaryFile(delete=False)`，本该在 finally 里 os.unlink。
    但文件句柄会被**孙进程继承**：`scripts/sync-kb.mjs` 用 `spawnSync(..., {stdio:'inherit'})`
    起 npm / powershell，而 autostart.ps1 里的 `Start-Process -RedirectStandardOutput ...`
    会以 `bInheritHandles=TRUE` 启动常驻的 bot / http-server —— 常驻进程不退出，
    Windows 就不允许删除这些文件。实测一次真实全量同步后，`%TEMP%` 里会留下
    2 个 `whatsapp_kb_sync_*` 文件，要等下一次同步重启这些进程后才解锁。

    所以每轮同步**结束**时（此时上一轮常驻进程已被 stage 3 重启掉、句柄已释放）
    清掉 1 小时前的旧文件；本轮自己的文件刚创建，不会被误删，并发跑同步也不会动别人的。
    开头也清一次，兜住「上一轮是在别的进程里跑完的」这种情况。
    """
    cutoff = time.time() - _TEMP_KEEP_SEC
    try:
        base = tempfile.gettempdir()
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        if not name.startswith(_TEMP_PREFIX):
            continue
        path = os.path.join(base, name)
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
            os.unlink(path)
        except OSError:
            pass  # 仍被常驻进程占着 / 已被别人清掉 —— 都不影响本轮同步


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
    _prune_stale_temp()  # 顺手清掉上一轮被常驻进程占住、现在已解锁的临时输出
    root = _bot_root()
    script = os.path.join(root, "scripts", "sync-kb.mjs")
    if not os.path.isfile(script):
        msg = f"未找到同步脚本：{script}"
        logger.warning("whatsapp 知识库同步跳过 —— %s", msg)
        return {"success": False, "skipped": True, "error": msg}

    node = os.environ.get("NODE_EXE") or "node"
    cmd = [node, script] + (["--force"] if force else [])
    t0 = time.time()
    # 输出必须落**临时文件**而不是管道（2026-11-06 修复 4 小时挂死）。
    #
    # 原因：sync-kb.mjs 内部会用 stdio:'inherit' 把 stdout 原样传给自己的孙进程
    # （npm.cmd → ingest.js、powershell.exe → autostart.ps1 → Start-Process 起的
    # 常驻 bot）。孙进程继承了 Python 这个 capture_output 管道的**写端**，
    # 于是 python 侧 communicate() 永远等不到 EOF：
    #   · timeout 只在「读管道」时检查，管道不 EOF → 超时判定被架空；
    #   · 直接子进程其实早已退出（11-06 04:44:08 索引就重建好了），
    #     但父进程一直卡在读管道上，直到 4 小时后被 worker 看门狗当孤儿回收。
    # 实测：timeout=6s 被拖成 45.1s；生产上 11-04 那次 elapsed=6324s
    # （同步超时已判定，但清理阶段仍多等了 1h38m）。
    #
    # 改用文件承接输出后，subprocess 只等「直接子进程退出」，不再等管道 EOF，
    # timeout 恢复正常语义（实测 0.4s 返回）。文件句柄被孙进程继承也无妨 ——
    # 文件没有 EOF 语义。
    #
    # 保持默认二进制 w+b，不要加 encoding= —— 二进制模式下它直接抛
    # ValueError；字节→文本的解码统一交给 _read_text（utf-8 + replace）。
    out_f = tempfile.NamedTemporaryFile(prefix="whatsapp_kb_sync_", suffix=".out", delete=False)
    err_f = tempfile.NamedTemporaryFile(prefix="whatsapp_kb_sync_", suffix=".err", delete=False)
    try:
        try:
            proc = subprocess.run(
                cmd,
                cwd=root,
                stdout=out_f,
                stderr=err_f,
                stdin=subprocess.DEVNULL,
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
        stdout_text = _read_text(out_f.name)
        stderr_text = _read_text(err_f.name)
        # 到此 stage 3 已把上一轮常驻进程重启掉，它们占着的旧临时文件已解锁 —— 顺手清掉。
        _prune_stale_temp()
    finally:
        for f in (out_f, err_f):
            try:
                f.close()
            except OSError:
                pass
            try:
                os.unlink(f.name)
            except OSError:
                pass

    tail = _tail(stdout_text, stderr_text)
    if proc.returncode != 0:
        logger.error("whatsapp 知识库同步失败（exit=%s）：%s", proc.returncode, tail)
        return {
            "success": False,
            "error": f"exit={proc.returncode}",
            "output_tail": tail,
            "elapsed_sec": elapsed,
        }

    skipped = "未变化，跳过" in stdout_text
    logger.info("whatsapp 知识库同步完成（%s，%.1fs）", "无变化" if skipped else "已重建", elapsed)
    return {
        "success": True,
        "skipped": skipped,
        "output_tail": tail,
        "elapsed_sec": elapsed,
    }


def _read_text(path: str) -> str:
    """读回临时输出文件；读不到就返回空串（不能因为读日志失败而让整个同步失败）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


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
