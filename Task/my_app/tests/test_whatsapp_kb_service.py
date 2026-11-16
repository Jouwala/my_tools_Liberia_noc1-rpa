# -*- coding: utf-8 -*-
"""WhatsApp 知识库同步的「4 小时挂死」回归测试（whatsapp_kb_service）。

## 为什么需要这个文件

2026-11-04 / 11-05 / 11-06 各出现一次同步任务卡死 4 小时（任务日志：
`elapsed=6324.41s`、`Worker 进程已失效`，正常全量同步只要 240~260s）。
根因不是同步慢，而是 `subprocess.run(capture_output=True)` 的**管道写端被孙进程继承**：
`scripts/sync-kb.mjs` 用 `spawnSync(..., {stdio:'inherit'})` 起 `npm.cmd` / `powershell`
（后者再经 `autostart.ps1` 拉起常驻 bot），孙进程一直活着 → 管道永远等不到 EOF →
`communicate()` 卡住；`timeout` 只在读管道时检查，于是「超时已判定」之后清理阶段仍无限等待。

修复（2026-11-06，commit f4e8bc6d）把 stdout/stderr 改落**临时文件**。文件没有 EOF 语义，
所以哪怕孙进程还持有句柄，`subprocess.run` 也只在直接子进程退出后返回。

这里锁住三条不变量，防止有人“顺手”改回 capture_output：

1. 传给 `subprocess.run` 的 stdout/stderr 必须是**文件对象**，且不能用 `capture_output` / `PIPE`；
2. 孙进程持着继承来的输出句柄时，函数仍能很快返回（不挂死）；
3. `timeout` 恢复正常语义：子进程超时被杀后函数按时返回，不再卡在清理阶段。

注意：`Task/whatsapp-kb-bot/autostart.ps1` 里给 bot 的 `Start-Process` 加
`-RedirectStandardOutput/-RedirectStandardError` 属于**反方向**改动（重定向会强制
`UseShellExecute=false` + `bInheritHandles=TRUE`，让常驻进程继承调用方的管道写端）。
真正的修复在 my_app 侧，不在那个脚本里。
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import whatsapp_kb_service as wks  # noqa: E402

NODE = shutil.which("node")


def _write_fake_bot(root: Path, sync_js: str) -> Path:
    """在临时目录里造一个最小 bot 目录（只需要 scripts/sync-kb.mjs）。"""
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "sync-kb.mjs").write_text(sync_js, encoding="utf-8")
    return root


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError, AttributeError):
        pass


def test_subprocess_gets_files_not_pipes(tmp_path, monkeypatch):
    """不变量 1：输出必须落文件，不能是 capture_output / PIPE。"""
    bot = _write_fake_bot(tmp_path, "process.exit(0);\n")
    captured = {}

    class FakeProc:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        captured["_cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(wks.subprocess, "run", fake_run)
    monkeypatch.setenv("WHATSAPP_KB_DIR", str(bot))

    result = wks.sync_knowledge_base()

    assert result["success"] is True, result
    assert "capture_output" not in captured, "回潮成 capture_output=True：管道写端会被孙进程继承"
    for name in ("stdout", "stderr"):
        handle = captured[name]
        assert hasattr(handle, "name"), f"{name} 必须是文件对象，而不是 subprocess.PIPE"
        assert handle.closed, f"{name} 临时文件句柄没有关闭"
    assert captured["stdin"] == subprocess.DEVNULL
    # 临时文件必须删掉，不能在 %TEMP% 里越攒越多
    assert not os.path.exists(captured["stdout"].name)
    assert not os.path.exists(captured["stderr"].name)


@pytest.mark.skipif(NODE is None, reason="需要本机有 node 才能造出长命孙进程")
def test_grandchild_holding_stdio_does_not_hang(tmp_path, monkeypatch):
    """不变量 2：孙进程持着继承来的输出句柄时，sync 仍必须秒级返回。

    复现形状与真实链路同构：sync-kb.mjs 先起一个 detached 长命 node（stdio 继承），
    然后自己立刻退出。修复前：capture_output 的管道写端被长命进程持有 → 永不 EOF。
    """
    pidfile = tmp_path / "grandchild.pid"
    grandchild = (
        "import { spawn } from 'node:child_process';\n"
        "import { writeFileSync } from 'node:fs';\n"
        "const c = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'],\n"
        "  { stdio: 'inherit', detached: true, windowsHide: true });\n"
        "c.unref();\n"
        f"writeFileSync({json.dumps(str(pidfile))}, String(c.pid));\n"
        "console.log('✓ 知识库同步完成');\n"
        "process.exit(0);\n"
    )
    bot = _write_fake_bot(tmp_path, grandchild)
    monkeypatch.setenv("WHATSAPP_KB_DIR", str(bot))

    box = {}

    def run_sync():
        box["result"] = wks.sync_knowledge_base()

    thread = threading.Thread(target=run_sync, daemon=True)
    started = time.time()
    thread.start()
    thread.join(15)

    pid = 0
    try:
        if pidfile.exists():
            pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0

    if thread.is_alive():
        # 释放管道让旧实现能收尾，再把测试判成失败（而不是把整个测试套件挂住）
        if pid:
            _kill_pid(pid)
        thread.join(10)
        pytest.fail("sync_knowledge_base 仍在等继承管道 EOF —— 疑似回潮成 capture_output 写法")

    elapsed = time.time() - started
    assert elapsed < 10, f"sync 耗时 {elapsed:.1f}s，明显被孙进程拖住了"
    assert box["result"]["success"] is True, box["result"]
    _kill_pid(pid)


def test_timeout_still_kills_and_returns(tmp_path, monkeypatch):
    """不变量 3：子进程超时被杀后必须按时返回，不能卡在清理阶段。"""
    assert NODE is not None, "需要本机有 node"
    bot = _write_fake_bot(tmp_path, "setTimeout(() => {}, 30000);\n")
    monkeypatch.setenv("WHATSAPP_KB_DIR", str(bot))
    monkeypatch.setattr(wks, "_SYNC_TIMEOUT_SEC", 2)

    started = time.time()
    result = wks.sync_knowledge_base()
    elapsed = time.time() - started

    assert result["success"] is False
    assert "同步超时" in result["error"]
    assert elapsed < 15, f"超时后仍耗时 {elapsed:.1f}s，清理阶段被管道 EOF 拖住了"


def test_skip_detection_from_file_output(tmp_path, monkeypatch):
    """输出落文件后，「未变化，跳过」的判定仍要生效。"""
    bot = _write_fake_bot(tmp_path, "console.log('✓ 规则源文件自上次同步后未变化，跳过');\n")
    monkeypatch.setenv("WHATSAPP_KB_DIR", str(bot))

    result = wks.sync_knowledge_base()

    assert result["success"] is True
    assert result["skipped"] is True


def test_prune_removes_only_old_temp_files(tmp_path, monkeypatch):
    """被常驻进程占住而删不掉的临时文件，下一轮同步要能清掉（只清自己 1 小时前的）。"""
    monkeypatch.setattr(wks.tempfile, "gettempdir", lambda: str(tmp_path))
    old = tmp_path / f"{wks._TEMP_PREFIX}old.out"
    fresh = tmp_path / f"{wks._TEMP_PREFIX}fresh.out"
    unrelated = tmp_path / "not_ours.out"
    for path in (old, fresh, unrelated):
        path.write_text("x", encoding="utf-8")
    past = time.time() - wks._TEMP_KEEP_SEC - 60
    os.utime(old, (past, past))
    os.utime(unrelated, (past, past))

    wks._prune_stale_temp()

    assert not old.exists(), "上一轮的旧临时文件没被清掉"
    assert fresh.exists(), "本轮刚创建的临时文件不能被误删"
    assert unrelated.exists(), "不是本模块的文件不能动"


# --------------------------------------------------------------------------- #
# 2026-11-16：失败原因必须可读，且带目标地址（自愈链路依赖它）
# --------------------------------------------------------------------------- #

def test_failure_headline_takes_last_cross_line():
    """多条 ✗ 时取**最后**一条：ingest 的 ✗ 在前，同步脚本汇总的 ✗ 才是结论。"""
    stdout = "[1/4] 预检…\n✗ Ollama /api/tags 超时（10000ms）\n✗ 索引重建失败（exit=1）\n"
    assert wks._failure_headline(stdout, "") == "索引重建失败（exit=1）"


def test_failure_headline_falls_back_to_failure_line():
    assert wks._failure_headline("", "npm ERR! 构建失败\n") == "npm ERR! 构建失败"
    assert wks._failure_headline("", "") == ""


def test_compose_error_keeps_url_from_tail():
    """error 里没有地址、但输出里有 → 补上「目标 …」。

    没有这条，auto_retry 的探测门控就提不到 host:port，只能按冷却烧额度
    （2026-11-16 就是这样在 1 小时内烧光 2 次重试的）。
    """
    stdout = (
        "✗ 规则源文件缺失：eflow_TT_rules.xlsx\n"
        "  请确认 http://192.168.100.27:11434 可达\n"
    )
    error = wks._compose_error(stdout, "", 1)
    assert error.startswith("规则源文件缺失")
    assert "目标 http://192.168.100.27:11434" in error


def test_compose_error_does_not_duplicate_url():
    line = "✗ 索引重建失败（exit=1）：Ollama 嵌入服务 http://192.168.100.27:11434 不可用或超时"
    error = wks._compose_error(line + "\n", "", 1)
    assert error.count("http://192.168.100.27:11434") == 1


def test_compose_error_falls_back_to_exit_code():
    assert wks._compose_error("", "", 7) == "exit=7"


def test_compose_error_is_capped():
    long_line = "✗ " + "很长的原因" * 100
    assert len(wks._compose_error(long_line, "", 1)) <= wks._HEADLINE_MAX


def test_task_result_error_is_not_bare_exit_code(tmp_path, monkeypatch):
    """端到端形状：子进程退出 1 时，任务结果里的 error 要能直接看懂。"""
    script = (
        "console.log('[1/4] 检查 Ollama…');\n"
        "console.error('✗ 索引重建失败（exit=1）：Ollama 嵌入服务 "
        "http://192.168.100.27:11434 不可用或超时');\n"
        "process.exit(1);\n"
    )
    bot = _write_fake_bot(tmp_path, script)
    monkeypatch.setenv("WHATSAPP_KB_DIR", str(bot))

    result = wks.sync_knowledge_base()

    assert result["success"] is False
    assert result["error"] != "exit=1", "Run History 上不能只显示裸 exit=1"
    assert "索引重建失败" in result["error"]
    assert "http://192.168.100.27:11434" in result["error"]
    assert result["exit_code"] == 1


def test_error_is_probe_gated_by_auto_retry():
    """拼出来的 error 必须落进 auto_retry 的「网络类 + 可提取目标」分支。

    这是「嵌入机凌晨不在线 → 知识库陈旧一整天」的自愈契约：
    网络类才会走 TCP 探测门控，探测到目标不可达时**跳过重试且不消耗额度**；
    提不到 host:port 就只能按冷却烧额度（2026-11-16 就是这样烧光的）。
    改 `NETWORK_ERROR_KEYS` 或改报错文案都可能悄悄破坏它，所以钉成测试。
    """
    from backend.services import auto_retry as ar

    line = "✗ 索引重建失败（exit=1）：Ollama 嵌入服务 http://192.168.100.27:11434 不可用或超时"
    error = wks._compose_error(line + "\n", "", 1)

    assert ar._classify_error(error) == "network"
    assert ("192.168.100.27", 11434) in ar._extract_targets(error)
    # 命中永久性错误会让 auto_retry 直接放弃重试
    assert not any(k in error for k in ar.NON_RETRYABLE_KEYS)


