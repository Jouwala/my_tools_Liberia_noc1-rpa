# reconcile.py — my_app 迁移 R5 一致性对账脚本（只读）

对应迁移计划 `my_app_migration_plan.md` Phase R / R5：自动比对 **sqlite 源库 vs PostgreSQL 目标 schema**，输出差异报告，作为 R2 切流 gating（误差 <0.1%）的证据之一。

## 红线（脚本内强制）
- **只读**：PG 会话 `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`；sqlite 以 `file:...?mode=ro` URI 打开。脚本不含任何 INSERT/UPDATE/DELETE/DROP。
- **密码不落盘不打印**：`DATABASE_URL` 取自 `backend/.env` 或环境变量，控制台/报告仅输出脱敏串（`postgresql://myapp:***@127.0.0.1:5432/myapp`）。
- 全库空 / schema 缺失 / 表缺失时结论为 **NOT_READY**，不抛异常。

## 用法

```powershell
# 缺省跑全部 8 个内置域（battery / ms_sla / ran_ume / ran_ume_ro / lte_pl / fw / eflow / app）
D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe backend\migrations\reconcile.py

# 只跑 battery 域
python backend\migrations\reconcile.py --domain battery

# 自定义对账域（JSON：{域名: {sqlite, pg_schema, tables}}，tables=null 表示自动发现）
python backend\migrations\reconcile.py --config my_domains.json --out TMP
```

内置域（`DEFAULT_DOMAINS`）：

| 域 | sqlite 源 | PG schema | 说明 |
|---|---|---|---|
| battery | `data/battery/battery_kpi.sqlite3` | `battery` | 电池 KPI |
| ms_sla | `data/ms_sla/lbr_ms_sla_kpi.sqlite3` | `ms_sla` | MS SLA 小时 KPI |
| ran_ume | `backend/services/ran_kpi_daily.sqlite3` | `ran_ume` | RAN UME 写库 |
| ran_ume_ro | `data/ran_ume/ran_kpi_daily.sqlite3` | `ran_ume_ro` | RAN UME 读库（读写两库分离） |
| lte_pl | `data/packet_lost/lte_pl.sqlite3` | `lte_pl` | 丢包率（75 万行大表） |
| fw | `backend/services/fw_kpi/fw_db.sqlite` | `fw` | 防火墙 KPI |
| eflow | `data/eflow/eflow.sqlite3` | `eflow` | eFlow 工单 |
| app | `db/app.db` | `app` | 主库（37 表） |

## 每表比对项
1. **表存在性**：两侧 `sqlite_master` / `information_schema.tables`。
2. **rowcount**：`COUNT(*)` 双侧对比。
3. **全量多重集行 hash**（顺序无关，替代早期的抽样比对）：
   - 两侧逐行 md5（归一化：NULL→空串、bool 先行、数值统一 `repr(float(v))`），
     按 Counter 多重集比较（重复行按次数计），行序 / rowid 空洞不影响结果；
   - PG 侧按 sqlite 列序显式 SELECT，规避两库列序不一致造成的假差异；
   - sqlite 长列名超 PG 63 字节标识符上限被截断时，按截断规则自动回退映射
     （报告中逐表列出 `truncated_columns`）；
   - `alembic_version` 预期分叉（sqlite 停在 0002、PG 已升级 0004），已排除不参与判定。
4. **数值列聚合**：两侧数值列取交集（sqlite 按样本可转数值性判定、PG 按 `information_schema` 类型），对每列 `SUM/MIN/MAX` 比对；全 NULL 列自动一致跳过（相对误差阈值 1e-6）。

## 结论规则
- **差异率 = (行数差 + 全量行 hash 不对称差) / max(两侧行数)**
- `PASS`：差异率 < 0.1%（含零差异）
- `FAIL`：差异率 ≥ 0.1%，或源有数据而 PG 缺表/缺列，或比对异常
- `NOT_READY`：PG schema 空 / 不存在、sqlite 源缺失或空、两侧空表 —— 报告正常产出，不算错误
- 域/总体结论取各表最坏值（FAIL > PASS > NOT_READY；全 NOT_READY 时总体为 NOT_READY）

## 性能
- sqlite 侧原生游标流读；PG 侧服务端游标 `arraysize=10000` 批读，会话 READ ONLY。
- 72 表全量逐行比对（含 75 万行 lte_pl）实测 ≈32 秒。

## 输出
- 控制台摘要表（域/表/行数/行差/hash差/聚合异/结论）。
- JSON 差异报告：默认 `TMP/reconcile_report_<时间戳>.json`（文件被占用时按 `_序号` 规则另存），含逐表明细、聚合不一致项、脱敏连接串与总耗时（秒）。
- 退出码：PASS/NOT_READY = 0，FAIL = 1，便于接入 CI/gating。

## 依赖
见同目录 `reconcile_requirements.txt`（pandas / psycopg2；当前 `.venv-test` 已具备：pandas 3.0.3、psycopg2 2.9.12）。
> 命名为 `reconcile_requirements.txt` 以避免与 Wave1 搬运脚本在同目录的 `requirements.txt` 冲突。

## 空跑验证记录（2026-08-07）
对 `data/battery/battery_kpi.sqlite3` vs PG `battery` schema 空跑：当前 PG 全部 schema 为空（Wave1 未搬运），脚本按预期输出 **NOT_READY** 报告（4 表逐一列出源行数、0 行已迁）且正常退出（exit 0），总耗时 0.05 秒。app 预留域（38 表）同样正确报 NOT_READY。报告见 `TMP/reconcile_report_20260807_211222.json`。

## Phase 5 实跑验证记录（2026-08-07）
8 域 72 表全量对账 **总体 PASS**：除 3 张两侧均空表（credentials / transfer_details / uploaded_files，NOT_READY）外全部“完全一致”，行差 0、全量行 hash 差 0、聚合异 0，总耗时 32 秒。报告见 `TMP/reconcile_report_20260807_215813.json`。
过程中修复的三个对账假阳性根因（均为脚本自身缺陷，非数据问题）：
1. 抽样错位：sqlite rowid 从 1 起 vs PG 位置从 0 起，且 rowid 存在空洞 → 改用顺序无关的全量多重集 hash；
2. 列序不一致：个别表（如 task_schedule_config）两库列序不同 → PG 侧按 sqlite 列序显式 SELECT；
3. PG 63 字节标识符截断：ms_sla / ran_ume 共 13 个超长 KPI 列名在 PG 被静默截断（数据完整，仅列名变短）→ 对账按截断规则自动映射，并在报告中逐表登记。注意：**切流后应用代码若用原长列名查 PG 会找不到列，R2 门禁前需核对这些列的访问代码**。
