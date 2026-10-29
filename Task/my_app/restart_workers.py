#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""worker / worker_watchdog 规范化重启入口 —— **唯一入口，自带留痕**。

## 为什么要有这个脚本
2026-09-10 排查「09:56 四个 worker 同时退出」时，日志只能证明「同时退出」，
无法回答「是谁杀的」，最后靠 WorkBuddy 工具审计日志才定位到一条手敲的
`for g in u n m c; do taskkill //PID $p //T //F; done`。
本脚本把「重启 worker」这件事收敛成一个入口，并在动手前后写入
`log/worker_restart_marker.log`（谁 / 何时 / 杀哪些 pid / 为什么 / 新 pid 是谁），
配合 `worker_watchdog.py` 写出的 `worker_exit` / `worker_spawn`，
任何一次 worker 世代更替都能一眼归因。

## 用法
    # 看现状（pid / 存活 / 队列）
    python restart_workers.py --list

    # 看最近 20 条留痕
    python restart_workers.py --tail 20

    # 只重启 worker 子进程（watchdog 会在 ≤2s 内自动拉起 → 重新 import 改动后的 service 代码）
    python restart_workers.py --reason "重新加载 backend/services/whatsapp_service.py"

    # 只重启部分组
    python restart_workers.py --groups m --reason "只重载 m 组的截图链路"

    # 重启 watchdog 本身（env 变了才需要；经计划任务 MyApp_EnsureRunning 中继拉起）
    python restart_workers.py --mode watchdog --reason "MY_APP_TASK_QUEUE 注入生效"

    # 演习
    python restart_workers.py --dry-run --reason "演练"

## ⚠ agent 沙箱必读（2026-09-10 实证）
WorkBuddy / agent 的 Bash 工具用 Job Object 圈住派生进程，【工具调用一结束，
DETACHED 子进程也会被连带杀掉】（实验：TMP/_detach_probe.py 派生后 17s 即死，
连第一行日志都没写出来）。因此：
- `--mode worker`（默认）是安全的：只杀 worker 子进程，由「沙箱外」的 watchdog 自动拉起；
- `--mode watchdog` 必须经计划任务中继（schtasks /Run → start_hidden.ps1），
  直接 Popen 派生的 watchdog 会在本调用结束时静默死亡（当日 11:29 实测翻车一次）。

## 退出码
    0 成功 / 1 参数或安全检查失败 / 2 重启后校验失败
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
LOG_DIR = ROOT / "log"
sys.path.insert(0, str(ROOT))

# ⚠ 本脚本的输出**全是中文**，而 Windows 上 python 的 stdout 默认跟随控制台代码页
# （本机 cp1252）→ 第一句 print 就 UnicodeEncodeError 崩掉。
# 后果不是"看不到日志"而是**运维入口整体不可用**：2026-09-21 用它重启 watchdog 时，
# 脚本死在 `print("=== 重启前 ===")`，进程一个都没杀、也没留痕，只留一行 traceback，
# 很容易被误读成"重启失败但杀过了"。
# 与仓库其它脚本（db_freshness_check / avail_recon_sync …）保持一致：显式改 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - 非 TTY / 老版本兜底
    pass

from backend.restart_marker import append_marker, caller_name, read_markers  # noqa: E402

# 组清单单一来源（2026-09-18）：直接从 worker_watchdog.GROUP_TASK_MAP 取键，
# 避免“拆了新组但本脚本 ALL_GROUPS 没跟上”导致 --list/--groups 默认值漏掉该组
# （旧值 ("u", "n", "m", "c") 在两处写死，拆 v 组时就是靠测试守卫发现这类遗漏）。
try:
    from backend.worker_watchdog import GROUP_TASK_MAP as _GROUP_TASK_MAP
    ALL_GROUPS = tuple(_GROUP_TASK_MAP.keys())
except Exception:  # pragma: no cover - import 失败时不阻断运维入口
    ALL_GROUPS = ("u", "n", "s", "w", "m", "c", "v", "x", "g", "p")
WD_PID_FILE = BACKEND / "worker_watchdog.pid"
WD_CONSOLE = LOG_DIR / "worker_watchdog_console.log"
WD_CONSOLE_ERR = LOG_DIR / "worker_watchdog_console.log.err"


