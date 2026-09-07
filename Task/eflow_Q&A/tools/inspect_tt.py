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
    3. 结论提示

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
from datetime import datetime, timezone

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
    ("告警", ["alarm_id", "aid", "alarm_severity", "alarm_type", "alarm_code",
              "alarm_reason_type", "sub_alarm_name", "impacted_service",
              "site_outage"]),
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


def ms_to_str(v):
    """eFlow 毫秒时间戳 → UTC 可读串（非时间戳原样返回）。"""
    s = str(v)
    if s.replace(".0", "").isdigit() and len(s.replace(".0", "")) >= 13:
        try:
            return datetime.fromtimestamp(int(float(s)) / 1000,
                                          timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return s
    return s


# 告警库记录里要展示的主信息列
ALARM_DISPLAY_COLS = [
    "alarmcode", "codename", "alarm_title", "restypename", "networktype",
    "site_name", "site_id", "site_attribute", "auxiliarycount", "clearstate",
    "alarmraisedtime", "alarmclearedtime", "site_status", "site_vip_level",
    "ran_site_type",
]


def num_tail(v):
    """去掉 eFlow 数值的 '.0' 尾巴（'1764204783913.0' → '1764204783913'）。"""
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def blank(v):
    """eFlow 用 '--' 占位空值，与真正的空串同等对待。"""
    return v is None or str(v).strip() in ("", "--", "—")


def find_alarm_row(conn, alarm_id):
    """按 alarm_id 查实时告警（48h 滚存）→ 历史告警，返回 (sqlite3.Row|None, 表名)。"""
    if not alarm_id:
        return None, ""
    aid = num_tail(alarm_id)
    if not aid.isdigit():
        return None, ""
    for table in ("realtime_alarm", "history_alarm"):
        try:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE CAST(id AS TEXT)=? LIMIT 1",
                (aid,)).fetchone()
        except sqlite3.Error:
            continue
        if row:
            return row, table
    return None, ""


def build_skill_prompt(tt, alarm):
    """拼技能「TT单分析」的入参：告警表为主，eflow_tt 补充。

    vipSite←eflow_tt.vip_site(Yes=1)，alarmCode←alarmcode，
    assetType←site_type，siteSubType←site_attribute(空则 ran_site_type)，
    downSiteCount←auxiliarycount，status←clearstate(0=ACTIVE)。
    """
    def s(v):
        return "" if blank(v) else str(v).strip()

    def num(v):
        x = s(v)
        return x[:-2] if x.endswith(".0") and x[:-2].isdigit() else x

    vip = s(tt.get("vip_site")).lower()
    vip_val = "1" if vip == "yes" else ("0" if vip in ("no", "") else vip)

    if alarm is not None:
        code = num(alarm.get("alarmcode")) or num(tt.get("alarm_code"))
        # site_attribute 常为 eFlow 占位 '--'，ran_site_type 同域（ERA/REGULAR）且有值
        sub_type = s(alarm.get("site_attribute")) or s(alarm.get("ran_site_type"))
        down = num(alarm.get("auxiliarycount")) or s(tt.get("down_site_count"))
        clear = num(alarm.get("clearstate"))
        status = "ACTIVE" if clear == "0" else ("CLEARED" if clear == "1" else clear)
    else:
        code = num(tt.get("alarm_code"))
        sub_type, down, status = "", num(tt.get("down_site_count")), ""

    asset = s(tt.get("site_type"))

    parts = [f"vipSite={vip_val}", f"alarmCode={code}"]
    if asset:
        parts.append(f"assetType={asset}")
    if sub_type:
        parts.append(f"siteSubType={sub_type}")
    if down:
        parts.append(f"downSiteCount={down}")
    if status:
        parts.append(f"status={status}")
    return "请分析以下TT工单：" + " ".join(parts) \
        + "\n请严格按照TT单分析知识库中的规则判断"


def build_alarm_block(alarm_dict, source):
    """告警行（本地库 / eFlow 活查归一化后）→ {found, source, items} 展示块。"""
    if not alarm_dict:
        return {"found": False, "source": "", "items": []}
    items = []
    for k in ALARM_DISPLAY_COLS:
        if k not in alarm_dict:
            continue
        v = alarm_dict[k]
        if blank(v):
            continue
        if k in ("alarmraisedtime", "alarmclearedtime"):
            v = ms_to_str(v)
        else:
            v = num_tail(v)  # 本地库存 float：5.0 → 5
        items.append({"key": k, "value": clean(v)})
    return {"found": True, "source": source, "items": items}


