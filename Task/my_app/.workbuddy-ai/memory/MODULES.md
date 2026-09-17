# my_app 业务模块细节（原 MEMORY.md §4 拆出）

> 主索引在 `memory/MEMORY.md`。本文件保存各业务模块的实现细节与口径坑，按需读。
> 更新时间：2026-09-16

## 4.1 WhatsApp 发送
（`whatsapp_service`）
- 图片清单**每次执行时重新收集**（`_collect_photos_and_captions()`；worker 长驻，模块级 `PHOTOS` 只是 import 快照）；`photos=[]` 要**显式传**，传 `None` 会把站点中断截图灌进目标群。
- 本机 WhatsApp Web 是**中文界面且没有附件按钮** → 只有**剪贴板路径**可用；⚠️ `Ctrl+V` 后弹的是**全屏「文档预览页」**，必须等「附件预览 + 发送按钮」同时就绪再**点发送按钮**（`div[role='button'][aria-label*='发送']`；**回车在预览页无效**）。
- `_verify_file_sent` **只认消息行内**（`div[role='row'], div[data-testid='msg-container']`）的文件名，预览页/输入框不算（否则假成功）。聊天列表是**虚拟列表**（DOM 只留 ~25 条）。
- 用户偏好：只做**最小改动**，别顺手重构发送流程（大改曾被要求全部回退）。

## 4.2 SP 备件报表
（`sp_report_gen/gernarate_sp_report.py`）
- 任务 `sp_report_generate`（05:15）→ 10 xlsx + 4 png 到 `data/sp_email`。明细 sheet 列序由脚本顶部常量唯一决定，别在 Excel 手工改列。
- 就地重生成要复用 main() 前处理链再逐个 `generate_report()`（见 `TMP/t_sp_status_regen.py`），**别调 main()**（会重下载 + 删旧文件）。
- `inventory_details.xlsx` 用 openpyxl `read_only` 只看到 1 列（dimension 缺失），必须 pandas 读。
- **`sp_email_details`**（cron `55 5 * * *`）：4 份明细合并成一个工作簿 → 发邮件 → **再把同一份作为文档发 WhatsApp 群 WH&SP Management**。⚠️ 该任务在 `email_recovery.EMAIL_TASK_IDS` 内，error 命中 `EWS_FAIL_KEYS` 会**整链补发** → 重复收报表；WhatsApp 侧失败只写固定标记 `WHATSAPP_FAIL: ...`（`task_runner` 在 success=False 且无 error 时用 message 兜底，"留空"躲不过去）。
- **数据源（2026-09-16 变更，重要）**：`/home/ubuntu/sp/<目录名>/<yyyymmdd>/<yyyymmddHHMMSSfff>/<同名文件>.xlsx`，
  按「目录名 + 固定文件名」取最新一份（`_find_latest_named_excel`，文件名精确匹配）。
  `inbound.xlsx` / `outbound.xlsx` / `inventory_management.xlsx` / `wh_transfer.xlsx` / `wh_transfer_return.xlsx`
  → 本地仍叫 `inband/outband/inventory/transfer/transfer_return_details.xlsx`（下游依赖本地名，别改）。
  ⚠️ 旧目录 `sp/spinbound|spoutbound|spinventory|sp-wh_transfer` 已于 **2026-09-15 08:00 停更**；
  旧逻辑只取「最新 xlsx」不校验文件名 → 换名后会静默取过期快照。同一变更也应用于
  `get_sp_table.py`（仓库看板同步，n 组）与 `task_configs_registry.py` 的 `sp_sftp_config.json` 默认目录。
