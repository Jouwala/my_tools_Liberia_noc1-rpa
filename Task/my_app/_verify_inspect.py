# -*- coding: utf-8 -*-
"""离线验证 analyze_tt_remote/_build_report 重构正确性，不影响任何库。"""
import sys, sqlite3, importlib.util
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

spec = importlib.util.spec_from_file_location("it", r"D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py")
it = importlib.util.module_from_spec(spec); spec.loader.exec_module(it)

db = it.DEFAULT_DB
conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
row = conn.execute("SELECT * FROM eflow_tt WHERE tt_no='TT202609100084'").fetchone()
conn.close()
assert row, "sample ticket not in db"
d = {k: row[k] for k in row.keys()}

# 1) 远程模拟：用本地行当作 eFlow 实时行，验证 analyze_tt_remote
rep = it.analyze_tt_remote("TT202609100084", d, db)
print("found:", rep.get("found"), "| site:", rep.get("site_name"), "| grp:", rep.get("assigned_group"))
print("alarm found:", (rep.get("alarm") or {}).get("found"), "| source:", (rep.get("alarm") or {}).get("source"))
print("timing lag_text:", (rep.get("timing") or {}).get("lag_text"))
print("fields sections:", [s["section"] for s in rep.get("fields", [])])
print("skill_prompt head:", (rep.get("skill_prompt") or "")[:60])
print("has analyze_tt_remote:", hasattr(it, "analyze_tt_remote"), "| has _build_report:", hasattr(it, "_build_report"))

# 2) 本地 analyze_tt 行为回归
rep2 = it.analyze_tt("TT202609100084", db)
print("\nlocal analyze_tt found:", rep2.get("found"), "-> same keys:", set(rep.keys()) == set(rep.keys()))
# not-found 回归
rep3 = it.analyze_tt("TT202609100091", db)
print("not-found ticket still found=False:", not rep3.get("found"), "| error:", rep3.get("error"))