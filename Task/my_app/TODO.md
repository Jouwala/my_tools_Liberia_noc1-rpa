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

- [ ] **FineBI 仓库看板镜像库停更的远端侧改造。** `sp_data_sync` 写
      `\\DESKTOP-D4GF62\...\WareHouseDashBoard\inventory.db` 自 **2026-09-24** 起 100% 失败
      （`database is locked`），根因是**该库为 WAL 模式且被远端活进程持有，而 WAL 的共享内存
      字节锁在 SMB 上无法建立** —— 属架构限制，调 `timeout`/`busy_timeout` 无效
      （实测 30s / 30000ms 均失败，逐项排除过程见 `docs\manual\04-task-system.md` 的「`sp_data_sync`
      的两个已知缺陷」缺陷一）。
      **动作**：远端侧改为「本地库 + 接口/定时快照导出」，或由写库进程自己在本地落库后导出
      `inventory.db`；本仓库无法单方面解决。
      **验收**：`result_json.mirror_success=true`，且不再出现 `[降级] 镜像写入 FineBI inventory.db 失败` 通知。
      > 代码侧能做的已做完（2026-09-27 降级告警 + 结构诊断；2026-09-28 修掉诊断字符串
      > 引发的 `'str' object has no attribute 'get'` 回归 —— 它曾把镜像失败谎报成 SFTP 故障，
      > 并把单轮耗时从 534s 推到 1576s）。

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