- **过滤链（2026-09-16 起每个 sheet 标题下第 3 行有蓝色说明行，写明该 sheet 的口径）**：
  1. 明细预处理（写回 `data/sp_email/data`，`sp_email_details` / `sp_online` 同口径）：`apply_exclude_to_details()` 按 `in&out_exclude.xlsx` 的 `3_剔除单据Serial明细` 剔除入库/出库行（full 四字段全等 / loose 单据号+Serial 兜底）；`apply_status_filters()` 出库剔除 `Status='WaitingForUpdate'`；`apply_operation_result_filter()` + `apply_operation_result_filter_to_file()` 剔除 `Operation Result Status='Canceled'`（inbound/outbound/wh_transfer 有该列，inventory 没有）；`apply_inventory_fields()` 覆盖 Material Name（`sp_material` 表）/ Material Type（inventory）。
  2. 报表额外：`preprocess()` 排除仓库 `Liberia Monrovia material warehouse`；`generate_report()` 只留 `Material Type='SpareParts'`（或 `Consumables`）；分仓报表再按 `Warehouse Name` 过滤。
  3. 已停用：`filter_data()`（Borrow Return Inbound / Repair Outbound）——2026-09-08 起注释。
  > 实测（2026-09-16 19:45 快照）：inbound 4233 → −299(exclude) −2(Canceled) −28(排除仓库) → 报表 3904（SP 2254 + CS 1650）；
  > outbound 2217 → −6 −45(WaitingForUpdate) −20(Canceled) −26 → 2120。inbound 的 301 个 Canceled 有 299 个早已被 in&out_exclude 覆盖。
- 说明行实现：`_build_filter_note(kind, material_type, warehouse_name)` 生成文案；`_insert_title(..., filter_note=)` 多插一行并**返回表头行号**；`style_excel(..., filter_note=)` / `style_summary_changed(..., filter_note=)` 据此把 header_row 从 3 改成 4、data_start 从 4 改成 5。**不传 `filter_note` 时行为与改动前完全一致**（`generate_sp_online_report.py` 复用 `style_excel` 未传 → 不受影响）。
- 核对脚本：`TMP/verify_sp_report_filters.py "<时间戳>"`；说明行验证 `TMP/t_sp_filter_note_check.py`；新数据源端到端（隔离目录，不碰生产）`TMP/t_sp_new_flow_check.py`。
- ⚠️ **仓库看板链路（`get_sp_table.py`，任务 `sp_data_sync` 07:00）**：同一个上游、同样切到新目录。
  它写的是 **PG**（生产 `DB_MODE = pg`）—— `db/app.db`（1.58 GB）是**遗留 sqlite**，
  **别用它判断同步结果**，要看 PG 的 `sp_sync_log`。镜像写 FineBI `inventory.db` 长期报
  `database is locked`（远端库是 WAL 模式 + 7.8MB 未 checkpoint 的 `-wal`，SMB 上不可靠），
  失败不影响本系统看板（读 PG）。
  ⚠️ 该链路**没有** Canceled 过滤 → PG 里 inband 仍含 301 / outband 含 26 行 Canceled，
  与 SP 报表口径不一致（`sp_material_summary_service` 读这两张表，会连带受影响）。

## 4.3 eFlow TT 能力
- 判定口径唯一真相源 = `services/eflow_rules/eflow_rules_matcher.py`（读 `eflow_TT_rules.xlsx` ACTIVE 规则）。它内部直连 sqlite，生产是 pg → Web 路径必须走 `backend.database.get_raw_connection()` 双模连接；复用 `load_rules()` 记得 `redirect_stdout` 静音。
- AI 结论走 Open WebUI「TT单分析」技能（`openwebui_client.py`，取 `command=TT_PROVITY` preset）。模型见 `backend/.env` 的 `OPENWEBUI_MODEL=agnes-2.5-flash`（2026-09-15 由 auto 改固定：agnes-3.0-flash 慢 14 倍且把 TT202609140039 判成 P4，规则引擎与 2.5 均为正确的 P2）；**别改 `incident_ai_service.py::AGNES_MODEL`**（另一条链路）。
- ⚠️ `openwebui_client._TIMEOUT = 120` 硬编码（是 `_http()` 默认参数值，运行时改模块属性无效），**超时抛 `RuntimeError` 而非 `ModelError`**，而 `analyze_tt()` failover 只捕 `ModelError` → **模型一慢就整链路失败、不降级**。
- 诊断脚本 `TMP/t_model_probe.py`、`t_owui_visibility.py`、`t_tt_model_ab.py`。

