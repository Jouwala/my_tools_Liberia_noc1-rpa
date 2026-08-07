#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 6 PostgreSQL API 冒烟测试。

职责：
1. 以 MY_APP_DB_MODE=pg + backend/.env（缺失回退根 .env）启动 uvicorn(7099)；
   设置 MY_APP_DISABLE_SCHEDULER=1，避免 APScheduler 后台任务干扰验证。
2. 等待端口就绪并校验 /api/health、/api/db/info 显示 db_mode=pg。
3. 对 tt_wo/alarm/packet_loss/battery/sp/gis/tasks/tables 路由器执行 2-3 个代表性 GET。
4. 直连 PG 校验关键 schema/表：app.eflow_tt、lte_pl.packet_loss_data、
   battery.battery_reading、ran_ume_ro schema。
5. 结束前关闭自启的 uvicorn 进程，确保 7099 端口不残留。

用法（项目根目录）：
    .venv-test\\Scripts\\python.exe backend\\migrations\\smoke_test_pg.py

退出码：0 = 全部通过；1 = 存在失败项。
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
PORT = int(os.environ.get("SMOKE_PG_PORT", "7099"))
BASE_URL = f"http://127.0.0.1:{PORT}"
START_TIMEOUT = float(os.environ.get("SMOKE_PG_START_TIMEOUT", "60"))
LOG_FILE = BACKEND_DIR / "migrations" / ".smoke_pg_uvicorn.log"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_PYTHON = Path(os.environ.get("MY_APP_PYTHON", "")) or (ROOT / ".venv-test" / "Scripts" / "python.exe")
if not _PYTHON.is_file():
    _PYTHON = Path(sys.executable)

COMPILE_TARGETS = [
    "backend/database.py",
    "backend/main.py",
    "backend/routers/system.py",
    "backend/routers/alarm_dashboard.py",
    "backend/routers/tables.py",
    "backend/dialect_helpers.py",
    "backend/services/task_runner.py",
    "backend/migrations/smoke_test_pg.py",
]

RESULTS = []


def log(msg: str) -> None:
    print(msg, flush=True)


def sanitize_url(url: str) -> str:
    return re.sub(r"//[^@/]+@", "//***@", url)


