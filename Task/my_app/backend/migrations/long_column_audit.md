# Phase 6 —— 超长列名（PG 63 字节截断）访问路径核查报告

日期：2026-08-07 ｜ 性质：只读调研（未修改任何代码/配置/数据库，未做 git 操作）
范围：Phase 5 对账登记的 9 个超 PG 63 字节标识符上限的 KPI 列名（数据已完整搬运，PG 侧列名=UTF-8 前 63 字节截断形式）。

## 1. PG 侧截断事实复核（information_schema 只读实测）

| PG schema | 表 | 截断列（前 63 字节）数 |
|---|---|---|
| ms_sla | Hourly_KPI_RPA_SITE_MS_SLA_GSM1day/1month_NW/SITE（4 表） | 各 1（`U31_ZTE_Traffic of Downlink Data TBF (GByte)_901415_2_gv4.bsc-M`） |
| ms_sla | Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day/1month_NW/SITE（4 表） | 各 8（901596/901597/901598/901604/901605/901621/900005/Inter-RAT PS GPRS；另 `Cell Inter-RAT CS Outgoing...(WCDMA->GSM)(%)` 恰好 63 字节、**完整保留**） |
| ran_ume | 3G_OLIB_Network_KPIs | 4（901597/901598/901604/901605） |
| ran_ume_ro | 3G_OLIB_Network_KPIs | 4（同上） |

与 reconcile 报告（TMP/reconcile_report_20260807_215813.json 的 truncated_columns）一致。

## 2. 全仓引用检索结果

对 9 个列名的特征串（`901596_2/901597_2/901598_2/901604_2/901605_2/901621_2/901415_2/900005_2/1552876397284`、`Inter-RAT PS Outgoing`、`Channel Elements Congestion`、`UROP.RNC-MO`、`gv4.bsc-MO`、`Traffic of Downlink Data TBF`、`HSDPA Average Throughput per User` 等）做全仓检索（py/json/前端/配置，含 frontend 目录单独复查）：

**唯一命中：`backend/services/ms_sla_report.py`**，且仅涉及 9 列中的 2 个：

| 列 | 引用位置（ms_sla_report.py） |
|---|---|
| `U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO`（74 字节） | 行 111（NETWORK_KPI_DAILY_MAP）、121（NETWORK_KPI_MONTHLY_MAP）、133（PERSITE_KPI_DAILY_MAP）、147（PERSITE_KPI_MONTHLY_MAP） |
| `U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO`（65 字节） | 行 112、122、134、148（同上 4 个 MAP） |

其余 7 列在全仓（含前端）**零硬编码引用**。
frontend 目录对全部 9 列特征串及 `OLIB/Hourly_KPI/MS_SLA` 均无匹配 → 不存在"前端列配置清单"类引用点。

注：ms_sla_report.py 中还硬编码了 `901593_2`（56B）、`901620_2`（55B）、`Cell Inter-RAT CS Outgoing...(WCDMA->GSM)(%)`（恰好 63B）三个长名，均未超限、PG 完整保留，不在本审计 9 列内。

## 3. 访问模式判定

### 3.1 ms_sla_report.py（读路径，模式 b 的软化版）
- 调用链：`run_contract_kpis_report` → `get_raw_connection(data/ms_sla/lbr_ms_sla_kpi.sqlite3)` → `get_db_value` / `get_persite_ratio` 用硬编码长列名拼 `SELECT "长列名" FROM "表"`。
- 关键防护：两个函数先 `table_columns()` 枚举实际列，**长列名不在列集合中即直接返回 None，不执行 SQL**（ms_sla_report.py:343、394），且外层有 try/except 静默。
- 后果判定：DB_MODE=pg 下**不会报"列不存在"、任务不失败**，但 Contract KPIs 报表中 `3G_CSSR_HSDPA / 3G_DCR_HSDPA`（日/月 × 网络级/站点达标率，共 8 个取值点）**静默为空**，且报表照常导出上传 FTP/发邮件 → 属"静默缺数"，非崩溃。

### 3.2 ran_ume 读路径（模式 a，无影响）
- `ran_ume_service.run_availability_report`（读 data/ran_ume/ran_kpi_daily.sqlite3）：`SELECT *` + `df.columns` 动态找列，3G 使用列 `Cell Validity Rate(%)` 为短名、未截断（ran_ume_service.py:159、904、917）。截断对其无影响。

