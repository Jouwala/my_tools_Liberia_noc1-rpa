# -*- coding: utf-8 -*-
"""R2 切流后首个写任务自动复查（一次性监控脚本）。

功能
----
1. 记录基线：PG app.task_execution_log 最新 started_at、battery.battery_reading 行数、
   各 sqlite 源库文件 mtime。
2. 轮询 PG task_execution_log，等待切流后新产生的任务执行记录（最长 MAX_WAIT 秒）。
3. 等该记录完成（completed_at 非空，最长 COMPLETION_WAIT 秒）。
4. 复查：
   a. 任务名 / 成功失败 / 耗时 / 错误摘要；
   b. 写效果：battery.battery_reading 行数前后对比（battery_kpi_sync 的目标表）；
   c. 旁证：sqlite 源库文件 mtime 是否保持冻结（写入应只进 PG）。
5. 输出报告 r2_post_write_check_report.md（被占用则加 _序号）。

用法：python r2_post_write_check.py   （在后台运行，自行轮询）
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

T0 = time.time()

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
MY_APP_ROOT = BASE_DIR.parent                      # my_app/

MAX_WAIT = 2 * 3600        # 等新任务记录出现的最长秒数
POLL_INTERVAL = 30         # 轮询间隔
COMPLETION_WAIT = 1800     # 等单条记录完成的最长秒数

# ---------- 读取 backend/.env 的 DATABASE_URL（不 import backend，避免受运行模式影响） ----------
def _read_env(key):
    env_file = BASE_DIR / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key, "")


DATABASE_URL = _read_env("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL 未配置，无法复查")

import psycopg2  # noqa: E402

SQLITE_FILES = [
    MY_APP_ROOT / "db" / "app.db",
    MY_APP_ROOT / "data" / "battery" / "battery_kpi.sqlite3",
    MY_APP_ROOT / "data" / "eflow" / "eflow.sqlite3",
    MY_APP_ROOT / "data" / "ms_sla" / "lbr_ms_sla_kpi.sqlite3",
    MY_APP_ROOT / "data" / "packet_lost" / "lte_pl.sqlite3",
]


def _mtime_str(p: Path):
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "N/A"


def _pg_conn():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)


def main():
    print(f"[{datetime.now():%H:%M:%S}] R2 写任务复查启动，轮询间隔 {POLL_INTERVAL}s，最长等待 {MAX_WAIT}s")

    # ---------- 基线 ----------
    conn = _pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(started_at), '') FROM app.task_execution_log")
    baseline_started = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM battery.battery_reading")
    battery_before = cur.fetchone()[0]
    conn.close()
    mtime_before = {p.name: _mtime_str(p) for p in SQLITE_FILES}
    print(f"[基线] exec_log 最新 started_at={baseline_started!r}，battery_reading={battery_before} 行")

    # ---------- 等待新任务记录 ----------
    new_id = None
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            conn = _pg_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, task_name, started_at FROM app.task_execution_log "
                "WHERE started_at > %s ORDER BY id LIMIT 1",
                (baseline_started,),
            )
            row = cur.fetchone()
            conn.close()
            if row:
                new_id, task_name, started_at = row
                print(f"[{datetime.now():%H:%M:%S}] 捕获新任务执行记录 id={new_id} name={task_name}")
                break
        except Exception as e:  # noqa: BLE001
            print(f"[{datetime.now():%H:%M:%S}] 轮询异常（继续）: {e}")
    else:
        write_report(None, baseline_started, battery_before, battery_before,
                     mtime_before, mtime_before, verdict="TIMEOUT：等待窗口内无新任务执行")
        print("TIMEOUT：等待窗口内无新任务执行，报告已写")
        return 2

    # ---------- 等待该记录完成 ----------
    rec = None
    deadline = time.time() + COMPLETION_WAIT
    while time.time() < deadline:
        conn = _pg_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT task_name, trigger_type, success, started_at, completed_at, "
            "elapsed_seconds, LEFT(COALESCE(error, ''), 400) FROM app.task_execution_log WHERE id = %s",
            (new_id,),
        )
        rec = cur.fetchone()
        conn.close()
        if rec and rec[4] is not None:  # completed_at 非空
            break
        time.sleep(10)

    # ---------- 复查写效果 ----------
    conn = _pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM battery.battery_reading")
    battery_after = cur.fetchone()[0]
    conn.close()
    mtime_after = {p.name: _mtime_str(p) for p in SQLITE_FILES}

    success = bool(rec and rec[2])
    sqlite_frozen = all(mtime_before[k] == mtime_after[k] for k in mtime_before)
    verdict = ("PASS：任务成功且写入 PG、sqlite 保持冻结"
               if success and sqlite_frozen else
               "FAIL：任务失败或 sqlite 被写入，需要排查（必要时回退 MY_APP_DB_MODE=sqlite）")
    write_report(rec, baseline_started, battery_before, battery_after,
                 mtime_before, mtime_after, verdict=verdict)
    print(verdict)
    print(f"总耗时 {time.time() - T0:.2f} 秒")
    return 0 if success and sqlite_frozen else 1


def write_report(rec, baseline_started, battery_before, battery_after,
                 mtime_before, mtime_after, verdict):
    """写报告（文件被占用则加 _序号）。"""
    lines = [
        "# R2 切流后首个写任务自动复查报告",
        "",
        f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S} ｜ 监控总耗时 {time.time() - T0:.2f} 秒",
        "",
        f"**结论：{verdict}**",
        "",
        f"基线：exec_log 最新 started_at = `{baseline_started}`",
        "",
        "## 任务执行记录（PG app.task_execution_log）",
        "",
    ]
    if rec:
        task_name, trigger_type, success, started_at, completed_at, elapsed, err = rec
        lines += [
            f"- 任务名：{task_name}",
            f"- 触发方式：{trigger_type}",
            f"- 结果：{'成功' if success else '失败'}",
            f"- started_at：{started_at} ｜ completed_at：{completed_at} ｜ 耗时：{elapsed} 秒",
            f"- 错误摘要：{err or '无'}",
        ]
    else:
        lines.append("- （未捕获到任务记录）")
    lines += [
        "",
        "## 写效果对比",
        "",
        f"- battery.battery_reading 行数：{battery_before} → {battery_after}"
        f"（{'有新增' if battery_after > battery_before else '无变化'}）",
        "",
        "## sqlite 源库 mtime（应保持冻结）",
        "",
        "| 文件 | 切流基线 | 复查时 | 变化 |",
        "|---|---|---|---|",
    ]
    for k in mtime_before:
        changed = "⚠️ 变了" if mtime_before[k] != mtime_after[k] else "未变"
        lines.append(f"| {k} | {mtime_before[k]} | {mtime_after[k]} | {changed} |")
    lines.append("")

    out = Path(__file__).resolve().parent / "r2_post_write_check_report.md"
    n = 1
    while True:
        try:
            out.write_text("\n".join(lines), encoding="utf-8")
            break
        except PermissionError:
            out = out.with_name(f"r2_post_write_check_report_{n}.md")
            n += 1
    print(f"报告已写入：{out}")


if __name__ == "__main__":
    raise SystemExit(main())