## 4.4 Alarm Management 看板
（`frontend/public/alarm-management.html`）
- 门户 Site Down Dashboard 的单文件内嵌版，`FMS_REAL` 是**冻结快照**，实时刷新只覆盖「值」，**结构性常量（下拉选项/列头/KPI 口径）不会自愈**。
- **RAN Site Type 选项真源** = 门户 `https://10.100.20.8:28001/api/alarmstatistics-service/v1/levelregion/getConfigCenterSiteTypeList` → `data.siteTypeOptions`（2026-09 为 ALL/REGULAR/COOL/ERA），已做成 live 源 `ranSiteTypes`。
- FMS 只有 `/api/alarmstatistics-service/v1/<段>/<方法>` 一种形态，别猜服务名。查真实口径捷径：`site_outage` 任务（01:00，m 组）日志里的 `[SiteOutage] 找到 N 个选项: [...]`。

## 4.5 incident-overview AI provider
（`frontend/public/incident-overview.html`，遗留单文件页）
- 7 个 provider → `POST /api/incident-overview/ai/{provider}` → `services/incident_ai_service.py::dispatch()`。**Key 一律由前端请求体传入**。
- **agnes 分支直连上游**（`apihub.agnes-ai.com`），**绕过 Open WebUI**，不能复用 `openwebui_client` 选型逻辑。
- ⚠️ apihub 对**不存在的模型返回 503**（`No available channel for model xxx under group default`），**不是 400/404**；判「模型下线」必须「状态码 400/404/503 **且** 错误文本命中该措辞」。

## 4.6 UME PM-analysis 协议（可复用）
- 真相源 = `services/mw_ume/mw_ume_kpi_service.py`：原始 socket + TLS（绕证书，`ALL:@SECLEVEL=0`）→ `GET /api/oauth2/v1/authorize` → `GET /api/oauth2/v1/login/publickey` → RSA(PKCS1v15) 加密密码 → `POST /api/oauth2/v1/login_rsa` → `POST /api/pm-analysis/v2/history` 建查询拿 queryid → `GET /api/pm-analysis/v1/history?type=0&queryid=` 轮询（`querystate==1` 或 `progress>=100` 完成）→ `POST /api/pm-analysis/v3/history/export` 导出（**返回 ZIP 包裹的 xlsx，要内存解包**）。
- **换门户/换模板只改 `HOST/PORT/LOGIN_PORTAL` + 7 个 cfg 字段**（`favoriteconditionname`/`gr`/`motid`/`nfctid`/`items`/`templatename`/`templateid`/`filterlayer`/`grouplayer`），HTTP 层零改动，**字段顺序敏感**。
- 写库统一 `save_to_db()` → `get_raw_connection()`（sqlite/PG 双模 upsert，主键 `Begin Time` + 身份列；PG 用 `pg_advisory_lock` 防并发 DROP/CREATE UNIQUE INDEX 竞态）。

