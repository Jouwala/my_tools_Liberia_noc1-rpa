#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
核查一张 TT 工单的派单依据 —— 回答「这张单是不是派错了？」

用法:
    python tools/inspect_tt.py TT202608220047
    python tools/inspect_tt.py TT202608220047 --json
    python tools/inspect_tt.py TT202608220047 --db <app.db路径>

输出:
    1. 工单基本信息（站点 / 时间 / 告警 / 根因 / 派单组）
    2. 告警时刻 → 派单时刻 的时间差（延迟派单会导致站点状态变化）
    3. 掉站制式分布（2G/3G/4G）
    4. 该根因在全库的派单归属分布（判断这次派单是否属于常规）
    5. 结论提示

说明:
    本工具输出在终端、不落盘，因此不做脱敏（运维排查需要看真实处理人）。
    若要粘贴到文档/群里，请自行隐去人员字段。

    核心分析逻辑在 analyze_tt()，返回结构化 dict —— my_app 的
    /api/eflow-qa/inspect-tt 端点与页面「TT 分析」组件复用同一份实现，
    改这里两边同时生效。
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_DB = r"D:\01_RPA\Task\my_app\db\app.db"

# 报告要展示的关键字段（按业务阅读顺序）
FIELDS = [
    ("站点", ["site_name", "site_id", "ne_name", "ne_id", "region_level1"]),
    ("时间", ["alarm_occur_time", "created_time", "last_modified_time",
              "alarm_clear_time", "sla_deadline", "fault_duration_time"]),
    ("告警", ["alarm_severity", "alarm_type", "alarm_code", "alarm_reason_type",
              "sub_alarm_name", "impacted_service", "site_outage"]),
    ("制式掉站", ["col_2g_down_site_count", "col_3g_down_site_count",
                  "col_4g_down_site_count", "col_5g_down_site_count",
                  "down_site_count", "down_site_list"]),
    ("根因", ["root_cause", "sub_root_cause", "root_cause_description",
              "specific_problem"]),
    ("派单", ["last_processer_group", "last_processer", "last_process_time",
              "organization_id", "vendor"]),
    ("状态", ["status", "ticket_severity", "suspended", "sla_status",
              "fault_resolved", "operation_type"]),
]


