任务：my_app 迁移 Phase 5 Wave2 —— app 主库归口：PG app schema 建表（Alembic 实跑）+ app.db 数据搬运。

【前置阅读，必须先读再动手】
1. backend\migrations\transfer_lib.py 与 transfer_lib.md —— Wave1 公共搬运框架，直接复用。
2. alembic\env.py —— pg 模式读 backend\.env 的 DATABASE_URL；alembic\versions\ 三个迁移（0001/0002/5415704359dc_phase4_coverage，幂等建表）。
3. D:\01_RPA\Task\my_app\my_app_migration_plan.md —— 风险 5（app.db 是 eflow_tt 的唯一活源）、Phase 2 第 61 条（PG 建表由 Alembic 接管，禁止 create_all）。

【运行环境】Python：D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe（alembic 1.19.0）。工作目录 D:\01_RPA\Task\my_app。

【步骤】
1. 备份（R0）：拷贝 db\app.db 到 backup\phase5_wave2_<时间戳>\。
2. PG 建表：设环境变量 MY_APP_DB_MODE=pg（仅本命令进程内），运行 .venv-test 的 python -m alembic upgrade head，在 PG app schema 建出受管表；确认 alembic_version 落在 head。
3. 数据搬运：写 backend\migrations\transfer_app.py 调用 transfer_lib，把 db\app.db（只读）搬到 PG app schema。表清单以 2026-08-07 实测 39 表为准，但排除 _metadata（sqlite 元数据性质）与 alembic_version（PG 已由步骤 2 管理）；其余 37 表全搬（含 eflow_tt 28455 行、inventory_details 32013 行、task_execution_log 1852 行等）。注意：transfer_lib 默认 DROP+重建会摧毁 Alembic 建好的表结构——搬运 app 域时必须用「只 INSERT 不重建」模式（若 transfer_lib 无此模式，为它增加 insert-only 参数开关，这是允许的唯一框架改动，保持向后兼容并更新 transfer_lib.md）。
4. 行数核对：37 表逐一 源行数 vs 目标行数 对照输出。

【硬性红线】
- 只写 PG 的 app schema；禁止动其它 schema。
- 禁止修改 backend\.env 文件本身、禁止把 MY_APP_DB_MODE=pg 写进任何持久配置（运行态默认必须保持 sqlite）。
- 源 db\app.db 只读（生产应用可能还在用，用 mode=ro URI 打开）。
- 不做 git 操作。

【完成后输出】① alembic upgrade head 结果与 app schema 表数；② 37 表行数对照（必须全部一致）；③ transfer_lib 若改动给出 diff 摘要；④ py_compile 结果；⑤ 总耗时秒数。