任务：编写 my_app 迁移 R5 一致性对账脚本（只写脚本并做空跑验证，不做任何数据搬运）。

【前置阅读】D:\01_RPA\Task\my_app\my_app_migration_plan.md 的 R1/R5 条目（对账要求：表清单/行数/关键列聚合/抽样行 hash，差异报告）；backend\database.py（PG 连接方式）；backend\.env（DATABASE_URL，密码不要打印）。

【运行环境】Python：D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe。工作目录 D:\01_RPA\Task\my_app。

【交付：backend\migrations\reconcile.py + 同目录 requirements.txt 与 reconcile.md】
功能：
1. 配置化：入参 JSON 或内置 dict 描述对账域，每条 = {sqlite 路径, pg schema, 表清单}。初始内置：battery(ms_sla 等按 Phase 5 实际搬运域，以参数传入为准)、以及 app.db→app 的预留项（当前 PG app schema 为空，脚本须能正确报告 0 行差异而不是崩溃）。
2. 逐表比对：① 表存在性；② rowcount（sqlite COUNT(*) vs pg COUNT(*)）；③ 抽样行 hash：每表按固定种子取最多 200 行（sqlite 用 rowid 取模抽样、pg 用 ctid 或 ORDER BY 前 N），对每行所有列 str() 拼接后 md5，比对 hash 集合差异数；④ 数值列聚合抽查（SUM/MIN/MAX，可空跳过）。
3. 输出：控制台摘要表 + JSON 差异报告（默认写 D:\01_RPA\Task\my_app\TMP\reconcile_report_<时间戳>.json）；差异率 = 差异行数/总行数，给 PASS(<0.1%) / FAIL 结论。
4. 全库空/表缺失时结论为 NOT_READY 而非报错。
5. 显示总运行耗时（秒）。读取尽量向量化（pandas read_sql 分块或 executemany 批读）。

【空跑验证】对 data\battery\battery_kpi.sqlite3 vs schema battery 跑一次（当前 PG battery 可能为空或已被 Wave1 搬运，两种情况脚本都须正常出报告）。

【硬性红线】只读对账：禁止 INSERT/UPDATE/DELETE/DROP 任何 PG 表；禁止修改任何现有代码文件；白名单 = backend\migrations\reconcile.py / reconcile.md / requirements（若与 Wave1 同名 requirements 冲突则命名 reconcile_requirements.txt）/ TMP\ 报告产物。不做 git 操作。

【完成后输出】① 空跑报告摘要（NOT_READY 或差异数据）；② py_compile 结果；③ 总耗时秒数。