# ---------------------------------------------------------------- 基础工具
def _no_window_flags() -> int:
    if sys.platform != "win32":
        return 0
    return (getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0))


def read_pid(path: Path):
    try:
        txt = path.read_text(encoding="utf-8").strip()
        return int(txt) if txt else None
    except Exception:
        return None


def pid_alive(pid) -> bool:
    """用 OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) 判存活（不受完整性级别限制）。"""
    if not pid:
        return False
    if sys.platform != "win32":
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        h = k32.OpenProcess(0x1000, False, int(pid))
        if h:
            k32.CloseHandle(h)
            return True
        return False
    except Exception:
        return False


def snapshot():
    """返回 (watchdog_pid, {group: pid})。"""
    return read_pid(WD_PID_FILE), {g: read_pid(BACKEND / f"worker_{g}.pid") for g in ALL_GROUPS}


def taskkill(pid, tree: bool = True):
    cmd = ["taskkill", "/PID", str(pid), "/F"] + (["/T"] if tree else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           **_no_window_kw())
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:
        return -1, str(exc)


def _no_window_kw():
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {}


# ---------------------------------------------------------------- 队列安全检查
def queue_busy(groups=None):
    """返回 (busy:int, detail:str)。查 PG task_queue 里 running/pending 的条数。

    groups 非空时只统计「属于目标组的任务」+ 归属未知的任务（保守起见），
    其它组在跑不影响本次重启。
    拿不到 DB 时返回 (0, 'skip: ...')，绝不因为 DB 抖动挡住重启。
    """
    mode = os.environ.get("MY_APP_DB_MODE", "").strip().lower()
    env_file = BACKEND / ".env"
    dsn = None
    try:
        if env_file.exists():
            for ln in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if ln.startswith("DATABASE_URL="):
                    dsn = ln.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass
    if not dsn:
        dsn = os.environ.get("DATABASE_URL")
    if mode == "sqlite" or not dsn:
        return 0, f"skip: db_mode={mode or 'unset'} dsn={'有' if dsn else '无'}"
    try:
        import psycopg2  # type: ignore
    except Exception as exc:
        return 0, f"skip: psycopg2 不可用 ({exc})"
    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT task_id, status FROM task_queue "
                    "WHERE status IN ('running','pending')"
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        if groups:
            task_group = {}
            try:
                from backend.worker_watchdog import GROUP_TASK_MAP
                for g, tasks in GROUP_TASK_MAP.items():
                    for t in (tasks or "").split(","):
                        if t.strip():
                            task_group[t.strip()] = g
            except Exception:
                task_group = {}
            want = set(groups)
            # 只保留「属于目标组」的任务；归属未知的保守保留（视为所有组都在用）
            rows = [r for r in rows
                    if task_group.get(r[0]) in want or r[0] not in task_group]
        detail = ", ".join(f"{t}:{s}" for t, s in rows) or "无"
        return len(rows), detail
    except Exception as exc:
        return 0, f"skip: 查询失败 ({exc})"


# ---------------------------------------------------------------- 启动 watchdog
def python_exe() -> Path:
    """规范 Python：系统 Python312 的 pythonw（与 start_hidden.ps1 一致）。"""
    la = os.environ.get("LOCALAPPDATA", "")
    cands = [
        Path(la) / "Programs" / "Python" / "Python312" / "pythonw.exe",
        Path(la) / "Programs" / "Python" / "Python312" / "python.exe",
        ROOT / "Scripts" / "pythonw.exe",
        Path(r"C:\Python312\pythonw.exe"),
    ]
    for c in cands:
        if c.exists():
            return c
    return Path(sys.executable)


def canonical_env() -> dict:
    """复刻 start_hidden.ps1 line 111-116 的启动环境。"""
    env = os.environ.copy()
    env["MY_APP_WORKER_GROUPS"] = ",".join(ALL_GROUPS)
    env["MY_APP_TASK_QUEUE"] = "1"          # 纵深防御：子 worker 只投递，由主循环串行认领
    env["PYTHONUTF8"] = "1"
    env["CODEBUDDY_SESSION_ID"] = ""
    env["CLAUDE_SESSION_ID"] = ""
    env["CODEBUDDY_SAFE_DELETE_SANDBOX"] = ""
    return env


