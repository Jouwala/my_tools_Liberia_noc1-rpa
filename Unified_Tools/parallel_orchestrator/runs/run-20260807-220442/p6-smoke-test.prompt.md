任务：my_app 迁移 Phase 6 —— PG 模式 API 冒烟测试（临时进程，不持久化任何配置）。

【背景】Phase 5 已完成：PG 9 个 schema（app/battery/ms_sla/ran_ume/ran_ume_ro/lte_pl/fw/eflow）数据已搬运并对账 PASS。现在要在 MY_APP_DB_MODE=pg 下启动后端做只读冒烟，验证 R2 切流可行性。backend\database.py 的 DB_MODE 从 OS 环境变量读取（load_dotenv 不覆盖已存在的环境变量），因此只需在启动进程注入环境变量即可，绝不改任何配置文件。

【前置阅读，必须先读再动手】
1. backend\database.py —— DB_MODE 熔断开关、_resolve_pg_schema 路径→schema 映射、R8 鉴权库硬排除。
2. backend\main.py —— 路由清单（tables/upload/analysis/gis/tt_wo_dashboard/alarm_dashboard/packet_loss_dashboard/battery_dashboard/credentials/tasks/sp_dashboard/system）。
3. backend\routers\system.py —— /api/health、/api/db/info 端点。

【运行环境】Python：D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe。工作目录 D:\01_RPA\Task\my_app。

【交付：backend\migrations\smoke_test_pg.py + smoke_test_pg.md + smoke_requirements.txt】冒烟脚本要求：
1. 以子进程启动 uvicorn backend.main:app，端口 7099（避免与任何在用端口冲突），注入环境变量 MY_APP_DB_MODE=pg（DATABASE_URL 由 backend\.env 提供，不要动 .env）。启动前先探测 7099 空闲；轮询 /api/health 直到就绪（上限 60 秒）。
2. 注意：main.py 导入 task_runner，若有 APScheduler 在启动时拉起定时任务，冒烟窗口尽量短（全部请求完成立即杀进程），并在报告中记录观察到的后台任务行为。
3. 冒烟端点（GET 优先，覆盖 8 个数据域；每个请求记录 状态码/耗时/响应摘要前 200 字符）：
   a. /api/health、/api/db/info（必须确认返回中 DB 模式为 pg）；
   b. tt_wo_dashboard、alarm_dashboard、packet_loss_dashboard、battery_dashboard、sp_dashboard、gis、tasks、tables 各路由下自选 2-3 个代表性只读 GET 端点（先读 router 源码确定真实路径与参数，不许瞎猜 URL）；
   c. 明确覆盖读取 eflow_tt（app schema）、packet_loss_data（lte_pl schema）、battery_reading（battery schema）的端点各至少一个。
4. 全部请求完成后立即终止 uvicorn 子进程，确认进程已退出、7099 端口释放。
5. 输出冒烟结论：总端点数 / 2xx 数 / 非 2xx 明细（含响应体片段，便于定位是 SQL 方言问题还是业务问题）；打印总耗时秒数。

【硬性红线】
- 禁止修改 backend\.env；禁止把 MY_APP_DB_MODE=pg 写进任何持久配置或代码默认值。
- 禁止写源 sqlite（冒烟期间应用对 PG 的正常写入允许，那是目标库）。
- 白名单：backend\migrations\smoke_test_pg.py / smoke_test_pg.md / smoke_requirements.txt、TMP\ 下的冒烟日志。不做 git 操作。

【完成后输出】① 冒烟结果表（端点/状态码/耗时）；② /api/db/info 返回的 DB 模式证据；③ py_compile 结果；④ 总耗时秒数。