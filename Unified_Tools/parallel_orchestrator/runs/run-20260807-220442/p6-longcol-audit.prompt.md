任务：my_app 迁移 Phase 6 —— 超长列名（PG 63 字节截断）访问路径核查，只读调研，输出报告。

【背景】Phase 5 对账发现以下 9 个 KPI 列名超过 PG 63 字节标识符上限，在 PG 中被静默截断（数据已完整搬运，仅列名变短，截断形式=UTF-8 前 63 字节）。切流到 PG 后，任何用原长列名拼 SQL 的代码都会报"列不存在"。需要你核查应用代码访问这些列的全部路径，判定切流风险。

【9 个受影响列名】
1. Cell Inter-RAT PS Outgoing Handover Success Rate(WCDMA->GPRS)(%)
2. U31_3G & 3G+ Channel Elements Congestion Rate_901621_2_UROP.RNC-MO
3. U31_3G Call Setup Success Rate - R99 Data services_901596_2_UROP.RNC-MO
4. U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO
5. U31_3G+ Call Setup Success Rate – HSUPA Data services_901598_2_UROP.RNC-MO
6. U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO
7. U31_3G+ Drop Call Rate - HSUPA Data services_901605_2_UROP.RNC-MO
8. U31_HSDPA Average Throughput per User_1552876397284-0-88_900005_2_UROP.RNC-MO
9. U31_ZTE_Traffic of Downlink Data TBF (GByte)_901415_2_gv4.bsc-MO

受影响表：ms_sla schema 的 Hourly_KPI_RPA_SITE_MS_SLA_GSM/UMTS 系列 8 表；ran_ume 与 ran_ume_ro schema 的 3G_OLIB_Network_KPIs。

【前置阅读】
1. backend\migrations\reconcile.md —— "Phase 5 实跑验证记录"一节有截断背景。
2. backend\services\ran_ume_service.py（读库 data\ran_ume）、backend\services\ran_ume_network_kpi.py（写库）、backend\services 下 ms_sla 相关服务、backend\routers 下相关看板路由。

【调研内容】
1. 全仓 grep 这 9 个列名的任何片段（如 901597_2、901415_2、Inter-RAT PS Outgoing 等特征串），找出所有硬编码引用点（py/json/前端/配置）。
2. 判定每处访问模式：a) SELECT * / df.columns 动态列（截断无影响或影响可控）；b) 硬编码长列名拼 SQL（切流即断）；c) 前端列配置清单（展示缺列但不报错）。
3. 特别确认：读取 ran_ume/ms_sla 数据的 API 在 DB_MODE=pg 下会走哪个 schema（参考 backend\database.py 的 _resolve_pg_schema 路径→schema 映射），映射是否正确指向 ran_ume_ro / ms_sla。
4. 给出逐列结论表（列名/引用点/访问模式/切流风险等级 高|中|低|无）与整改建议（如需代码改动，列出文件与建议方案，但本次不改）。

【硬性红线】只读调研：禁止修改任何代码/配置/数据库，禁止 git 操作。白名单仅一个输出文件：backend\migrations\long_column_audit.md。

【完成后输出】① 逐列结论表；② 总体风险判定（可直接切流 / 需先修 N 处）；③ 总耗时秒数。