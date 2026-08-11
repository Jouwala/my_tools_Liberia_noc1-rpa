#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parallel_orchestrator.py — 多 Agent 并行编排器（派发/轮询模型）

背景与动机
----------
把长任务塞进同步 RPC（如 MCP tools/call）会被客户端请求超时杀死
（本机实测：WORKbuddy MCP 报 -32001 Request timed out，小探测能过、
长改写必死）。本编排器改用"派发/轮询"模型：

  dispatch : 把每个任务作为独立后台进程拉起（codex exec / qoderclicn -p），
             stdout 重定向日志、退出码写 rc 文件，秒级返回，不阻塞。
  status   : 一次性拉取系统进程表（向量化匹配 PID），判定 运行中/已完成/丢失。
  wait     : 周期性轮询直到全部结束或全局超时，产出 summary.md。
  verify   : 验证门——py_compile 批量编译 + 残留模式扫描（配置化）。

执行器（默认，可在任务文件 "executors" 段覆盖）：
  codex : node codex.js exec --approve-for-me --skip-git-repo-check -C <cwd>
          （prompt 经 stdin 注入，无命令行长度限制；--full-auto 在新版已废弃，
          且 --sandbox 与 --approve-for-me 互斥，2026-08-07 实测确认）
  qoder : qoderclicn -p "<指令文件引读>" --no-session-persistence
          --dangerously-skip-permissions
          （prompt 写入文件由 agent 自行读取，规避 8K 命令行限制与队列挂死）

安全警告：两个执行器都以"免审批"模式运行，只应在可信的本机工作区使用；
任务清单里务必限定"只允许修改列出的文件"。

用法示例
--------
  python parallel_orchestrator.py dispatch --tasks tasks_phase3_remaining.json
  python parallel_orchestrator.py status
  python parallel_orchestrator.py wait --interval 20 --timeout 7200
  python parallel_orchestrator.py verify --spec verify_spec_phase3.json
  python parallel_orchestrator.py runs
