# -*- coding: utf-8 -*-
"""progress 宽表重建（看板 `progress` / `progress_v3` 的数据源）。

=========================== 这张表是什么 ===========================

`progress.sqlite3.progress_full` = `Eflow_TT_FB` **LEFT JOIN** `Eflow_WO_FB`
（按 `WO No.`，1:1，已验证 12739 distinct / 12739 rows）后的宽表，
逐行复刻 FineDB 数据集 `4bc5a679` 的 Progress 相关计算列：

    WO/IPT/Fiber/BO/FO 各自的 ORG + STATUS、ORG_F/STATUS_F、
    FB_ORG1/FB_STATUS1/FB_ORG2/FB_ORG/FB_STATUS2/FB_STATUS21/FB_STATUS、
    ORG_Handler、Month、MTTR1/MTTR2、clear_null

说明（与原脚本一致）：
  - `Duration(Hours)` / `SLA(%)` 依赖「当前时间」，**不落库**；
    组件 SQL 里用 `julianday('now','localtime')` 实时算。
  - `'nan'` / `'NaT'` / `''` 一律按 NULL 处理（FineBI 日期/文本解析的空形态）。

=========================== 为什么收进 my_app ===========================

原实现是 my-finebi 项目的一次性脚本 `TMP/etl_progress.py`，属于**手工
「ETL 快照刷新」**。my-finebi 门户退役后无人再跑 —— 表冻结在 2026-08-31，
`?page=finebi_progress` / `?page=finebi_progress_v3` 静默停更
（2026-09-21 与 avail_recon / mttr_tt 一并发现）。

现在由定时任务 `progress_sync` 每日重建到本机 `data/progress.sqlite3`。

=========================== 数据来源 ===========================

全部来自远端 `db.sqlite3`（`Eflow_TT_FB` 35k 行 + `Eflow_WO_FB` 14k 行，
均在远端 API 单次 5 万行上限内），不依赖任何 my-finebi 侧文件。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.remote_readonly import query_dicts

logger = logging.getLogger("progress_sync")

SERVICE_DIR = Path(__file__).resolve().parent
OUT_DB = SERVICE_DIR.parent.parent / "data" / "progress.sqlite3"

SRC_DB = "db.sqlite3"

TT_SQL = '''SELECT "Ticket No.","Title","Status","TT Source","Creator","Ticket Severity",
    "Current Handler","Created Time","Alarm Occur Time","Alarm Clear Time","Region ID",
    "Site ID","Site Name","WO No.","Third Accept Detail","Third Process Detail","BO Process Detail"
    FROM "Eflow_TT_FB"'''

WO_SQL = '''SELECT "WO No.","Status","Current Handler","Operation Step","E2E SLA Status",
    "Fault Duration Time","Down Site List" FROM "Eflow_WO_FB"'''

DDL = """CREATE TABLE progress_full (
  "Ticket No." TEXT, "Title" TEXT, "Status" TEXT, "TT Source" TEXT, "Creator" TEXT,
  "Ticket Severity" TEXT, "Current Handler" TEXT, "Created Time" TEXT,
  "Alarm Occur Time" TEXT, "Alarm Clear Time" TEXT, "Region ID" TEXT,
  "Site ID" TEXT, "Site Name" TEXT, "WO No." TEXT,
  "Third Accept Detail" TEXT, "Third Process Detail" TEXT, "BO Process Detail" TEXT,
  "WO Status" TEXT, "WO Current Handler" TEXT, "WO Operation Step" TEXT,
  "E2E SLA Status" TEXT, "Fault Duration Time1" TEXT, "Down Site List1" TEXT,
  "WO_ORG" TEXT, "WO_STATUS" TEXT, "IPT_ORG" TEXT, "IPT_STATUS" TEXT,
  "Fiber_ORG" TEXT, "Fiber_STATUS" TEXT, "BO_ORG" TEXT, "BO_STATUS" TEXT,
  "FO_ORG" TEXT, "FO_STATUS" TEXT, "ORG_F" TEXT, "STATUS_F" TEXT,
  "FB_ORG1" TEXT, "FB_STATUS1" TEXT, "FB_ORG2" TEXT, "FB_ORG" TEXT,
  "FB_STATUS2" TEXT, "FB_STATUS21" TEXT, "FB_STATUS" TEXT,
  "ORG_Handler" TEXT, "Month" TEXT, "MTTR1" REAL, "MTTR2" REAL, "clear_null" INTEGER)"""

NULLISH = ("", "nan", "NaT", "None")

# ============================================================
# 外部化配置（Settings →「任务配置」维护的 progress_config.json）
#   优先级：环境变量 > 配置文件 > 内置默认。src_db 是 DbWriter 侧的库逻辑名，不是本地路径。
# ============================================================
try:
    from backend.services.task_config_files import apply_config_overrides
except ImportError:
    from task_config_files import apply_config_overrides  # type: ignore

apply_config_overrides(
    globals(),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "progress_config.json"),
    {
        "src_db": ("SRC_DB", str, "PROGRESS_SRC_DB"),
    },
    log_name="progress",
)


class ProgressSyncError(Exception):
    """重建失败（远端不可达 / 源表为空等）。"""


# ----------------------------------------------------------------------
# 口径辅助（逐字移植自 TMP/etl_progress.py，勿随意"优化"）
# ----------------------------------------------------------------------
def nn(v: Any) -> Optional[str]:
    """normalize null-ish：''/'nan'/'NaT'/'None' → None。"""
    if v is None:
        return None
    s = str(v).strip()
    if s in NULLISH:
        return None
    return s


def parse_ts(s: Any) -> Optional[datetime]:
    s = nn(s)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            pass
    return None


def SWITCH(x: Any, *pairs_default: Any) -> Any:
    """FineBI SWITCH(expr, v1, r1, ..., default)。"""
    *pairs, default = pairs_default
    it = iter(pairs)
    for v, r in zip(it, it):
        if x == v:
            return r
    return default


def _first_nonempty(*vals: Any) -> Any:
    for v in vals:
        if v is not None and str(v).strip() != "":
            return v
    return ""


def _derive(d: Dict[str, Any], w: Optional[Dict[str, Any]]) -> Tuple[Any, ...]:
    """一行 TT（+ 关联 WO）→ progress_full 的 47 个字段。"""
    status = nn(d["Status"]) or ""
    handler = nn(d["Current Handler"])
    wono = nn(d["WO No."])
    clear = nn(d["Alarm Clear Time"])
    occur = nn(d["Alarm Occur Time"])
    created = nn(d["Created Time"])
    bo_detail = nn(d["BO Process Detail"])
    wo_status = nn(w["Status"]) if w else None
    has_wo = wono is not None   # OR(NOT ISNULL, !='')：nn 已合一

    # ---- WO_ORG / WO_STATUS（bean 7/8，WO 系）----
    if status == "Closed":
        wo_org, wo_st = "", "Closed"
    elif has_wo:
        wo_org = SWITCH(wo_status or "",
            "Wait For Confirm", "FO", "Waiting for FO Process", "FO",
            "Waiting for BONPO Process", "BO", "Waiting for Accept", "FE",
            "Waiting for FO Process(FE Handling)", "FE",
            "Waiting for FO Process(WO Confirming)", "FE",
            "Waiting for FO Process(WO refused by FE)", "FE",
            "Waiting for FO Process(WO Dispatched FE Handling)", "FE",
            "Waiting for FO Process(WO Reject to FO Confirm)", "FO",
            "Waiting For Start Trip", "FE", "Waiting for Arrive Site", "FE",
            "Waiting for Process", "FE", "Closed", "FO", "", "FO", "")
        wo_st = SWITCH(wo_status or "",
            "Wait For Confirm", "Refused", "Waiting for BONPO Process", "Accept",
            "Waiting for Accept", "WaitingAccept", "Waiting For Start Trip", "Accept",
            "Waiting for Arrive Site", "Accept", "Waiting for Process", "Accept",
            "Closed", "WaitingConfirm", "", "WaitingProcess", "")
    else:
        wo_org, wo_st = "", ""

    # ---- IPT（bean 9/10，handler 含 3rd_power）----
    ipt_org = ipt_st = ""
    if handler:
        if "3rd_power" in handler.lower().strip():
            ipt_org = SWITCH(status, "Waiting for Third Accept", "IPT",
                             "Waiting for Third Process", "IPT",
                             "Wait For Confirm", "FO", "Closed", "IPT", "")
        if "3rd_Power" in handler:  # 原公式区分大小写
            ipt_st = SWITCH(status, "Waiting for Third Accept", "WaitingAccept",
                            "Waiting for Third Process", "Accept",
                            "Wait For Confirm", "Refused", "Closed", "Closed", "")

    # ---- Fiber（bean 11/12，handler 含 3rd_Fiber）----
    fiber_org = fiber_st = ""
    if handler and "3rd_Fiber" in handler:
        fiber_org = SWITCH(status, "Waiting for Third Accept", "Fiber",
                           "Waiting for Third Process", "Fiber",
                           "Wait For Confirm", "FO", "Closed", "", "")
        fiber_st = SWITCH(status, "Waiting for Third Accept", "WaitingAccept",
                          "Waiting for Third Process", "Accept",
                          "Wait For Confirm", "Refused", "Closed", "Closed", "")

    # ---- BO（bean 13/14）----
    bo_org = bo_st = ""
    if not has_wo:
        if status in ("Waiting for BO Accept", "Waiting for BO Process"):
            bo_org = "BO"
        elif (status == "closed" and bo_detail and
              "Operation Groups:G:ZTE_BO" in bo_detail.replace(";", "").replace(".", "")):
            bo_org = ""
    else:
        if status == "Waiting for BO Accept":
            bo_st = "WaitingAccept"
        elif status == "Waiting for BO Process":
            bo_st = "Accept" if clear is None else "Accept_Restor"
        elif (status == "closed" and bo_detail and
              "Operation Groups:G:ZTE_BO" in bo_detail.replace(";", "").replace(".", "")):
            bo_st = "Closed"

    # ---- FO（bean 15/16，无 WO 时）----
    fo_org = fo_st = ""
    if not has_wo:
        fo_org = SWITCH(status,
            "Wait For Confirm", "FO", "Waiting for FO Process", "FO",
            "Waiting for FO Process(FE Handling)", "FE",
            "Waiting for FO Process(WO Confirming)", "FE",
            "Waiting for Third Process", "3rd",
            "Waiting for Third Accept(Suspended)", "3rd",
            "Waiting for FO Process(WO Dispatched FE Handling)", "FE",
            "Closed(WO Confirming)", "FO", "Closed(FE Handling)", "FE",
            "Wait For Confirm(WO Confirming)", "FO", "")
        fo_st = SWITCH(status,
            "Wait For Confirm", "WaitingConfirm",
            "Waiting for FO Process", "WaitingProcess",
            "Waiting for FO Process(FE Handling)", "WaitingProcess",
            "Waiting for FO Process(WO Confirming)", "WaitingConfirm",
            "Closed(WO Confirming)", "WaitingConfirm",
            "Closed(FE Handling)", "WaitingProcess",
            "Wait For Confirm(WO Confirming)", "WaitingConfirm", "")

    # ---- ORG_F / STATUS_F（bean 17/18，首个非空）----
    if status != "Closed":
        org_f = _first_nonempty(wo_org, ipt_org, fiber_org, bo_org, fo_org)
        status_f = _first_nonempty(wo_st, ipt_st, fiber_st, bo_st, fo_st)
    else:
        org_f, status_f = "", "Closed"

    # ---- FB_ORG1 / FB_STATUS1 / FB_ORG2（bean 19/20/21，级联 IF）----
    if status == "Closed":
        fb_org1, fb_status1, fb_org2 = "", "Closed", ""
    else:
        if org_f.strip() != "":
            fb_org1 = fb_org2 = org_f
        else:
            fb_org1 = SWITCH(status, "Waiting for Third Accept", "3rd",
                "Waiting for Third Process(WO Confirming)", "3rd",
                "Waiting for FO Process", "FO", "Wait For Confirm", "FO",
                "Waiting for BO Process", "BO", "")
            fb_org2 = SWITCH(status, "Waiting for Third Accept", "Orange",
                "Waiting for FO Process(WO Dispatched FE Handling)", "FE",
                "Waiting for FO Process(WO Reject to FO Confirm)", "FO",
                "Waiting for FO Process", "FO", "Wait For Confirm", "FO",
                "Waiting for BO Process", "BO", "")
        if status_f.strip() != "":
            fb_status1 = status_f
        else:
            fb_status1 = SWITCH(status,
                "Waiting for Third Accept", "WaitingAccept",
                "Waiting for Third Process(WO Confirming)", "WaitingConfirm",
                "Waiting for FO Process", "WaitingProcess",
                "Wait For Confirm", "WaitingConfirm",
                "Waiting for FO Process(WO Dispatched FE Handling)", "WaitingProcess",
                "Waiting for Third Process", "WaitingProcess",
                "Waiting for Third Accept(Suspended)", "WaitingAccept",
                "Waiting for FO Process(WO Reject to FO Confirm)", "WaitingConfirm",
                "Waiting for BO Process", "Accept", "")

    # ---- FB_ORG（bean 22）----
    if fb_org2 is None or fb_org2 == "":
        fb_org = SWITCH(status,
            "Waiting for Third Process(WO Confirming)", "3rd",
            "Waiting for BO Process(WO Confirming)", "BO",
            "Waiting for BO Accept(WO Confirming)", "BO",
            "Wait For Confirm", "FO", "Waiting for FO Process", "FO",
            "Waiting for FO Process(FE Handling)", "FO",
            "Waiting for FO Process(WO Confirming)", "FO",
            "Closed(WO Confirming)", "FO", "Closed(FE Handling)", "FO",
            "Wait For Confirm(WO Confirming)", "FO", "")
    else:
        fb_org = fb_org2

    # ---- FB_STATUS2 / FB_STATUS21 / FB_STATUS（bean 23/24/25）----
    clear_not_null = clear is not None
    if status != "Closed" and clear_not_null and fb_org == "FO":
        fb_status2 = "WaitingClose"
    else:
        fb_status2 = fb_status1
    if status != "Closed":
        if fb_status2 == "Refused":
            fb_status21 = "Reassign"
        elif fb_status2 in ("Accept_Restor", "WaitingConfirm") and clear_not_null:
            fb_status21 = "WaitingClose"
        elif fb_status2 in ("Accept", "Accept_Restor"):
            fb_status21 = "WaitingProcess"
        else:
            fb_status21 = fb_status2
    else:
        fb_status21 = fb_status2
    if fb_status21 is None or fb_status21 == "":
        fb_status = SWITCH(status,
            "Wait For Confirm", "WaitingConfirm",
            "Waiting for FO Process", "WaitingProcess",
            "Waiting for FO Process(FE Handling)", "WaitingProcess",
            "Waiting for FO Process(WO Confirming)", "WaitingConfirm",
            "Closed(WO Confirming)", "WaitingConfirm",
            "Closed(FE Handling)", "WaitingProcess",
            "Wait For Confirm(WO Confirming)", "WaitingConfirm",
            "Waiting for Third Process(WO Confirming)", "WaitingConfirm",
            "Waiting for BO Process(WO Confirming)", "WaitingConfirm",
            "Waiting for BO Accept(WO Confirming)", "WaitingConfirm", "")
    else:
        fb_status = fb_status21

    # ---- ORG_Handler（bean 46）----
    org_handler = "ZTE" if (handler and "ZTE" in handler) else "3rd"

    # ---- Month / MTTR ----
    month = occur[:7] if occur else None
    o, c = parse_ts(occur), parse_ts(clear)
    mttr1 = mttr2 = None
    if o and c:
        mttr1 = (c - o).total_seconds() / 3600.0
        if 0 < mttr1 < 48:
            mttr2 = mttr1

    return (
        d["Ticket No."], nn(d["Title"]), status, nn(d["TT Source"]), nn(d["Creator"]),
        nn(d["Ticket Severity"]), handler, created, occur, clear,
        nn(d["Region ID"]), nn(d["Site ID"]), nn(d["Site Name"]), wono,
        nn(d["Third Accept Detail"]), nn(d["Third Process Detail"]), bo_detail,
        wo_status, nn(w["Current Handler"]) if w else None,
        nn(w["Operation Step"]) if w else None,
        nn(w["E2E SLA Status"]) if w else None,
        nn(w["Fault Duration Time"]) if w else None,
        nn(w["Down Site List"]) if w else None,
        wo_org, wo_st, ipt_org, ipt_st, fiber_org, fiber_st, bo_org, bo_st,
        fo_org, fo_st, org_f, status_f,
        fb_org1, fb_status1, fb_org2, fb_org, fb_status2, fb_status21, fb_status,
        org_handler, month, mttr1, mttr2, 0 if clear_not_null else 1)


# ----------------------------------------------------------------------
# 重建
# ----------------------------------------------------------------------
def build(target: Path = OUT_DB, progress=None) -> Dict[str, Any]:
    """全量重建 progress_full 到 target（原子替换）。"""
    t0 = time.time()
    say = progress or (lambda m: logger.info("%s", m))

    say(f"[1/4] 读取远端 {SRC_DB} 的 TT / WO ...")
    tt = query_dicts(SRC_DB, TT_SQL)
    wo = {r["WO No."]: r for r in query_dicts(SRC_DB, WO_SQL)}
    if not tt:
        raise ProgressSyncError("TT 明细为空，拒绝重建（否则会把看板写成空）")
    say(f"      TT={len(tt)}  WO={len(wo)}")

    say("[2/4] 逐行推导 Progress 计算列 ...")
    batch: List[Tuple[Any, ...]] = []
    wo_hit = 0
    for d in tt:
        wono = nn(d["WO No."])
        w = wo.get(wono) if wono else None
        if w is not None:
            wo_hit += 1
        batch.append(_derive(d, w))

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(str(tmp), timeout=60)
    try:
        out.execute(DDL)
        out.executemany(
            "INSERT INTO progress_full VALUES (" + ",".join("?" * 47) + ")", batch)
        out.execute('CREATE INDEX idx_pf_month ON progress_full("Month")')
        out.execute('CREATE INDEX idx_pf_status ON progress_full("Status")')
        out.execute('CREATE INDEX idx_pf_fb ON progress_full("FB_STATUS","FB_ORG")')
        out.commit()
        stat = out.execute('SELECT MIN("Alarm Occur Time"), MAX("Alarm Occur Time"), '
                           'COUNT(*) FROM progress_full WHERE "Alarm Occur Time" LIKE \'2%\''
                           ).fetchone()
    finally:
        out.close()

    os.replace(tmp, target)
    elapsed = round(time.time() - t0, 2)
    say(f"[3/4] 写入 {len(batch)} 行（WO join 命中 {wo_hit}）")
    say(f"[4/4] 完成：真实日期范围 {stat[0]} ~ {stat[1]}，耗时 {elapsed}s -> {target}")
    return {
        "success": True,
        "rows": len(batch),
        "wo_join_hit": wo_hit,
        "min_occur": stat[0],
        "max_occur": stat[1],
        "path": str(target),
        "elapsed_seconds": elapsed,
    }


def run_progress_sync(target: Path = OUT_DB) -> Dict[str, Any]:
    """task_registry 入口：重建本机 progress.sqlite3。"""
    started = datetime.now().isoformat(timespec="seconds")
    logger.info("[progress] 开始重建，目标 %s", target)
    try:
        res = build(target)
    except Exception as e:  # noqa: BLE001 — 任务层要把失败回报给调度器
        logger.error("[progress] 重建失败: %s", e, exc_info=True)
        return {"success": False, "started": started, "errors": [str(e)]}
    res["started"] = started
    res["finished"] = datetime.now().isoformat(timespec="seconds")
    logger.info("[progress] 重建成功: %s", res)
    return res


if __name__ == "__main__":
    import json
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    r = run_progress_sync(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DB)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("success") else 1)
