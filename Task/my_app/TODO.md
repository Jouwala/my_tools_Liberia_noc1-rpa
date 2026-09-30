# 03 TODO.md —— 当前任务、优先级和开发进度

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\TODO.md`
> **本文只留在办项。** 历史规划与复盘看 `PROJECT_DOCS.md`（历史档案）。

## 一、进度快照

my_app 处于**稳定运行**阶段（后端 7038 + 多组 worker + 双看门狗）。近期工作重心是稳定性、数据正确性与前端视觉统一。

| 模块 | 状态 |
| --- | --- |
| 数据采集与入库（44+ 定时任务） | 运行中 |
| 任务队列 + worker 分组 + 看门狗 | 完成（含僵尸回收、自动重试） |
| SQLite / PostgreSQL 双模 | 完成（`MY_APP_DB_MODE`） |
| 23+ 功能页 | 完成 |
| 深浅双主题（`theme.ts` 双套令牌） | 完成 |
| 中英文国际化 | 完成 |
| 站内使用帮助（与 MD 同源生成） | 完成 |
| 邮件 / WhatsApp 分发 | 完成 |
| FineBI → my_app 迁移 | **进行中** |
| SQLite → PostgreSQL 迁移 | **规划定稿，未执行** |
| 数据访问层统一（裸连接治理） | **未启动（前置调研中）** |

## 二、P0 —— 影响正确性或可用性

- [x] **FineBI 仓库看板镜像库停更 —— 已根治（2026-09-30）。**
      原判断「WAL-over-SMB 架构限制、本仓库无法单方面解决」是**错误的**（该结论建立在
      「`inventory.db` 唯一写入方是 my_app」这一与实测不符的推断上）。2026-09-30 查清：
      同一 SMB 目录新建库、甚至切成 WAL，只要**没有远端持有者**，本机读写都正常；
      真正症结是远端有活进程长期持有该库 `-shm` 的**字节范围锁**，而 SMB 无法代理该语义，
      于是本机每次 `open` 都永久阻塞（`timeout`/`busy_timeout` 对此无效）。
      **修法**：改为「本地构建 + 整文件推送」（`backend/services/sp_mirror_push.py`）——
      本机建新库再 `copyfile` 整文件覆盖，**整文件覆盖不需要字节锁**（实测库被占用时也能覆盖成功）。
      **实测结果**：两轮生产运行 `mirror_success=true`、`mirror_errors=[]`、5 张表齐全，
      镜像耗时 **507.9s（失败） → 2.6s（成功）**，整轮 525.75s → 21s。
      生产库 113MB（含 14.7MB 未 checkpoint 的 `-wal`）→ 47.7MB 单文件，
      `integrity_check=ok`，此前远端**整个缺失**的 `ocrule_details` 表已补齐。
      顺带修掉同类事故：镜像挂死会把 worker 永久卡死（09:10 卡到 10:22 人工重启），
      已加镜像阶段 15min 硬超时，并把 worker 回收文案从误导性的「进程中断」改为区分
      「进程已失效」与「任务挂死」。
      详见 `docs/manual/04-task-system.md` 的 `sp_data_sync` 小节。
      > **遗留（低优先）**：远端目录仍留有陈旧的 `inventory.db-wal`(14.7MB) /
      > `inventory.db-shm`(32KB) 边车文件。当前主库是 `delete` 模式，它们**无害**；
      > 但 `-shm` 仍被远端进程持有，且一旦有人把该库改回 WAL，这些陈旧边车会立刻造成混淆。
      > 建议在远端侧确认无进程使用后删除（本机无法删，`-shm` 被占用）。
      > 还有一个 `inventory.db.bak_20260930`（113MB）本机备份，确认无需留存后可在远端删除。

- [ ] **worker 分组覆盖巡检常态化。** 未归组的任务会 **pending 卡死**且不报错。
      **验收**：`tests\test_worker_group_coverage.py` 通过；新增任务时同步 `GROUP_TASK_MAP` + `start_hidden.ps1` + `restart_workers.py` 三处。

- [ ] **`db_ps_cs_cn` 本地 0 字节占位文件的处置。** 真数据在远端（HTTP `8765`），本地同名文件是空占位——被误当数据源时会得到**空结果而非报错**，极易误判为"数据为零"。
      **动作**：要么删除，要么改名/加 README 说明。

- [ ] **`backend\app.db` 空占位确认。** 该文件已在 `.gitignore` 中标注为"误建的空 sqlite 占位"（真库是 `db\app.db`）。确认无代码按此路径读取。

- [ ] **图表数据源裸连接登记。** 已知 `ipran_chart_service.py:233`、`fw_kpi_services.py:488` 绕过 `get_raw_connection`。
      **当前动作（不是改造）**：把已有点位登记成清单，并确保**不再新增**。

## 三、P1 —— 文档与一致性

- [ ] **FineBI 迁移推进。** 见 `docs\FINEBI_MIGRATION.md`。迁移后页面走 `?page=` 直链，门户内 FineBI 占位条目需同步替换。

- [ ] **功能页与手册同步核对。** 抽查 `frontend\src\App.tsx` 菜单数组、`i18n.tsx` 中英字典、`docs\manual\11-feature-guide.md` 三处是否一一对应（新增页面漏登记是既定风险点）。

- [ ] **`docs\manual\15-user-help*.md` 重新生成确认。** 若 `helpContent.ts` / `helpTaskDocs.ts` 有未生成的改动，跑 `cd frontend && node scripts\generate-help-doc.mjs` 并核对站内帮助页一致。

- [ ] **本 8 份文档体系的落地校验。** 三处（工作区根、门户、my_app）文件名一致、互链可达。

## 四、P2 —— 工程卫生

- [ ] **带 `_bak_*` 时间戳备份的文件治理。** `frontend\src\pages\` 下有 15+ 个 `*_bak_20260918_vmax_dark` 等备份（单文件可达 85KB），`backend\main.py_bak_*`、`frontend\src\*.ts_bak_*` 等散布各处。虽已被 `.gitignore` 忽略，但目录噪音大。
      **建议**：确认无用后归档到 `_myapp_trash_*` 或删除。

- [ ] **`.venv-test` 与仓库根 `pyvenv.cfg`（3.13.14）的清理决策。** 二者都不是运行时解释器（运行时用脚本探测到的系统 Python 3.12），`.venv-test` 仅被 `backend\migrations\smoke_test_pg.py:44` 使用。留着易误导。

- [ ] **`tests\` 测试报告目录治理。** `tests\reports\` 为产出目录，确认已在忽略范围或定期清理。

- [ ] **根目录残留脚本清理。** `patch.py`、`_p.py`、`_s.py`、`out1.txt`、`t.txt`、`sec.txt`、`old_block.txt`、`_slice1.txt`、`_tmp_view.txt` 等一次性过程产物。**清理前先确认无引用。**

## 五、待定 —— 需决策（有明确前置条件）

- [ ] **SQLite → PostgreSQL 迁移是否启动。**
      规划已定稿（单 PG 实例 + 每域一个 schema `app_`/`eflow_`、同机 Docker PG、连接池 `pool_size=20 / max_overflow=10`、低峰切流）。
      **执行前提（四项全部落地才可动）**：
      1. 回退保证 R7；
      2. 风险 10 / 11 有对策；
      3. 风险 R8 有对策；
      4. 队列层覆盖到位。

      **范围要点**：
      - `db_ps_cs_cn` **整体移出迁移范围**（真数据在远端，保持 remote HTTP 读取）；
      - `eflow_tt` 双源归一到 `app.db.eflow_tt` 作为唯一活源，`eflow.sqlite3` 按**只读快照**迁移；
      - 告警表按 schema 分离（`app_`/`eflow_`）即可，无需合并决策。

      > 全量稽核的完整事实与逐条出处见 `PROJECT_DOCS.md` §2。

- [ ] **数据访问层是否统一（裸连接治理）如何推进。** 稽核已证伪"全部经 `get_raw_connection`"的假设（存在裸连接，且是图表数据源）；`get_raw_connection` 调用点约 76 处。需决策是"纳入迁移一并改造"还是"长期只登记不改造"。

- [ ] **`credentials` 表明文存储是否改造。** 现状凭据在 `db/app.db` 的 `credentials` 表**以明文存储**（已知风险，见 `docs\manual\05-security-and-credentials.md`）。是否需要加密或接入密钥管理需决策。

- [ ] **BP 报告模块 4 个文件超 500 行上限（AGENTS.md 第三节原则 2）。**
      2026-09-29 新增该模块时实测：`bp_caliber.py` 625 行、`bp_report_sync.py` 594 行、
      `bp_report_service.py` 585 行、`frontend\src\pages\BpReport.tsx` 619 行。
      **2026-09-30 复测（下钻补全 + 判定修复后）**：`BP Report.tsx` 957 行、
      `bp_report_sync.py` 630 行、`bp_report_service.py` 577 行、`bp_caliber.py` 528 行
      —— 前两个继续变长，**拆分优先级上调**。
      注释只占 58~85 行，**不是注释导致的膨胀**，是模块本身职责较重
      （口径常量 + 判定 + Excel 周期标签解析 / 增量同步 + 三方重算 + 对账 /
      概览 + 三粒度聚合 + 下钻 / 页面 + 5 个图表 + 3 个弹窗）。
      **动作（择机，不要在下钻验收刚通过时动）**：
      ① `bp_caliber.py` 拆出 `bp_caliber_labels.py`（周期标签解析与换算：
         `parse_excel_week` / `resolve_excel_weeks` / `parse_excel_month` /
         `excel_period_to_iso` / `period_to_day_range` / `week_days_in_month`）；
      ② `bp_report_service.py` 拆出 `bp_report_drill.py`（`load_cells` 与下钻相关）；
      ③ `BpReport.tsx` 把三个弹窗（明细 / 区域 / 频层）拆成同目录子组件，
         并考虑把**四张数字卡的判定推导**（`verdictValue`/`verdictLevel`/
         `verdictSub`/`verdictWhy`/`openVerdictDrill`）抽成 `useBpVerdict()` 自定义
         hook —— 这 5 段是本次新增里最长的一块，且与表格列共用同一套成因文案。
      **验收**：`python TMP\_verify_drill.py` 与 `npm run check:i18n` 均通过，
      且 `/api/bp-report/*` 的 5 个端点响应逐字段不变。
      > 拆分前先建 `_bak_<日期>_bp_split` 快照；该模块的下钻契约（见
      > `docs\manual\11-feature-guide.md` §30「下钻：能下钻尽下钻」）是拆分的回归基线。

- [ ] **BP 忙时口径（bp-v3）的后续三件事（2026-09-30 已修复趋势断层，剩下的都是可选扩展）。**
      **断层根因（已定位并修复）**：bp-v2 只对 AU 取峰值、PRB/Thr 仍用日均值，
      导致重算 BP 数只有 10~31 个/天，与 Excel 真值（350~600 个/天）差 30 倍，
      趋势图出现断崖。**标定实验**（09-21）证明 umlaut 的三个条件按**忙时**判定：
      取 AU 最大小时的 PRB/Thr/AU 三值判三条件，与 Excel 明细**逐小区一致
      （Jaccard=1.00，607/607）**。已改为该口径（`bp-v3`）并回填
      09-22 ~ 09-29 八天，重算值与 Excel 真值逐日偏差稳定在 −8~−9%
      （512/555、399/432、350/383、420/463、441/486），趋势已连续。
      取数事实与复现要点见 `docs\manual\11-feature-guide.md` §30 与
      `bp_active_user.py` 的模块 docstring。

      剩下的三件（都非阻塞）：
      ① **−8~−9% 的系统性偏差是否要追**：方向恒定（重算略低于 Excel），
         可能来自 Excel Overall 与 BP Cells List 的既有不一致
         （Excel 自身相邻两天名单重叠率仅 74~80%），也可能来自
         忙时选择/`indexfillingtype` 的细节差异。量级已可用，暂不追。
      ② **回填窗口是否扩大**：UME 保留实测 ≥3 个月、1 年前为 0。
         当前只回填了 8 天，可择机扩到保留窗口；**Excel 覆盖的 2023–2026
         历史无法从 UME 补齐**，那部分永远只有 Excel 值。
      ③ ~~**周/月的 `bp_days` / `bp_weeks` 为 NULL**~~ —— **2026-09-30 已修**。
         原先 `bp_overall_week` / `bp_overall_month` 的既存行判定列恒为 NULL
         （`_recompute_week/_recompute_month` 是 insert-only，只写新周期），
         页面「最新一期判定」因此永远显示「不可判定」。
         新增 `bp_report_sync.backfill_period_verdicts()`：**只 UPDATE 判定列、
         且带 `... IS NULL` 条件**，Excel 的指标真值一个字不碰 ——
         关键是把「Excel 的指标真值」与「Excel 从来不提供的判定列」分开，
         后者补算是**填空**而非覆盖。实测补算 139 周 + 42 月。
         **遗留（已确认，非 bug）**：`2026-09` / `2026-10` 只有 3 个完整周，
         而口径要求 `MONTH_TOTAL_WEEKS=4`，故 `is_bp_month` 恒为 None
         —— 这两个月**在现行口径下永远判不出来**。界面现已显示
         「本月仅 3 个完整周（口径要求 ≥4 个）」，不再是一句「不可判定」。
         是否要放宽该口径（如允许 3 个完整周）需业务方决策，**未经确认不要改**。

- [ ] **BP 页下钻已按 1b 补全，但有两处「对不上」值得业务方决策（2026-09-30 复核）。**
      已接上的：趋势表 `bp_cells`/`明细行数`/`不可判定`/`total_cells`(ume 期)、
      趋势图柱子、四张数字卡、分区图柱子、分层表 `bp_number`；实测全部一致。
      两处**刻意置灰**并给出原因：
      ① 趋势表 `total_cells` 的 **excel 期**（Excel 全网口径、无名单）；
      ② 分层表 `total_cell` —— `bp_layer_daily.total_cell` 是「按天 × 层」累加，
         而 Excel 来源的天在 `bp_cell_daily` 里只含 BP 小区；
         实测混合区间 6 个层只有 2 个对得上，仅 ume 天则 6/6 全对（分区表 1/9 → 9/9）。
      若业务方希望这两处也能点，前置条件是**统一 population**
      （要么把 Excel 历史期的全网小区也补进明细表，要么让分层/分区汇总只统计 ume 天）。

- [ ] **周/月粒度的「概览 vs 下钻」数字对不上（既有现象，本次复核确认非 bug）。**
      实测 2026-09-30：`/overview?granularity=week` 的 `bp_cells`（如 W39=462）
      直接取自 `bp_overall_week`，那批行 `source=excel`，是 **Excel 汇总值**；
      而 `/cells?start&end&scope=bp` 数的是 `bp_cell_daily` 里的小区-日行
      （W39 范围 716 行 / 607 个去重小区）。**两个分母不同，本来就不该相等**。
      **日粒度不存在该问题**（两侧同源 `bp_overall_daily`，实测 5/5 完全一致）。
      需要决策：周/月概览页是否要显式标注"此值为 Excel 口径，与下钻行数不可比"，
      避免用户把它当成 bug。相关背景见 `11-feature-guide.md` §30 的两总体说明。

- [ ] **`pyjab`（GPLv2）的分发边界认定。** `backend\services\cn_ems\cs_ems_jab.py:27` 依赖 GPLv2 的 `pyjab`，属**强传染**许可。前置条件：确认 `cn_ems\`（U31 EMS 桌面客户端 GUI 自动化）**是否随产品交付客户**——仅内网自用则 GPL「分发」未触发、风险可控；随产品交付则该脚本须 GPL 开源，与闭源定位冲突，需替换或隔离。该目录当前**无 router / `task_registry.py` 入口 import**，传染面有限。核查记录见 `docs\THIRD-PARTY-NOTICES.md` 第二节。

- [ ] **两个未登记依赖的处置。** ① `python-calamine`：`ipran_ume_kpi_service.py:686` 用 `engine='calamine'` 且**无兜底**，缺失即抛错——需确认该任务是否在目标环境启用，是则补装并登记进 `requirements.lock.txt`。② `twilio`：`incident_overview_service.py:667/709` 走 `try/except` **静默降级**，虚拟助手电话/短信实际不可用——决定是补依赖还是移除该分支。核查记录见 `docs\THIRD-PARTY-NOTICES.md` 第四节。

## 六、维护本文的约定

1. **只留在办项**，做完移走或删掉。
2. **每条可执行**：写清改哪里、验收标准是什么。
3. **待定项写清前置条件**（等哪几项落地）。
4. **定期与 `PROJECT_DOCS.md` 的规划状态对齐**，避免与历史档案矛盾。
5. **不写敏感值。**

## 七、相关文档

| 内容 | 去哪里 |
| --- | --- |
| my_app 历史规划与复盘 | `PROJECT_DOCS.md`（§2 迁移计划、§3 架构评估、§5 i18n 审计、§10 失败复盘） |
| 待清理残留清单 | `docs\manual\90-appendix.md` |
| 安全现状与已知风险 | `docs\manual\05-security-and-credentials.md` |
| 第三方许可与归属声明 | `docs\THIRD-PARTY-NOTICES.md` |
| 数据层与迁移前提 | `docs\manual\03-data-layer.md` |
| 任务系统 | `docs\manual\04-task-system.md` |
| FineBI 迁移专项 | `docs\FINEBI_MIGRATION.md` |
| 代码清理指南 | `docs\CODE_CLEANUP_GUIDE.md` |
| 测试发现与建议 | `tests\DEEP_FINDINGS_AND_SUGGESTIONS.md` |
| 架构与数据流 | `architecture.md` |
| 开发与回归清单 | `development.md` |

> **工具负责整理，人与 AI 负责协作执行。**
