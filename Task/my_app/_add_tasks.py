# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r'D:\01_RPA\Task\my_app\backend\task_registry.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "def register_all_tasks"
register_line = -1
for i, line in enumerate(lines):
    if 'def register_all_tasks' in line:
        register_line = i
        break

if register_line == -1:
    print("ERROR: Could not find register_all_tasks")
    sys.exit(1)

print(f"Found register_all_tasks at line {register_line}")

# Check if new tasks already exist
has_ipran = any('ipran_m6k_chart_email' in l for l in lines)
has_ccn = any('ccn_free_rating_chart_email' in l for l in lines)

if has_ipran and has_ccn:
    print("Tasks already exist, skipping.")
    sys.exit(0)

# Find the last dict entry (the packet_loss_sync one) or the closing bracket
insert_idx = -1
for i in range(len(lines)-1, -1, -1):
    if ']' in lines[i] and i < register_line:
        insert_idx = i
        break

if insert_idx == -1:
    print("ERROR: Could not find insertion point")
    sys.exit(1)

print(f"Will insert before line {insert_idx}: {lines[insert_idx].strip()}")

new_entries = [
    '\n',
    '    # 23. IP RAN M6K-FW Chart Email - 3组 ME+SmartGroup 折线图，每天 6:45\n',
    '    dict(task_id="ipran_m6k_chart_email", name="IP RAN M6K-FW 图表邮件", name_en="IP RAN M6K-FW Chart Email",\n',
    '         loader=("backend.services.ipran_chart_service", "run_ipran_m6k_chart_email"),\n',
    '         description="从 ipran_ume_kpi.sqlite3 查询 HQ_M6K_FW_bnctp_15mins，按 ME+SmartGroup 生成3张利用率折线图并发送",\n',
    '         description_en="Query HQ_M6K_FW_bnctp_15mins by ME+SmartGroup, generate 3 utilization line charts and email",\n',
    '         default_cron="45 6 * * *", category="email"),\n',
    '\n',
    '    # 24. CNN Free Rating Group Chart Email - 4个 MO 柱状图，每天 7:45\n',
    '    dict(task_id="ccn_free_rating_chart_email", name="CNN Free Rating 图表邮件", name_en="CNN Free Rating Chart Email",\n',
    '         loader=("backend.services.ccn_free_rating_chart_service", "run_ccn_free_rating_chart_email"),\n',
    '         description="从 db_ps_cs_cn.sqlite3 查询 FREE_RATING_GROUP_TEMPLATE_OSS_update_UME，按 MO 生成4张柱状图并发送",\n',
    '         description_en="Query FREE_RATING by MO, generate 4 bar charts and email",\n',
    '         default_cron="45 7 * * *", category="email"),\n',
]

new_lines = lines[:insert_idx] + new_entries + lines[insert_idx:]

with open(r'D:\01_RPA\Task\my_app\backend\task_registry.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Success: Added 2 new tasks to task_registry.py")
