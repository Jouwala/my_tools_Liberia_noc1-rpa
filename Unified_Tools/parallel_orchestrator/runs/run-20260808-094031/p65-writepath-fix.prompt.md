任务：my_app 迁移 Phase 6.5 —— 修复 PG 写路径阻断项（upsert 标识符未加引号 + 超长列名 63 字节截断适配）。

【背景】my_app 双模架构（MY_APP_DB_MODE=sqlite|pg，熔断开关在 backend\database.py）。Phase 5 已把 sqlite 数据全量搬运到 PG 9 schema 并对账 PASS。Phase 6 冒烟发现写路径 2 处阻断：
1. backend\dialect_helpers.py 的 upsert()：col_sql/conflict_sql/set_sql 拼列名未加引号，实测含空格列名（如 'Begin Time'）报 near "Time": syntax error。ms_sla 全部 12 表、ran_ume 全部 4 表、eflow_tt 的 90 列都含空格列名，切流后所有 upsert 必断。
2. backend\services\ms_sla_sync.py 与 backend\services\ran_ume_network_kpi.py 的动态建表/补列/写入链路：PG 标识符上限 63 字节（NAMEDATALEN-1），超长列名在 PG 中已被静默截断（截断规则=UTF-8 编码取前 63 字节再安全解码）。这两处服务用原始长列名做 CREATE TABLE / ALTER ADD COLUMN / INSERT，切流后：列存在性判断失配（table_columns 返回截断名）→ 重复 ADD COLUMN → 报错；且 ran_ume_network_kpi.py 的 except 只捕获 sqlite3.OperationalError，PG 下 psycopg2 异常会直接炸。

【修复要求】
A. dialect_helpers.py upsert()：双模统一用双引号包裹所有标识符（sqlite 与 PG 都支持双引号标识符）——col_sql、conflict_sql、set_sql（含 EXCLUDED."c"）全部加引号，引号内嵌的 " 按双双引号转义。其余函数（list_table_names/table_columns/safe_pragma/write_df）不动。
B. dialect_helpers.py 新增公共助手 pg_trunc_ident(name)：UTF-8 字节长度 <=63 原样返回；>63 则取前 63 字节 .decode('utf-8', errors='ignore')（若末位截出残缺字符则继续回退到完整码点边界），供下面两个服务与对账脚本复用。sqlite 模式必须原样返回（sqlite 无长度限制）。
C. ms_sla_sync.py write_to_db()：PG 分支（isinstance(conn, sqlite3.Connection) 为 False 时）所有从 headers 派生的列名（CREATE TABLE 列定义、exist_cols 比较、ALTER ADD COLUMN、主键引用、INSERT 列清单）统一经 pg_trunc_ident 映射后再拼 SQL；sqlite 分支行为逐字节不变。ALTER 失败要捕获广义异常并 warning 跳过（对齐 ran_ume_network_kpi 的降级风格），不能让整个同步任务因单列失败崩溃。
D. ran_ume_network_kpi.py write_to_db()：同 C 的 PG 截断映射，覆盖 CREATE TABLE / ALTER ADD COLUMN / quoted_headers / upsert records 的列名派生点；两处 except sqlite3.OperationalError 扩为 except Exception（保留 [SILENT-EXCEPT] warning 日志风格）。sqlite 分支行为不变。

【前置阅读，必须先读再动手】
1. backend\dialect_helpers.py 全文（99 行）。
2. backend\services\ms_sla_sync.py 的 write_to_db()（约 253-350 行）与它后续的 upsert 调用点。
3. backend\services\ran_ume_network_kpi.py 的 write_to_db()（约 780-900 行）。
4. backend\migrations\reconcile.py 的 PG_MAX_IDENT 截断回退实现（约 40-60 行附近，已验证的截断算法，保持同款规则）。
5. backend\migrations\long_column_audit.md（超长列名背景与 9 个受影响列名清单）。

【验证要求（全部要做，结果写进报告）】
1. py_compile 全部改动文件。
2. sqlite 模式回归：写一个临时验证脚本（放 backend\migrations\tmp_verify_writepath_sqlite.py），用 dialect_helpers.upsert 向 db\app.db 之外的临时 sqlite 文件写入含空格列名 + 含双引号列名的数据，验证 INSERT OR REPLACE 正确；跑完打印耗时秒数，验证通过后删除该临时脚本。
3. PG 模式验证：环境变量 MY_APP_DB_MODE=pg + backend\.env 的 DATABASE_URL，写临时脚本（backend\migrations\tmp_verify_writepath_pg.py）：a) upsert 向 ms_sla schema 某表写 1 行含空格列名数据（先查 information_schema 选一张真实表，BEGIN 事务内写入后 ROLLBACK，不留脏数据）；b) 用 ms_sla_sync.write_to_db 或 ran_ume_network_kpi.write_to_db 的截断映射函数验证 9 个超长列名全部映射为 PG 中真实存在的截断列名（对照 information_schema.columns，schema=ms_sla / ran_ume）；c) 全程不动任何持久数据（写操作必须 ROLLBACK 或写临时 schema/临时表并 DROP）。跑完打印耗时秒数后删除该临时脚本。注意：禁止改 backend\.env，只允许用环境变量注入；PG 连接参数从 backend\.env 读取即可。
4. 不要启动 uvicorn，本任务只验函数级行为。

【硬性红线】
- 白名单文件：backend\dialect_helpers.py、backend\services\ms_sla_sync.py、backend\services\ran_ume_network_kpi.py、backend\migrations\writepath_fix_report.md（交付报告）、两个 tmp_verify_* 临时脚本（用完删除）。禁止动 backend\database.py、backend\services\ms_sla_report.py（另一个 agent 在改，文件分区互斥）。
- 禁止修改 backend\.env 与任何持久配置；sqlite 模式行为必须逐字节兼容（改动后 sqlite 分支生成的 SQL 与原来等价）。
- 禁止任何 git 操作（不 commit / 不 push / 不 reset / 不 checkout）。
- 禁止删除或覆盖数据库中的既有数据。

【交付】backend\migrations\writepath_fix_report.md：改动清单（文件/函数/改动点）、py_compile 结果、sqlite 与 PG 验证证据（含 SQL 片段与输出摘要）、9 个超长列名→截断名映射对照表、总耗时秒数。