def start_watchdog(by: str = None) -> int:
    """直接派生 watchdog（仅作 schtasks 不可用时的兜底，沙箱内有被连带杀风险）。

    派生前必须先问内核单例锁：这里曾经只看 worker_watchdog.pid，而 2026-10-16
    那个修后端的脚本把 pid 文件删了却没杀进程 —— 于是本函数又叠了一套栈上去，
    当天累计 5 套 watchdog / 40 个 worker 抢同一张 task_queue。
    返回 0 表示「已有存活实例，未派生」。
    """
    try:
        from backend.worker_watchdog import _probe_singleton_lock
        state = _probe_singleton_lock()
    except Exception:
        state = "unavailable"
    if state == "held":
        print("[SKIP] 已有 watchdog 持有单例锁，跳过派生（不再叠加第二套 worker 栈）")
        return 0
    if state == "unavailable":
        print("[WARN] 单例锁探测不可用，仅按 PID 文件判断 → 仍会派生（看门狗自身会拒绝重复实例）")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    py = python_exe()
    out = open(WD_CONSOLE, "ab", buffering=0)
    err = open(WD_CONSOLE_ERR, "ab", buffering=0)
    env = canonical_env()
    # 让新 watchdog 在 watchdog_start 留痕里自报「谁把我拉起来的」
    if by:
        env["MY_APP_RESTART_BY"] = by
    proc = subprocess.Popen([str(py), "-m", "backend.worker_watchdog"], cwd=str(ROOT),
                            env=env, stdout=out, stderr=err,
                            creationflags=_no_window_flags())
    return proc.pid


def in_agent_sandbox() -> bool:
    env_keys = " ".join(os.environ.keys()).lower()
    return "codebuddy" in env_keys or "workbuddy" in env_keys


RELAUNCH_HINT = ("请用 PowerShell 工具执行:  Start-ScheduledTask -TaskName 'MyApp_EnsureRunning'\n"
                 "  （schtasks.exe 在 agent 沙箱程序黑名单内，不可从 Bash 调用；\n"
                 "    Start-ScheduledTask 走 PowerShell 工具是允许的，由任务计划程序服务拉起，\n"
                 "    进程父级是 svchost，不受沙箱 Job Object 管辖，必然存活）")


def relaunch_watchdog(by: str) -> tuple:
    """重启 watchdog 本体（杀完之后的「拉起」环节）。

    ⚠ 关键教训（2026-09-10 实证）：agent 沙箱用 Job Object 圈住派生进程，
    【工具调用结束的瞬间，DETACHED 子进程也会被连带杀掉】
    （实验：TMP/_detach_probe.py 派生后 17s 即死，连第一行日志都没写出）。
    所以拉起环节绝不能用本进程直接 Popen，必须交给外部：
      - 人工终端运行本脚本 → schtasks /Run 可用（不在黑名单）
      - agent 沙箱内运行   → schtasks.exe 被程序黑名单拦截 → 明确跳过，
                             返回 None 并让调用方改用 PowerShell 工具的
                             Start-ScheduledTask（RELAUNCH_HINT）。

    返回 (新watchdog pid 或 None, 说明文字)。
    """
    if in_agent_sandbox():
        print("[SKIP] 检测到 agent 沙箱：schtasks.exe 在程序黑名单内，跳过。")
        print("[ACTION] " + RELAUNCH_HINT)
        return None, "需人工/PowerShell 工具执行 Start-ScheduledTask"
    r = subprocess.run(["schtasks", "/Run", "/TN", "MyApp_EnsureRunning"],
                       capture_output=True, text=True, errors="replace", **_no_window_kw())
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode == 0:
        return None, f"schtasks OK: {out[:80]}"
    print(f"[WARN] schtasks /Run 失败 rc={r.returncode}: {out[:120]}")
    print("[WARN] 退回直接派生 —— 若本进程运行在沙箱内，新 watchdog 会在本调用结束时被连带杀死！")
    pid = start_watchdog(by)
    if pid == 0:
        return None, "已有 watchdog 持有单例锁，未派生"
    return pid, "direct-popen(有沙箱风险)"


