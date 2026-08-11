任务：复核 my_app Phase 3 验证门产出的 warn 清单（只读复核，默认不改代码）。

【背景】backend 目录已完成 sqlite/pg 双模改写并通过验证门（py_compile 29/29，硬失败 0），但残留扫描有若干 warn，需要逐条判定：A=合法（已在 DB_MODE/isinstance 守卫分支内或纯注释）；B=需修复（pg 模式会实际走到且会崩）。

【前置阅读】backend\dialect_helpers.py（双模工具）、backend\database.py（DB_MODE / _PsycopgRaw：pg 模式裸连接自动把 ? 转 %s）、backend\routers\gis.py（参考范本）。

【复核点清单（文件:行号，均在 backend\ 下）】
1. main.py:109 与 scripts/init_db.py:250 —— AUTOINCREMENT DDL：确认已被 DB_MODE 守卫（sqlite 才执行 / pg 有 IDENTITY 等价分支）。
2. import_topology.py:20、services/get_sp_table.py:268、services/task_runner.py:92、services/task_stats.py:30 —— AUTOINCREMENT：同上判定。
3. services/eflow_data_mapper.py:495 与 services/ran_ume_main_kpi.py:904,953 —— df.to_sql(conn)：确认处于 sqlite 守卫分支或带 TODO-PHASE3-SCHEMA 标记（独立库 pg engine_override 属 Phase 5 范畴，判 A 并注明）。
4. services/ipran_ume_kpi_service.py:752-753 与 services/ms_sla_sync.py:292-293 与 services/sync_from_eflow_api.py:329-330 —— rowid 去重 SQL：确认已有 pg 分支（ctid）且 sqlite 分支保持原样。
5. services/task_runner.py:145 —— cur.lastrowid：确认 pg 分支已用 RETURNING id。
6. services/battary_kpi_fetch/battery_kpi_service.py:344 —— INSERT OR IGNORE：确认 pg 分支为 ON CONFLICT DO NOTHING。
7. 其余 INSERT OR REPLACE 出现的注释/文档字符串（eflow_data_mapper.py:896、ipran_ume_kpi_service.py:11,707,768-769、ran_ume_network_kpi.py:779,859、ms_sla_sync.py:311-312、sync_from_eflow_api.py:304,345）—— 判 A（注释）即可，快速过。

【硬性规则】
- 只读复核，不改任何代码；仅当发现 B 类（pg 模式真实会崩）才允许最小化修复该点，且修复后 py_compile 验证。
- 不做 git 操作、不新建文件。

【完成后输出】
- 表格：复核点 | 结论(A/B) | 证据（守卫分支行号或代码片段）。
- 若有 B 类修复，列出改动文件与行号区间。
- 末尾给出总耗时秒数。