任务：my_app 迁移 Phase 6.5 —— 修复 PG search_path 同名表歧义 + ms_sla_report.py 超长列名截断回退。

【背景】my_app 双模架构（MY_APP_DB_MODE=sqlite|pg）。Phase 5 数据已搬运到 PG 9 schema，其中 ran_ume（写库，backend/services 写入）与 ran_ume_ro（读库，原 data\ran_ume）存在同名表（如 3G_OLIB_Network_KPIs）。

【阻断项 1：search_path 歧义】backend\database.py 的 _PsycopgRaw._SEARCH_PATH（约 305 行）当前为 'app,eflow,lte_pl,battery,ms_sla,fw,ipran_ume,ran_ume,ran_ume_ro,public'——所有 PG 原始连接（_pg_raw_connection）无论来源路径都统一用这条全局 search_path，导致不带 schema 限定的同名表查询命中第一个匹配 schema。读 data\ran_ume 的服务（ran_ume_service.py 等）本意读 ran_ume_ro，却命中写库 ran_ume。另外 _pg_raw_connection(db_path, logical_name, timeout) 收到 db_path/logical_name 后完全没用（_resolve_pg_schema 是死代码）。

【修复要求 1】改 _pg_raw_connection：用 _resolve_pg_schema(db_path)（logical_name 显式传入时优先）解析出目标 schema，把它放在 search_path 最前，其余沿用现有全局列表（去重）。即每连接 search_path = '<resolved_schema>, app,eflow,lte_pl,battery,ms_sla,fw,ipran_ume,ran_ume,ran_ume_ro,public'（去重）。这样：读 data\ran_ume → ran_ume_ro 优先命中读库；写 ran_ume → ran_ume 优先命中写库；跨 schema 限定名查询仍可用；sqlite 模式完全不受影响（此函数只在 pg 模式被调）。_PsycopgRaw 需支持传入 search_path 字符串（构造函数加参数，默认值为现有全局列表，保持其它调用方兼容）。

【阻断项 2：ms_sla_report.py 长列名静默空值】该文件 NETWORK_KPI_DAILY_MAP / NETWORK_KPI_MONTHLY_MAP / PERSITE_KPI_DAILY_MAP / PERSITE_KPI_MONTHLY_MAP 硬编码了超长 KPI 列名（901597/901604 等），get_db_value()（约 336 行）用 table_columns() 防护后对不存在的列返回 None——切流到 PG 后这些列已被截断（UTF-8 前 63 字节），防护会让报表静默出空值。修复：get_db_value() 在列名不在 existing_cols 时，先尝试截断回退（列名 UTF-8 >63 字节则取前 63 字节安全解码后匹配），命中则用截断名查询；sqlite 模式下列名原样存在，回退逻辑天然不触发，行为不变。截断算法与 backend\migrations\reconcile.py 的 PG_MAX_IDENT 实现保持一致（可参考其代码，注意不要 import reconcile，本函数自包含实现 10 行以内）。

【前置阅读，必须先读再动手】
1. backend\database.py 全文（376 行）：_pg_raw_connection / _PsycopgRaw / _resolve_pg_schema / get_raw_connection。
2. backend\services\ms_sla_report.py 的四个 KPI MAP 常量与 get_db_value()。
3. backend\services\ran_ume_service.py：确认它读 data\ran_ume 时调 get_raw_connection 传的路径（用于验证修复后 search_path 首项正确）。
4. backend\migrations\long_column_audit.md（9 个超长列名清单）。
5. backend\migrations\reconcile.py 的截断回退实现。

【验证要求（全部要做，结果写进报告）】
1. py_compile backend\database.py 与 backend\services\ms_sla_report.py。
2. PG 模式验证（环境变量 MY_APP_DB_MODE=pg 注入，禁止改 backend\.env）：写临时脚本 backend\migrations\tmp_verify_searchpath.py：a) get_raw_connection('data\ran_ume\ran_ume_ro.sqlite3' 之类实际存在的读库路径——先读 ran_ume_service.py 确认真实路径) 后执行 SELECT current_schemas(false)，断言 ran_ume_ro 在 ran_ume 之前；b) get_raw_connection 对写库路径断言 ran_ume 在前；c) 对 app.db 默认路径断言 app 在前；d) 不带 schema 限定 SELECT 同名表（如 3G_OLIB_Network_KPIs）验证读库连接命中的是 ran_ume_ro（可用 SELECT to_regclass 或 information_schema 佐证）。跑完打印耗时秒数并删除临时脚本。只读验证，禁止任何写操作。
3. get_db_value 截断回退单测（临时脚本，sqlite 行为不变验证 + PG 截断名映射验证，对照 information_schema 真实列名），跑完删除。
4. 不要启动 uvicorn。

【硬性红线】
- 白名单文件：backend\database.py、backend\services\ms_sla_report.py、backend\migrations\searchpath_fix_report.md（交付报告）、tmp_verify_* 临时脚本（用完删除）。禁止动 backend\dialect_helpers.py、backend\services\ms_sla_sync.py、backend\services\ran_ume_network_kpi.py（另一个 agent 在改，文件分区互斥）。
- 禁止修改 backend\.env；禁止任何 git 操作（不 commit / 不 push / 不 reset / 不 checkout）；PG 验证只做只读查询。
- sqlite 模式行为必须逐字节兼容。

【交付】backend\migrations\searchpath_fix_report.md：改动清单、py_compile 结果、current_schemas 验证证据（每个路径一条）、截断回退验证证据、总耗时秒数。