def load_env_file(path: Path) -> dict:
    """极简 .env 读取（不引入 python-dotenv 依赖）。"""
    out = {}
    if not path or not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def http_get(path: str, timeout: float = 30.0):
    req = urllib.request.Request(BASE_URL + path, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except Exception:
                data = None
            return resp.status, data, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        return e.code, data, raw
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


def check_py_compile() -> bool:
    import py_compile

    ok = True
    for rel in COMPILE_TARGETS:
        path = ROOT / rel
        try:
            py_compile.compile(str(path), doraise=True)
            log(f"[py_compile] OK  {rel}")
        except Exception as e:
            ok = False
            log(f"[py_compile] FAIL {rel}: {type(e).__name__}: {e}")
    return ok


def build_env() -> dict:
    backend_env = load_env_file(BACKEND_DIR / ".env")
    root_env = load_env_file(ROOT / ".env")
    env = os.environ.copy()
    # 强制 PG；DATABASE_URL 优先级：OS 环境 > backend/.env > 根 .env
    env["MY_APP_DB_MODE"] = "pg"
    env["MY_APP_DISABLE_SCHEDULER"] = "1"
    if not env.get("DATABASE_URL"):
        env["DATABASE_URL"] = backend_env.get("DATABASE_URL") or root_env.get("DATABASE_URL") or ""
    if not env.get("DATABASE_URL"):
        raise SystemExit("FAIL: DATABASE_URL 缺失（backend/.env 与根 .env 均无）")
    return env


def start_server(env: dict):
    log(f"[server] 启动 uvicorn backend.main:app -> 127.0.0.1:{PORT}")
    log(f"[server] python = {_PYTHON}")
    log(f"[server] DATABASE_URL = {sanitize_url(env['DATABASE_URL'])}")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_FILE, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [
            str(_PYTHON), "-m", "uvicorn", "backend.main:app",
            "--host", "127.0.0.1", "--port", str(PORT),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return proc, log_file


def wait_server(proc, log_file) -> bool:
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            log("[server] 进程提前退出，日志尾部：")
            _print_log_tail(log_file)
            return False
        if port_in_use(PORT):
            break
        time.sleep(0.5)
    if not port_in_use(PORT):
        log("[server] 60s 内端口未就绪，日志尾部：")
        _print_log_tail(log_file)
        return False
    # 端口就绪后，再等 /api/health 返回 200
    while time.time() < deadline:
        status, data, _ = http_get("/api/health", timeout=5)
        if status == 200:
            log(f"[server] /api/health 200 -> {json.dumps(data, ensure_ascii=False)}")
            return True
        if proc.poll() is not None:
            log("[server] 进程提前退出，日志尾部：")
            _print_log_tail(log_file)
            return False
        time.sleep(0.5)
    log("[server] /api/health 超时未返回 200，日志尾部：")
    _print_log_tail(log_file)
    return False


def _print_log_tail(log_file, lines: int = 80) -> None:
    try:
        log_file.flush()
    except Exception:
        pass
    try:
        tail = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        for line in tail:
            log("    " + line)
    except Exception:
        pass


def run_http_checks() -> None:
    checks = [
        ("health", "/api/health", lambda d: d.get("db_mode") == "pg", "db_mode==pg"),
        ("db_info", "/api/db/info", lambda d: _db_info_ok(d), "db_mode==pg 且含 app.eflow_tt / lte_pl.packet_loss_data / battery.battery_reading"),
        ("tt_wo_dashboard.overview", "/api/tt-wo-dashboard/overview", lambda d: isinstance(d, dict), "JSON 对象"),
        ("tt_wo_dashboard.drilldown", "/api/tt-wo-dashboard/drilldown?type=tt&dimension=all_tt", lambda d: isinstance(d, dict), "JSON 对象"),
        ("alarm_dashboard.overview", "/api/alarm-dashboard/overview", lambda d: isinstance(d, dict), "JSON 对象"),
        ("alarm_dashboard.history_drilldown", "/api/alarm-dashboard/history-drilldown", lambda d: isinstance(d, dict), "JSON 对象"),
        ("alarm_dashboard.realtime_drilldown", "/api/alarm-dashboard/realtime-drilldown", lambda d: isinstance(d, dict), "JSON 对象"),
        ("packet_loss.overview", "/api/packet-loss-dashboard/overview", lambda d: isinstance(d, dict), "JSON 对象"),
        ("packet_loss.map_sites", "/api/packet-loss-dashboard/map-sites", lambda d: isinstance(d, dict), "JSON 对象"),
        ("packet_loss.drilldown", "/api/packet-loss-dashboard/drilldown", lambda d: isinstance(d, dict), "JSON 对象"),
        ("battery_dashboard.all", "/api/battery-dashboard/all", lambda d: isinstance(d, dict), "JSON 对象"),
        ("battery_dashboard.trend", "/api/battery-dashboard/trend?days=7&source=auto", lambda d: isinstance(d, dict), "JSON 对象"),
        ("sp_dashboard.summary", "/api/sp-data/summary", lambda d: isinstance(d, dict), "JSON 对象"),
        ("sp_dashboard.warehouses", "/api/warehouses", lambda d: isinstance(d, dict), "JSON 对象"),
        ("sp_dashboard.data", "/api/data", lambda d: isinstance(d, dict), "JSON 对象"),
        ("gis.sites", "/api/gis/sites", lambda d: isinstance(d, dict), "JSON 对象"),
        ("gis.regions_summary", "/api/gis/regions/summary", lambda d: isinstance(d, dict), "JSON 对象"),
        ("gis.topology", "/api/gis/topology", lambda d: isinstance(d, dict), "JSON 对象"),
        ("tasks.list", "/api/tasks", lambda d: isinstance(d, dict), "JSON 对象"),
        ("tasks.history", "/api/tasks/history", lambda d: isinstance(d, dict), "JSON 对象"),
        ("tasks.eflow_status", "/api/eflow/status", lambda d: isinstance(d, dict), "JSON 对象"),
        ("tables.list", "/api/tables", lambda d: isinstance(d, dict), "JSON 对象"),
        ("tables.eflow_tt_data", "/api/tables/eflow_tt/data?page=1&page_size=5", lambda d: isinstance(d, dict), "JSON 对象"),
    ]
    for name, path, check, desc in checks:
        t0 = time.time()
        status, data, raw = http_get(path, timeout=45)
        ok = status == 200 and check(data) if data is not None else status == 200
        detail = desc if ok else f"status={status}, check={desc}"
        if not ok and raw:
            detail += " | body=" + raw[:400]
        RESULTS.append((name, ok, status, round(time.time() - t0, 2), detail))

    # tables 路由：从 /api/tables 选 1 个非空表再做 /data 下钻
    status, data, _ = http_get("/api/tables", timeout=45)
    if status == 200 and isinstance(data, dict):
        tables = data.get("tables") or []
        target = next((t["name"] for t in tables if t.get("row_count", 0) > 0 and not t["name"].startswith("_")), None)
        if target:
            name = f"tables.{target}_data"
            t0 = time.time()
            st, d, raw = http_get(f"/api/tables/{target}/data?page=1&page_size=5", timeout=45)
            ok = st == 200 and isinstance(d, dict)
            detail = "JSON 对象" if ok else f"status={st} body={raw[:400]}"
            RESULTS.append((name, ok, st, round(time.time() - t0, 2), detail))
        else:
            log("[tables] 未找到非空表，跳过动态 /data 检查")
    else:
        RESULTS.append(("tables.dynamic_data", False, status, 0.0, "无法从 /api/tables 获取表列表"))


def _db_info_ok(data) -> bool:
    if not isinstance(data, dict) or data.get("db_mode") != "pg":
        return False
    names = {t.get("name") for t in (data.get("tables") or [])}
    return all(x in names for x in ("app.eflow_tt", "lte_pl.packet_loss_data", "battery.battery_reading"))


def run_sql_checks(env: dict) -> None:
    import psycopg2

    conn = None
    try:
        conn = psycopg2.connect(env["DATABASE_URL"], connect_timeout=10)
        cur = conn.cursor()
        checks = [
            ("schema_table.app.eflow_tt", "SELECT to_regclass('app.eflow_tt') IS NOT NULL"),
            ("schema_table.lte_pl.packet_loss_data", "SELECT to_regclass('lte_pl.packet_loss_data') IS NOT NULL"),
            ("schema_table.battery.battery_reading", "SELECT to_regclass('battery.battery_reading') IS NOT NULL"),
            ("schema.ran_ume_ro", "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name='ran_ume_ro')"),
        ]
        for name, sql in checks:
            t0 = time.time()
            cur.execute(sql)
            ok = bool(cur.fetchone()[0])
            RESULTS.append((name, ok, 200, round(time.time() - t0, 2), "SQL 通过" if ok else "SQL 校验失败"))
        cur.close()
    except Exception as e:
        RESULTS.append(("sql.connect", False, 0, 0.0, f"{type(e).__name__}: {e}"))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def stop_server(proc, log_file) -> None:
    log("[server] 关闭 uvicorn 进程...")
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
    try:
        log_file.close()
    except Exception:
        pass
    deadline = time.time() + 10
    while time.time() < deadline and port_in_use(PORT):
        time.sleep(0.3)
    if port_in_use(PORT):
        log(f"[server] 警告：{PORT} 端口仍被占用（可能是历史进程），未做强制清理")
    else:
        log("[server] 7099 端口已释放")


def print_summary() -> int:
    passed = sum(1 for r in RESULTS if r[1])
    total = len(RESULTS)
    log("")
    log("=" * 78)
    log(f"Phase 6 PG 冒烟测试汇总：PASS {passed}/{total}")
    log("=" * 78)
    for name, ok, status, elapsed, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        log(f"  [{mark}] {name:<42} status={status:<4} {elapsed:>6.2f}s  {detail}")
    log("=" * 78)
    return 0 if passed == total else 1


def main() -> int:
    log("===== Phase 6 PostgreSQL API 冒烟测试 =====")
    log(f"项目根目录: {ROOT}")
    log(f"Python: {_PYTHON}")

    if port_in_use(PORT):
        log(f"FAIL: 端口 {PORT} 已被占用，请先释放后重试（脚本不会清理未知进程）")
        return 1

    if not check_py_compile():
        log("FAIL: py_compile 未通过，中止冒烟测试")
        return 1

    env = build_env()
    log(f"[env] MY_APP_DB_MODE={env['MY_APP_DB_MODE']}  MY_APP_DISABLE_SCHEDULER={env['MY_APP_DISABLE_SCHEDULER']}")
    log(f"[env] DATABASE_URL={sanitize_url(env['DATABASE_URL'])}")

    proc = None
    log_file = None
    try:
        proc, log_file = start_server(env)
        if not wait_server(proc, log_file):
            return 1
        run_http_checks()
        run_sql_checks(env)
        # 收尾再确认服务仍存活
        status, data, _ = http_get("/api/health", timeout=10)
        RESULTS.append(("server.alive_final", status == 200 and data.get("db_mode") == "pg",
                        status, 0.0, "最终 /api/health 存活检查"))
    finally:
        stop_server(proc, log_file)
        failed = any(not r[1] for r in RESULTS)
        if failed:
            log("")
            log("[server] 存在失败项，保留 uvicorn 日志供排查: " + str(LOG_FILE))
            _print_log_tail(log_file, lines=200)
        else:
            try:
                if LOG_FILE.exists():
                    LOG_FILE.unlink()
            except Exception:
                pass

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