# ---------------------------------------------------------------- 子命令
def cmd_list() -> int:
    wd, ws = snapshot()
    busy, detail = queue_busy()
    print(f"watchdog pid={wd} {'ALIVE' if pid_alive(wd) else 'DEAD'}")
    for g in ALL_GROUPS:
        p = ws[g]
        print(f"  worker[{g}] pid={p} {'ALIVE' if pid_alive(p) else ('-' if not p else 'DEAD')}")
    print(f"task_queue running/pending: {busy} ({detail})")
    print(f"最近留痕: {len(read_markers(5))} 条 -> {LOG_DIR / 'worker_restart_marker.log'}")
    return 0


def cmd_tail(n: int) -> int:
    lines = read_markers(n)
    if not lines:
        print("(暂无留痕)")
        return 0
    for ln in lines:
        print(ln)
    return 0


def cmd_restart(args) -> int:
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    bad = [g for g in groups if g not in ALL_GROUPS]
    if bad:
        print(f"[FAIL] 未知组: {bad}（可选 {ALL_GROUPS}）")
        return 1

    wd_old, ws_old = snapshot()
    print("=== 重启前 ===")
    print(f"watchdog pid={wd_old} {'ALIVE' if pid_alive(wd_old) else 'DEAD'}")
    for g in groups:
        p = ws_old[g]
        print(f"  worker[{g}] pid={p} {'ALIVE' if pid_alive(p) else ('-' if not p else 'DEAD')}")

    # --- 安全检查：目标组有任务在跑则默认拒绝 ---
    busy, detail = queue_busy(groups if args.mode == "worker" else None)
    print(f"=== 队列检查 === running/pending={busy} ({detail})")
    if busy > 0 and not args.force:
        print("[FAIL] 队列中有 running/pending 任务，拒绝重启（避免打断正在执行的任务）。")
        print("       确认无妨请加 --force。")
        return 1

    if args.mode == "watchdog" and not wd_old:
        print("[WARN] 未找到 worker_watchdog.pid（可能被人删了却没杀进程）："
              "派生前会先问单例锁，已有存活实例时不会叠加第二套栈。")

    targets = {"worker": {g: ws_old[g] for g in groups if ws_old.get(g)},
               "watchdog": {g: ws_old.get(g) for g in groups if ws_old.get(g)}}[args.mode]

    reason = args.reason or "(未说明目的)"
    if not args.reason:
        print("[WARN] 未提供 --reason，留痕里会记成「(未说明目的)」，建议补充。")

    if args.dry_run:
        print("=== DRY-RUN ===")
        print(f"将杀 {args.mode}: " + (", ".join(f"{g}:{p}" for g, p in targets.items()) or "(无)")
              + (f" + watchdog:{wd_old}" if args.mode == "watchdog" and wd_old else ""))
        print(f"将写留痕: reason={reason!r} by={args.by}")
        return 0

    append_marker("restart_intent", by=args.by, mode=args.mode, groups=groups,
                  old_pids={g: ws_old.get(g) for g in groups},
                  reason=reason,
                  note=("dry-run" if args.dry_run else None))

    t0 = time.time()
    if args.mode == "watchdog":
        if wd_old:
            rc, msg = taskkill(wd_old, tree=True)
            print(f"taskkill watchdog(+tree) pid={wd_old} -> rc={rc} {msg[:60]}")
        # 等旧 watchdog 与子进程彻底退出
        for _ in range(15):
            if not pid_alive(wd_old):
                break
            time.sleep(1)
        for g in groups:
            p = ws_old.get(g)
            if p and pid_alive(p):
                rc, msg = taskkill(p, tree=True)
                print(f"  taskkill worker[{g}] pid={p} -> rc={rc}")
        relaunched, how = relaunch_watchdog(args.by)
        if relaunched:
            print(f"新 watchdog 已直接派生 pid={relaunched} ({how})")
        elif in_agent_sandbox():
            append_marker("restart_done", by=args.by, mode=args.mode, groups=groups,
                          old_pids={g: ws_old.get(g) for g in groups},
                          lived_s=round(time.time() - t0, 1), reason=reason,
                          note="已杀旧 watchdog，沙箱内无法自行拉起，待外部 Start-ScheduledTask")
            print("留痕已写入（本次记录到「已杀待拉起」，拉起后的 watchdog_start/worker_spawn "
                  "会由新 watchdog 自己补写）")
            return 0
        else:
            print(f"已请求计划任务 MyApp_EnsureRunning 拉起新 watchdog（{how}），等待就绪 ...")
    else:
        for g in groups:
            p = ws_old.get(g)
            if not p:
                print(f"  worker[{g}] 无 pid 文件，跳过")
                continue
            rc, msg = taskkill(p, tree=True)
            print(f"  taskkill worker[{g}] pid={p} -> rc={rc} {msg[:50]}")
        new_wd = wd_old
        print(f"watchdog pid={wd_old} 保持不变，等待其自动拉起新 worker ...")

    # --- 等待新 pid 并校验 ---
    # watchdog 走计划任务中继时，start_hidden.ps1 全程约 40s，默认 60s 太紧
    wait_s = max(args.wait, 120) if args.mode == "watchdog" else max(10, args.wait)
    deadline = time.time() + wait_s
    new_ws = {}
    while time.time() < deadline:
        _, cur = snapshot()
        new_ws = cur
        if args.mode == "watchdog":
            nwd = read_pid(WD_PID_FILE)
            ready = bool(nwd) and nwd != wd_old and pid_alive(nwd) and at_least(groups, cur, ws_old)
        else:
            nwd = wd_old
            ready = at_least(groups, cur, ws_old)
        if ready:
            break
        time.sleep(1)

    elapsed = time.time() - t0
    new_wd = read_pid(WD_PID_FILE)
    print("=== 重启后 ===")
    print(f"watchdog pid={new_wd} {'ALIVE' if pid_alive(new_wd) else 'DEAD'}")
    ok = True
    for g in groups:
        op, np_ = ws_old.get(g), new_ws.get(g)
        changed = bool(np_) and np_ != op
        alive = pid_alive(np_)
        flag = "OK" if (changed and alive) else ("UNCHANGED?" if not changed else "DEAD?")
        if not (changed and alive):
            ok = False
        print(f"  worker[{g}] {op} -> {np_} {flag}")
    print(f"耗时 {elapsed:.1f}s")

    append_marker("restart_done", by=args.by, mode=args.mode, groups=groups,
                  pids={g: new_ws.get(g) for g in groups},
                  old_pids={g: ws_old.get(g) for g in groups},
                  lived_s=round(elapsed, 1),
                  reason=reason,
                  note=("全部就绪" if ok else "部分未就绪，请查 log/worker_watchdog.log"))
    print(f"留痕已写入 {LOG_DIR / 'worker_restart_marker.log'}")
    return 0 if ok else 2