def parse_dt(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def fmt_dt(s):
    return str(s) if s else "—"


def clean(v, maxlen=150):
    if v is None:
        return "—"
    s = str(v).replace("\n", " / ").replace("\r", "").strip()
    if not s:
        return "—"
    return s if len(s) <= maxlen else s[:maxlen] + "…"


def analyze_tt(tt_no, db_path=DEFAULT_DB):
    """分析一张 TT 工单，返回结构化 dict（CLI 与 my_app API 共用）。

    返回：
      未找到: {"found": False, "tt_no":..., "error":..., "suggestions": [...]}
      找到:   {"found": True, "tt_no":..., "fields":[{section,items:[{key,value}]}],
               "timing":{...}, "down_type":..., "csd_psd":{...},
               "root_cause_stats":{...}}
    """
    if not os.path.exists(db_path):
        return {"found": False, "tt_no": tt_no, "error": f"数据库不存在: {db_path}", "suggestions": []}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tabs = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "eflow_tt" not in tabs:
            return {"found": False, "tt_no": tt_no, "error": "数据库里没有 eflow_tt 表", "suggestions": []}

        cols = [r[1] for r in conn.execute("PRAGMA table_info('eflow_tt')").fetchall()]
        key_col = "tt_no" if "tt_no" in cols else None
        if not key_col:
            return {"found": False, "tt_no": tt_no, "error": "eflow_tt 表里找不到 tt_no 列", "suggestions": []}

        row = conn.execute(
            f"SELECT * FROM eflow_tt WHERE {key_col}=?", (tt_no,)).fetchone()
        if not row:
            like = conn.execute(
                f"SELECT {key_col} FROM eflow_tt WHERE {key_col} LIKE ? LIMIT 5",
                (f"%{tt_no}%",)).fetchall()
            return {"found": False, "tt_no": tt_no,
                    "error": f"未找到工单 {tt_no}",
                    "suggestions": [r[0] for r in like]}

        d = {k: row[k] for k in cols}

        # 时间差
        occur = parse_dt(d.get("alarm_occur_time"))
        created = parse_dt(d.get("created_time"))
        lag = None
        lag_txt = "—（时间字段缺失或格式无法解析）"
        if occur and created:
            lag = created - occur
            lag_s = lag.total_seconds()
            lag_txt = f"{int(lag_s // 3600)} 小时 {int((lag_s % 3600) // 60)} 分 " \
                      f"{int(lag_s % 60)} 秒  ({lag_s / 3600:.2f} h)"

        # 掉站类型
        sub_alarm = str(d.get("sub_alarm_name") or "")
        if "CSD" in sub_alarm:
            down_type = "CSD（Complete Site Down / 全部掉站）"
        elif "PSD" in sub_alarm:
            down_type = "PSD（Partial Site Down / 部分掉站）"
        else:
            down_type = "告警名中未标注 CSD/PSD"

        # 根因在全库的派单分布
        rc = d.get("root_cause")
        rc_stats = []
        if rc:
            sql = """SELECT REPLACE(REPLACE(last_processer_group,char(10),''),char(13),'') g,
                            COUNT(*) n FROM eflow_tt
                     WHERE root_cause=? AND last_processer_group IS NOT NULL
                       AND TRIM(last_processer_group)<>''
                     GROUP BY 1 ORDER BY n DESC LIMIT 5"""
            rc_stats = conn.execute(sql, (rc,)).fetchall()
            rc_total = conn.execute(
                "SELECT COUNT(*) FROM eflow_tt WHERE root_cause=?", (rc,)).fetchone()[0]
        else:
            rc_total = 0

        # CSD/PSD 对照
        csd_p3 = conn.execute(
            "SELECT COUNT(*) FROM eflow_tt WHERE sub_alarm_name LIKE '%CSD%' "
            "AND last_processer_group LIKE '%3rd_Power%'").fetchone()[0]
        csd_all = conn.execute(
            "SELECT COUNT(*) FROM eflow_tt WHERE sub_alarm_name LIKE '%CSD%'").fetchone()[0]
        psd_p3 = conn.execute(
            "SELECT COUNT(*) FROM eflow_tt WHERE sub_alarm_name LIKE '%PSD%' "
            "AND last_processer_group LIKE '%3rd_Power%'").fetchone()[0]
        psd_all = conn.execute(
            "SELECT COUNT(*) FROM eflow_tt WHERE sub_alarm_name LIKE '%PSD%'").fetchone()[0]

        fields = []
        for section, keys in FIELDS:
            items = [(k, d.get(k)) for k in keys if k in d]
            items = [(k, v) for k, v in items
                     if v is not None and str(v).strip() != ""]
            if items:
                fields.append({
                    "section": section,
                    "items": [{"key": k, "value": clean(v)} for k, v in items],
                })

        return {
            "found": True,
            "tt_no": tt_no,
            "fields": fields,
            "timing": {
                "alarm_occur_time": fmt_dt(d.get("alarm_occur_time")),
                "created_time": fmt_dt(d.get("created_time")),
                "lag_hours": round(lag.total_seconds() / 3600, 2) if lag else None,
                "lag_text": lag_txt,
                "delayed_over_1h": bool(lag and lag.total_seconds() > 3600),
            },
            "down_type": down_type,
            "csd_psd": {
                "csd": {"third": csd_p3, "all": csd_all,
                        "pct": round(csd_p3 / csd_all * 100, 1) if csd_all else 0.0},
                "psd": {"third": psd_p3, "all": psd_all,
                        "pct": round(psd_p3 / psd_all * 100, 1) if psd_all else 0.0},
            },
            "root_cause_stats": {
                "root_cause": clean(rc, 80),
                "sub_root_cause": clean(d.get("sub_root_cause"), 80),
                "total": rc_total,
                "groups": [
                    {"group": clean(g, 50),
                     "count": n,
                     "pct": round(n / rc_total * 100, 1) if rc_total else 0.0}
                    for g, n in rc_stats
                ],
                "assigned_3rd_power": "3rd_Power" in str(d.get("last_processer_group") or ""),
            },
            "assigned_group": clean(d.get("last_processer_group"), 60),
            "site_name": clean(d.get("site_name"), 60),
        }
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="核查 TT 工单派单依据")
    ap.add_argument("tt_no", help="TT 单号，如 TT202608220047")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true", help="输出 JSON（analyze_tt 原始结构）")
    args = ap.parse_args()

    if args.json:
        import json
        print(json.dumps(analyze_tt(args.tt_no, args.db),
                         ensure_ascii=False, indent=2))
        return 0

    rep = analyze_tt(args.tt_no, args.db)
    if not rep.get("found"):
        print(f"✗ {rep.get('error')}")
        if rep.get("suggestions"):
            print("  是否想找：")
            for s in rep["suggestions"]:
                print(f"    {s}")
        return 1

    d_rep = rep
    W = 78
    print("=" * W)
    print(f"TT 工单派单依据核查：{args.tt_no}")
    print("=" * W)

    for sec in d_rep["fields"]:
        print(f"\n【{sec['section']}】")
        for it in sec["items"]:
            print(f"  {it['key']:34s} {it['value']}")

    t = d_rep["timing"]
    print(f"\n【时间差（告警 → 派单）】")
    print(f"  {'alarm_occur_time':34s} {t['alarm_occur_time']}")
    print(f"  {'created_time':34s} {t['created_time']}")
    print(f"  {'间隔':34s} {t['lag_text']}")
    if t["delayed_over_1h"]:
        print("  ⚠️ 延迟派单超过 1 小时：派单时刻的站点状态可能已与告警时刻不同，")
        print("     但派单判定以【告警发生时刻】为准，延迟不改变判定结果。")

    print(f"\n【掉站类型】")
    print(f"  {'判定':34s} {d_rep['down_type']}")
    cp = d_rep["csd_psd"]
    print(f"  参考：CSD 派三方占比 {cp['csd']['third']}/{cp['csd']['all']} = "
          f"{cp['csd']['pct']}%  |  "
          f"PSD 派三方占比 {cp['psd']['third']}/{cp['psd']['all']} = "
          f"{cp['psd']['pct']}%")
    print("  → 两者接近，说明掉站类型【不决定】派单归属。")

    print(f"\n【根因归属分布（全库）】")
    rs = d_rep["root_cause_stats"]
    if rs["total"]:
        print(f"  本单 root_cause = {rs['root_cause']}   该根因工单总数 {rs['total']}")
        for g in rs["groups"]:
            print(f"    {g['count']:>7} ({g['pct']:>5.1f}%)  {g['group']}")
        if rs["assigned_3rd_power"]:
            print("  → 本单派往三方电源组，与该根因的常规归属一致。")
    else:
        print("  本单 root_cause 为空，无法比对。")

    print("\n" + "=" * W)
    print("结论要点（人工判断，工具只提供数据）")
    print("=" * W)
    print(f"  1. 根因：{rs['root_cause']} / {rs['sub_root_cause']}"
          f" —— 派单归属主要看这个")
    print(f"  2. 掉站类型：{d_rep['down_type']} —— 不影响归属，别拿它当理由")
    print(f"  3. 派往：{d_rep['assigned_group']}")
    print(f"  4. 延迟：{t['lag_text']}")
    print()
    print("  详细规则见：00_操作篇_Operations/02_告警与故障_Alarm/")
    print("              掉站工单派单归属判定规则.md")
    print("=" * W)
    return 0


if __name__ == "__main__":
    sys.exit(main())