### 3.3 写路径（附带发现，超出 9 列但同属切流阻断项）
- `ms_sla_sync.write_to_db`（ms_sla_sync.py:254-329）与 `ran_ume_network_kpi.write_to_db`（ran_ume_network_kpi.py:777-865）在 PG 模式下：
  1. 超长列走 `ALTER TABLE ... ADD COLUMN "原长名"`（带引号）——PG 对**带引号**标识符超 63 字节是直接报错（不截断），且 except 只捕获 `sqlite3.OperationalError`，PG 异常会上抛 → 同步任务失败；
  2. `dialect_helpers.upsert`（dialect_helpers.py:61-87）列名**未加引号**拼 SQL，`Begin Time` 等含空格列名在 sqlite 即语法错误（内存库实测：`near "Time": syntax error`），PG 下同样必断 → 影响全部列而非仅 9 列。

### 3.4 邮件报表 kpi_email_report.py
只读 data/ms_sla 下的 xlsx/html 成品文件，不访问数据库列名 → 无影响（但其上游即 3.1 的报表，缺数会传导到邮件）。

## 4. DB_MODE=pg 下 schema 走向核查（backend/database.py）

- `get_raw_connection` 在 pg 模式返回 `_PsycopgRaw` 包装连接，`search_path` 为**固定全量列表**：`app,eflow,lte_pl,battery,ms_sla,fw,ipran_ume,ran_ume,public`（database.py:268）。
- `_resolve_pg_schema`（database.py:178）**定义了但全仓无任何调用点**（死代码）；`_pg_raw_connection` 接收 `logical_name` 参数但**完全忽略**（database.py:313）。
- 结论：
  - **ms_sla 读**：`Hourly_KPI_RPA_SITE_MS_SLA_*` 表名在 PG 各 schema 中唯一，search_path 含 ms_sla → 正确命中 ms_sla schema。✔（列名问题见 3.1）
  - **ran_ume 读**：search_path **不含 `ran_ume_ro`**；data/ran_ume 读库的 4 张 OLIB 表与 ran_ume schema 同名，`SELECT * FROM "3G_OLIB_Network_KPIs"` 实际命中 **ran_ume（写库 schema）而非 ran_ume_ro**。Phase 5 对账两 schema 行数/内容一致，当前不产生数据差异，但与"读写两库分离"设计不符；若切流后写库持续更新而 ro 不再同步，读路径将长期读写库数据。✘

## 5. 逐列结论表

| # | 列名（原长名） | 引用点 | 访问模式 | 切流风险 |
|---|---|---|---|---|
| 1 | Cell Inter-RAT PS Outgoing Handover Success Rate(WCDMA->GPRS)(%) | 无（代码引用的是 CS/GSM 变体，63B 完整保留） | — | **无** |
| 2 | U31_3G & 3G+ Channel Elements Congestion Rate_901621_2_UROP.RNC-MO | 无 | — | **无** |
| 3 | U31_3G Call Setup Success Rate - R99 Data services_901596_2_UROP.RNC-MO | 无（代码引用 901593 CS 变体，56B） | — | **无** |
| 4 | U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO | ms_sla_report.py:111/121/133/147 | b：硬编码长列名拼 SQL，有 table_columns 防护 → 静默返回 None | **中**（报表 4 取值点静默空） |
| 5 | U31_3G+ Call Setup Success Rate – HSUPA Data services_901598_2_UROP.RNC-MO | 无 | — | **无** |
| 6 | U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO | ms_sla_report.py:112/122/134/148 | b：同上 | **中**（报表 4 取值点静默空） |
| 7 | U31_3G+ Drop Call Rate - HSUPA Data services_901605_2_UROP.RNC-MO | 无 | — | **无** |
| 8 | U31_HSDPA Average Throughput per User_1552876397284-0-88_900005_2_UROP.RNC-MO | 无 | — | **无** |
| 9 | U31_ZTE_Traffic of Downlink Data TBF (GByte)_901415_2_gv4.bsc-MO | 无（仅出现在 GSM 4 表，无代码按名读取） | — | **无** |
| — | （通用）写路径对全部 9 列 | ms_sla_sync.py:276、ran_ume_network_kpi.py:830/841、dialect_helpers.py:61-87 | 带引号 ALTER 超长名（PG 报错）+ upsert 列名未加引号（语法错误） | **高**（pg 模式写入全断，不限 9 列） |
| — | （通用）ran_ume 读 schema 映射 | database.py:268（search_path 缺 ran_ume_ro）、178/313（死代码/忽略 logical_name） | 读库实际命中 ran_ume 写库 schema | **低**（当前数据一致，不符设计） |

