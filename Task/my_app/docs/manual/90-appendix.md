# 90 附录

## A. 后端接口前缀速查

注册在 `backend/main.py:95-131`（实测 25 处 `include_router`）。前端 `baseURL` 是 `/api`（`frontend/src/api.ts:4`）。

**带 prefix 的 router**

| 前缀 | 对应页面/用途 |
| --- | --- |
| `/api/tables` | 表浏览器（数据、画像、导入导出、视图模板）；`/api/tables/import-exclude` 与 `/exclude-meta` 为 NUR 排除名单专用（同前缀，见 `routers/tt_exclude.py`） |
| `/api/upload` | 数据上传 |
| `/api/analysis` | 分析仪表盘 + 分析归档 |
| `/api/gis` | GIS 地图 / 实时告警地图（含 `/gis/realtime/*`） |
| `/api/tt-wo-dashboard` | TT&WO 看板（`page=ttwo` / `v1_ttwo` / `tt`，以 `eflow_tt` 为主表） |
| `/api/wo-dashboard` | WO 看板（`page=wo`，以 `eflow_wo` 为数据源；SLA 取自关联 `eflow_tt`） |
| `/api/alarm-dashboard` | 实时告警看板（含 history/realtime 两种下钻） |
| `/api/packet-loss-dashboard` | 丢包看板 |
| `/api/battery-dashboard` | 电池看板 |
| `/api/ms-sla-dashboard` | MS Operation KPI 看板 |
| `/api/nur` | NUR 看板（`/overview`、`/options`、`/detail`） |
| `/api/mw-ume` | MW 微波拓扑（`/topology` 日粒度）、MW 微波实时（`/realtime` 15 分钟槽位） |
| `/api/incident-overview` | 事件总览（iframe 内页调用） |
| `/api/ip-trace` | IP 链路探测（iframe 内页调用：`/trace`、`/status`、`/stop`、`/analyze`） |
| `/api/portals` | 门户一键登录（`/`、`/login`、`/login/status`、`/close`） |
| `/api/credentials` | 凭据（`/`、`/test`、`/{key}/reveal`） |
| `/api/email-recipients` | 收件人（`/`、`/reset`） |
| `/api/settings` | 设置（`/remote-host`、`/test-connection`） |

**路径写在装饰器里的 router**（没有统一 prefix，容易漏找）

| 文件 | 端点 |
| --- | --- |
| `routers/tasks.py:30-195` | `/api/tasks`、`/api/tasks/{id}`、`/api/tasks/{id}/run|stop|toggle|schedule|status|history|stats`、`/api/tasks/failures`、`/api/tasks/toggle-all`、`/api/eflow/sync|status` |
| `routers/system.py:21-96` | `/health`、`/data-source/timestamps`、`/db/info` |
| `routers/email_reports.py:92-152` | `/api/email-reports/latest`、`/api/email-reports/eflow_tt_rules_check`、下载 |
| `routers/finebi_reports.py:26-48` | `/api/finebi-reports/latest`、下载 |
| `routers/sp_dashboard.py:25-55` | 仓库看板 iframe 用：`/api/data`、`/api/warehouses`、`/api/details` |
| `routers/realtime_proxy.py:23-39` | 实时代理入口（实际代理端口 8787/8790 只绑回环） |
| `routers/portal_qa.py` | 门户问答挂件：`/api/portal-qa/ask`、`/api/portal-qa/session/clear`、`/api/portal-qa/health`（转发到本机 9269，见 `13-operations.md`） |
| `routers/cm_flows.py:21-46` | CM 小区配置流程 |
| `routers/task_configs.py:48-82` | 任务参数配置（系统设置 → 任务配置页签） |

**受 Token 保护的只有 4 个 router**：`tasks`、`upload`、`task_configs`、`cm_flows`（共 18 处装饰器）。原因与风险见 `05-security-and-credentials.md`。

## B. 数据库对象速查

| 对象 | 位置 | 说明 |
| --- | --- | --- |
| `task_queue` | 主库（PG） | 任务队列，worker 用 `UPDATE…RETURNING` 原子认领；保留 3 天 |
| `task_execution_log` | 主库 | 每次执行的历史；保留 3 天 |
| `task_schedule_config` | 主库 | cron 覆盖表，界面改排程写这里 |
| `credentials` | **`db/app.db`（SQLite，明文）** | 绕过 `MY_APP_DB_MODE`，备份必带 |
| `mw_ume_bw_ultilazation` | 主库 | MW 微波带宽利用率（注意表名里 `ultilazation` 是既有拼写，勿改） |
| `mw_ume_bw_ultilazation_rt` | 主库 | MW 微波带宽利用率 15 分钟粒度实时表（每 15 分钟覆盖最近 2 小时窗口，拼写沿用主表） |
| `cm_cell_data` / `cm_site_summary` | 远程主机 `db.sqlite3` | CM 小区配置，全量替换写入 |
| `battery_kpi.sqlite3` / `lte_pl.sqlite3` / `ms_sla_dashboard.sqlite3` | `data/` 各子目录 | 独立 SQLite，见 `03-data-layer.md` |
| 动态 eFlow 表 | 主库 | **不在 Alembic 管理内**，运行时按上游字段建表 |

## C. 页面 → 接口对照（一图速查）

