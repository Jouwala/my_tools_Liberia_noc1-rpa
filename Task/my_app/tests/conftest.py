# -*- coding: utf-8 -*-
"""pytest 收集配置。

tests/ 目录里混着两类文件：
  1) 真正的 pytest 单元测试（本地临时 DB，零副作用）—— 会被收集
  2) 历史遗留的"手动运行脚本"（模块级就会真连 UME / eFlow / 浏览器 E2E）
     —— 一旦被 pytest 导入就会打生产接口，必须排除

所以这里显式忽略第 2 类，保证 `pytest tests/` 始终安全可跑。
需要跑那些脚本时按文件头注释单独 `python tests/xxx.py` 执行。

⚠️ 2026-09-27 补充：以下文件同样是"手动脚本"形态，但它们**模块级就调用
`sys.exit()`**，一旦被收集会直接把 pytest 打成 INTERNALERROR（不是普通
失败，整个 session 崩掉、连其他文件的用例都跑不了）。这是"跑不起来"而不是
"跑不过"，所以必须排除；要跑它们请单独 `python tests/xxx.py`。
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
    # ---- 模块级 sys.exit() 的手动脚本：被收集会让 pytest INTERNALERROR ----
    "test_olib_soc_kpi_store.py",   # :842 sys.exit(1 if FAIL else 0)
    "test_olib_soc_report.py",      # :719 sys.exit(main(...))
    "test_task_config_live_effect.py",  # :443 sys.exit(main())
    "test_task_health_alert.py",    # :142 sys.exit(...)
    "test_task_health_detect.py",   # :151 sys.exit(...)
    "test_vmax_multi_data.py",      # :473 sys.exit(main())
    "test_worker_group_coverage.py",  # :212 sys.exit(...)
]
