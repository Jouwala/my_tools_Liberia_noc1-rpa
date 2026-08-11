任务：完成 my_app 迁移 Phase 4 —— Alembic 补全（env.py 去硬编码 + 基线迁移 + 空库验证）。

【前置阅读，必须先读再动手】
1. D:\01_RPA\Task\my_app\my_app_migration_plan.md —— 迁移总计划（重点读 Phase 4 定义与 R0-R8 回退方案，禁止违反 R2 切流门禁）。
2. alembic\env.py —— 当前实现：sqlalchemy.url 硬编码 sqlite 绝对路径（第 28-33 行），target_metadata=Base.metadata。
3. alembic.ini —— script_location=alembic，sqlalchemy.url 为占位符。
4. alembic\versions\0001_baseline.py 与 0002_task_queue.py —— 已有迁移（revision/down_revision 链）。
5. backend\database.py —— DB_MODE 熔断开关（MY_APP_DB_MODE 环境变量，默认 sqlite）、DATABASE_URL 从 backend\.env 读取（load_dotenv）。
6. backend\models\__init__.py —— 聚合模块，import 即注册全部主库模型到 Base.metadata。

【运行环境】
- Python：D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe（已装 alembic 1.19.0 / sqlalchemy 2.0.51 / psycopg2 2.9.12）。
- 工作目录：D:\01_RPA\Task\my_app（alembic 命令都在此目录执行）。

【改造要求】
1. env.py 双模 URL 分派：读环境变量 MY_APP_DB_MODE（默认 sqlite）——sqlite 模式保持现有绝对路径逻辑不变（含 MY_APP_DB_OVERRIDE 支持）；pg 模式读 backend\.env 的 DATABASE_URL 作为 sqlalchemy.url，且 render_as_batch 仅在 sqlite 方言时开启（pg 下关闭）。
2. 表覆盖盘点：用 .venv-test 的 python 枚举 db/app.db 实际表清单（sqlite_master），与 Base.metadata.tables 对比，列出「metadata 未登记」的表清单写进输出报告（不要为动态表如 eflow_*、_temp_* 强行建模型）。
3. 生成迁移：若 metadata 与现有迁移有差异，用 `alembic revision --autogenerate -m "phase4_coverage"` 生成增量迁移；若无差异则跳过并在报告中说明。禁止手改 0001/0002 已有迁移文件。
4. 空库验证（不碰生产文件）：把 db/app.db 复制为 D:\01_RPA\Task\my_app\TMP\phase4_test.db，用 MY_APP_DB_OVERRIDE 指向该副本跑 `alembic upgrade head`，再跑 `alembic downgrade base` 与再次 `upgrade head`，全部成功才算验证通过。

【硬性红线】
- 禁止对真实 db/app.db、db 目录下任何 .sqlite3 文件执行 upgrade/downgrade。
- 禁止连接 PostgreSQL 执行任何写操作（本任务不切流；DATABASE_URL 仅用于 env.py 代码路径，不实际连库跑迁移）。
- 只允许修改：alembic\env.py、alembic.ini（如需）、alembic\versions\ 下新增迁移文件、TMP\ 下测试产物。其余文件一律不动、不做 git 操作。
- sqlite 模式下 alembic 行为必须与改造前完全一致（零回归）。

【完成后输出】
- 对改过的 .py 跑 py_compile（用 .venv-test 的 python）。
- 输出末尾给出：① env.py 改动摘要（行号区间）；② 表覆盖盘点结果（metadata 未登记表清单）；③ 空库验证 upgrade/downgrade/upgrade 三段结果；④ 总耗时秒数。