| 页面 | 关键接口 |
| --- | --- |
| 任务管理 | `GET /api/tasks`、`POST /api/tasks/{id}/run|stop|toggle|schedule`、`GET /api/tasks/failures` |
| 任务报告文件 | `GET /api/email-reports/latest`、`/finebi-reports/latest`、`/email-reports/eflow_tt_rules_check`、`POST /api/tasks/eflow_tt_rules_check/run` |
| 实时告警看板 | `/api/alarm-dashboard/overview`、`/history-drilldown`、`/realtime-drilldown` |
| TT&WO | `/api/tt-wo-dashboard/overview`、`/drilldown`；`/workflow`（eFlow 流程定义，`Workflow` 里程碑的阶段顺序来源） |
| WO（`page=wo`） | `/api/wo-dashboard/overview`、`/drilldown`（数据源 `eflow_wo`，口径函数与 TT&WO 共用；不接 `owner` 参数） |
| NUR | `/api/nur/overview`、`/options`、`/detail` |
| MS SLA | `/api/ms-sla-dashboard/overview`（返回 daily/weekly/monthly 三档；weekly 下 network/persite 为空表）、下钻复用 `/api/nur/detail`（`gran=weekly` + `period=2026-W12`） |
| GIS / 实时告警地图 | `/api/gis/sites`\|`/gis/realtime/sites`、`/gis/topology`、`/gis/region-boundaries`、`/gis/drilldown/{id}` |
| 丢包 | `/api/packet-loss-dashboard/overview`、`/map-sites`、`/drilldown`、复用 `/api/gis/topology` |
| 电池 | `/api/battery-dashboard/all`、`/trend`、`/site/{site}` |
| 数据总览 | `GET /api/db/info` |
| 表浏览器 | `GET /api/tables`、`/tables/{t}/data`、`/tables/{t}/profile`、`/tables/{t}/export`、`POST /api/tables/import`、`/api/tables/view-templates` |
| 数据上传 | `POST /api/upload`、`GET /api/upload/history` |
| 分析归档 | `GET/POST /api/analysis`、`GET/DELETE /api/analysis/{id}` |
| 系统设置 | `/api/credentials*`、`/api/email-recipients*`、`/api/settings/remote-host`、`/api/task-configs*` |
| 门户一键登录 | `/api/portals`、`/portals/login`、`/portals/login/status`、`/portals/close` |
| 6 个 iframe 页 | 由 `public/*.html` 自调接口（见上表 `sp_dashboard`、`ip-trace`、`incident-overview`） |

## D. 待清理的仓库残留（已验证未被代码引用）

| 文件 | 判断依据 |
| --- | --- |
| `check_rules.py` | 一次性脚本，读同目录 `eflow_TT_rules.xlsx`；正式规则在 `backend/services/eflow_rules/`（`eflow_rules_matcher.py:29`） |
| `eflow_TT_Rule_Collector - Copy.py` | 正式版在 `backend/services/eflow_rules/` 下同名，根目录是副本 |
| `eflow_TT_rules.xlsx`（根目录） | 同上，注意别把它当规则源改 |
| `test_owa_access.py`、`test_owa_simple.py` | 一次性 OWA 连通性探测 |
| `send_test_v22.log` | 发信测试输出 |
| `backend/restart_dbg.log` | ≈751 KB 调试日志 |
| `data/app.db`、`data/my_app.db`（均 0 字节） | 历史路径遗留，实测根目录下无同名文件 |
| `frontend/dist`、`dist2`、`dist3` | 未被 `outDir` 使用 |
| `templates/`（根目录） | 只剩 `_roi_debug_*.png` 调试图；真正的图片模板在 `backend/services/cn_ems/templates`（`cs_ems_kpi_code_image.py:43`） |
| `monitor_fixes/` | 监控远程主机的脚本集（路径写 `E:\01_RPA\...`），与本机启停无关。确认无引用后可移出仓库 |

**清理前确认**：`git ls-files` 里是否被跟踪、以及是否有计划任务/计划作业在直接调用这些 `.py`/`.bat`。

## E. 本手册迁移说明

以下内容从 `PROJECT_DOCS.md` 迁入本手册，原文件保留作历史档案：

| PROJECT_DOCS.md 原章节 | 迁入位置 | 迁移时的修正 |
| --- | --- | --- |
| §1 项目说明 README（技术栈/结构/快速启动/功能模块/数据源） | `01-overview.md`、`02-architecture.md`、`10-quickstart.md`、`11-feature-guide.md` | 原文只列 **9 个**功能模块小节，实际菜单已有 **23 个页面**；原文 `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload` + `http://localhost:5173` 只是开发模式，生产实走 7038 + watchdog（`main.py:298` 的 8000 分支仅调试） |
| §7 MS SLA / NUR 服务说明 | `11-feature-guide.md` 第 5–6 节、`14-integrations.md`、`03-data-layer.md` | **原文已过时**：列出的 `ms_sla_sync`、`contract_kpis_report` 两个 task_id 在当前 `TASK_SPECS` 中**已不存在**（现为 `ms_sla_full`、`kpi_ms_contract`、`kpi_ms_wo_sla`）；库名也从 `lbr_ms_sla_kpi.sqlite3` 变为 `ms_sla_dashboard.sqlite3`。NUR/SLA/WO 口径 2026-08 起改为 `nur_calc` 实时计算 |
| §9 局域网访问 | `13-operations.md`「局域网访问」 | 保留"与 MTN_Comsal 共用 7038/7090"与 PG 放行步骤；原文依赖的三个脚本中，`firewall_setup.bat` **本项目内不存在**（同机 `Task/MTN_Comsal/my_app/` 有同名文件，端口路径不同不可直接用），`setup_pg_lan_access.bat`、`install_ensure_task.bat` 在 `D:\01_RPA` 全树均未找到。手册中已标注为待补脚本缺口 |

**保留在 PROJECT_DOCS.md 不动**（属于历史决策与复盘，不是"现状描述"）：§2 迁移计划、§3 架构评估与 Django 论证、§4 FastAPI 架构优化方案、§5–§6 i18n 审计与复查、§8 IP Trace 集成方案、§10 迁移失败复盘、§11 优化建议。
