任务：my_app 迁移 Phase 5 Wave1 —— ① 写公共 sqlite→PG 搬运框架；② 用它搬运 A 车道三域（battery / ms_sla / ran_kpi_daily）。

【前置阅读，必须先读再动手】
1. D:\01_RPA\Task\my_app\my_app_migration_plan.md —— Phase 5 定义（5.1 建 schema / 5.2 搬运+类型修正）、风险 3（反向工程类型不可信）、R0（备份）、R4（脚本幂等可重跑）。
2. backend\database.py —— DB_MODE 熔断、_resolve_pg_schema 路径→schema 映射、PG_DATABASE_URL 从 backend\.env 读取。
3. backend\.env —— DATABASE_URL（pg 连接串，密码不要打印到任何输出）。

【运行环境】Python：D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe（有 psycopg2 2.9.12 / pandas / sqlalchemy）。工作目录 D:\01_RPA\Task\my_app。

【PG 现状（2026-08-07 实测）】9 个 schema 已建全空：app/battery/eflow/fw/ipran_ume/lte_pl/ms_sla/public/ran_ume。

【交付 1：搬运框架 backend\migrations\transfer_lib.py（新建目录与文件）】
- 输入：sqlite 文件路径（只读 URI mode=ro 打开）、目标 schema、表清单（缺省=全部非 sqlite_ 表）、可选的类型修正回调。
- 行为：① 每表先 DROP TABLE IF EXISTS 再建表重建（保证幂等可重跑，R4）；② DDL 从 sqlite PRAGMA table_info 反射列名，类型映射规则：INTEGER→BIGINT、REAL→DOUBLE PRECISION、TEXT/BLOB/无类型→TEXT；③ 类型修正钩子：对指定 (schema, table, column) 强制 TEXT（用于 *_time 混 '2d0h0m' 时长串这类脏类型）；④ 数据用 executemany 分批（默认 5000/批）写入，用 pandas 向量化读取分块（chunksize）避免大表爆内存；⑤ 每表写完输出 源行数 vs 目标行数；⑥ 显示总运行耗时（秒）。
- 同目录 requirements.txt 与 transfer_lib.md（依赖：pandas/psycopg2/sqlalchemy，其余标准库）。

【交付 2：A 车道搬运脚本 backend\migrations\transfer_lane_a.py（调用 transfer_lib）】
按以下实测清单搬运（2026-08-07 盘点行数，搬完必须行数一致）：
1. data\battery\battery_kpi.sqlite3 → schema battery：battery_latest(1532) / battery_meta(8) / battery_reading(34853) / battery_trend(47)。
2. data\ms_sla\lbr_ms_sla_kpi.sqlite3 → schema ms_sla：12 张 Hourly_KPI_RPA_SITE_MS_SLA_* 表（合计约 10.9 万行）。注意 *_time 与 sla_time 列含 '2d0h0m' 时长串 → 一律 TEXT。
3. backend\services\ran_kpi_daily.sqlite3 → schema ran_ume：2G/3G/FDD/TDD_OLIB_Network_KPIs（768/480/576/480 行）。注意：data\ran_ume\ran_kpi_daily.sqlite3 是旧副本（行数不同），不搬，脚本里注释说明。
- 表名以数字开头（2G_/3G_）在 PG 必须双引号包裹，DDL/DML 全用 "" 引号标识符。

【搬运前备份（R0）】把三个源 sqlite 文件拷贝到 backup\phase5_wave1_<时间戳>\ 目录。

【硬性红线】
- 只写 PG 的 battery / ms_sla / ran_ume 三个 schema；禁止动 app / eflow / fw / lte_pl schema，禁止动 credential_store。
- 禁止修改 MY_APP_DB_MODE（保持 sqlite 默认），禁止改 backend\.env。
- 源 sqlite 文件只读，绝不写。
- 允许修改的文件白名单：backend\migrations\ 下新建的一切、backup\ 下备份产物。其余文件一律不动，不做 git 操作。

【完成后输出】① 每表 源行数→目标行数 对照表（必须全部一致）；② 类型修正实际应用清单；③ py_compile 结果；④ 总耗时秒数。