## 4.7 Customer Service KPI 看板（ume_in，09-15 新增）
- `services/ume_in/ume_in_kpi_service.py` + `routers/ume_in_kpi.py` + `frontend/src/pages/UmeInKpi.tsx`（pageKey `ume_in_kpi`）。路由 `GET /api/ume-in/overview?days=7`、`POST /api/ume-in/sync?days_back=7`、`GET /api/ume-in/specs`；任务 `ume_in_kpi_sync`（`45 5 * * *`，组 n，category `ume_in`）。
- ⚠️ **自带 `UMEPortalClient`，刻意不复用 4.6 的模块级函数**——那边 HOST/PORT 是模块全局变量，同进程改会污染 MW UME；只复用其纯函数（`read_xlsx_bytes`/`save_to_db`/`ensure_unique_key_cols`）。
- 表 `ume_in_customer_kpi`（PG，日粒度，主键 `Begin Time`+`KPI`+`NE`+`SERVICE`——**必须带 KPI 维度**，7 模板同天同 SERVICE 会撞车）。7 模板：IVR/P4M/VC/USSD/PPS/CPU/Memory（NE 恒 `pr-zxin-osg`，gr=86400，回看 7 天 ≈238 行）。门户 `172.17.208.1:28808`，账号见 `backend/services/ume_in/url.txt`（也在 Settings 凭据组 `ume_in`）。
- ⚠️ **PG 列名 `"KPI"`/`"Begin Time"` 等是大写带引号的**，SQL 必须写 `"KPI"`，否则折叠成小写报 `字段 "kpi" 不存在`。
- **分析口径**：失败按归因分侧（`fail_cols` 三元组带 side=system/user）。**告警只看系统侧失败率**（≥1% critical / ≥0.1% warning）与资源日均利用率（≥90 critical / ≥80 warning；峰值仅用于 spike 检测 ≥95% 且日均 ≥50%）；总成功率仅用于配色。否则 PPS(82%)、USSD(89%) 会被误报——其失败 100% 属「余额不足/用户失败」等业务正常结果。P4M 是「请求→订阅」转化率（34%），标 `alarm:False`。
- **全页统一下钻（09-15 追加，完整入口清单见 `memory/2026-09-15.md`）**：只维护一个 `{target, anchor}` state，`drillTo(target, anchor?)` 不传 anchor 时沿用当前锚点；`DrillModal` 按 target 反查 `data.kpis` 自组装页签与导出。入口已覆盖业务 KPI 表各列、资源表、三张图表（`onEvents.click`）、7 张概览卡、告警行、弹窗内行。`day` 有值时趋势页签只显示该天并改名「当日指标」，**顶部摘要也要换成该天数字**（否则自相矛盾）。
- ⚠️ **口径坑**：「服务数」卡片 = 最新一天 **distinct SERVICE** 个数（=16），下钻必须按 SERVICE **归并**（同一 SERVICE 挂在 CPU/MEM 等多个 KPI 下，不归并得 34 行、与卡片对不上）；归并后 `kpi` 列是 `"CPU, MEM"`，继续下钻要 `split(',')[0]`；归并行 status 取组内最严重，排序 `critical > warning > good > info`。
- ⚠️ **未完成（用户选择暂缓）**：该任务**尚未被 worker 认领**（队列 `pending`），修法见 §2 `--mode watchdog`；此前「立即同步」按钮可手动抓数（≈11.4s）。

## 4.8 OSG Weekly QoS Analysis Report（09-16 新增）
- 模板 `data/in_data/OSG Weekly QoS Analysis Report.xlsx`（10 sheet：PPS / USSD / VC / IVR / P4M / OSG CAPS / CPU Resource / Memory Resource / SMS Traffic_HQ / SMS Traffic_ODC；7 日期行 + 9 张图表 + 大量公式）。生成脚本 `TMP/t_osg_build.py [起日 止日]`（默认 2026-09-08~09-14）→ `data/in_data/OSG Weekly QoS Analysis Report_<起>_<止>.xlsx`。
- **做法 = 复制文件后直接改内部 sheet XML 数值单元格**（openpyxl 保存会丢条件格式扩展、且有 9 张图表），公式/图表/样式零改动；最后给 `calcPr` 加 `fullCalcOnLoad="1"` 并同步公式缓存值。
- **列映射**：PPS B←`Call attempts`、D←`Success Times`、F←`Balance Insufficient Times`、G←`User Status Abnormal Times`、H←`Other User Failed Times`（表头写 Network Failure）、I←`System Failed Times`；USSD B←`Call Attempts`、D←`Send Success Times`、F←`User Fail Times`、G←`DataBase result error Times`、H←`System Fail Times`；VC 六字段**只取 SERVICE=`Nzxin_ImpVcRecharge_0`**（排除 VcManage 小流量，否则与历史值对不上）；IVR B=C=`PA Times`、D=`PA Failed Times`；P4M B←`Request Times`、C←`Subscribe Times`、D/E←黑/白名单；CPU/MEM **只取 SERVICE=`CommonS_OSG_0`**。
- **口径（用户明确要求）**：填**最近 7 天**。表里的同步是滚动窗口、且任务可能被禁用/漏跑 → **生成前先触发一次 `POST http://127.0.0.1:7038/api/ume-in/sync?days_back=7`**（本机回环免登录，≈11.5s，返回 `rows_written`），再把表里**最后 7 个不同日期**填进去（09-16 实测：跑完同步后 09-08~09-15 共 8 天 → 取 09-09~09-15）。
- **同步覆盖不到**（每次都要作为缺口报出）：`OSG CAPS`（源=EM System 大屏 20H 峰值）、`SMS Traffic_HQ`/`_ODC`（源=SMS license 报表；`data/in_data/License Utilizatio Ratio.xlsx` 是那份人工台账，2026-09 只更到 09-05 且数值与报告 HQ/ODC 列对不上）、`P4M` 的 `Total P4M Users` 列。
- ⚠️ 校验时注意**起始行**：PPS 数据从第 4 行起（第 2 行 Column1..、第 3 行表头），USSD 从第 3 行起，其余表从第 2 行起；写校验脚本容易错一天。

