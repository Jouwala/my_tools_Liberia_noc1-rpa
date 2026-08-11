任务：my_app 迁移 Phase 5 Wave2 —— 用 Wave1 已交付的搬运框架搬 B 车道三域（lte_pl / fw / eflow）。

【前置阅读，必须先读再动手】
1. backend\migrations\transfer_lib.py 与 transfer_lib.md —— Wave1 交付的公共搬运框架（幂等 DROP+重建、分批 executemany、行数核对），直接复用，禁止重复造轮子。
2. backend\migrations\transfer_lane_a.py —— Wave1 的调用范例（备份、类型修正钩子、行数对照的写法）。
3. D:\01_RPA\Task\my_app\my_app_migration_plan.md —— 风险 2（eflow_tt 无主键）、风险 5（eflow.sqlite3 只读快照迁）。

【运行环境】Python：D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe。工作目录 D:\01_RPA\Task\my_app。

【交付：backend\migrations\transfer_lane_b.py】按以下实测清单搬运（2026-08-07 盘点行数）：
1. data\packet_lost\lte_pl.sqlite3（194MB）→ schema lte_pl：packet_loss_data(750371) / pl_meta(5) / site_pl_summary(670)。75 万行大表必须分块读（chunksize≤2万）+ executemany 批写。
2. backend\services\fw_kpi\fw_db.sqlite（8MB）→ schema fw：device_whole_throughput(42580)。
3. data\eflow\eflow.sqlite3（425MB，只读快照）→ schema eflow：eflow_cr(205) / eflow_pm(1632) / eflow_tt(28455) / eflow_wo(10000) / history_alarm(165) / person(133) / realtime_alarm(56) / site(808)。注意 eflow_tt 无主键、无唯一约束，纯搬运不建唯一索引。另注意：schema ran_ume 已被 Wave1 占用（写库 backend\services\ran_kpi_daily.sqlite3），你绝不碰 ran_ume schema；读库 data\ran_ume\ran_kpi_daily.sqlite3（4 表 768/480/576/480 行）搬到新 schema ran_ume_ro（先 CREATE SCHEMA IF NOT EXISTS ran_ume_ro；写/读两库分离是代码现状，后续 engine_override 按 schema 区分）。

【搬运前备份（R0）】三个源文件拷贝到 backup\phase5_wave2_<时间戳>\（425MB 大文件允许用硬链接或注明体积跳过拷贝，但必须记录源文件 SHA256 前后一致证明未改动）。

【硬性红线】
- 只写 PG 的 lte_pl / fw / eflow / ran_ume_ro 四个 schema；禁止动 app / battery / ms_sla / ran_ume schema。
- 禁止修改 MY_APP_DB_MODE（保持 sqlite）、禁止改 backend\.env、禁止改 transfer_lib.py。
- 源 sqlite 只读。白名单：backend\migrations\transfer_lane_b.py、backup\ 产物。不做 git 操作。

【完成后输出】① 每表 源行数→目标行数 对照（必须全部一致）；② py_compile 结果；③ 总耗时秒数。