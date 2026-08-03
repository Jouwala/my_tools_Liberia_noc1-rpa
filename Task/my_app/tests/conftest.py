# -*- coding: utf-8 -*-
"""pytest 收集配置。

tests/ 目录里混着两类文件：
  1) 真正的 pytest 单元测试（本地临时 DB，零副作用）—— 会被收集
  2) 历史遗留的"手动运行脚本"（模块级就会真连 UME / eFlow / 浏览器 E2E）
     —— 一旦被 pytest 导入就会打生产接口，必须排除

所以这里显式忽略第 2 类，保证 `pytest tests/` 始终安全可跑。
需要跑那些脚本时按文件头注释单独 `python tests/xxx.py` 执行。
"""
collect_ignore = [
    "test_ran_ume_network_kpi.py",  # 真实登录 UME 并导出 xlsx
    "test_all_apis.py",             # 打本地/远端 API 全量巡检
    "test_frontend_deep.py",        # 浏览器深度巡检
    "test_frontend_e2e.py",         # 浏览器 E2E
    "run_all_tests.py",
    "run_backend_tests.py",
    "run_deep_all.py",
    "run_deep_tests.py",
    "report_utils.py",
]