def at_least(groups, cur, old) -> bool:
    for g in groups:
        p = cur.get(g)
        if not p or p == old.get(g) or not pid_alive(p):
            return False
    return True


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(
        description="worker / watchdog 规范化重启入口（自带留痕）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="查看当前 pid 与队列状态")
    ap.add_argument("--tail", type=int, metavar="N", help="查看最近 N 条重启留痕")
    ap.add_argument("--mode", choices=("worker", "watchdog"), default="worker",
                    help="worker=只重启子进程(默认)；watchdog=连 watchdog 一起重启(env 变更时才需要)")
    ap.add_argument("--groups", default=",".join(ALL_GROUPS),
                    help=f"逗号分隔，默认 {','.join(ALL_GROUPS)}（取自 worker_watchdog.GROUP_TASK_MAP）")
    ap.add_argument("--reason", default="", help="重启目的（强烈建议写，会进留痕）")
    ap.add_argument("--by", default=None, help="发起方（默认自动推断）")
    ap.add_argument("--wait", type=int, default=60, help="等待新 pid 就绪的最长秒数，默认 60")
    ap.add_argument("--force", action="store_true", help="队列非空时也强制重启")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要做什么")
    args = ap.parse_args()

    if args.by is None:
        args.by = caller_name()
    if args.list:
        return cmd_list()
    if args.tail is not None:
        return cmd_tail(args.tail)
    if not args.reason and not args.dry_run:
        print("[WARN] 建议用 --reason 说明重启目的，便于日后归因。")
    return cmd_restart(args)


if __name__ == "__main__":
    sys.exit(main())