## 4.9 前端 / Playwright / i18n 硬规则
→ 见 `memory/FRONTEND_PITFALLS.md`（antd v6 传 CSS 变量给 color 会变白字白底、antd v6 DOM 类名与 v5 不同、ECharts 点击下钻的 canvas 像素取点法、`:text-is` 等选择器坑、下钻弹窗复用 `DraggableClickModal` + `SearchableExportTable`、i18n 只本地化「请求时生成」的文案）。**做前端页面 / 写 Playwright 断言 / 改文案前先读它。**

## 4.10 MsPortal 看板目录 API（`portal_catalog`，09-17 新增）
给 MsPortal 静态门户（nginx `location /MsPortal/`）提供「组件内的看板可增删改」的服务端目录。
**权限模型照抄 `ui_config.py`**：全局共享一份、只允许本机（或持 `X-API-Token`）修改。

- `GET /api/portal-catalog` 已登录可读 → `{catalog, updated_at, editable}`；
  `editable = is_privileged(request)`（仅本机回环 / 持 token），前端据此决定是否显示编辑入口
- `PUT /api/portal-catalog`（`require_protected`）整体替换；`DELETE`（同权限）删除 → 前端回落内置 data.js
- 持久化 `backend/data/portal_catalog.json`（`atomic_replace_file` 原子写，文件不存在 = 从未保存过）
- ⚠️ **刻意不在 `main.py` 的 `_PUBLIC_API` 白名单里**：未登录访客连目录都读不到
  （与 MsPortal 的整页门禁同口径）。本机回环由中间件放行，局域网登录用户持 `myapp_session` 也能读。
- 校验：`items` 必须是非空数组（≤500）；每条必须有 `titleZh`/`titleEn` 之一 **且** 以 `http(s)://` 开头的
  `url`，否则 400；字段走白名单 + 长度截断（文本 600 / 描述 2000 / 标签 24×40 / 分组 24×64 / URL 1000）；
  `no` 重复直接 400（它是前端分组覆盖与卡片锚点的键）
- 语义：**出厂值 `data.js` + 运行时覆盖 `portal_catalog.json`** 两层，与 uniplam 的
  `INITIAL_DASHBOARDS` + `portal-default.json` 完全同构；`DELETE` 即回滚出厂
- 改完要**重启 7038**：杀 uvicorn 子进程即可，`backend_watchdog`（父进程）会自动拉起（实测 8 秒）
- 前端消费方：`MsPortal/assets/portal.js` 的 `loadCatalog()` / `saveCatalog()` / `resetCatalog()`
  —— ⚠️ 那里**只能用 `renderCatalog()`，不能调 `render()`**（`render()` 会重建 `#secTopo`，
  把 4 个地图 iframe 全部重载），原因与验证见 `D:\01_RPA\liberia-noc_soc-数据看板统一门户\TMP\verify_board_edit.cjs` 与技能 `msportal-ref-and-map-embed`