"""
import argparse
import base64
import csv
import datetime
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(ROOT, "runs")
CREATE_NO_WINDOW = 0x08000000  # Windows: 后台拉起不弹 CMD 窗口

# 默认执行器配置（与本机实测路径一致，可用任务文件 executors 段覆盖）
DEFAULT_EXECUTORS = {
    "codex": {
        "node": r"C:\Program Files\nodejs\node.exe",
        "codex_js": r"C:\Users\ZTEEMS\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js",
        "extra_args": ["exec", "--approve-for-me", "--skip-git-repo-check"],
    },
    "qoder": {
        "cli": r"C:\Users\ZTEEMS\AppData\Roaming\npm\qoderclicn.cmd",
        "extra_args": ["--no-session-persistence", "--dangerously-skip-permissions"],
    },
}


def log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def safe_write(path, text):
    """写文件；若目标被占用（PermissionError/共享冲突）则追加 _1 _2 ... 另存。"""
    base, ext = os.path.splitext(path)
    candidates = [path] + ["%s_%d%s" % (base, i, ext) for i in range(1, 10)]
    for cand in candidates:
        try:
            with open(cand, "w", encoding="utf-8") as f:
                f.write(text)
            return cand
        except (PermissionError, OSError):
            continue
    raise RuntimeError("无法写入（文件被占用）: %s" % path)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def latest_run_id():
    if not os.path.isdir(RUNS_DIR):
        return None
    subs = [d for d in os.listdir(RUNS_DIR)
            if os.path.isdir(os.path.join(RUNS_DIR, d))]
    return max(subs) if subs else None


def run_dir(run_id):
    return os.path.join(RUNS_DIR, run_id)


def state_path(run_id):
    return os.path.join(run_dir(run_id), "state.json")


def load_state(run_id):
    return load_json(state_path(run_id))


def save_state(run_id, state):
    safe_write(state_path(run_id), json.dumps(state, ensure_ascii=False, indent=2))


def ps_quote(s):
    """PowerShell 单引号字符串转义。"""
    return "'" + s.replace("'", "''") + "'"


def build_ps_script(executor, ex_cfg, cwd, prompt_file, out_log, rc_file):
    """生成后台执行的 PowerShell 脚本：跑完把退出码写入 rc 文件。"""
    if executor == "codex":
        args = " ".join(ex_cfg.get("extra_args", DEFAULT_EXECUTORS["codex"]["extra_args"]))
        core = "Get-Content -LiteralPath %s -Raw | & %s %s %s -C %s *> %s" % (
            ps_quote(prompt_file),
            ps_quote(ex_cfg.get("node", DEFAULT_EXECUTORS["codex"]["node"])),
            ps_quote(ex_cfg.get("codex_js", DEFAULT_EXECUTORS["codex"]["codex_js"])),
            args, ps_quote(cwd), ps_quote(out_log))
    elif executor == "qoder":
        # prompt 不内联：让 agent 先读指令文件再执行，规避命令行长度限制
        inline = ("你的任务指令在文件 %s 中。请先用文件读取工具完整读取该文件，"
                  "然后严格按其中要求执行；只允许修改指令中明确列出的文件。" % prompt_file)
        args = " ".join(ex_cfg.get("extra_args", DEFAULT_EXECUTORS["qoder"]["extra_args"]))
        core = "& %s -p %s %s *> %s" % (
            ps_quote(ex_cfg.get("cli", DEFAULT_EXECUTORS["qoder"]["cli"])),
            ps_quote(inline), args, ps_quote(out_log))
    else:
        raise ValueError("未知执行器: %s（支持 codex / qoder）" % executor)
    return ("$ErrorActionPreference='Continue'; Set-Location -LiteralPath %s; %s; "
            "$LASTEXITCODE | Out-File -LiteralPath %s -Encoding ascii"
            % (ps_quote(cwd), core, ps_quote(rc_file)))


def spawn_detached(script, cwd):
    """以隐藏窗口的 powershell -EncodedCommand 启动，返回 PID。"""
    b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-EncodedCommand", b64],
        cwd=cwd, creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.pid


# ---------------- dispatch ----------------
def cmd_dispatch(args):
    t0 = time.perf_counter()
    spec = load_json(args.tasks)
    run_id = args.run_id or datetime.datetime.now().strftime("run-%Y%m%d-%H%M%S")
    rd = run_dir(run_id)
    os.makedirs(rd, exist_ok=True)
    executors = dict(DEFAULT_EXECUTORS)
    executors.update(spec.get("executors", {}))
    defaults = spec.get("defaults", {})

    state = {"run_id": run_id, "created": datetime.datetime.now().isoformat(timespec="seconds"),
             "source": os.path.abspath(args.tasks), "tasks": {}}
    for task in spec.get("tasks", []):
        tid = task["id"]
        executor = task.get("executor", "codex")
        cwd = task.get("cwd", defaults.get("cwd", os.getcwd()))
        prompt = task.get("prompt", "")
        prompt_file = os.path.join(rd, "%s.prompt.md" % tid)
        out_log = os.path.join(rd, "%s.out.log" % tid)
        rc_file = os.path.join(rd, "%s.rc" % tid)
        safe_write(prompt_file, prompt)
        # 重复派发同一 task 时清理旧产物，避免陈旧 rc 造成 status 误报 DONE
        for stale in (rc_file, out_log):
            if os.path.exists(stale):
                os.remove(stale)
        script = build_ps_script(executor, executors.get(executor, {}),
                                 cwd, prompt_file, out_log, rc_file)
        pid = spawn_detached(script, cwd)
        state["tasks"][tid] = {
            "executor": executor, "cwd": cwd, "pid": pid,
            "started": time.time(),
            "prompt_file": prompt_file, "out_log": out_log, "rc_file": rc_file,
        }
        log("已派发 %-28s executor=%-6s pid=%d" % (tid, executor, pid))
    save_state(run_id, state)
    log("run_id=%s 共派发 %d 个任务，状态目录: %s" % (run_id, len(state["tasks"]), rd))
    log("查看进度: python parallel_orchestrator.py status --run-id %s" % run_id)
    log("总耗时 %.2f 秒" % (time.perf_counter() - t0))


# ---------------- status / wait ----------------
def alive_pids():
    """一次 tasklist 拉全量进程表，向量化构造存活 PID 集合。"""
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                         capture_output=True, text=True).stdout
    alive = set()
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 2 and row[1].isdigit():
            alive.add(int(row[1]))
    return alive


def classify(info, alive):
    # 进程仍在且日志近 120 秒内有增长 → 优先判 RUNNING（rc 文件可能是陈旧残留）
    if info["pid"] in alive:
        try:
            idle = time.time() - os.path.getmtime(info["out_log"])
        except OSError:
            idle = 0.0
        if idle < 120:
            return ("RUNNING", None)
    if os.path.exists(info["rc_file"]):
        try:
            rc = int(open(info["rc_file"], encoding="ascii").read().strip())
        except Exception:
            rc = -1
        return ("DONE rc=%d" % rc, rc)
    if info["pid"] in alive:
        return ("RUNNING", None)
    return ("GONE(无rc且进程不在)", -2)


def print_status(state):
    alive = alive_pids()
    now = time.time()
    fmt = "%-28s %-7s %-20s %10s %12s"
    print(fmt % ("TASK", "EXEC", "STATUS", "ELAPSED(s)", "LOG(B)"))
    print("-" * 82)
    n_done = n_run = n_bad = 0
    for tid, info in state["tasks"].items():
        st, rc = classify(info, alive)
        elapsed = "%.0f" % (now - info["started"])
        try:
            size = os.path.getsize(info["out_log"])
        except OSError:
            size = 0
        print(fmt % (tid, info["executor"], st, elapsed, size))
        if st.startswith("DONE") and rc == 0:
            n_done += 1
        elif st == "RUNNING":
            n_run += 1
        else:
            n_bad += 1
    total = len(state["tasks"])
    print("-" * 82)
    print("共 %d 个任务：成功 %d / 运行中 %d / 异常 %d" % (total, n_done, n_run, n_bad))
    return n_done, n_run, n_bad


def cmd_status(args):
    t0 = time.perf_counter()
    run_id = args.run_id or latest_run_id()
    if not run_id or not os.path.exists(state_path(run_id)):
        log("没有找到任何 run（先执行 dispatch）")
        sys.exit(2)
    print_status(load_state(run_id))
    log("耗时 %.2f 秒" % (time.perf_counter() - t0))


def write_summary(run_id, state):
    lines = ["# 编排运行汇总 %s" % run_id, "",
             "创建时间: %s" % state.get("created", "-"),
             "任务来源: %s" % state.get("source", "-"), "",
             "| 任务 | 执行器 | 状态 | PID | 日志 |", "|---|---|---|---|---|"]
    alive = alive_pids()
    for tid, info in state["tasks"].items():
        st, rc = classify(info, alive)
        lines.append("| %s | %s | %s | %d | %s |" % (
            tid, info["executor"], st, info["pid"],
            os.path.basename(info["out_log"])))
    path = safe_write(os.path.join(run_dir(run_id), "summary.md"), "\n".join(lines))
    log("汇总已写入: %s" % path)


def cmd_wait(args):
    t0 = time.perf_counter()
    run_id = args.run_id or latest_run_id()
    if not run_id or not os.path.exists(state_path(run_id)):
        log("没有找到任何 run（先执行 dispatch）")
        sys.exit(2)
    deadline = time.time() + args.timeout
    while True:
        state = load_state(run_id)
        log("轮询 run_id=%s ..." % run_id)
        n_done, n_run, n_bad = print_status(state)
        if n_run == 0:
            break
        if time.time() > deadline:
            log("达到全局超时 %d 秒，仍有 %d 个任务在跑（后台进程不受影响，可稍后再 status）"
                % (args.timeout, n_run))
            break
        time.sleep(args.interval)
    write_summary(run_id, state)
    log("总耗时 %.2f 秒" % (time.perf_counter() - t0))
    sys.exit(0 if (n_run == 0 and n_bad == 0) else 1)


def cmd_runs(_args):
    if not os.path.isdir(RUNS_DIR):
        log("暂无运行记录")
        return
    for d in sorted(os.listdir(RUNS_DIR)):
        sp = os.path.join(RUNS_DIR, d, "state.json")
        if os.path.exists(sp):
            st = load_json(sp)
            print("%-24s tasks=%d  created=%s" % (d, len(st["tasks"]), st.get("created")))


# ---------------- verify（验证门） ----------------
def cmd_verify(args):
    t0 = time.perf_counter()
    spec = load_json(args.spec)
    root = spec.get("root", os.path.dirname(os.path.abspath(args.spec)))
    files = [os.path.join(root, f) for f in spec.get("files", [])]
    patterns = [(re.compile(p["regex"]), p.get("desc", p["regex"]), p.get("mode", "fail"))
                for p in spec.get("patterns", [])]

    # 第 1 关：批量 py_compile（一次性聚合结果）
    compile_fail = {}
    for fp in files:
        if not os.path.exists(fp):
            compile_fail[fp] = "文件不存在"
            continue
        try:
            py_compile.compile(fp, doraise=True)
        except py_compile.PyCompileError as e:
            compile_fail[fp] = str(e).splitlines()[0]

    # 第 2 关：残留模式扫描（每文件读一次，逐模式聚合命中）
    hits = []
    for fp in files:
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            compile_fail[fp] = "读取失败: %s" % e
            continue
        for i, line in enumerate(lines, 1):
            for rx, desc, mode in patterns:
                if rx.search(line):
                    hits.append((fp, i, desc, mode, line.strip()[:120]))

    fails = [h for h in hits if h[3] == "fail"]
    warns = [h for h in hits if h[3] == "warn"]

    print("==== 验证门结果 ====")
    print("[1] py_compile: %d/%d 通过" % (len(files) - len(compile_fail), len(files)))
    for fp, err in compile_fail.items():
        print("    FAIL %s :: %s" % (fp, err))
    print("[2] 残留扫描: fail=%d warn=%d" % (len(fails), len(warns)))
    for fp, i, desc, mode, txt in fails:
        print("    FAIL %s:%d (%s) %s" % (fp, i, desc, txt))
    for fp, i, desc, mode, txt in warns:
        print("    WARN %s:%d (%s) %s" % (fp, i, desc, txt))

    ok = not compile_fail and not fails
    print("结论: %s（总耗时 %.2f 秒）" % ("PASS" if ok else "FAIL", time.perf_counter() - t0))
    sys.exit(0 if ok else 1)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="多 Agent 并行编排器（派发/轮询模型）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("dispatch", help="派发任务（后台进程，秒级返回）")
    p.add_argument("--tasks", required=True, help="任务清单 JSON")
    p.add_argument("--run-id", default=None)

    p = sub.add_parser("status", help="查看全部任务状态（秒级）")
    p.add_argument("--run-id", default=None)

    p = sub.add_parser("wait", help="轮询等待全部任务结束")
    p.add_argument("--run-id", default=None)
    p.add_argument("--interval", type=int, default=15, help="轮询间隔秒，默认15")
    p.add_argument("--timeout", type=int, default=7200, help="全局等待上限秒，默认7200")

    p = sub.add_parser("verify", help="验证门：py_compile + 残留模式扫描")
    p.add_argument("--spec", required=True, help="验证规格 JSON")

    sub.add_parser("runs", help="列出历史运行")

    args = ap.parse_args()
    handlers = {"dispatch": cmd_dispatch, "status": cmd_status, "wait": cmd_wait,
                "verify": cmd_verify, "runs": cmd_runs}
    if args.cmd in handlers:
        handlers[args.cmd](args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