def analyze_tt(tt_no, db_path=DEFAULT_DB):
    """分析一张 TT 工单，返回结构化 dict（CLI 与 my_app API 共用）。

    返回：
      未找到: {"found": False, "tt_no":..., "error":..., "suggestions": [...]}
      找到:   {"found": True, "tt_no":..., "fields":[{section,items:[{key,value}]}],
               "timing":{...}, "root_cause":..., "sub_root_cause":...,
               "assigned_group":..., "site_name":...}
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

        # 按 alarm_id 查实时告警（48h 滚存）→ 历史告警，拿主信息 + 拼技能入参
        alarm_row, alarm_src = find_alarm_row(conn, d.get("alarm_id"))
        alarm_dict = dict(alarm_row) if alarm_row else None
        # 告警行的 AID 列（RAN UME 侧告警 ID）：注入「告警」字段段 + 报告级 aid 字段
        aid_val = num_tail(str((alarm_dict or {}).get("aid") or "").strip())
        if aid_val in ("--", "—", "None"):
            aid_val = ""
        if aid_val:
            d["aid"] = aid_val
        alarm_block = build_alarm_block(alarm_dict, alarm_src)
        skill_prompt = build_skill_prompt(d, alarm_dict)

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

        # 掉站类型 / 全库 CSD/PSD 对照、全库根因归属分布均为全库汇总统计，
        # 与单张 TT 的派单依据无关，不再计算（掉站类型仍可在工单字段中看到）。

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
            "alarm": alarm_block,
            "skill_prompt": skill_prompt,
            "alarm_id": num_tail(str(d.get("alarm_id") or "").strip()),
            "aid": aid_val,
            "tt_prompt_fields": {k: d.get(k) for k in
                                 ("vip_site", "site_type", "alarm_code",
                                  "down_site_count")},
            "timing": {
                "alarm_occur_time": fmt_dt(d.get("alarm_occur_time")),
                "created_time": fmt_dt(d.get("created_time")),
                "lag_hours": round(lag.total_seconds() / 3600, 2) if lag else None,
                "lag_text": lag_txt,
                "delayed_over_1h": bool(lag and lag.total_seconds() > 3600),
            },
            "root_cause": clean(d.get("root_cause"), 80),
            "sub_root_cause": clean(d.get("sub_root_cause"), 80),
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

    al = d_rep.get("alarm") or {}
    if al.get("found"):
        print(f"\n【告警库记录（{al['source']}，按 alarm_id 匹配）】")
        for it in al["items"]:
            print(f"  {it['key']:34s} {it['value']}")
    else:
        print("\n【告警库记录】realtime_alarm / history_alarm 中未找到该 alarm_id"
              "（可能未被同步或已滚出），技能入参已用 eflow_tt 字段兜底")
    print(f"\n【技能「TT单分析」入参】")
    print(d_rep["skill_prompt"])

    t = d_rep["timing"]
    print(f"\n【时间差（告警 → 派单）】")
    print(f"  {'alarm_occur_time':34s} {t['alarm_occur_time']}")
    print(f"  {'created_time':34s} {t['created_time']}")
    print(f"  {'间隔':34s} {t['lag_text']}")
    if t["delayed_over_1h"]:
        print("  ⚠️ 延迟派单超过 1 小时：派单时刻的站点状态可能已与告警时刻不同，")
        print("     但派单判定以【告警发生时刻】为准，延迟不改变判定结果。")

    print("\n" + "=" * W)
    print("结论要点（人工判断，工具只提供数据）")
    print("=" * W)
    print(f"  1. 根因：{d_rep['root_cause']} / {d_rep['sub_root_cause']}"
          f" —— 派单归属主要看这个")
    print(f"  2. 派往：{d_rep['assigned_group']}")
    print(f"  3. 延迟：{t['lag_text']}")
    print()
    print("  详细规则见：00_操作篇_Operations/02_告警与故障_Alarm/")
    print("              掉站工单派单归属判定规则.md")
    print("=" * W)
    return 0


if __name__ == "__main__":
    sys.exit(main())
