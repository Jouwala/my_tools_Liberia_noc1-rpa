# -*- coding: utf-8 -*-
"""
Deep test for ran_ume_network_kpi.py
-------------------------------------
Drives the REAL data-fetching functions of the script (login -> create history
query -> poll until ready -> export xlsx) for all 8 task types, but with a small
time window so queries return fast. Exports go to a TEMP directory (not ~/Downloads)
to avoid polluting production files. Verifies each exported xlsx contains real rows.

Also validates the DB-import logic (read_xlsx + write_to_db) on a TEMP SQLite DB
WITHOUT calling upload_to_ftp (FTP upload is a destructive side effect we don't run).

Usage:
  cd D:/01_RPA/Task/my_app
  "C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe" tests/test_ran_ume_network_kpi.py
"""
import sys
import os
import io
import json
import time
import glob
import shutil
import sqlite3
import traceback
import importlib.util
from datetime import datetime, timezone, timedelta

# --- locate and import the module under test ---
SERVICES_DIR = r"D:/01_RPA/Task/my_app/backend/services"
TASK_DIR = r"D:/01_RPA/Task"  # needed for auth_manager import
sys.path.insert(0, TASK_DIR)
sys.path.insert(0, SERVICES_DIR)

spec = importlib.util.spec_from_file_location(
    "ran_ume_network_kpi", os.path.join(SERVICES_DIR, "ran_ume_network_kpi.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# --- TEMP sandbox so we never touch ~/Downloads or the production DB / FTP ---
# IMPORTANT: keep TEST_OUT under the OS temp dir so the sandbox safe-delete shim
# lets Python's native os.remove / shutil.rmtree through (recycle bin unavailable).
import tempfile
TEST_OUT = os.path.join(tempfile.gettempdir(), "ran_kpi_test_out")
TEST_DB = os.path.join(TEST_OUT, "ran_kpi_test.sqlite3")
if os.path.exists(TEST_OUT):
    shutil.rmtree(TEST_OUT)
os.makedirs(TEST_OUT, exist_ok=True)

m.OUTPUT_DIR = TEST_OUT   # redirect exports away from ~/Downloads
m.DB_PATH = TEST_DB       # redirect DB (only used if we call import path)

# --- small time window so PM queries return quickly (2 days) ---
_now = datetime.now(timezone.utc)
_end = _now.replace(hour=0, minute=0, second=0, microsecond=0)
_start = (_now - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
START_ISO = _start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
END_ISO = _end.strftime("%Y-%m-%dT%H:%M:%S.000Z")

print(f"[TEST] Time window: {START_ISO}  ->  {END_ISO}")
print(f"[TEST] Export dir (temp): {TEST_OUT}")

results = {
    "login": None,
    "tasks": [],
    "db_import_test": None,
    "ftp_reachability": None,
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "window": {"start": START_ISO, "end": END_ISO},
}


def verify_xlsx(path):
    """Open the exported xlsx and report rows/headers. Returns dict."""
    with open(path, "rb") as f:
        data = f.read()
    wb = m.openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            headers = [str(c).strip() if c is not None else "" for c in next(it)]
        except StopIteration:
            return {"ok": False, "rows": 0, "headers": [], "note": "empty sheet"}
        rows = sum(1 for r in it if any(v is not None for v in r))
    finally:
        wb.close()
    return {
        "ok": rows > 0,
        "rows": rows,
        "headers": headers[:30],
        "header_count": len(headers),
        "bytes": len(data),
    }


# 1) LOGIN
print("\n" + "=" * 70)
print("[STEP 1] LOGIN")
print("=" * 70)
t0 = time.time()
try:
    auth = m.login()
    ok = bool(auth.get("cookie")) and bool(auth.get("forgery_token"))
    results["login"] = {
        "ok": ok,
        "cookie_len": len(auth.get("cookie", "")),
        "has_forgery": bool(auth.get("forgery_token")),
        "elapsed_s": round(time.time() - t0, 2),
    }
    print(f"[LOGIN] ok={ok} elapsed={results['login']['elapsed_s']}s")
    if not ok:
        print("[FATAL] login failed; cannot continue data-fetch test.")
        with open(os.path.join(TEST_OUT, "result.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        sys.exit(0)
except Exception as e:
    results["login"] = {"ok": False, "error": str(e), "trace": traceback.format_exc()}
    print(f"[LOGIN] FAILED: {e}")
    with open(os.path.join(TEST_OUT, "result.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    sys.exit(0)

cookie = auth["cookie"]
forgery = auth["forgery_token"]

# 2) DATA FETCH for ALL 8 tasks (small window, parallel)
print("\n" + "=" * 70)
print("[STEP 2] DATA FETCH - all 8 KPI tasks")
print("=" * 70)

# reduce per-query poll timeout for the test (don't wait the full 300s)
POLL_TIMEOUT = int(os.environ.get("NW_KPI_TEST_POLL_TIMEOUT", "240"))

import concurrent.futures as cf


def run_one(task):
    label = f"{task['tech']}/{task['layer']}"
    rec = {"label": label, "tech": task["tech"], "layer": task["layer"]}
    try:
        t0 = time.time()
        payload = m.build_nw_kpi_payload(
            task["tech"], task["gr"], task["groupbygroup"],
            start_iso=START_ISO, end_iso=END_ISO,
        )
        qid = m.create_history_query(cookie, forgery, payload)
        data = m.wait_history_ready(cookie, forgery, qid, timeout=POLL_TIMEOUT, interval=6)
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        prefix = m.build_filename(payload["templatename"], task["layer"], task["gr"])
        fname = f"{prefix}_{ts}"
        saved = m.export_history(cookie, forgery, qid, fname)
        rec["queryid"] = qid
        rec["file"] = saved
        rec["file_bytes"] = os.path.getsize(saved)
        rec["verify"] = verify_xlsx(saved)
        rec["elapsed_s"] = round(time.time() - t0, 2)
        rec["ok"] = rec["verify"]["ok"]
        # cleanup this test file immediately
        try:
            os.remove(saved)
        except Exception:
            pass
    except Exception as e:
        rec["ok"] = False
        rec["error"] = str(e)
        rec["trace"] = traceback.format_exc()
    return rec


with cf.ThreadPoolExecutor(max_workers=m.MAX_PARALLEL_WORKERS) as ex:
    futs = {ex.submit(run_one, t): t for t in m.NW_KPI_TASKS}
    for fut in cf.as_completed(futs):
        rec = fut.result()
        results["tasks"].append(rec)
        status = "OK" if rec.get("ok") else "FAIL"
        rows = rec.get("verify", {}).get("rows", "-") if rec.get("verify") else "-"
        print(f"[{status}] {rec['label']:10s} rows={rows:>6} "
              f"time={rec.get('elapsed_s','-')}s")

# 3) DB IMPORT LOGIC test (no FTP) - reuse exported data by re-exporting one task to temp
print("\n" + "=" * 70)
print("[STEP 3] DB IMPORT LOGIC (read_xlsx + write_to_db on TEMP db, NO ftp)")
print("=" * 70)
try:
    # pick first successful task file we can regenerate quickly: re-run 2G/Group export
    sample_task = m.NW_KPI_TASKS[0]
    payload = m.build_nw_kpi_payload(
        sample_task["tech"], sample_task["gr"], sample_task["groupbygroup"],
        start_iso=START_ISO, end_iso=END_ISO,
    )
    qid = m.create_history_query(cookie, forgery, payload)
    m.wait_history_ready(cookie, forgery, qid, timeout=POLL_TIMEOUT, interval=6)
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    prefix = m.build_filename(payload["templatename"], sample_task["layer"], sample_task["gr"])
    fname = f"{prefix}_{ts}"
    saved = m.export_history(cookie, forgery, qid, fname)

    headers, data = m.read_xlsx(saved)
    tbl = f"{sample_task['tech']}_OLIB_Network_KPIs"
    # mimic import_to_database column handling minimally: add Group + Source File
    if "Group" not in headers:
        headers.append("Group")
        for row in data:
            row.append(f"{sample_task['tech']}_NW")
    n = m.write_to_db(TEST_DB, tbl, headers, data)

    # verify written rows
    conn = sqlite3.connect(TEST_DB)
    cur = conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
    db_rows = cur.fetchone()[0]
    cur.execute(f'PRAGMA table_info("{tbl}")')
    cols = [r[1] for r in cur.fetchall()]
    conn.close()
    try:
        os.remove(saved)
    except Exception:
        pass
    results["db_import_test"] = {
        "ok": db_rows == n and n > 0,
        "written_rows": n,
        "db_rows": db_rows,
        "columns": cols[:15],
        "note": "write_to_db + read_xlsx verified on temp DB (FTP upload NOT executed)",
    }
    print(f"[DB] written={n} db_rows={db_rows} cols={len(cols)}")
except Exception as e:
    results["db_import_test"] = {"ok": False, "error": str(e), "trace": traceback.format_exc()}
    print(f"[DB] FAILED: {e}")

# 4) FTP reachability only (no upload) - fast socket probe
print("\n" + "=" * 70)
print("[STEP 4] FTP reachability (connect only, NO upload)")
print("=" * 70)
try:
    import socket
    s = socket.create_connection((m.FTP_HOST, 21), timeout=8)
    banner = s.recv(256)
    s.close()
    results["ftp_reachability"] = {
        "ok": True,
        "host": m.FTP_HOST,
        "port": 21,
        "banner": banner.decode("utf-8", "replace").strip()[:80],
        "note": "reachable; actual upload is a destructive side effect and was NOT run",
    }
    print(f"[FTP] reachable: {m.FTP_HOST}:21 -> {results['ftp_reachability']['banner']}")
except Exception as e:
    results["ftp_reachability"] = {"ok": False, "error": str(e),
                                   "note": "reachability probe failed (does not prove upload fails)"}
    print(f"[FTP] unreachable: {e}")

# summary
ok_tasks = [t for t in results["tasks"] if t.get("ok")]
print("\n" + "=" * 70)
print(f"SUMMARY: login={results['login']['ok']}  "
      f"data_fetch={len(ok_tasks)}/{len(results['tasks'])}  "
      f"db_logic={results['db_import_test']['ok'] if results['db_import_test'] else 'n/a'}  "
      f"ftp_reach={results['ftp_reachability']['ok'] if results['ftp_reachability'] else 'n/a'}")
print("=" * 70)

with open(os.path.join(TEST_OUT, "result.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"[TEST] result -> {os.path.join(TEST_OUT, 'result.json')}")
