# -*- coding: utf-8 -*-
"""临时脚本：在 DataSync.tsx 中添加新的任务分组"""

import sys
sys.stdout.reconfigure(encoding='utf-8')
import re

with open(r'D:\01_RPA\Task\my_app\frontend\src\pages\DataSync.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if already added
if 'ipran_m6k_chart_email' in content:
    print("Tasks already exist in frontend, skipping.")
    sys.exit(0)

# Find and replace the section
old_pattern = r"(task_ids: \['packet_loss_sync'\],\n    },\n    \{\n      label_zh: 'Liberia 宕站报告邮件',\n      label_en: 'Liberia Site-Down Email',\n      task_ids: \['liberia_email_1h', 'liberia_email_8h'\],\n    \})"

new_text = """task_ids: ['packet_loss_sync'],
    },
    {
      label_zh: 'CNN UME 数据同步',
      label_en: 'CNN UME Data Sync',
      task_ids: ['cnn_kpi_sync'],
    },
    {
      label_zh: '图表邮件',
      label_en: 'Chart Email Reports',
      task_ids: [
        'ipran_m6k_chart_email',
        'ccn_free_rating_chart_email',
      ],
    },
    {
      label_zh: 'Liberia 宕站报告邮件',
      label_en: 'Liberia Site-Down Email',
      task_ids: ['liberia_email_1h', 'liberia_email_8h'],
    }"""

match = re.search(old_pattern, content)
if match:
    print(f"Found pattern at position: {match.start()}")
    content = content[:match.start()] + new_text + content[match.end():]
    
    with open(r'D:\01_RPA\Task\my_app\frontend\src\pages\DataSync.tsx', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Success: Added chart email tasks to frontend")
else:
    print("Pattern not found!")
    # Debug - show context around packet_loss_sync
    idx = content.find("task_ids: ['packet_loss_sync']")
    if idx >= 0:
        print(f"Context around match:")
        print(repr(content[idx-100:idx+300]))