## 6. 总体风险判定

**不可直接切流，需先修 3 处：**

1. **ms_sla_report.py（读，中风险）**：901597/901604 两个硬编码长列名。建议方案：在 `get_db_value`/`get_persite_ratio` 的列存在性检查失败时，增加"UTF-8 前 63 字节截断名"回退匹配（与 reconcile.py 的 truncated_columns 规则同一算法），或维护一张"长名→PG 实际名"映射表统一翻译；也可在 PG 侧用 `ALTER COLUMN RENAME` 把 13 个截断列改为业务短名并双向同步映射（一劳永逸，推荐与 R2 门禁一起做）。
2. **写路径（高风险，阻断项）**：`dialect_helpers.upsert` 列名加双引号（sqlite 实测未加引号即语法错误，此缺陷与 9 列无关但切流必触发）；ms_sla_sync / ran_ume_network_kpi 的 `ALTER ADD COLUMN` 在 PG 模式下对超 63 字节列名改用截断名（或跳过已存在的截断列），避免带引号长标识符报错。
3. **database.py schema 映射（低风险，设计纠偏）**：`_SEARCH_PATH` 增加 `ran_ume_ro`，并理顺顺序/按需设置（`_resolve_pg_schema` 已实现路径→schema 映射但未被调用，`logical_name` 被忽略）——建议让 `_pg_raw_connection` 真正按 `_resolve_pg_schema(db_path)` 或 `logical_name` 设置 search_path，使读库命中 ran_ume_ro。注意：ran_ume 与 ran_ume_ro 表同名，search_path 顺序决定命中方，需按连接用途区分。

其余 7 个超长列无任何按名访问路径，数据已在 PG 完整可用，切流无风险。

## 7. 证据索引

- 截断登记：TMP/reconcile_report_20260807_215813.json（domains ms_sla / ran_ume / ran_ume_ro 的 truncated_columns）+ 本次 information_schema 只读实测（50 个 63 字节列，含恰好 63B 未截断的 CS Outgoing 列）。
- 硬编码引用：backend/services/ms_sla_report.py:106-151（4 个 KPI MAP）。
- 防护逻辑：backend/services/ms_sla_report.py:336-394（get_db_value/get_persite_ratio 列存在性检查）。
- 动态列读取：backend/services/ran_ume_service.py:899-918（SELECT * + Cell Validity Rate 短名）。
- schema 映射：backend/database.py:178-197（死代码）、268（search_path）、313-324（忽略 logical_name）。
- 写路径缺陷：backend/dialect_helpers.py:61-87（upsert 未加引号，sqlite 内存库实测 syntax error）、ms_sla_sync.py:254-329、ran_ume_network_kpi.py:777-865。

## 8. 复核勘误（协调方独立复核，2026-08-07）

1. **本报告第 4/5/6 节"search_path 缺 ran_ume_ro"有误**：实测 database.py:299 `_SEARCH_PATH` 已含 `ran_ume_ro`（完整列表：app,eflow,lte_pl,battery,ms_sla,fw,ipran_ume,ran_ume,ran_ume_ro,public）。但**顺序问题仍成立**：ran_ume 排在 ran_ume_ro 之前，同名表（如 3G_OLIB_Network_KPIs）会先命中写库 schema，与读写分离设计不符，风险等级维持"低"。
2. **upsert 缺陷实测确认**：sqlite 内存库实测 `upsert` 对含空格列名（如 Begin Time）报 `near "Time": syntax error`；且已核实 ms_sla 全部 12 表、ran_ume 全部 4 表、eflow_tt（90/161 列）列名均含空格 → 写路径阻断结论成立。
3. **遗留疑问**：该缺陷在 sqlite 模式下同样存在，但生产 ms_sla/ran_ume 库数据持续在更新（当日有新数据）——说明生产实际写入路径可能未走本仓 write_to_db 的 upsert 分支（或走了降级分支/独立 RPA 副本），切流前修复时需一并查清真实写入链路。
