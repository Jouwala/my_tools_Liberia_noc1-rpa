# -*- coding: utf-8 -*-
"""验证：1) 真正不存在的单号仍 found=False；2) fetch_tt_live 实网拉取归一化。"""
import io, sys, importlib.util
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

spec = importlib.util.spec_from_file_location("it", r"D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py")
it = importlib.util.module_from_spec(spec); spec.loader.exec_module(it)

# 1) not-found 回归（用确定不存在的单号）
rep = it.analyze_tt("TT999912340001", it.DEFAULT_DB)
print("nonexistent analyzed -> found:", rep.get("found"), "| error:", rep.get("error"))

# 2) 实网 fetch_tt_live
from backend.services.eflow_data_mapper import fetch_tt_live
row = fetch_tt_live("TT202609100091")
if row is None:
    print("fetch_tt_live -> None (未命中)")
else:
    print("fetch_tt_live -> 命中，tt_no:", row.get("tt_no"),
          "| site_name:", row.get("site_name"),
          "| status:", row.get("status"),
          "| created_time:", row.get("created_time"),
          "| alarm_occur_time:", row.get("alarm_occur_time"),
          "| alarm_id:", row.get("alarm_id"))
    # 用实时行构建远程报告
    rrep = it.analyze_tt_remote("TT202609100091", row, it.DEFAULT_DB)
    print("remote report found:", rrep.get("found"), "| site:", rrep.get("site_name"))