# -*- coding: utf-8 -*-
import sys

PATH = r"D:\01_RPA\Task\eflow_Q&A\tools\inspect_tt.py"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

start_marker = "        d = {k: row[k] for k in cols}\n"
end_marker = "    finally:\n        conn.close()\n"

i = content.index(start_marker)
j = content.index(end_marker, i)

replacement = (
    "        return _build_report(conn, tt_no, d)\n"
    "    finally:\n"
    "        conn.close()\n"
    "\n"
    "\n"
    "def _build_report(conn, tt_no, d):\n"
    "    \"\"\"由工单行字段 dict 构建分析报告（本地库查询与实时 eFlow 回退共用，只读不写库）。\n"
    "\n"
    "    d：eflow_tt 列名 → 值的字典。\n"
    "    \"\"\"\n"
    "    # 按 alarm_id 查实时告警（48h 滚存）→ 历史告警，拿主信息 + 拼技能入参\n"
    "    alarm_row, alarm_src = find_alarm_row(conn, d.get(\"alarm_id\"))\n"
    "    alarm_dict = dict(alarm_row) if alarm_row else None\n"
    "    # 告警行的 AID 列（RAN UME 侧告警 ID）：注入「告警」字段段 + 报告级 aid 字段\n"
    "    aid_val = num_tail(str((alarm_dict or {}).get(\"aid\") or \"\").strip())\n"
    "    if aid_val in (\"--\", \"—\", \"None\"):\n"
    "        aid_val = \"\"\n"
    "    if aid_val:\n"
    "        d[\"aid\"] = aid_val\n"
    "    alarm_block = build_alarm_block(alarm_dict, alarm_src)\n"
    "    skill_prompt = build_skill_prompt(d, alarm_dict)\n"
    "\n"
    "    # 时间差\n"
    "    occur = parse_dt(d.get(\"alarm_occur_time\"))\n"
    "    created = parse_dt(d.get(\"created_time\"))\n"
    "    lag = None\n"
    "    lag_txt = \"—（时间字段缺失或格式无法解析）\"\n"
    "    if occur and created:\n"
    "        lag = created - occur\n"
    "        lag_s = lag.total_seconds()\n"
    "        lag_txt = f\"{int(lag_s // 3600)} 小时 {int((lag_s % 3600) // 60)} 分 \" \\\n"
    "                  f\"{int(lag_s % 60)} 秒  ({lag_s / 3600:.2f} h)\"\n"
    "\n"
    "    fields = []\n"
    "    for section, keys in FIELDS:\n"
    "        items = [(k, d.get(k)) for k in keys if k in d]\n"
    "        items = [(k, v) for k, v in items\n"
    "                 if v is not None and str(v).strip() != \"\"]\n"
    "        if items:\n"
    "            fields.append({\n"
    "                \"section\": section,\n"
    "                \"items\": [{\"key\": k, \"value\": clean(v)} for k, v in items],\n"
    "            })\n"
    "\n"
    "    return {\n"
    "        \"found\": True,\n"
    "        \"tt_no\": tt_no,\n"
    "        \"fields\": fields,\n"
    "        \"alarm\": alarm_block,\n"
    "        \"skill_prompt\": skill_prompt,\n"
    "        \"alarm_id\": num_tail(str(d.get(\"alarm_id\") or \"\").strip()),\n"
    "        \"aid\": aid_val,\n"
    "        \"tt_prompt_fields\": {k: d.get(k) for k in\n"
    "                             (\"vip_site\", \"site_type\", \"alarm_code\",\n"
    "                              \"down_site_count\")},\n"
    "        \"timing\": {\n"
    "            \"alarm_occur_time\": fmt_dt(d.get(\"alarm_occur_time\")),\n"
    "            \"created_time\": fmt_dt(d.get(\"created_time\")),\n"
    "            \"lag_hours\": round(lag.total_seconds() / 3600, 2) if lag else None,\n"
    "            \"lag_text\": lag_txt,\n"
    "            \"delayed_over_1h\": bool(lag and lag.total_seconds() > 3600),\n"
    "        },\n"
    "        \"root_cause\": clean(d.get(\"root_cause\"), 80),\n"
    "        \"sub_root_cause\": clean(d.get(\"sub_root_cause\"), 80),\n"
    "        \"assigned_group\": clean(d.get(\"last_processer_group\"), 60),\n"
    "        \"site_name\": clean(d.get(\"site_name\"), 60),\n"
    "    }\n"
    "\n"
    "\n"
    "def analyze_tt_remote(tt_no, row_dict, db_path=DEFAULT_DB):\n"
    "    \"\"\"用实时 eFlow 拉到的工单行字段构建报告（纯内存，不落库）。\n"
    "\n"
    "    当本地 eflow_tt 未命中时，由上游调用 fetch_tt_live 拿到 row_dict（eflow_tt 列名\n"
    "    归一化后的 dict），再据此产出与 analyze_tt 同构的报告。\n"
    "    \"\"\"\n"
    "    conn = sqlite3.connect(db_path)\n"
    "    conn.row_factory = sqlite3.Row\n"
    "    try:\n"
    "        return _build_report(conn, tt_no, dict(row_dict or {}))\n"
    "    finally:\n"
    "        conn.close()\n"
)

new = content[: i + len(start_marker)] + replacement + content[j + len(end_marker):]

with open(PATH, "w", encoding="utf-8") as f:
    f.write(new)

print("done; old_len=%d new_len=%d" % (len(content), len(new)))