# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r'D:\01_RPA\Task\my_app\backend\task_registry.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the malformed section and fix it
# The issue is that new tasks were inserted inside the register_all_tasks function
# We need to restore the original structure with new tasks added before the closing bracket

# Look for the original packet_loss_sync entry and add after it
old_text = '''    # 22. Packet Loss ??+?r?O?-? + ??`S?"Y^??^?_??c??T"6:30%%
    dict(task_id="packet_loss_sync", name="Packet Loss ??+?r?", name_en="Packet Loss Sync",
         loader=("backend.services.packet_loss_service", "run_packet_loss_sync"),
         description="RAN UME ??+?r?(SDR/IPRAN IPPD)?7???????,???? lte_pl.sqlite3 ??? Packet Loss Status Report",
         description_en="Sync last-7-day hourly Packet Loss Rate (SDR/IPRAN IPPD) from RAN UME, merge into lte_pl.sqlite3 and generate Packet Loss Status Report",
         default_cron="30 6 * * *", category="packet_loss"),
]


def register_all_tasks'''

new_text = '''    # 22. Packet Loss ??+?r?O?-? + ??`S?"Y^??^?_??c??T"6:30%%
    dict(task_id="packet_loss_sync", name="Packet Loss ??+?r?", name_en="Packet Loss Sync",
         loader=("backend.services.packet_loss_service", "run_packet_loss_sync"),
         description="RAN UME ??+?r?(SDR/IPRAN IPPD)?7???????,???? lte_pl.sqlite3 ??? Packet Loss Status Report",
         description_en="Sync last-7-day hourly Packet Loss Rate (SDR/IPRAN IPPD) from RAN UME, merge into lte_pl.sqlite3 and generate Packet Loss Status Report",
         default_cron="30 6 * * *", category="packet_loss"),

    # 23. IP RAN M6K-FW Chart Email - 3组 ME+SmartGroup 折线图，每天 6:45
    dict(task_id="ipran_m6k_chart_email", name="IP RAN M6K-FW 图表邮件", name_en="IP RAN M6K-FW Chart Email",
         loader=("backend.services.ipran_chart_service", "run_ipran_m6k_chart_email"),
         description="从 ipran_ume_kpi.sqlite3 查询 HQ_M6K_FW_bnctp_15mins，按 ME+SmartGroup 生成3张利用率折线图并发送",
         description_en="Query HQ_M6K_FW_bnctp_15mins by ME+SmartGroup, generate 3 utilization line charts and email",
         default_cron="45 6 * * *", category="email"),

    # 24. CNN Free Rating Group Chart Email - 4个 MO 柱状图，每天 7:45
    dict(task_id="ccn_free_rating_chart_email", name="CNN Free Rating 图表邮件", name_en="CNN Free Rating Chart Email",
         loader=("backend.services.ccn_free_rating_chart_service", "run_ccn_free_rating_chart_email"),
         description="从 db_ps_cs_cn.sqlite3 查询 FREE_RATING_GROUP_TEMPLATE_OSS_update_UME，按 MO 生成4张柱状图并发送",
         description_en="Query FREE_RATING by MO, generate 4 bar charts and email",
         default_cron="45 7 * * *", category="email"),
]


def register_all_tasks'''

if old_text in content:
    content = content.replace(old_text, new_text)
    print("Fixed: replaced old text")
else:
    # Try to find and fix differently
    lines = content.split('\n')
    # Find where the corruption starts
    corrupt_start = -1
    for i, line in enumerate(lines):
        if 'category="category"' in line:
            corrupt_start = i
            break
    
    if corrupt_start > 0:
        # Rebuild the file from scratch with correct structure
        print(f"Found corruption at line {corrupt_start}")
        # Keep everything up to but not including the corrupt line
        fixed_lines = lines[:corrupt_start]
        # Add the closing bracket for TASK_SPECS and the function definition
        fixed_lines.append('],')
        fixed_lines.append('')
        fixed_lines.append('')
        fixed_lines.append('def register_all_tasks(task_runner) -> int:')
        fixed_lines.append('    """将 TASK_SPECS 中的全部任务注册到 task_runner，返回注册数量"""')
        
        # Add remaining lines after corruption
        for i in range(corrupt_start + 1, len(lines)):
            line = lines[i]
            # Skip the corrupted dict entries that are now outside TASK_SPECS
            if 'dict(task_id="ipran_m6k_chart_email"' in line or 'dict(task_id="ccn_free_rating_chart_email"' in line:
                continue
            if 'loader=("backend.services.ipran_chart_service"' in line or 'loader=("backend.services.ccn_free_rating_chart_service"' in line:
                continue
            if 'description="从 ipran_ume_kpi' in line or 'description="从 db_ps_cs_cn' in line:
                continue
            if 'description_en="Query HQ_M6K_FW' in line or 'description_en="Query FREE_RATING' in line:
                continue
            if 'default_cron="45 6' in line or 'default_cron="45 7' in line:
                continue
            if 'category="email"' in line and ('ipran_m6k' in ''.join(lines[max(0,i-3):i+3]) or 'ccn_free_rating' in ''.join(lines[max(0,i-3):i+3])):
                continue
            if line.strip() == '#' and i+1 < len(lines) and ('23.' in lines[i+1] or '24.' in lines[i+1]):
                continue
            fixed_lines.append(line)
        
        content = '\n'.join(fixed_lines)
        print("Fixed: rebuilt file structure")
    
    else:
        print("Could not find corruption pattern, trying manual fix...")
        # Manual reconstruction
        # Find where TASK_SPECS list ends and fix
        import re
        # Match the pattern around the corruption
        pattern = r'(category="category"\s*\n)(.*?)(\],)'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            print(f"Found pattern at: {match.group(0)[:100]}")

# Write back
with open(r'D:\01_RPA\Task\my_app\backend\task_registry.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("File written")
