# my_app User Help & Guide

> User-facing platform features & operations guide. Generated from the same source as the in-app Help page (frontend/src/helpMarkdown.ts), compiled from docs/manual/ and backend/task_registry.py. Generated on 2026-09-30.

> In-app entry: the "Help" sidebar item, or `http://<host>/myapp/?page=help` directly.

---

## Contents

- [1. Platform Overview](#1-platform-overview)
- [2. General Usage](#2-general-usage)
- [3. Task Manager Deep Dive (68 tasks)](#3-task-manager-deep-dive)
- [4. Pages Guide](#4-pages-guide)
- [5. Ops & Troubleshooting](#5-ops-troubleshooting)
- [6. FAQ](#6-faq)

## 1. Platform Overview

An automation platform for network operations: scheduled jobs collect & sync data from upstream systems (eFlow, various NMS — RAN/iPRAN/CNN/MW UME & CN EMS, FineBI, FTP, mailboxes), store it centrally, and present it as dashboards, tables and reports.

Typical pipeline: scheduled collection → central storage (PostgreSQL main DB + per-task SQLite files) → dashboards / Excel reports & email, WhatsApp delivery → alarm & ticket analysis.

Built for the NOC scenario "boards every day, reports must go out": 41+ scheduled tasks, 20+ pages, auto-retry & missed-run backfill, watchdog-based process self-healing.

**What it does**

- 41+ scheduled tasks drive collection & report delivery (registered in backend/task_registry.py)
- All pages in one SPA, Chinese/English switchable, board metrics click-to-drill-down
- Generic table powers: browse any table, column profiles, Excel/CSV import & export, view templates
- Auto backfill: failed-task retry & missed-run backfill; process self-healing: watchdogs + heartbeat force-restart

**What it does NOT do (boundaries)**

- No multi-user system: no signup/roles/audit — anyone reaching the entry has full control
- No HTTPS out of the box: TLS must be terminated by a front nginx; upstream TLS verification is off by default
- No data editing: data is "collected read-only"; pages cannot write back to upstreams (only credentials/recipients/schedules are configurable)
- Not highly available: a single-instance lock (db/instance.lock) allows only one copy per machine; no clustering/failover

---

## 2. General Usage

| Operation | Description |
| --- | --- |
| Sidebar navigation | The sidebar is collapsed by default — click the ☰ button (top-left) to expand/collapse; on mobile it slides out as a drawer under the header. |
| Open in a new tab | Right-click any menu item → "Open in new tab", handy for wall screens / multi-monitor duty. |
| Direct links | Every page can be opened with ?page=<key>, e.g. /myapp/?page=battery — bookmarkable and shareable. |
| Auto refresh | Pick an interval in the header (default 5 minutes; 0/30s~30min available). While you are typing, a dialog is open, or the tab is in the background, the round is skipped to avoid interrupting you. |
| Theme & language | Switch dark/light theme and Chinese/English in the top-right; preferences are remembered locally (localStorage). |
| Data freshness | Some pages show a "last synced" time in the header. Boards are fed by scheduled tasks with different frequencies (alarms every 30 min, microwave topology daily 05:15, packet loss daily 06:30...). See "Task Manager Deep Dive" for the full catalog. |

---

## 3. Task Manager Deep Dive

### 3.1 Lifecycle of a task

**① Schedule fires** APScheduler fires inside the backend process per cron (backend/task_runner.py). Default crons live in TASK_SPECS (task_registry.py); the effective schedule is read from the task_schedule_config table — so editing it on the page takes effect immediately and survives restarts.

**② Enqueue** enqueue_task() writes one pending row into the task_queue table (main DB).

**③ Worker claim** The group's worker atomically claims the row via UPDATE…RETURNING (backend/worker.py). Without MY_APP_TASK_QUEUE=1 tasks fall back to in-process threads.

**④ Run** run_task() invokes the real service function (each TASK_SPECS entry declares func or a lazy loader tuple). Throwing an exception marks the task failed — never swallow exceptions in business code.

**⑤ Finish** _finish() writes the final state and an execution history row into task_execution_log (queue & logs kept 3 days). Failures notify via WeChat + email.

### 3.2 Worker groups: serial within, parallel across

| Group | Why grouped |
| --- | --- |
| **u** | RAN UME single-account session; tasks run serially (parallel runs kick the session) |
| **n** | NMS / eFlow API / remote systems: independent but conservatively grouped |
| **v** | VMAX portal (local 8790 single-session proxy): the three tasks share one session and must serialize; split out of group n on 2026-09-18 so long tasks no longer block them |
| **m** | Housekeeping tasks: EWS mail session + screenshot/WhatsApp file dependencies |
| **c** | CN EMS dedicated session: cache sync & daily aggregation share _pmcache, serialized for mutual exclusion |

> ⚠️ **New tasks MUST also be registered in `GROUP_TASK_MAP` in worker_watchdog.py** — declaring them only in TASK_SPECS leaves them pending forever. This accident happened four times (finebi_report_sync / whatsapp_send_ext / sp_email_details / the olib_soc and vmax_multi_data_sync tasks found on 2026-09-18).

### 3.3 Full task catalog (68 tasks)

| Task | task_id | Default cron | Group | Workflow script |
| --- | --- | --- | --- | --- |
| eFlow Data Sync | `eflow_sync` | `22 * * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")` |
| eFlow Daily Full Sync | `eflow_sync_full` | `0 1 * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")` |
| RAN UME Daily Report | `ran_ume_daily` | `0 2 * * *` | u | `services/ran_ume_service.py → run_ran_ume_full_task` |
| Site Outage Screenshot | `site_outage_screenshot` | `0 1 * * *` | m | `services/site_outage_service.py → run_site_outage_screenshot` |
| WhatsApp Message Send | `whatsapp_send` | `0 3 * * *` | m | `services/whatsapp_service.py → run_whatsapp_send` |
| WhatsApp Message Send (Extension) | `whatsapp_send_ext` | `0 3 * * *` | m | `services/whatsapp_ext_service.py → run_whatsapp_send_ext` |
| eFlow P1 Alarm WhatsApp Push | `tt_alarm_whatsapp_alert` | `*/15 * * * *` | m | `services/tt_alarm_whatsapp_service.py → run_tt_alarm_whatsapp_alert` |
| MS SLA Full Sync | `ms_sla_full` | `0 */6 * * *` | n | `services/ms_sla_service.py → run_full_sync` |
| eFlow Realtime Alarm Sync | `eflow_active_alarm` | `*/30 * * * *` | n | `services/eflow_api_client.py → fetch_and_save_active_alarm` |
| eFlow History Alarm Sync | `eflow_history_alarm` | `0 */3 * * *` | n | `services/eflow_api_client.py → fetch_and_save_history_alarm` |
| eFlow TT Rules Collect & Match Check | `eflow_tt_rules_check` | `20 4 * * *` | n | `services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check` |
| RAN Main KPI Sync | `main_kpi_sync` | `0 4 * * *` | u | `services/ran_ume_main_kpi.py → run_main_kpi_sync` |
| RAN Cell Availability 1-Day Sync | `cell_availability_sync` | `30 4 * * *` | u | `services/ran_cell_availability_sync.py → run_cell_availability_sync` |
| RAN Cells KPI Sync | `cells_kpi_sync` | `50 4 * * *` | u | `services/ran_cells_kpi_sync.py → run_cells_kpi_sync` |
| RAN Network KPI Sync | `network_kpi_sync` | `0 5 * * *` | u | `services/ran_ume_network_kpi.py → run_network_kpi_sync` |
| Availability Recon Rebuild | `avail_recon_sync` | `10 6 * * *` | u | `services/avail_recon_sync.py → run_avail_recon_sync` |
| BP Cells Report Sync | `bp_report_sync` | `20 6 * * *` | u | `services/bp_report_sync.py → run_bp_report_sync` |
| CNN UME KPI Sync | `cnn_kpi_sync` | `0 6 * * *` | n | `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync` |
| SP Spare Data Sync | `sp_data_sync` | `10 * * * *` | s | `services/get_sp_table.py → run_sp_data_sync` |
| iPRAN UME KPI Sync | `ipran_kpi_sync` | `0 8 * * *` | u | `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync` |
| Liberia Site-Down 1H Report Email | `liberia_email_1h` | `5 * * * *` | m | `services/liberia_email_report.py → run_1h_report` |
| Liberia Site-Down 8H Report Email | `liberia_email_8h` | `10 */8 * * *` | m | `services/liberia_email_report.py → run_8h_report` |
| MS Contract KPIs Daily Report Email | `kpi_ms_contract` | `30 17 * * *` | m | `services/kpi_email_report.py → run_ms_contract_kpi` |
| MS WOs SLA Daily Report Email | `kpi_ms_wo_sla` | `35 17 * * *` | m | `services/kpi_email_report.py → run_ms_wo_sla` |
| SpareParts Report Email | `kpi_sp_spareparts` | `45 9 * * *` | m | `services/kpi_email_report.py → run_sp_spareparts` |
| Comsumables Report Email | `kpi_sp_consumables` | `50 9 * * *` | m | `services/kpi_email_report.py → run_sp_consumables` |
| SP Report Generate | `sp_report_generate` | `15 5 * * *` | m | `services/kpi_email_report.py → run_sp_report_generate` |
| SP Spare Parts Details Report Email | `sp_email_details` | `0 7 * * *` | m | `services/kpi_email_report.py → run_sp_details_email` |
| SP Spare Parts Details Files Email | `sp_details_files_email` | `5 10 * * *` | m | `services/kpi_email_report.py → run_sp_details_files_email` |
| Comsumables&SpareParts Report Whatsapp | `sp_whatsapp_report` | `15 7 * * *` | m | `services/kpi_email_report.py → run_sp_whatsapp_report` |
| SP Material Stock & Consumption Report Email | `sp_material_report` | `33 7 * * *` | m | `services/kpi_email_report.py → run_sp_material_stock_consumption` |
| MS Network Availability Daily Report Email | `kpi_ran_availability` | `30 9 * * *` | m | `services/kpi_email_report.py → run_ran_availability` |
| Email Recovery after EWS Restored | `email_recovery` | `*/20 * * * *` | m | `services/email_recovery.py → run_email_recovery_task` |
| Packet Loss Sync | `packet_loss_sync` | `30 6 * * *` | u | `services/packet_loss_service.py → run_packet_loss_sync` |
| Packet Loss Daily Report Email | `packet_loss_email` | `45 6 * * *` | u | `services/kpi_email_report.py → run_packet_loss_email` |
| IP RAN M6K-FW Chart Email | `ipran_m6k_chart_email` | `45 6 * * *` | m | `services/ipran_chart_service.py → run_ipran_m6k_chart_email` |
| CNN Free Rating Chart Email | `ccn_free_rating_chart_email` | `45 7 * * *` | m | `services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email` |
| FW Throughput KPI Sync + Chart Email | `fw_kpi_sync` | `15 7 * * *` | n | `services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync` |
| Battery KPI Sync | `battery_kpi_sync` | `5 * * * *` | u | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync` |
| Battery KPI Email | `battery_email` | `0 7,19 * * *` | m | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email` |
| Mailbox Storage Guard | `mailbox_cleanup` | `0 * * * *` | m | `services/mailbox_cleanup.py → run_mailbox_cleanup` |
| Incident Overview Data Sync | `incident_overview_sync` | `0 * * * *` | m | `services/incident_overview_sync.py → run_incident_overview_sync` |
| FineBI Report Files Sync | `finebi_report_sync` | `10 * * * *` | m | `services/finebi_report_sync.py → run_finebi_report_sync` |
| DB Data Freshness Check | `db_freshness_check` | `15 * * * *` | m | `services/db_freshness_check.py → run_db_freshness_check` |
| MTTR/TT Wide Table Rebuild | `mttr_tt_sync` | `40 7 * * *` | m | `services/mttr_tt_sync.py → run_mttr_tt_sync` |
| Progress Wide Table Rebuild | `progress_sync` | `50 7 * * *` | m | `services/progress_sync.py → run_progress_sync` |
| Failed Task Auto Retry | `auto_retry_failed` | `*/10 * * * *` | m | `services/auto_retry.py → run_auto_retry_task` |
| RAN CM Cell Data Sync | `cm_data_sync` | `30 8 * * *` | u | `services/cm_data/cm_data_export.py → run_cm_data_sync` |
| PG→SQLite Data Snapshot | `pg_to_sqlite_sync` | `45 * * * *` | m | `backend/scripts/sync_pg_to_sqlite.py → main` |
| MW UME KPI Sync | `mw_ume_kpi_sync` | `15 5 * * *` | w | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync` |
| MW UME KPI Realtime Sync | `mw_ume_kpi_sync_rt` | `*/15 * * * *` | w | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt` |
| CN EMS KPI Cache Sync | `ems_kpi_cache_sync` | `*/15 * * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync` |
| CN EMS KPI Daily CSV | `ems_kpi_daily` | `20 0 * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily` |
| CXO Dashboard Cache Sync | `cxo_dashboard_cache_sync` | `*/10 * * * *` | v | `services/cxo_dashboard_cache.py → run_cxo_dashboard_cache_sync` |
| VMAX CXO Daily Value Archive | `vmax_cxo_daily_sync` | `15 * * * *` | v | `services/vmax_cxo_daily_cache.py → run_vmax_cxo_daily_sync` |
| VMAX Multi-Report KPI Collect | `vmax_multi_data_sync` | `45 * * * *` | v | `services/vmax_multi_data/vmax_multi_data_service.py → run_vmax_multi_data_sync` |
| OLIB SOC Dashboard KPI Sync | `olib_soc_kpi_daily_sync` | `20 6 * * *` | m | `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_kpi_sync` |
| OLIB SOC VMAX Routine Report | `olib_soc_vmax_report` | `30 7 1 * *` | m | `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_report` |
| Customer Service KPI Sync | `ume_in_kpi_sync` | `45 5 * * *` | n | `services/ume_in/ume_in_kpi_service.py → run_ume_in_kpi_sync` |
| Customer Service KPI + OSG Weekly Report Email | `ume_in_osg_report` | `30 6 * * *` | n | `services/ume_in/osg_report_task.py → run_ume_in_osg_report（内部依次调 ume_in_kpi_service + t_osg_build.py）` |
| SP Online Ticket Sync | `sp_online_sync` | `35 * * * *` | n | `services/sp_online_sync.py → run_sp_online_sync` |
| SP Material Master Sync | `sp_material_sync` | `55 4 * * *` | n | `services/sp_material_sync.py → run_sp_material_sync` |
| SP Online Open Tickets Report Generate | `sp_online_report_generate` | `0 6 * * *` | m | `services/kpi_email_report.py → run_sp_online_report_generate` |
| SP Online Open Tickets Report Send | `sp_online_report_send` | `20 6 * * *` | m | `services/kpi_email_report.py → run_sp_online_report` |
| eFlow Alarm Rules Collect | `eflow_alarm_rules_collect` | `59 23 */3 * *` | n | `services/eflow_rules/eflow_Alarm_Rule_Collector.py → run_eflow_alarm_rules` |
| eFlow Push Rules Collect | `eflow_push_rules_collect` | `59 23 */3 * *` | n | `services/eflow_rules/eflow_Push_Rule_Collector.py → run_eflow_push_rules` |
| Log Files Cleanup | `log_cleanup` | `17 3 * * *` | m | `services/log_cleanup.py → run_log_cleanup` |
| TMP Directory Cleanup | `tmp_cleanup` | `47 3 * * *` | m | `services/tmp_cleanup.py → run_tmp_cleanup` |

Workflow & maintenance notes per task:

#### eFlow Data Sync（`eflow_sync`）

- Default cron: `22 * * * *`　|　worker group: **n**
- Workflow script: `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")`

**What it does**: Incrementally sync TT/WO/CR/PM/Site/Person from the ZTE eFlow API

**Workflow & data flow**:

1. Hourly :22 pull delta TT/WO/CR/PM/Site/Person from eFlow API
1. Clean and write into dynamic eFlow tables in the main DB (runtime-created, not in Alembic)
1. Feeds TT&WO / alarms / GIS / eFlow knowledge base pages

**Maintenance**:

- Delta mode only fetches changes; gaps are backfilled next night by eflow_sync_full
- Credential group eflow; kicked sessions cause consecutive failures, auto-retried by auto_retry_failed

#### eFlow Daily Full Sync（`eflow_sync_full`）

- Default cron: `0 1 * * *`　|　worker group: **n**
- Workflow script: `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")`

**What it does**: Full-window backfill (default since 2026-01-01) to cover delta gaps and refresh reports

**Workflow & data flow**:

1. Daily 01:00 pull the full window
1. Write into the same dynamic tables with dedup
1. Refresh related report artifacts afterwards

**Maintenance**:

- First remedy when eFlow data is missing mid-day — run it manually from Task Manager
- The window start is configurable; mind the fetch duration when adjusting

#### RAN UME Daily Report（`ran_ume_daily`）

- Default cron: `0 2 * * *`　|　worker group: **u**
- Workflow script: `services/ran_ume_service.py → run_ran_ume_full_task`

**What it does**: Fetch RAN UME PM data, generate the Daily Availability KPI report, upload via FTP

**Workflow & data flow**:

1. RSA-encrypted login to RAN UME NMS, query PM data
1. Generate the Daily Availability KPI report
1. Upload the report via FTP for later mail/board consumption

**Maintenance**:

- Credential group zte_ume; serial within group u — a stuck predecessor delays this task
- Query templates and days_back live in services/ran_ume_config.json

#### Site Outage Screenshot（`site_outage_screenshot`）

- Default cron: `0 1 * * *`　|　worker group: **m**
- Workflow script: `services/site_outage_service.py → run_site_outage_screenshot`

**What it does**: Auto-screenshot the ERA/Regular/ALL views of the Site Outage Monitor board

**Workflow & data flow**:

1. Playwright opens the Alarm Management board
1. Screenshots each of ERA / Regular / ALL views to disk
1. Output is consumed by whatsapp_send at 03:00

**Maintenance**:

- Screenshots the iframe page alarm-management.html — before changing its DOM, verify the screenshot selectors still resolve
- Shares group m with whatsapp_send; ordering is guaranteed by cron times (01:00 → 03:00)

#### WhatsApp Message Send（`whatsapp_send`）

- Default cron: `0 3 * * *`　|　worker group: **m**
- Workflow script: `services/whatsapp_service.py → run_whatsapp_send`

**What it does**: Send Site Outage screenshots and files to WhatsApp groups (Playwright automation)

**Workflow & data flow**:

1. Reads screenshots produced by site_outage_screenshot at 01:00
1. Drives WhatsApp Web via Playwright to send to groups

**Maintenance**:

- Depends on the screenshot task finishing first; re-scan QR manually when the WhatsApp Web session expires

#### WhatsApp Message Send (Extension)（`whatsapp_send_ext`）

- Default cron: `0 3 * * *`　|　worker group: **m**
- Workflow script: `services/whatsapp_ext_service.py → run_whatsapp_send_ext`

**What it does**: Extension-based WhatsApp sending: dispatches a send job; a browser extension sends it in the logged-in WhatsApp Web (coexists with the Playwright version)

**Workflow & data flow**:

1. Dispatch a send job to the queue
1. The browser extension (whatsapp_sender_extension) actually sends it in the logged-in WhatsApp Web tab

**Maintenance**:

- Missed its worker-group registration on 2026-08-31 and stuck pending; now in group m — always register new tasks in GROUP_TASK_MAP

#### eFlow P1 Alarm WhatsApp Push（`tt_alarm_whatsapp_alert`）

- Default cron: `*/15 * * * *`　|　worker group: **m**
- Workflow script: `services/tt_alarm_whatsapp_service.py → run_tt_alarm_whatsapp_alert`

**What it does**: Every 15 min, pick P1 TTs from the last 3h that are still uncleared and not alarm_code 99933, render them as WhatsApp text, and record send status

**Workflow & data flow**:

1. Query eflow_tt for the last 3h with empty alarm_clear_time and ticket_severity=P1 (99933 excluded)
1. Compare against eflow_tt_whatsapp_alert_log and keep rows past the 20-minute re-push throttle
1. Render 6 lines of text and dispatch a job to data/tt_alert_job.json for the browser extension
1. On the extension's confirmation, set the row send_status to Y (otherwise stays N with last_error)

**Maintenance**:

- Groups come from the TT_ALERT_WHATSAPP_GROUPS env var; refuses to send when unset (never falls back to a test group)
- The 99933 exclusion must stay in Python — the DB holds both '99933' and '99933.0', so a SQL predicate misses rows
- Depends on the extension's text-sending capability; status stays N until confirmed (never fakes Y)
- ⚠️ Measured: uncleared P1 rows are mostly legacy, so 0 messages per run is the normal case

#### MS SLA Full Sync（`ms_sla_full`）

- Default cron: `0 */6 * * *`　|　worker group: **n**
- Workflow script: `services/ms_sla_service.py → run_full_sync`

**What it does**: SLA metrics sync + Contract KPIs report update (self-contained, no external files)

**Workflow & data flow**:

1. Every 6h recompute NUR/SLA/WO metrics via the live nur_calc logic
1. Write to data/ms_sla/ms_sla_dashboard.sqlite3
1. Feeds the MS SLA board and two daily report emails

**Maintenance**:

- Board numbers follow this live calculation (snapshot files may differ)
- Adjust criteria in backend/services/nur_calc.py

#### eFlow Realtime Alarm Sync（`eflow_active_alarm`）

- Default cron: `*/30 * * * *`　|　worker group: **n**
- Workflow script: `services/eflow_api_client.py → fetch_and_save_active_alarm`

**What it does**: Fetch realtime alarms from eFlow FM Active API, save to CSV + SQLite

**Workflow & data flow**:

1. Pull FM Active alarms every 30 min
1. Dual-write app.db realtime_alarm and an eflow.sqlite3 copy (report-only)
1. Feeds the realtime alarm board / realtime map / alarm management board

**Maintenance**:

- Pages read app.db only; "realtime" means 30-minute granularity, not second-level push
- Field mapping lives in services/eflow_alarm_config.json

#### eFlow History Alarm Sync（`eflow_history_alarm`）

- Default cron: `0 */3 * * *`　|　worker group: **n**
- Workflow script: `services/eflow_api_client.py → fetch_and_save_history_alarm`

**What it does**: Fetch last-7-day history alarms from eFlow FM History API, filter by TT ID, save to CSV + SQLite

**Workflow & data flow**:

1. Pull last 7 days of FM History alarms every 3h
1. Keep only TT-associated records into history_alarm

**Maintenance**:

- The 7-day window is fixed; older history must be queried from retained DB data

#### eFlow TT Rules Collect & Match Check（`eflow_tt_rules_check`）

- Default cron: `20 4 * * *`　|　worker group: **n**
- Workflow script: `services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check`

**What it does**: Daily 04:20: collect active TT Update Severity Rules from eFlow, then match the latest 1000 eflow_tt records and produce severity corrections

**Workflow & data flow**:

1. Fetch rules and regenerate eflow_TT_rules.xlsx (the authoritative rule sheet)
1. Match the latest 1000 eflow_tt records and correct severities
1. Rules/corrections/report saved for download on the Task Report Files page

**Maintenance**:

- The authoritative rule sheet is backend/services/eflow_rules/eflow_TT_rules.xlsx — the root-level copy is a draft, editing it has no effect
- The eFlow tab on the Task Report Files page supports "Run Now" to trigger manually

#### RAN Main KPI Sync（`main_kpi_sync`）

- Default cron: `0 4 * * *`　|　worker group: **u**
- Workflow script: `services/ran_ume_main_kpi.py → run_main_kpi_sync`

**What it does**: RAN UME Main KPI history sync (2G/3G/4G × Cells/Sites/Group/NW), export Excel + incremental SQLite update + FTP upload

**Workflow & data flow**:

1. Log into RAN UME, query Main KPI history per 2G/3G/4G templates
1. Export Excel, incrementally update SQLite, FTP upload

**Maintenance**:

- Templates & days_back in services/main_kpi_config.json
- Serial in group u at 04:00 — a stuck 02:00 daily task delays it

#### RAN Cell Availability 1-Day Sync（`cell_availability_sync`）

- Default cron: `30 4 * * *`　|　worker group: **u**
- Workflow script: `services/ran_cell_availability_sync.py → run_cell_availability_sync`

**What it does**: RAN UME cell availability daily KPI sync (FDD/UMTS/GSM/TDD templates), writes ran_kpi_avalability_1day.sqlite3 + FTP upload

**Workflow & data flow**:

1. Query daily cell availability KPI via 4 templates (FDD/UMTS/GSM/TDD)
1. Write data/ran_kpi_avalability_1day.sqlite3
1. FTP upload to the remote host

**Maintenance**:

- The misspelling "avalability" in the DB filename is historical and string-referenced — do NOT rename

#### RAN Cells KPI Sync（`cells_kpi_sync`）

- Default cron: `50 4 * * *`　|　worker group: **u**
- Workflow script: `services/ran_cells_kpi_sync.py → run_cells_kpi_sync`

**What it does**: Daily RAN UME cell data sync (2G/3G/4G), aggregate Cells KPI (target 99.65%) into ran_cells_kpi.sqlite3, current month only

**Workflow & data flow**:

1. Reuse the availability sync UME fetch to pull GSM/UMTS/FDD cell data
1. Derive per-cell availability and count meeting/below/blank
1. Materialize into data/ran_cells_kpi.sqlite3 (table cells_kpi_daily, current month only)

**Maintenance**:

- Definitions live at the top of services/ran_cells_kpi_service.py; 2G uses channel ratio, 3G/4G use service time / 86400
- The RAN Cells KPI dashboard reads the materialized DB first, falling back to live aggregation of ran_kpi_avalability_1day.sqlite3

#### RAN Network KPI Sync（`network_kpi_sync`）

- Default cron: `0 5 * * *`　|　worker group: **u**
- Workflow script: `services/ran_ume_network_kpi.py → run_network_kpi_sync`

**What it does**: RAN UME Network KPI (Zeenshan) history sync (2G/3G/4G × Group/NW), export Excel + SQLite import + FTP upload

**Workflow & data flow**:

1. Log into RAN UME (Zeenshan), query Network KPI history by Group/NW
1. Export Excel, import into SQLite, FTP upload

**Maintenance**:

- Query templates in services/network_kpi_config.json

#### Availability Recon Rebuild（`avail_recon_sync`）

- Default cron: `10 6 * * *`　|　worker group: **u**
- Workflow script: `services/avail_recon_sync.py → run_avail_recon_sync`

**What it does**: Rebuild the avail_recon availability reconciliation table (approx. aggregate of remote Site_Daily x Master_Site_Database region) into local data/avail_recon.sqlite3 for the Daily Availability KPI / Availability(TT) boards

**Workflow & data flow**:

1. Read site master data from remote olbr_ms_master_database (Site_Name -> Region)
1. Inline each region's site list into SQL and aggregate AVG(availability) of 2G/3G/4G_Main_Kpi_Site_Daily remotely
1. Atomically replace local data/avail_recon.sqlite3 (table availability_daily)

**Maintenance**:

- Definitions live at the top of services/avail_recon_sync.py: Cell_Availability=AVG(rate), NOT the share of sites meeting the target (v1 got this wrong, range 40-100%)
- The board resolves avail_recon.sqlite3 to the local file via dashboard_service.DB_ALIASES; register new derived DBs the same way
- Before 2026-09-21 this table was maintained by a manual ETL in the retired my-finebi project; with no scheduler it froze at 2026-09-13 and the board went silently stale

#### BP Cells Report Sync（`bp_report_sync`）

- Default cron: `20 6 * * *`　|　worker group: **u**
- Workflow script: `services/bp_report_sync.py → run_bp_report_sync`

**What it does**: Read per-cell 4G PRB/throughput/traffic plus hourly active users from RAN_UME, recompute Bad Performance cells by the umlaut busy-hour caliber (daily/weekly/monthly), refresh local data/bp_report.sqlite3 and reconcile against the Excel ground truth

**Workflow & data flow**:

1. Read PRB utilization / DL IP throughput / DL+UL traffic from remote 4G_Main_Kpi_Cell_Daily one day per SQL (avoids hitting the remote 50k row cap and being silently truncated)
1. Fetch Average DL Active User Number together with the same hour's PRB/throughput over a dedicated hourly channel (that metric is unavailable at daily grain) and aggregate the day's three values from the hour with the highest active users
1. Join bp_cell_dict to attach Cluster/Layer (RAN_UME has no such dimension; the dictionary comes from the Excel BP Cells List sheet)
1. Recompute per-cell daily is_bp and the daily/weekly/monthly rollups (weekly 4/7 days, monthly 3/4 full weeks); weekly/monthly are INSERT-only (new periods only, existing Excel rows untouched), while the verdict columns are filled in separately by backfill_period_verdicts
1. Reconcile day by day against the Excel bp_cells_excel values; store differences and caliber notes in bp_sync_meta

**Maintenance**:

- The single source of truth for the caliber is services/bp_caliber.py: daily (busy-hour three values), weekly 4/7, monthly 3/4
- WARNING: Average DL Active User Number is available ONLY at hourly granularity. At daily grain UME returns HTTP 200 with a valid queryid but SILENTLY DROPS that column and raises no error, hence the dedicated channel in services/bp_active_user.py (C373384373 + 1638004469342 + 1638004469332). When it cannot be fetched the day stays is_bp=NULL (undecidable) and is NEVER counted as 0
- WARNING: UME returns numeric values as strings and PRB carries a percent sign (e.g. "2.46%"), so strip the % and divide by 100; also itemsposition must be all zeros -- using [0,1,2] makes UME reject the query with 0001619999
- WARNING: PRB utilization is a FRACTION in the source table (0-1, observed max 0.9751), so the threshold is 0.80, not 80; using 80 makes the condition never fire and raises no error
- WARNING: the source column name "E-UTRAN\xa0FDD\xa0Cell Name" uses NO-BREAK SPACEs; with plain spaces SQLite does not error but treats the double-quoted identifier as a string literal, turning the whole column into its own name text (bp_caliber.assert_columns_exist / assert_no_literal_fallback guard exactly this)
- The Excel BP Cells List sheet holds only 53 rows for its final day (2026-09-26) versus a true 486, i.e. an incomplete export; do not treat that day's difference as an implementation defect
- WARNING: weekly/monthly recomputation MUST be INSERT-only (skip a period that already exists). An earlier version aggregated a whole month with ON CONFLICT DO UPDATE and overwrote the Excel rows for 2026-W39/W40/2026-09 with bp_cells=0. Never touch the metric ground truth of existing Excel rows; when a verdict column is NULL, backfill_period_verdicts fills it in separately
- WARNING: week_days_in_month yields only 3 full weeks for 2026-09 while MONTH_TOTAL_WEEKS=4, so is_bp_month is permanently NULL for that month (a caliber-vs-calendar mismatch, not missing data); the UI shows the cause instead of a bare "Undecidable"

#### CNN UME KPI Sync（`cnn_kpi_sync`）

- Default cron: `0 6 * * *`　|　worker group: **n**
- Workflow script: `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync`

**What it does**: CNN UME core-network KPI sync (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating), API write to DB CNN

**Workflow & data flow**:

1. Log into CNN UME, query core KPIs (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating)
1. Write to remote DB CNN via API

**Maintenance**:

- Free Rating output also feeds the ccn_free_rating_chart_email charts

#### SP Spare Data Sync（`sp_data_sync`）

- Default cron: `10 * * * *`　|　worker group: **s**
- Workflow script: `services/get_sp_table.py → run_sp_data_sync`

**What it does**: Pull 5 spare-part reports from SFTP (Inbound/Outbound/Inventory/OC Rule/Transfer) into app.db, then mirror into FineBI WareHouseDashBoard inventory.db

**Workflow & data flow**:

1. Log into the spare-parts SFTP (credential group sftp_sp)
1. Fetch the 5 reports
1. Clean and write into the main DB for the warehouse board and SP reports
1. After all tables are stored, mirror into the FineBI inventory.db (UNC path; full replace for normal tables, append-only for Inventory)
1. Finally prune Inventory snapshots older than the retention window (same policy for app.db and the mirror, default 180 days)

**Maintenance**:

- The warehouse board iframe reads exactly this data — if reports are missing, check this task first
- Mirror failures are reported in the task message without affecting app.db; path/toggle in Settings → Task Config (mirror_db_path / mirror_enabled)
- inventory_details is append-only and bounded by retention: Settings → Task Config, inventory_retention_days (default 180). The cutoff is based on the newest update_date in the table, so an upstream outage never wipes the table
- The warehouse board's "Inventory Quantity Trend" reads every date in this table (no date filter = full history), so lowering the retention window directly shortens the trend chart
- Since 2026-09-20 this runs hourly at :10 instead of daily 07:00: the upstream SFTP already exports every hour at :00:03, and the MsPortal QC panel's SPMS card reads the inband_details/outband_details this task writes — a daily sync left that number up to 24h stale. :10 avoids eflow_sync (:00) and sp_online_sync (:35) in the same worker group
- A run is lengthened by the trailing FineBI mirror (UNC inventory.db occasionally reports "database is locked"; observed 1-9 min). The queue has single-flight protection, so an unfinished run makes the next trigger skip — no pile-up, but that hour keeps the old data. If other QC metrics (TT/WO/CR/PMT) slow down too, check whether this task is occupying the group-n worker

#### iPRAN UME KPI Sync（`ipran_kpi_sync`）

- Default cron: `0 8 * * *`　|　worker group: **u**
- Workflow script: `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync`

**What it does**: iPRAN UME M6000 router KPI sync (HQ M6K-FW etc.), export Excel + SQLite import + FTP upload

**Workflow & data flow**:

1. Log into iPRAN UME, query M6000 router KPIs
1. Export Excel, write data/ipran_ume/ipran_ume_kpi.sqlite3, FTP upload

**Maintenance**:

- Output also feeds ipran_m6k_chart_email (06:45); runs at 08:00 within group u

#### Liberia Site-Down 1H Report Email（`liberia_email_1h`）

- Default cron: `5 * * * *`　|　worker group: **m**
- Workflow script: `services/liberia_email_report.py → run_1h_report`

**What it does**: Email the Liberia Orange Site Down hourly Report (inline charts + Excel) to recipient lists

**Workflow & data flow**:

1. Hourly :05 aggregate the last hour of site-down data
1. Build the inline-chart + Excel report
1. Send to the to/cc lists (managed in Settings)

**Maintenance**:

- When EWS is down, email_recovery (every 20 min) re-sends automatically once restored

#### Liberia Site-Down 8H Report Email（`liberia_email_8h`）

- Default cron: `10 */8 * * *`　|　worker group: **m**
- Workflow script: `services/liberia_email_report.py → run_8h_report`

**What it does**: Email the Liberia Orange Site Down 8-hour Report (inline charts + Excel) to recipient lists

**Workflow & data flow**:

1. Every 8 hours (:10 of 00/08/16) aggregate site-down data
1. Build and send the inline-chart + Excel report

**Maintenance**:

- Same script as the 1H version, different entry; recipient changes apply to both

#### MS Contract KPIs Daily Report Email（`kpi_ms_contract`）

- Default cron: `30 17 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_ms_contract_kpi`

**What it does**: Email the MS Contract KPIs Achievements Daily Report (local data + remote recipient list)

**Workflow & data flow**:

1. Read local ms_sla data produced by ms_sla_full (every 6h)
1. Build the Contract KPIs daily report
1. Send to recipients from the remote list

**Maintenance**:

- Data comes from ms_sla_full; the 17:30 send uses the 16:00 sync round

#### MS WOs SLA Daily Report Email（`kpi_ms_wo_sla`）

- Default cron: `35 17 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_ms_wo_sla`

**What it does**: Email the MS WOs SLA Achievements Daily Report (local data + remote recipient list)

**Workflow & data flow**:

1. Read local ms_sla data
1. Build and send the WOs SLA daily report to the remote list

**Maintenance**:

- Same script as kpi_ms_contract with a different entry; 5 minutes apart to avoid overlap

#### SpareParts Report Email（`kpi_sp_spareparts`）

- Default cron: `45 9 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_spareparts`

**What it does**: Email the SpareParts report (local sp_email data + remote shared recipient list)

**Workflow & data flow**:

1. Read reports generated into data/sp_email by sp_report_generate (05:15)
1. Send the SpareParts report to the remote shared list

**Maintenance**:

- Missing report files mean the 05:15 generation failed — fix upstream first, then re-run this task

#### Comsumables Report Email（`kpi_sp_consumables`）

- Default cron: `50 9 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_consumables`

**What it does**: Email the Comsumables (consumables) report (local sp_email data + remote shared list)

**Workflow & data flow**:

1. Read the consumables report generated under data/sp_email
1. Send to the remote shared list

**Maintenance**:

- The task name "Comsumables" is a historical misspelling referenced by the registry — do not rename

#### SP Report Generate（`sp_report_generate`）

- Default cron: `15 5 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_report_generate`

**What it does**: Download spare-part data from SFTP and generate Comsumables & SpareParts Inbound&Outbound&Inventory reports into data/sp_email

**Workflow & data flow**:

1. Log into SFTP and download raw spare data
1. Generate the Comsumables & SpareParts Inbound&Outbound&Inventory reports
1. Save to data/sp_email for the 09:45/09:50 email tasks and the 07:00 details email

**Maintenance**:

- Upstream of 3 SP email tasks — its failure blanks all spare-part emails for the day

#### SP Spare Parts Details Report Email（`sp_email_details`）

- Default cron: `0 7 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_details_email`

**What it does**: Merge the 4 spare-part detail files (inventory/inband/outband/transfer) under data/sp_email/data into one Excel (sheets: Inventory/Inbound/Outbound/Transfer) and email it; after the email, send the same Excel as a document to the WhatsApp group WH&SP Management

**Workflow & data flow**:

1. Merge the 4 *_details.xlsx (inventory/inband/outband/transfer) under data/sp_email/data into one workbook with a timestamped filename and subject
1. Send the email (default fixed recipients, overridable in Settings → Email Recipients)
1. After the email, send the same merged Excel as a document to the WhatsApp group WH&SP Management (added 2026-09-14)

**Maintenance**:

- Missed its worker-group registration on 2026-09-01 and stuck pending; now in group m — always register new tasks in GROUP_TASK_MAP
- This task is in EMAIL_TASK_IDS: on a WhatsApp-side failure the error carries only the WHATSAPP_FAIL marker, never the raw exception text — otherwise an EWS keyword would make email_recovery replay the whole chain and email the report twice to 11 recipients
- Upstream is sp_report_generate (05:15): without the detail files the merge fails and neither channel sends

#### SP Spare Parts Details Files Email（`sp_details_files_email`）

- Default cron: `5 10 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_details_files_email`

**What it does**: Daily 10:05: send the 6 spare-part detail files under data/sp_email/data to NOC as ONE EMAIL PER FILE, subject "Liberia OLR W.H <file name> <date time>"

**Workflow & data flow**:

1. Resolve each detail file: prefer the unfiltered *_source.xlsx raw snapshot (the SFTP snapshot sp_report_generate keeps at 05:15 before any filtering), falling back to the filtered *_details.xlsx
1. Check all 6 files up front: if any one is missing the whole run fails and NOTHING is sent (better no email at all than an incomplete set of reports)
1. Stage a copy of each under TMP using the OUTBOUND name (on disk they are inband/outband, recipients see inbound/outbound); the copies are removed after sending
1. Send one by one — each email carries exactly one attachment, subject "Liberia OLR W.H <attachment file name> <date time>" (e.g. Liberia OLR W.H inbound_details_source.xlsx 2026-09-30 10-05-00)
1. A single send failure does not stop the rest: the remaining files still go out, and the failures are reported by name so only those need a manual resend

**Maintenance**:

- Default To MS.NOC@zte.com.cn, Cc li.jing132@zte.com.cn / luo.wutao@zte.com.cn; overridable in Settings → Email Recipients, group sp_details_files
- Outbound file names differ from the on-disk source names (per user request): inband/outband become inbound/outbound, so attachments must be staged under the outbound name first (owa_mail_report uses Path(fp).name as the attachment name)
- Same data source as sp_email_details (05:00) but a different package: that one merges into a single multi-sheet workbook and posts to the WhatsApp group, this one sends one file per email to NOC — they do not affect each other
- One email per file means up to 6 EWS sessions per run, roughly 6x the duration of a single send; the task runs serially in group m, so a long run delays the other light tasks there
- On a single-send failure the error carries only the SEND_FAIL marker plus file names, never the raw exception text — otherwise an EWS keyword would make email_recovery resend all 6 and duplicate the ones that already went out; the details live in result.failed
- ocrule_details has no *_source snapshot and always uses the filtered version (hence no _source in its outbound name); that is expected, not a missing file
- Upstream is sp_report_generate (group m, 05:15): if detail files are missing, investigate that task rather than this one

#### Comsumables&SpareParts Report Whatsapp（`sp_whatsapp_report`）

- Default cron: `15 7 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_whatsapp_report`

**What it does**: Daily 07:15: send the same assets used by the Comsumables / SpareParts report emails (consolidated XLSX + report PNGs) to the WhatsApp group WH&SP Management

**Workflow & data flow**:

1. Pick the consolidated Comsumables / SpareParts XLSX under data/sp_email (excludes the " - Liberia" per-site files)
1. Collect the PNGs of both reports (main chart first, Summary-Changed last)
1. Send via the Playwright mechanism in whatsapp_service to the group WH&SP Management

**Maintenance**:

- Upstream is sp_report_generate (group m, 05:15) — if it fails this task finds no report files
- No email is sent here; emails are handled by kpi_sp_consumables / kpi_sp_spareparts

#### SP Material Stock & Consumption Report Email（`sp_material_report`）

- Default cron: `33 7 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_material_stock_consumption`

**What it does**: Daily 07:33: export the SP material stock & consumption summary (same scope as the page=sp_material page) to a UNIFIED_EXCEL_V1 Excel attachment plus an inline PNG of the same table, and email it

**Workflow & data flow**:

1. Call sp_material_summary_service.get_material_summary() (inventory_details daily snapshots + outband_details repair outbound)
1. Build a UNIFIED_EXCEL_V1 workbook (title / subtitle / two-row merged header / total row above the data / 13 columns + Info sheet), cell-for-cell identical to the page "Export Excel"
1. Draw the same summary table as a PNG with Pillow (same method as the SP report images: blue header + orange section bands + zebra rows)
1. Save to data/sp_material_report (keeps only the latest): the Excel as attachment, the PNG inlined in the body

**Maintenance**:

- Default 15 To + 2 Cc, overridable in Settings → Email Recipients
- Skips sending and reports failure when the summary has no data rows (usually the upstream SP data sync did not run)
- If PNG rendering fails it only warns and does not block the email — the Excel is still sent

#### MS Network Availability Daily Report Email（`kpi_ran_availability`）

- Default cron: `30 9 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_ran_availability`

**What it does**: Email the MS Network Availability Daily Report (remote FTP images + remote list, no Excel attachment)

**Workflow & data flow**:

1. Fetch availability images from remote FTP (produced & uploaded by ran_ume_daily at 02:00)
1. Assemble the report (no Excel) and send to the remote list

**Maintenance**:

- Missing images usually mean ran_ume_daily (group u, 02:00) failed — investigate that task instead

#### Email Recovery after EWS Restored（`email_recovery`）

- Default cron: `*/20 * * * *`　|　worker group: **m**
- Workflow script: `services/email_recovery.py → run_email_recovery_task`

**What it does**: Probes EWS every 20 minutes; once restored, re-sends email tasks that failed due to EWS timeouts in the last 3 hours

**Workflow & data flow**:

1. Probe Exchange (EWS) reachability
1. Scan email tasks failed by EWS timeout within the last 3h
1. Re-send them one by once EWS is back

**Maintenance**:

- For missing emails check this task's history first instead of manually re-running the original email task

#### Packet Loss Sync（`packet_loss_sync`）

- Default cron: `30 6 * * *`　|　worker group: **u**
- Workflow script: `services/packet_loss_service.py → run_packet_loss_sync`

**What it does**: Sync packet loss rate (SDR/IPRAN IPPD) from RAN UME into lte_pl.sqlite3 and generate the report; only the last 7 complete days are shown

**Workflow & data flow**:

1. Log into RAN UME and pull packet loss (SDR/IPRAN IPPD)
1. Compute STATUS (0-23 hourly flag blocks) and FINAL_STATUS five-level classification
1. Write data/packet_lost/lte_pl.sqlite3 (note the folder name) and generate the report

**Maintenance**:

- Criteria match the Packet_Loss automation Excel exactly; the unfinished current day is hidden
- The folder name packet_lost is historical — do not rename

#### Packet Loss Daily Report Email（`packet_loss_email`）

- Default cron: `45 6 * * *`　|　worker group: **u**
- Workflow script: `services/kpi_email_report.py → run_packet_loss_email`

**What it does**: Send the Packet Loss dashboard daily email (local screenshot + latest report xlsx + remote recipients) via the OWA account

**Workflow & data flow**:

1. Screenshot the packet-loss board + pick the latest report from the 06:30 sync
1. Send via OWA to the remote recipient list

**Maintenance**:

- Runs 06:45 right after the 06:30 sync (same group u, serialized — order guaranteed)

#### IP RAN M6K-FW Chart Email（`ipran_m6k_chart_email`）

- Default cron: `45 6 * * *`　|　worker group: **m**
- Workflow script: `services/ipran_chart_service.py → run_ipran_m6k_chart_email`

**What it does**: Query HQ_M6K_FW_bnctp_15mins from ipran_ume_kpi.sqlite3, generate 3 utilization line charts by ME+SmartGroup and email them

**Workflow & data flow**:

1. Query HQ_M6K_FW_bnctp_15mins in ipran_ume_kpi.sqlite3
1. Generate 3 utilization line charts by ME+SmartGroup
1. Send the chart email

**Maintenance**:

- Depends on the previous day's 08:00 ipran_kpi_sync; empty charts or failure follow u-group sync failures

#### CNN Free Rating Chart Email（`ccn_free_rating_chart_email`）

- Default cron: `45 7 * * *`　|　worker group: **m**
- Workflow script: `services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email`

**What it does**: Query FREE_RATING_GROUP_TEMPLATE_OSS_update_UME from db_ps_cs_cn.sqlite3, generate 4 bar charts by MO and email them

**Workflow & data flow**:

1. Query the FREE_RATING template table in db_ps_cs_cn.sqlite3
1. Generate 4 bar charts by MO and send

**Maintenance**:

- Data comes from cnn_kpi_sync (group n, daily 06:00) writing into DB CNN

#### FW Throughput KPI Sync + Chart Email（`fw_kpi_sync`）

- Default cron: `15 7 * * *`　|　worker group: **n**
- Workflow script: `services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync`

**What it does**: Fetch whole-device throughput from DPtech UMC, write to remote fw_db.sqlite via API, generate a 14-day chart and email it

**Workflow & data flow**:

1. Log into DPtech UMC (credential group fw_kpi), pull throughput
1. Write to remote fw_db.sqlite via API
1. Generate the 14-day throughput chart and send it

**Maintenance**:

- Sync, chart and email happen in one task — a failure stops the whole chain (DB write + email)

#### Battery KPI Sync（`battery_kpi_sync`）

- Default cron: `5 * * * *`　|　worker group: **u**
- Workflow script: `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync`

**What it does**: Fetch battery realtime KPI (health/SOC/charge status) from UME, in-memory only, write to battery_kpi.sqlite3 for the battery board

**Workflow & data flow**:

1. Hourly :05 log into UME and pull battery KPI
1. Process fully in memory (no intermediate files)
1. Write data/battery/battery_kpi.sqlite3

**Maintenance**:

- The battery board counts only readings ≤24h fresh by default (thresholds via BATT_FRESH_HOURS etc.)
- The module folder battary_kpi_fetch is a historical misspelling — do not rename

#### Battery KPI Email（`battery_email`）

- Default cron: `0 7,19 * * *`　|　worker group: **m**
- Workflow script: `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email`

**What it does**: Email the battery KPI report (Excel) to recipients from the remote list, daily at 07:00 & 19:00

**Workflow & data flow**:

1. Generate the Excel report from battery_kpi.sqlite3
1. Send to the remote recipient list (twice daily)

**Maintenance**:

- Same script as the sync task, different entry; recipients come from the remote FTP list

#### Mailbox Storage Guard（`mailbox_cleanup`）

- Default cron: `0 * * * *`　|　worker group: **m**
- Workflow script: `services/mailbox_cleanup.py → run_mailbox_cleanup`

**What it does**: Hourly Exchange mailbox guard: when count >500 AND usage >70%, hard-delete the 200 oldest emails to avoid the storage-limit warning

**Workflow & data flow**:

1. Hourly :00 inspect the Exchange mailbox (exchangelib/EWS)
1. Hard-delete the 200 oldest emails when count >500 and usage >70%

**Maintenance**:

- It deletes sent-mail history (including old report emails) — it is the guard keeping report delivery alive, do not disable

#### Incident Overview Data Sync（`incident_overview_sync`）

- Default cron: `0 * * * *`　|　worker group: **m**
- Workflow script: `services/incident_overview_sync.py → run_incident_overview_sync`

**What it does**: Hourly on-the-hour: pull the latest incident_overview.xlsx from all subfolders of FineBI FTP /webroot/WEB-INF/schedule/TT_WO/, stored as versioned files + a current.json pointer

**Workflow & data flow**:

1. Scan all TT_WO/ subfolders on FineBI FTP hourly
1. Save the latest incident_overview.xlsx as a versioned file + current.json pointer
1. Best-effort refresh of the incident_overview.xlsx snapshot for the incident overview page

**Maintenance**:

- The versioned design survives the upstream Excel being locked open — a hard-won fix, do not revert to direct overwrite

#### FineBI Report Files Sync（`finebi_report_sync`）

- Default cron: `10 * * * *`　|　worker group: **m**
- Workflow script: `services/finebi_report_sync.py → run_finebi_report_sync`

**What it does**: Hourly: pull the latest Excel from each subfolder of FineBI FTP /webroot/WEB-INF/schedule into data/finebi_reports for the Task Report Files page

**Workflow & data flow**:

1. Hourly :10 walk every subfolder under schedule
1. Download the latest Excel per folder into data/finebi_reports
1. Listed & downloadable under Task Report Files → FINEBI report tab

**Maintenance**:

- Stuck pending and broke the chain when group mode enabled on 2026-08-25 (ungrouped); now in group m — always register new tasks in GROUP_TASK_MAP

#### DB Data Freshness Check（`db_freshness_check`）

- Default cron: `15 * * * *`　|　worker group: **m**
- Workflow script: `services/db_freshness_check.py → run_db_freshness_check`

**What it does**: Hourly freshness audit of remote DBs (via db_writer_api) and local fallback DBs; outputs call chain and guidance when stale

**Workflow & data flow**:

1. Hourly :15 check the latest data date per table in remote & local fallback DBs
1. When stale, log the call chain and troubleshooting direction in the execution history

**Maintenance**:

- Suspect stalled data? Check this task's history first and follow its call chain — faster than browsing the task list

#### MTTR/TT Wide Table Rebuild（`mttr_tt_sync`）

- Default cron: `40 7 * * *`　|　worker group: **m**
- Workflow script: `services/mttr_tt_sync.py → run_mttr_tt_sync`

**What it does**: Rebuild the mttr_tt wide table (Eflow_TT_FB + OLR_CELLS/Site_Maintainer_Category reference) into local data/mttr_tt.sqlite3 for the MTTR board (daily/weekly/monthly)

**Workflow & data flow**:

1. Read local reference DB data/excel_ds.sqlite3 (Site ID->Site Category, Site Name->per-RAT cell counts)
1. Read the full remote Eflow_TT_FB via the read-only API
1. Derive Vender/MTTR1/MTTR2/MTTR_RANG_2H/Month/WK/Outage_Mins then atomically replace data/mttr_tt.sqlite3

**Maintenance**:

- Definitions parsed from FineDB dataset 4bc5a679, documented at the top of services/mttr_tt_sync.py; MTTR2 is non-null only when 0<MTTR1<48h
- excel_ds.sqlite3 is a static 114KB reference frozen from my-finebi (unchanged since 2026-08-31); re-export it if the FineBI Excel datasets ever change
- Before 2026-09-21 a manual ETL in the retired my-finebi project maintained this table; with no scheduler it froze at 2026-08-31

#### Progress Wide Table Rebuild（`progress_sync`）

- Default cron: `50 7 * * *`　|　worker group: **m**
- Workflow script: `services/progress_sync.py → run_progress_sync`

**What it does**: Rebuild the progress wide table (Eflow_TT_FB LEFT JOIN Eflow_WO_FB, replicating FineBI Progress computed columns) into local data/progress.sqlite3 for the Progress / Progress V3 boards

**Workflow & data flow**:

1. Read remote Eflow_TT_FB and Eflow_WO_FB via the read-only API (1:1 join on WO No.)
1. Replicate FineDB dataset 4bc5a679 Progress columns per row (per-stage ORG/STATUS, FB_* cascade, ORG_Handler, Month, MTTR1/2, clear_null)
1. Atomically replace data/progress.sqlite3

**Maintenance**:

- Duration(Hours)/SLA(%) depend on the current time and are deliberately NOT stored; widget SQL computes them live via julianday('now','localtime')
- Definitions live in _derive() of services/progress_sync.py; the SWITCH cascades are a verbatim port — compare with the original TMP/etl_progress.py before changing
- Before 2026-09-21 a manual ETL in the retired my-finebi project maintained this table; with no scheduler it froze at 2026-08-31

#### Failed Task Auto Retry（`auto_retry_failed`）

- Default cron: `*/10 * * * *`　|　worker group: **m**
- Workflow script: `services/auto_retry.py → run_auto_retry_task`

**What it does**: Scans every 10 min: re-enqueues failed tasks whose data gap is not yet filled (MAX_ATTEMPTS=2, give up after 24h); backfills missed tasks with no execution record at all

**Workflow & data flow**:

1. Scan the last 24h of execution records every 10 min
1. Failed tasks: re-enqueue only if the data gap is unfilled and under the attempt budget
1. Missed tasks: backfill once when nothing ran in the time window (15-min grace); email tasks excluded (handled by EWS recovery)

**Maintenance**:

- Retry is not "rerun on any failure" — filled gaps are skipped; tune via AUTO_RETRY_* env vars

#### RAN CM Cell Data Sync（`cm_data_sync`）

- Default cron: `30 8 * * *`　|　worker group: **u**
- Workflow script: `services/cm_data/cm_data_export.py → run_cm_data_sync`

**What it does**: Fetch GSM/UMTS/LTE/NR cell config from RAN UME, full-replace write to remote db.sqlite3 (cm_cell_data/cm_site_summary) via API, keep only the latest local Excel

**Workflow & data flow**:

1. Log into RAN UME and export cell config per flows defined in services/cm_data/cm_flows.json
1. Full-replace cm_cell_data / cm_site_summary in remote db.sqlite3 via the host API
1. Keep only the latest Excel locally

**Maintenance**:

- Export flows (flows/payload/moc) live in services/cm_data/cm_flows.json — check there first when the NMS UI changes

#### PG→SQLite Data Snapshot（`pg_to_sqlite_sync`）

- Default cron: `45 * * * *`　|　worker group: **m**
- Workflow script: `backend/scripts/sync_pg_to_sqlite.py → main`

**What it does**: Sync all remote PostgreSQL data into local db/app.db as an offline backup / fallback snapshot

**Workflow & data flow**:

1. Hourly :45 full-sync remote PG into local db/app.db
1. app.db also hosts the plaintext credentials table

**Maintenance**:

- Business tables in app.db are a one-hour-stale mirror — never assume realtime; do not delete the file (credentials + snapshot, ≈954MB)

#### MW UME KPI Sync（`mw_ume_kpi_sync`）

- Default cron: `15 5 * * *`　|　worker group: **w**
- Workflow script: `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync`

**What it does**: MW UME (ZXMW microwave) KPI history sync (FINBI 1-day template), in-memory export without disk, direct write to app.db table mw_ume_bw_ultilazation

**Workflow & data flow**:

1. Daily 05:15 export 1-day KPI via the FINBI template (in-memory, no temp files)
1. Dedup by Begin Time + identity columns, write mw_ume_bw_ultilazation

**Maintenance**:

- The microwave topology board changes once a day (after 05:15); the misspelling ultilazation in the table name is historical — do not rename

#### MW UME KPI Realtime Sync（`mw_ume_kpi_sync_rt`）

- Default cron: `*/15 * * * *`　|　worker group: **w**
- Workflow script: `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt`

**What it does**: MW UME realtime KPI sync (FINBI 15-min template): every 15 min fetch the last 2 hours, direct write to app.db table mw_ume_bw_ultilazation_rt

**Workflow & data flow**:

1. Every 15 min fetch the last 2 hours via FINBI (gr=900)
1. In-memory export, write mw_ume_bw_ultilazation_rt (overwrites slots in window)
1. The realtime board uses only the latest 15-min slot; the slider reviews history

**Maintenance**:

- Shares the NMS session with the daily task — serialized in group n; the board auto-refreshes every 900s with soft refresh

#### CN EMS KPI Cache Sync（`ems_kpi_cache_sync`）

- Default cron: `*/15 * * * *`　|　worker group: **c**
- Workflow script: `services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync`

**What it does**: Every 15 min, incremental download of today's (UTC) raw PM measurement files from CN EMS SFTP into local _pmcache (server retains ~1 day; fetch-only, no parsing)

**Workflow & data flow**:

1. Incrementally download today's UTC raw PM files via SFTP every 15 min
1. Fetch-only, no parsing (lightweight)
1. Store into the local _pmcache

**Maintenance**:

- The CN EMS server keeps raw files ~1 day — this task is what rescues the full day before server cleanup; do not disable

#### CN EMS KPI Daily CSV（`ems_kpi_daily`）

- Default cron: `20 0 * * *`　|　worker group: **c**
- Workflow script: `services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily`

**What it does**: Aggregate the previous complete UTC day of CN EMS KPIs into csv_out/<TEMPLATE>.csv per Query_Template.xml (7 templates: VLR/USSD/voice/location update/License/TDD/data subscribers)

**Workflow & data flow**:

1. Daily 00:20 UTC (08:20 Beijing): best-effort refetch of the previous-day window
1. Aggregate purely from the local _pmcache (server-independent)
1. Emit csv_out/<TEMPLATE>.csv per Query_Template.xml + samples formulas (7 templates)

**Maintenance**:

- Shares _pmcache/daily_raw.json with the cache sync — serialized in group c for mutual exclusion

#### CXO Dashboard Cache Sync（`cxo_dashboard_cache_sync`）

- Default cron: `*/10 * * * *`　|　worker group: **v**
- Workflow script: `services/cxo_dashboard_cache.py → run_cxo_dashboard_cache_sync`

**What it does**: Every 10 min pull all CXO dashboard APIs via the local 8790 VMAX proxy and merge them per-endpoint into a last-known-good cache (empty fetch keeps the old value) as the dashboard fallback

**Workflow & data flow**:

1. Pull every CXO dashboard endpoint via 127.0.0.1:8790 every 10 min
1. Merge per endpoint: an empty fetch keeps the old value instead of blanking the board
1. Persist data/cxo_dashboard/last_known_good.json

**Maintenance**:

- Split out of group n into group v on 2026-09-18 with the other two 8790 tasks: still serialized on the shared session, no longer queued behind sp_data_sync (1.5-2h)
- Missed its GROUP_TASK_MAP registration at launch → stuck pending and the board froze on a stale date (the fourth such accident)
- When the 8790 session dies this task fails but the board keeps showing last-known-good (looks fine, actually stalled) — trust the execution history

#### VMAX CXO Daily Value Archive（`vmax_cxo_daily_sync`）

- Default cron: `15 * * * *`　|　worker group: **v**
- Workflow script: `services/vmax_cxo_daily_cache.py → run_vmax_cxo_daily_sync`

**What it does**: Hourly: batch-pull the last 8 days of 1-hour detail for 50 KPIs (compressed into 8 multi-column requests) via the 8790 VMAX proxy, aggregate to daily values for the tabbed daily board (~3 weeks of review)

**Workflow & data flow**:

1. At :15 every hour pull 8 days of 1-hour detail (6 CXO trend + 14 network + 30 service/OTT KPIs)
1. Aggregate per day: SUM for volume, PEAK for users, AVG for rates
1. Persist data/vmax_cxo_daily/daily.json

**Maintenance**:

- Shares the single 8790 session with cxo_dashboard_cache_sync and vmax_multi_data_sync — serialized in group v
- Daily values are aggregated from hourly detail: missing hours are refilled from the 8-day window automatically

#### VMAX Multi-Report KPI Collect（`vmax_multi_data_sync`）

- Default cron: `45 * * * *`　|　worker group: **v**
- Workflow script: `services/vmax_multi_data/vmax_multi_data_service.py → run_vmax_multi_data_sync`

**What it does**: Hourly: fetch the vreport reports listed in url.txt (5GSA traffic / 5GSA video) via the 8790 proxy and persist latest.json plus vmax_multi_data.sqlite3

**Workflow & data flow**:

1. At :45 every hour request the vreport reports (sys_5gsa_traffic_ciservice / sys_5gsa_video_ciservice) via the 8790 proxy
1. report_query parameters are RSA block-encrypted
1. Persist data/vmax_multi_data/<key>_latest.json and vmax_multi_data.sqlite3 (kpi_rows + sync_runs)

**Maintenance**:

- Never ran before its group registration on 2026-09-18 (the fourth accident); now in group v with the other two 8790 tasks
- Pages read the latest.json snapshot, so a failing task still shows the previous run without any error

#### OLIB SOC Dashboard KPI Sync（`olib_soc_kpi_daily_sync`）

- Default cron: `20 6 * * *`　|　worker group: **m**
- Workflow script: `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_kpi_sync`

**What it does**: Daily incremental fill of the 90-day CXO dashboard KPI store (daily_kpi): only the 7 dashboard blocks, missing days plus the newest day re-read, no Excel output

**Workflow & data flow**:

1. Daily 06:20 connect straight to the VMAX GBase DWH (10.123.255.12:5258, db zxvmax)
1. Run only the 7 board blocks (traffic/active users/cache/video/game/TCP/top services)
1. Fetch missing days plus re-read the newest day (7-day lookback, idempotent) into daily_kpi in data/olib_soc_report/olib_soc_report.sqlite3

**Maintenance**:

- DWH partitions are kept ~90 days, so the lookback window must stay inside that retention
- When GBase is unreachable the task fails; once the link returns, days_back=7 refills the gap by itself
- Missed its group registration at launch, freezing the 90-day board on a stale date (added to group m on 2026-09-18)

#### OLIB SOC VMAX Routine Report（`olib_soc_vmax_report`）

- Default cron: `30 7 1 * *`　|　worker group: **m**
- Workflow script: `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_report`

**What it does**: Direct GBase DWH queries on daily partitions for the 9 notebook report blocks, producing a multi-sheet Excel plus run records; default window = previous calendar month

**Workflow & data flow**:

1. Monthly on the 1st at 07:30 run the 9 SQL blocks against GBase daily partitions
1. Emit a multi-sheet Excel and run records; default window is the previous calendar month (last_n_days/weekly/explicit configurable)
1. The window is clamped to the ~90-day partition retention

**Maintenance**:

- Low-frequency (monthly): the health check scales its window by cron, so it is not falsely reported as “silent for 24h”
- Config lives in the JSON files under services/olib_soc_report/ (range_mode/days/mail.enabled); the GBase password comes from credential group vmax_gbase

#### Customer Service KPI Sync（`ume_in_kpi_sync`）

- Default cron: `45 5 * * *`　|　worker group: **n**
- Workflow script: `services/ume_in/ume_in_kpi_service.py → run_ume_in_kpi_sync`

**What it does**: Fetch Dong customer service KPIs from the UME portal 172.17.208.1:28808 (7 templates: IVR/P4M/VC/USSD/PPS/CPU/Memory, 1-day granularity, 7-day lookback) and write table ume_in_customer_kpi

**Workflow & data flow**:

1. Daily 05:45 log into the UME portal and fetch the 7 templates at 1-day granularity
1. In-memory export, nothing written to disk
1. Direct write to ume_in_customer_kpi (dedup by Begin Time + KPI + NE + SERVICE)

**Maintenance**:

- Serialized in group n with the other NMS tasks
- Idempotent thanks to the 7-day lookback: late-arriving portal data is refilled automatically

#### Customer Service KPI + OSG Weekly Report Email（`ume_in_osg_report`）

- Default cron: `30 6 * * *`　|　worker group: **n**
- Workflow script: `services/ume_in/osg_report_task.py → run_ume_in_osg_report（内部依次调 ume_in_kpi_service + t_osg_build.py）`

**What it does**: Every morning, step by step: run the ume_in KPI sync, build the OSG Weekly QoS Analysis Report Excel from the latest 7 days in ume_in_customer_kpi, then email that Excel to djoumene.reussite1@zte.com.cn (cc dong.xinmin@zte.com.cn)

**Workflow & data flow**:

1. 06:30 ① call ume_in_kpi_service.run_ume_in_kpi_sync() to sync the 7 templates into ume_in_customer_kpi (same portal session as ume_in_kpi_sync)
1. ② call services/ume_in/t_osg_build.py to fill the OSG template with the latest 7 days, producing data/in_data/OSG Weekly QoS Analysis Report_<start>_<end>.xlsx (charts/conditional formatting/styles untouched; derived columns get both formula and cached value, per the original template formulas: PPS C/E/J, USSD C/E/I, VC H, IVR E)
1. ③ attach it to an Orange EWS mail to djoumene.reussite1@zte.com.cn, cc dong.xinmin@zte.com.cn

**Maintenance**:

- Serialized in group n with ume_in_kpi_sync: step ① shares the UME Dong portal session
- A failed sync aborts the run — a stale previous-window report is never emailed as the new one
- Recipients are editable under Settings → Email Recipient Settings (group ume_in_osg_report); only the latest 10 artifacts are kept

#### SP Online Ticket Sync（`sp_online_sync`）

- Default cron: `35 * * * *`　|　worker group: **n**
- Workflow script: `services/sp_online_sync.py → run_sp_online_sync`

**What it does**: Hourly: fetch online tickets from the eFlow SP APIs (sp-outbound/sp-inbound/sp-transfer) into the matching tables. Takes the union of the original filter and the all-status filter so a filter contradicting its own results can never silently pick the wrong data

**Workflow & data flow**:

1. At :35 every hour call the three eFlow SP APIs, each once with the original filter and once with the all-status filter
1. Merge both result sets by woId and write tables sp_outbound / sp_inbound / sp_transfer
1. Warn when every returned row has a status outside the filter enumeration (filter contradicts results)
1. Queryable in Table Browser; the Outbound leg of sp_online_report_generate consumes sp_outbound directly

**Maintenance**:

- Upstream account comes from the eflow credential group; a kicked eFlow session shows up as consecutive failures in the group, covered by auto_retry_failed
- Changed 2026-09-30 from "fall back to the all-status filter only when the original returns 0 rows" to a union: the old test mistook "this filter simply has no matches" for "the filter is broken", which turned inbound into a closed-ticket query (282 rows, all Closed) with no warning
- Upstream does not truly honour filter narrowing (inbound returns the same data for a 4-status and a 15-status filter), so never rely on filter precision

#### SP Material Master Sync（`sp_material_sync`）

- Default cron: `55 4 * * *`　|　worker group: **n**
- Workflow script: `services/sp_material_sync.py → run_sp_material_sync`

**What it does**: Fetch the full material master from the eFlow SP API (eflow-sp-material) into app.db table sp_material (upsert by materialNo)

**Workflow & data flow**:

1. Daily 04:55 pull the full eflow-sp-material master
1. Upsert into app.db table sp_material by materialNo
1. Queryable in Table Browser; sp_material_report builds the stock/consumption report from it

**Maintenance**:

- sp_material_report (07:33) only reads the table: if this task stalls, the email still sends but with stale content

#### SP Online Open Tickets Report Generate（`sp_online_report_generate`）

- Default cron: `0 6 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_online_report_generate`

**What it does**: Build the open-ticket Inbound/Outbound reports (PNG+XLSX, sorted by Create Time desc): Inbound from the details xlsx, Outbound from table sp_outbound tracking WaitingForUpdate / WaitingForReturn / WaitingForConfirm

**Workflow & data flow**:

1. Daily 06:00 emit Inbound/Outbound PNG + XLSX into data/sp_email/sp_online
1. Inbound: read the newest inband_details.xlsx under data/sp_email/data, keep open tickets
1. Outbound: read table sp_outbound (sp_online_sync pulls eFlow hourly) for the three in-flight statuses

**Maintenance**:

- Generates only — sp_online_report_send (06:20) delivers, so re-sending never requires regenerating
- Outbound used to read the SFTP details xlsx; switched to table sp_outbound on 2026-09-30 because that export carries no WaitingForUpdate — see sp_report_gen/README.md

#### SP Online Open Tickets Report Send（`sp_online_report_send`）

- Default cron: `20 6 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_online_report`

**What it does**: Send the open-ticket report: email (inline Inbound/Outbound PNG + XLSX attachments, default SP shared recipient list) + WhatsApp groups

**Workflow & data flow**:

1. Daily 06:20 pick up the newest sp_online report files
1. Email with inline PNG plus XLSX attachments
1. Also push to WhatsApp groups; recipients overridable under Settings → Email Recipients

**Maintenance**:

- Depends on the 06:00 generation task output — missing files make this one fail outright
- An email task: excluded from missed-run backfill by default, email_recovery replays it once EWS is back

#### eFlow Alarm Rules Collect（`eflow_alarm_rules_collect`）

- Default cron: `59 23 */3 * *`　|　worker group: **n**
- Workflow script: `services/eflow_rules/eflow_Alarm_Rule_Collector.py → run_eflow_alarm_rules`

**What it does**: Every 3 days at 23:59 pull rule types and alarm correlation rules from eFlow into eflow_alarm_rules.xlsx (sheets Alarm_Rules + Rule_Types)

**Workflow & data flow**:

1. Every 3 days at 23:59 pull the rule-type catalog and correlation rules (correlation-mgt)
1. Export backend/services/eflow_rules/eflow_alarm_rules.xlsx

**Maintenance**:

- Low-frequency (every 3 days): the health check scales its window by cron, so “no run in 24h” is not a false alarm
- The exported xlsx feeds downstream rule matching — treat it as a code asset, never hand-edit

#### eFlow Push Rules Collect（`eflow_push_rules_collect`）

- Default cron: `59 23 */3 * *`　|　worker group: **n**
- Workflow script: `services/eflow_rules/eflow_Push_Rule_Collector.py → run_eflow_push_rules`

**What it does**: Every 3 days at 23:59 pull all rules from the eFlow config-center (28 types: push/escalation/grouping/auto-close...), merging detail per rule into eflow_push_rules.xlsx

**Workflow & data flow**:

1. Every 3 days at 23:59 query the config-center with filter="" for all rules (28 types)
1. Merge the detail of each rule
1. Export backend/services/eflow_rules/eflow_push_rules.xlsx (Push_Rules + Rule_Type_Summary)

**Maintenance**:

- Low-frequency (every 3 days), same group and cadence as the alarm-rules collector
- Lives in services/eflow_rules/ next to the rule sheet used by eflow_tt_rules_check — do not rename paths

#### Log Files Cleanup（`log_cleanup`）

- Default cron: `17 3 * * *`　|　worker group: **m**
- Workflow script: `services/log_cleanup.py → run_log_cleanup`

**What it does**: Daily purge of log files older than the retention window (7 days by default, LOG_RETENTION_DAYS) under my_app/log, plus date-suffixing of legacy names no process writes to

**Workflow & data flow**:

1. Daily 03:17 scan log/ for log-shaped files
1. Delete those past retention (LOG_CLEANUP_DRY_RUN=1 reports without deleting)
1. Add date suffixes to legacy names so they roll with the date-based watchdog log names

**Maintenance**:

- On Windows a file held open cannot be renamed/deleted from outside — that is why the writers split logs by date
- db/app.db (credentials), backend/services/auth_cache/ and data/ task outputs are out of scope

#### TMP Directory Cleanup（`tmp_cleanup`）

- Default cron: `47 3 * * *`　|　worker group: **m**
- Workflow script: `services/tmp_cleanup.py → run_tmp_cleanup`

**What it does**: Two-stage reclaim of temp artifacts older than the retention window (7 days) under my_app/TMP: same-volume move into TMP/_quarantine_YYYYMMDD/ first (restorable), real delete only after another 7 days

**Workflow & data flow**:

1. Daily 03:47 scan TMP/ for entries past retention
1. Same-volume mv into _quarantine_<date>/ (nothing deleted outright)
1. Purge after another 7 days in quarantine; service paths in WHITELIST are skipped

**Maintenance**:

- TMP/ is the designated place for temp artifacts but nothing bounded its size (462MB on day one) — cleanup is required
- Service paths (charts/dl/state files) are whitelisted and never touched; add new ones to WHITELIST
- Staggered against log_cleanup (03:17) so the two full scans do not overlap

### 3.4 Reliability mechanisms (timeout / retry / self-healing)

| Mechanism | Description |
| --- | --- |
| **Zombie running recycling** | No per-task timeout (known gap). Worker scans every 300s: running rows older than 30 min (STALE_RUNNING_SECONDS) with a dead PID are marked failed. |
| **Auto retry** | auto_retry_failed scans every 10 min: a failed task is re-enqueued only if its data gap is not yet filled and attempts < MAX_ATTEMPTS=2; abandoned beyond the 24h hard cap. |
| **Missed-run backfill** | Tasks that should have fired but have no execution record at all are backfilled once (MISS_GRACE_MIN=15; email tasks excluded — handled by EWS recovery). |
| **Stale pending expiry** | A pending row unclaimed for over 6 hours (typical cause: the task was never registered in a worker group) is marked failed with an execution-log entry, freeing the single-flight slot it held — otherwise one stale row would block every later trigger of that task. |
| **Failure notification** | Failures notify via WeChat + email (services/weixin_notifier.py supports openclaw/wecom/serverchan/pushplus). |
| **Missed-run / stall alert** | db_freshness_check computes four health findings hourly (ungrouped / no execution record within the cron-scaled window / stuck queue / overdue since last success); services/task_health_alert.py pushes them to WeChat + email, notifying once per new anomaly and once on recovery, re-raising after 24h (added 2026-09-18). |
| **Process self-healing** | backend_watchdog / worker_watchdog supervise processes: port probing, crash backoff (give up & alert after 10 consecutive crashes); heartbeats in log/heartbeat_*.json stale >3 min → force kill & restart. |
| **Retention** | task_queue & task_execution_log are kept 3 days (auto-cleaned), no manual work. |

### 3.5 How to maintain tasks

**Change schedule (cron)** Task Manager → "Schedule" dialog; persisted into task_schedule_config, effective immediately, survives restarts — no code change needed.

**Change task parameters** Settings → "Task Config" tab (it lives under Settings, not Task Manager). Priority: env var > config file > default.

**Change upstream credentials** Settings → Credentials, pick the group, update, then "Test Connection" (plaintext in db/app.db credentials table; 30s cache).

**Change recipients** Settings → Email Recipients, edit groups or reset to defaults; applies to all kpi_* / *_email tasks.

**Run / stop manually** "Run" enqueues immediately, "Stop" interrupts a long task. After changing a schedule or script, run once manually and check the history.

**Add a new task** ① Append an entry to TASK_SPECS in task_registry.py; ② register it in GROUP_TASK_MAP in worker_watchdog.py (missing = forever pending, four accidents so far; tests/test_worker_group_coverage.py cross-checks task_id coverage and the three group-set declarations) — a brand-new group must be synced in three places: GROUP_TASK_MAP keys, MY_APP_WORKER_GROUPS in start_hidden.ps1, ALL_GROUPS in restart_workers.py; ③ business function in backend/services/, throw exceptions; ④ restart via stop.bat → start.bat (group-list-only changes: python restart_workers.py --mode watchdog --force, **needs elevation**); ⑤ verify manually and update docs (04-task-system.md list & helpTaskDocs.ts, then npm run docs).

**Edit a workflow script** All scripts live under backend/services/ (paths listed in the task catalog). Mind: ① never "fix" historical spellings (packet_lost, battary_kpi_fetch, ultilazation — string-referenced); ② dynamic collection tables stay out of Alembic; ③ sync-update task_registry.md / WORKER.md / the help data (frontend/src/pages/helpTaskDocs.ts).

**Pending / failed triage order** ① pending forever → check worker-group registration; ② failed → task_id stack in log/worker_runtime*.log (one file per worker group) → "Test Connection" for credentials; ③ data stalled → db_freshness_check history has the call chain.

### 3.6 When upstreams go down

| Upstream issue | Symptom | Self-healing |
| --- | --- | --- |
| eFlow / UME session kicked | Consecutive failures in the group | auto_retry_failed retries every 10 min; verify account via "Test Connection" |
| Exchange (EWS) down | Email tasks fail, reports missing | email_recovery re-sends last-3h failures automatically once restored |
| Remote host unreachable | DB writes/uploads fail, freshness alerts | db_freshness_check prints the call chain; check Settings → Remote Host connectivity |
| FineBI file locked open | (historical) fetch failures | Fixed with versioned files + current.json pointer — locked files no longer break ingestion |
| CN EMS server cleans raw files | Daily KPIs missing | ems_kpi_cache_sync caches incrementally every 15 min before server cleanup |

---

## 4. Pages Guide

Every page opens via a `?page=<key>` direct link, e.g. `http://<host>/myapp/?page=battery`; or right-click a menu item → "Open in new tab". Pages marked iframe render `frontend/public/*.html` inside, with slightly different styling.

### 4.1 Tasks & Data

#### Task Manager（`sync`）

Central control room for all scheduled sync/collection tasks: view status & schedules, run/stop/enable/disable, edit cron schedules, inspect run history and daily failure summary. See the "Task Manager Deep Dive" section on this page.

- First stop when data looks stale: click a stat card to filter, use the failure summary to see which tasks failed overnight
- Edit cron in the "Schedule" dialog (persisted in task_schedule_config, survives restarts)
- "Global History" searches runs across tasks; voice announcement on completion toggles here

#### Task Report Files（`email_reports`）

Collects three kinds of task artifacts for download: latest email report attachments, FineBI FTP reports, and eFlow rule check results. The bottom of the eFlow tab lists **every rule sheet collected from eFlow** (TT severity rules / alarm correlation rules / push & config rules) plus this run's outputs (severity correction sheet / matching report).

- Switch categories via tabs; click a file name or "Download" to save; set how many recent files to keep per category
- The three "Run Now / Collect" buttons on the eFlow tab trigger the matching task manually: TT check + severity correction, alarm rule collection, push rule collection; each auto-refreshes once after 3s (refresh manually if the task is slow)
- Table at the bottom of the eFlow tab: blue tag = rule sheet (TT rules refresh with the daily 04:20 check; alarm/push rules normally refresh every 3 days at 23:59 — use the "Collect" buttons to refresh them on demand), grey = this run's outputs

#### Data Upload（`upload`）

Drag-and-drop Excel/CSV ingestion with a data-quality score.

- Drop a file to upload; check the issue/conclusion panels before trusting the data
- The history list can be refreshed manually

#### Table Browser（`tables`）

Table Browser: browse any table without SQL, view column profiles, import & export — the go-to fallback tool.

- Pick a table → paginate & search (debounced); export xlsx / CSV
- Column visibility can be saved as view templates — save one when you always look at the same columns
- The "Profile" tab shows per-column statistics; Excel/CSV import supported

#### Overview（`overview`）

Database health-check page: how many tables exist, rows per table, Top10 by size.

- Sort by the "Rows" column; the page is read-only — it only answers "is the data there and how big"

### 4.2 Monitoring Boards

#### Alarm Dashboard（`alarm`）

Combined view of all current active network alarms: totals, severity, site-level multi-dimension statistics and trends.

- Click any number to open a searchable drill-down table
- "Realtime" data comes from eFlow active alarms (eflow_active_alarm every 30 min) — not second-level push

#### TT&WO Dashboard（`ttwo`）

Processing volume, timeliness and backlog trends of trouble tickets (TT) and work orders (WO). All three TT statistics dimensions (ticket severity / SLA status / ticket status) are number cards you can click to drill down; the MTTR trend is split into 4 charts by ticket severity (P1/P2/P3/P4), each a dual-axis chart with bars = TT count and line = MTTR, with tabs switching day / week / month granularity. The default window is the last 30 days.

- Filter with selects + segmented control + date range; click a card or a chart point to drill down. The default window is the last 30 days (over a 7-day window the weekly/monthly views have only one or two buckets, which shows no trend)
- "All owners" switches ZTE / 3rd: a non-empty WO number means ZTE (dispatched by us), empty means 3rd (handled by a third party)
- The "Advanced filters" button reveals site-level filters (region / province-county / network type / site type / VIP / TRM / supervisor / FME / power source / power vendor / site category), fed from the site table
- The percentage on a TT statistics card uses that dimension's own total as denominator (its internal composition), not the overall TT total
- The tabs above the MTTR trend switch day/week/month: all three load at once, so switching is instant; the weekly TT count is exactly the merge of that week's seven daily points, so the two views cross-check each other
- Each MTTR chart has two axes: bars are the TT count of that severity in the period (left axis), the line is the mean MTTR in minutes (right axis). A period with no ticket of that severity draws neither — it is not 0 ("no ticket" and "MTTR is 0" are different things)
- Bar height and line height are different units: bars show volume, the line shows speed. A line based on few tickets jumps around, so the hover tooltip adds "(N in MTTR avg)" to say how many tickets actually went into the average
- The four charts share hover tooltips and zoom (wheel / bottom slider) — dragging one moves the other three; the zoom bar appears automatically for the daily view, which has many points
- Click any point on a chart to drill into that period's tickets
- The header shows the latest sync time; data comes from hourly eflow_sync plus the nightly eflow_sync_full backfill

#### TT&WO Dashboard (v1, upper half only)（`v1_ttwo`）

The "upper half only" cut of the TT&WO Dashboard: renders up to the MTTR Trend (title, day/week/month tabs and four dual-axis "bars = TT count, line = MTTR" per-severity charts per tab included) — summary cards (TT Total / WO Total / WO No. Unique) + TT statistics (ticket severity / SLA status / ticket status, all number cards) + MTTR trend (P1/P2/P3/P4 × day/week/month); the three blocks below it (Domain & Root Cause, Work Order Analytics, Site Information) are omitted. The default window is the last 30 days.

- Filters (including the ZTE/3rd owner switch and advanced filters), the MTTR day/week/month tabs and dual-axis charts, card drill-down and Excel export are shared with the TT&WO Dashboard (same /tt-wo-dashboard/overview endpoint), so usage is identical and the numbers necessarily match
- Direct link http://<host>/myapp/?page=v1_ttwo; the full version is page=ttwo

#### TT Dashboard（`tt`）

The "TT only" cut of the TT&WO Dashboard (source table eflow_tt): summary card (TT Total only) → Statistics (severity / SLA status / status, all number cards that drill down on click) → MTTR trend (P1/P2/P3/P4 × day/week/month, each a dual-axis "bars = TT count, line = MTTR" chart). Everything below the MTTR trend is omitted: Domain & Root Cause, Work Order Analytics (WO by source / WO by status) and Site Information; the WO Total / WO No. (Unique) cards are gone too. The default window is the last 30 days.

- The section title reads "Statistics" and the severity dimension "Severity" (the full TT&WO Dashboard still uses "TT Statistics" and "Ticket Severity")
- Each MTTR chart is dual-axis: bars (ZTE blue #0072BC) are the TT count of that severity in the period, the line (orange) is the mean MTTR in minutes. The bar/line colours are fixed across all four charts — the severity is identified by the chart itself (four separate P1/P2/P3/P4 charts), while the colours only distinguish the two measures (volume vs duration). A period with no ticket of that severity draws neither a bar nor a point — it is not 0
- Filters (including the ZTE/3rd owner switch and advanced filters), card drill-down and the page-level Excel export are shared with the TT&WO Dashboard (same /tt-wo-dashboard/overview endpoint), so the numbers necessarily match; the export filename is prefixed TTWO_tt_
- Direct link http://<host>/myapp/?page=tt; the full version is page=ttwo, WO only is page=wo (same layout, sourced from eflow_wo)

#### WO Dashboard（`wo`）

The eflow_wo-sourced twin of the TT Dashboard: the layout matches page=tt block for block, only the data comes from eflow_wo. Summary card (WO Total only) → Statistics (severity / SLA status / status) → MTTR trend (P1/P2/P3/P4 × day/week/month dual-axis charts). Everything below the MTTR trend (Domain & Root Cause, Work Order Analytics, Site Information) is omitted, exactly as on page=tt. The default window is the last 30 days.

- Click a statistics card or a point on an MTTR chart to open a searchable WO drill-down table
- SLA status comes from the linked TT (eflow_wo has no such column — SLA is a TT-side concept): joined on wo.tt_no = tt.tt_no, and unmatched rows count as Unknown, so the cards still sum to the WO total
- MTTR uses the WO's own alarm_occur_time / alarm_clear_time, so this page shows the WO turnaround time — a different number from the TT figure on page=tt
- Only the "WO Total" summary card remains: every row on this page is itself a WO, so "WO No. (Unique)" would print the same number twice, and "TT Total" counts rows of a different table and is meaningless here
- The ZTE/3rd owner switch is hidden on this page: that ownership is defined on the TT's wo_no, a concept the WO table does not have
- Filters (region / advanced filters), drill-down and the page-level Excel export are shared with the TT&WO Dashboard, but the data endpoint is /wo-dashboard/overview; the export filename is prefixed TTWO_wo_
- Direct link http://<host>/myapp/?page=wo; the full version is page=ttwo, TT only is page=tt

#### NUR Dashboard（`nur`）

Network Unavailability Rate (NUR) daily/weekly/monthly trends, multi-dimension analysis and site compliance.

- Switch granularity and date range, filter by dimensions
- Click numbers to drill into a detail table (in-column filters & sorting); export to Excel

#### NUR Dashboard (NUR only)（`ms_nur_only`）

The "NUR only" cut of the NUR Dashboard: identical to the NUR half of page=nur (NUR daily/weekly/monthly tables + trends), with the three SLA blocks removed — handy for a NUR-only desk or wall screen.

- Filters, drill-down and Excel export are shared with the NUR Dashboard, so usage is identical
- Direct link http://<host>/myapp/?page=ms_nur_only; the other half is page=ms_sla_only (SLA scope, from the MS Operation KPI Dashboard)

#### MS Operation KPI Dashboard（`ms_sla`）

MS contract KPIs and WO SLA attainment: NUR / Network KPI / Per-Site / WO SLA (metrics as rows, periods as columns).

- Three granularity tabs: day / week / month; Network KPIs and Per-Site KPIs only exist at day/month (they come from the snapshot DB), so they are hidden at week granularity with an explanatory banner
- Switching day/week/month resets the time range to that tab default (day = current month to date, week = last 12 weeks, month = last 9 calendar months); the banner states the active range
- SLA attainment (TTR / TTR_P1~P4) is presented once, by the WOs SLA block as table + trend; there is no separate KPI List SLA card
- Drill-down reuses the NUR detail table; numbers come from the live nur_calc calculation (driven by ms_sla_full every 6h) and may differ from historical snapshot files — trust this page

#### MS KPI Dashboard (SLA only)（`ms_sla_only`）

The "SLA only" cut of the MS Operation KPI Dashboard: the WOs SLA block with WO SLA attainment (TTR / TTR_P1~P4 Total / Within SLA / Achieve + trend), without NUR, Network or Per-Site.

- Attainment ≥95% is green, below target is red — same scope as page=ms_sla
- Three granularity tabs: day (default = current month to date), week (default = last 12 weeks) and month (default = January 2026 to date); switching a tab resets the time range (explained by the banner)
- Click cells and data points to drill into TT details and export to Excel

#### CXO Dashboard（`cxoDashboard`, iframe page）

Service / Network / Summary three-tier executive dashboard (from the VMAX assurance board).

- The iframe embeds a full data snapshot: it renders even when the upstream is down, but may not show the latest data
- Re-run the sync task to refresh; credentials live in Settings → Credentials → vmax_cxo

#### MW UME Topology（`mwUmeTopology`, iframe page）

ZXMW microwave network topology & bandwidth utilization NOC board (daily granularity).

- Data is written daily at 05:15 by mw_ume_kpi_sync into mw_ume_bw_ultilazation — the page changes once a day
- Risk ranking, drawer and trend chart are all interactive

#### MW Realtime（`mwRealTime`, iframe page）

15-minute realtime variant of the microwave topology board (same skeleton, risk ranking, drawer and trends).

- Shows only the latest 15-minute slot by default; the slider reviews the last 2 hours
- Auto-refreshes every 900s with soft refresh (no iframe reload, no flicker)

#### Alarm Management（`alarmManagement`, iframe page）

Site Outage Monitor board: watches whether sites are down, with ERA / Regular / ALL views.

- Auto-screenshotted daily at 01:00 by site_outage_screenshot and sent to WhatsApp at 03:00 by whatsapp_send
- Caution: DOM changes on this page affect the screenshot task — verify the screenshot selectors still work first

#### fme_ranking（`fme_ranking`）

FME ranking board: site availability, work-order volume and SLA achievement per FME, ranked.

- Top3 / Bottom3 cards and the ranking table drill into that FME's site-level availability and WO details
- Two bar charts show availability for the "Top 5" and the "Bottom 5": horizontal bars are ordered by rank from top to bottom and print the availability value at the end of each bar. Each chart scales to its own real value range instead of a fixed 0–100, otherwise bars would all look the same length when the whole group sits above 99%
- The WO count (blue line) and SLA achievement (orange dashed line) appear only when values actually differ inside that group; when the whole group is identical the series is omitted rather than drawn as a flat line that reads like a trend
- Click any bar to drill into that FME's site details; the drill-down modal can also switch to the WO dimension

#### site_avail（`site_avail`）

Site availability board: per-site availability ranking and target compliance.

- Click a site name to drill into its availability details
- Availability uses the same per-site calculation as the FME ranking page

#### avail_ms（`avail_ms`）

MS Availability (availability matrix): network availability presented across three dimensions — region / technology / site type — with day, week and month granularity on tabs. Data comes from the local derived database avail_recon.sqlite3 (rebuilt daily at 06:10 by the avail_recon_sync task; the measure is site-weighted availability, SUM(numerator)/SUM(denominator)).

- Each matrix has a trend chart above it (30 periods for day, 12 for week, 12 for month, following the active tab): one line per dimension value, every point weighted as SUM(numerator)/SUM(denominator) and therefore identical to the table figures
- Chart points are clickable too, and they open **that point's own period** (e.g. when the month tab sits on 2026-09, clicking the 2026-08 point opens 2026-08 detail)
- The region chart omits the "unmatched master data" line (its magnitude would flatten the y-axis); a note under the chart points to the last table row, where it is shown
- Click any availability figure to drill down: the dialog holds a 30-period trend, the daily detail and a breakdown by dispatch group; the second tab lists the related TT tickets for that combination
- The threshold input (default 99.65%) drives the "below target" flag: values under it turn red and re-evaluate instantly — the figures themselves do not change
- The ALL row under Region includes sites not matched to master data, so ALL is not the sum of the three regions; that bucket gets its own last row — it can show availability detail but not TT tickets (the derived DB holds no site list for it)
- 4G NERA is an unmapped dispatch group: counted in the 4G technology total, shown separately as "Other" under site type, and only present in the 2025-12 ~ 2026-01 months; a yellow note appears on the page then
- Missing data renders as "—" (never 0); the "Data through" label at the top makes a stalled derived database obvious

#### avail_flm（`avail_flm`）

FLM availability: covers only the three FLM regions (Montserrado / North East / South West), with regions as rows and technology (2G/3G/4G) and site type (Regular / Cooli / ERA; the column keeps the raw data value, the requirement writes Cool.i) as columns; day / week / month granularity on tabs. The data is the same source as the Availability Matrix (local derived database avail_recon.sqlite3, measure SUM(numerator)/SUM(denominator)), and the "TTs affecting availability" list is shown right on the page.

- Each table has a trend chart above it: the upper one tracks the three regions (one line per region), the lower one the three site types; 30 periods for day, 12 for week, 12 for month, following the active tab
- Chart points are clickable and open **that point's own period**; the dashed threshold line (default 99.65%) is the same value that turns table figures red
- Click any availability figure to drill down: the dialog holds a 30-period trend, the daily detail and a breakdown by dispatch group; the second tab lists every TT ticket of that slice
- Each region also has a KPI card (all technologies combined) that can be clicked to drill down
- Site type is not scope-restricted: all three regions show the three columns Regular / Cooli / ERA (raw data value). The "NE has only Regular/Cool.i" note in the requirement contradicts both data sources (NE has 123 ERA sites and an ERA denominator of 65k in the derived database), and leaving cells blank would wrongly suggest NE has no ERA sites
- The last row "unmatched master data" is the part whose remote site names failed to match: it is outside the three regions and is not plotted (its magnitude would flatten the y-axis); it is listed for reconciliation only and can show availability detail but not TT tickets
- The page-level "TTs affecting availability" list shows **every TT of the period** with no "impacted service" judgement (that field and site_outage agree on every row of this period, so using either would make the definition look more precise than it is); each row carries the 2G/3G/4G down-site counts and MTTR so you can judge relevance yourself
- The TT list can be filtered by region (all / the three regions); a month can hold 3600+ tickets, and a yellow note appears when the display limit is hit — only the detail row count is affected, never the availability figures
- Click a ticket number to look up the availability of its region × site type together with all tickets of that slice
- 4G NERA is an unmapped dispatch group: counted in the 4G technology total, but this page lists only the three site types, so the 4G row will exceed the sum of the three columns and a yellow note appears
- Missing data renders as "—" (never 0); the "Data through" label at the top makes a stalled derived database obvious

#### bm_speedtest（`bm_speedtest`）

Speedtest Benchmark Report: puts the two operators (Orange and MTN) side by side using measured speed-test data, answering "who is faster / who has lower latency / by how much / is the gap widening or narrowing". Source: speedtest_data (imported from Speedtest.xlsx, 854 rows, 2025-07-16 ~ 2026-09-24, nationwide cellular median). Five blocks: overall competitiveness score -> key metric cards (download/upload/latency/jitter with mean and P50/P90) -> trend chart (switchable metric, adjustable moving-average window) -> daily head-to-head record -> monthly table and daily detail table.

- Quick ranges at the top (30 / 90 / 180 days / last year / all time) plus date pickers; the window is **half-open** internally while the UI shows a closed range
- The competitiveness score is **relative between the two operators**: the leader on each metric scores 100 and the other scales proportionally, then weights are download 35% / upload 20% / latency 30% / jitter 15%. It answers "who is stronger and by how much", not whether the absolute level is good; if either side lacks data for a metric, that metric drops out and its weight is redistributed
- Every figure in the key metric cards is clickable: click an operator value for all its rows on that metric, or click a win rate for **the days that operator won on that metric** (row count equals the win count, both computed from the same paired comparison)
- Use the segmented control to switch download/upload/latency/jitter and the dropdown to set the moving-average window (3/7/14/30 days). Solid lines are daily values, dashed lines are moving averages; speed is "higher is better" and latency "lower is better", noted below the chart
- The daily head-to-head block shows how many days each operator won per metric and the win rate, also clickable
- Click a date in the detail table to drill into both operators' raw rows for that day
- Days where only one operator has data are **excluded from win counts** (a blue note at the top states how many): "not tested that day" is not "lost that day"
- When the daily series exceeds 400 days the chart plots only the latest 400 and a yellow note appears; see the table below or export to Excel for the full series
- Location / device / technology / aggregation each have only one effective value in the data (nationwide / cellular / median), so **those four dimensions have no filters** — that is intentional, not an omission
- Missing data renders as "—" (never 0); all exports go through the "Export Excel" buttons in the header and on each card

#### noc_analyst（`noc_analyst`）

NOC operator analysis: quantifies each NOC operator's root-cause mismatch rate, average handling time, night-ticket share and SLA pass rate from eflow_tt.last_processer, and raises red flags. Built around "drill down wherever possible" — from the person to the ticket, then to the alarm chain.

- Scope: tickets are attributed to a month by alarm occurrence time (alarm_occur_time), not last-modified time; night = Accept operation time between 22:00 and 06:00
- Mismatch rate = mismatched tickets / tickets with a filed root cause. history_alarm.reason_type is authoritative and is compared against the NOC-filed root_cause (typically POWER←TRM: NOC filed power, the system says transmission)
- Layer 1: summary stat cards, Top3/Bottom3 cards, the ECharts bar chart, every column in the ranking table, and each operator named in the red-flag banner are all clickable
- Layer 2: the modal switches between five slices — All / Root-cause mismatch / Night / SLA failed / Slow (≥12h); row counts match that operator's metric exactly
- Layer 3: the "Abnormal sites" tab aggregates by site (mismatch / SLA fail / slow / night); click a site name to see all of its TTs
- Layer 4: click any TT number for the single-ticket postmortem — five tabs: time attribution / milestone timeline / should-do vs did / deviations / alarm chain, sharing the same source and definitions as the programmatic postmortem report on the EflowQa page
- Time attribution section ("where the time went"): every ticket of the month is parsed and aggregated to show where time is wasted. Six clickable stat cards, a stage-share pie chart, a deviation-type distribution, a segment table (total/average/P90/longest/over-threshold counts) and a milestone duration table
- "WO expected but not dispatched": high-severity site-down (P1/P2, VIP, Hub) tickets with no field work order, longest first. Click a TT number to open that ticket's postmortem on the "Deviations" tab
- Hover to see names: hover an alarm code (e.g. 99933) to see its official name (SITE DOWN DUE TO POWER OFF); hover a "Dispatch category" tag (e.g. rule_stopped) to see the reason plus the matched dispatch rule names and their status (ACTIVE/STOP), so it is obvious why no WO was raised
- Top-of-page "Handled by" switch (ZTE in-house / IPT 3rd party / All, defaults to ZTE): tickets routed to a third party (IPT) never get a WO by design, so mixing them with in-house tickets inflates "WO expected but not dispatched" by nearly 4x (1140 before the fix, 296 after). Switch to "IPT (3rd party)" to review third-party fulfilment on its own — that bucket legitimately shows 0 for "WO expected but not dispatched"
- Field-response timeliness — "Monthly WO hop durations": the work-order lifecycle split into created → FE accepted → start trip → arrive → work done → closed, so you can see which hop is stuck. In practice the slowest is "WO created → FE accepted" (median about 11 hours), while everything after acceptance takes only minutes
- "NOC / human action timeliness": how long each human-performed action (FO Accept, FO Process, field work) waited, whether it breached its contract deadline, and the over-deadline share
- In the single-ticket postmortem, the "Time attribution" tab's segment table carries a Phase column showing at a glance which kind of time dominates; below it sits the ticket's own "Field response timeline (WO lifecycle)" hop-by-hop detail with operators. Tickets with no WO say so explicitly instead of showing a blank area
- "Phases: who is holding the time": event-driven segments merged by phase (creation delay / accept wait / field response wait / field work / alarm cleared / submit close / confirm close), so NOC, field and system shares are comparable. In practice field response wait is 15.2% of the month with a 6.4-hour median
- The first computation parses every ticket of the month (about 150 s in practice); results are cached per month on disk, so later opens are millisecond-fast. Click "Recompute" at the top right to force a refresh
- Every table in the modal supports full-field search, column filters and sorting, and exports the current slice and search result to Excel

#### repeat_site_down（`repeat_site_down`）

Repeat site-down board: identifies sites that go down repeatedly within the window — for finding "sites that never get fixed".

- Counts site-downs per day; click a number to drill into that day's down sites
- Data comes from eflow_tt and eflow_site, complementing the alarm board

#### cr_analysis（`cr_analysis`）

CR Change Analysis: shows change-plan scheduling and execution by change category, answering "how many were planned, how many executed, and how many of those were on time".

- Data comes from eflow_cr (synced from eFlow); the default range covers the full data span
- Four core counts: "Planned" = has a planned start time; "Executed" = has an actual start time; "Not Executed" = planned but never started; "On Time / Delayed" = actual start before / after planned start
- Each rate shows its denominator: Plan Completion Rate = executed ÷ planned, On-Time Rate = on time ÷ executed. Shows "—" instead of 0 when the denominator is zero
- Every number is clickable: the category table, chart bars, monthly trend and sub-category table all drill into details, and the detail row count matches the card figure exactly
- A yellow banner appears when drill-down results are truncated — narrow the date range and retry rather than ignoring it

#### pm_analysis（`pm_analysis`）

PM Execution Analysis: shows preventive-maintenance work orders (PMT) by PM plan number (pmp_no), answering "how far has each plan progressed, how many are overdue, and where are they stuck".

- Data comes from eflow_pm (synced from eFlow); the default range covers the full data span
- Four core counts: "Closed" = status is Closed; "Open" = not yet Closed; "Overdue" = the source column pmt_overdue is Yes (the upstream verdict is used as-is, never recomputed from dates); "Not Started" = completed item count is 0
- Two finer breakdowns: "Closed & Overdue" = back-filled / late delivery; "Open & Overdue" = genuinely still unfinished — look at this one first
- Each rate shows its denominator: Closure Rate = closed ÷ total, Overdue Rate = overdue ÷ total (lower is better), Started Rate = share of work orders with at least one item completed. Shows "—" instead of 0 when the denominator is zero
- The "Workflow Progress" funnel follows the REAL chronological order: Created → Scheduled → Accepted → PM Manager Approved → Processed → FLM Leader Approved. Beware: the source column names are misleading — last_accept_time actually precedes last_process_time, so never infer the order from the column names
- Every number is clickable: KPI cards, rate cards, chart bars, the monthly trend, the site bar chart and the plan table all drill into details, and the detail row count matches the card figure exactly
- A yellow banner appears when drill-down results are truncated — narrow the date range and retry rather than ignoring it

#### bp_report（`bp_report`）

BP Cells Report: umlaut-caliber BP cell statistics, viewable by day/week/month and drillable down to cell detail.

- Caliber (busy-hour three values): take the hour with the highest active users and judge all three conditions on that hour's values — DL PRB utilization > 80% AND DL throughput < 3 Mbps AND active users > 2.5; weekly = BP on 4 of 7 days; monthly = BP in 3 of 4 full weeks
- This busy-hour caliber is calibrated against the Excel: it matches the umlaut detail cell-by-cell (Jaccard = 1.00), whereas a daily-average caliber would miss about 97% of BP cells
- ⚠️ "Average DL Active User Number" is only available at hourly granularity in RAN_UME; a daily-grain query silently drops that column, so a dedicated hourly channel fetches it. When it is unavailable the day is marked "Undecidable" and never counted as 0
- Every figure drills down: BP counts, detail rows, undecidable counts, trend-chart bars, all four KPI cards, the region chart and the layer table BP counts — row counts match the displayed figures exactly (same query predicate)
- The drill-down detail table carries a "Site ID" column (the ManagedElement ID / NE ID) plus a "Site name" column, so each cell maps to a concrete site; site names are resolved by NE ID against the site database with about 98% coverage, and unmatched rows show —
- The "Total cells" column drills down only for RAN_UME-sourced periods (the denominator is the detail row count); Excel-sourced periods provide no roster and are greyed out with an explanation
- The "Detail rows" column shows how many rows the Excel BP Cells List actually holds for that period, with the difference from the displayed value in brackets — the upstream Excel sheets disagree with each other and the gap is shown as-is
- Periods with no detail in the Excel BP Cells List (all of 2023, plus some 2024 dates) have their drill-down entry greyed out
- The "Latest period verdict" gives yes/no for week/month; when undecidable it states the cause — a week still in progress (just wait) versus a month with too few full weeks (2026-09 has only 3 full weeks against the required 4, so that month can never be decided; a caliber-vs-calendar mismatch, not missing data)
- Regions (Cluster1~6 / Rural / ERA) can only be maintained in Excel; RAN_UME has no such dimension, and new cells missing from the dictionary fall back to Unknown
- The trend switches between day / week / month granularity; if the chart looks empty on week or month, first check that the date range covers periods that actually have data
- Data is incrementally refreshed from RAN_UME by the bp_report_sync task daily at 06:20

#### Packet Loss（`packet_loss`）

LTE packet loss board (RAN UME SDR / IPRAN IPPD): last 7 complete calendar days at hourly granularity; the ongoing day is hidden.

- Criteria match the Packet_Loss automation Excel report exactly; the Popover explains them
- The switch controls whether OK sites are included; supports drill-down and topology overlay

#### Battery Dashboard（`battery`）

Site battery health / SOC / charge-discharge status and alarm details.

- The first dimension is data freshness: by default only readings ≤24h old are counted (battery_kpi_sync hourly :05); turning off "fresh only" mixes in stale data
- Click a site name to drill into batteries and history; export to Excel supported

#### ume_in_kpi（`ume_in_kpi`）

Customer Service KPI dashboard: pulls Dong customer weekly service KPIs from the UME portal (172.17.208.1:28808) across 7 templates — IVR / P4M / VC / USSD / PPS / CPU / Memory (1-day granularity). Besides volume and success rate, failures are attributed to "system side" vs "user side" — only system-side failure rate and resource utilisation raise alerts, so business-normal outcomes such as PPS "insufficient balance" or USSD "user failure" are not misreported as faults.

- Click "Sync now" to trigger a fetch manually (about 10-60 s); the ume_in_kpi_sync task normally runs daily at 05:45
- Switch "Last 7 / 14 / 30 days" to change the trend window; columns are sortable and filterable by status
- Expand a row in the service KPI table to see per-SERVICE volume, success rate, system/user-side failures and failure-reason tags
- "Failure-rate composition" stacks each KPI's failure rate by attribution; "Success-rate trend" shows the daily movement
- Resource utilisation is judged on the daily average (≥80% warning, ≥90% critical); peaks are informational only — brief saturation is normal
- "Export Excel" writes 6 sheets: KPI summary / service detail / failure breakdown / resources / trend / alerts

#### UME iMonitor Screen（`imonitor`, iframe page）

UME iMonitor screen (guard-imonitor-iui, screen_id=1): embeds the original UME monitoring screen from the UME portal (172.17.208.1:28808) inside myapp, keeping all of its charts and interactions. The page is reverse-proxied to the upstream through nginx port 8088 (the portal dedicated-port scheme); on first visit an injected script signs in to em-portal automatically using the credentials from Settings → Credentials ("UME Customer Service KPI Portal", key ume_in). The login page frame-bust is neutralised in the proxy and the iframe additionally carries a sandbox, so the sign-in flow can never replace the myapp shell.

- The first visit takes about 3-6 s to sign in automatically, then the screen renders; later visits inside the same session open instantly
- When the session expires the screen SPA redirects itself to the login page, the injected script signs in again and the iframe is pulled back to screen_id=1 — no user action needed
- Toolbar "Re-login" forces a fresh portal login (use when the account changes or the portal drops the session); "Refresh" just reloads the screen page
- Open in new tab shows this screen in its own browser tab (it shares the same browser session — cookies are scoped per host, not per port)
- Auto Refresh (header) reloads the screen in place via the iframe instead of remounting the page, so there is no white flash; the page is listed in AR_SOFT_REFRESH_PAGES
- The upstream sets Content-Security-Policy: frame-ancestors self, so the page must go through the proxy (nginx/portal_ume_in_8088.conf) and cannot be embedded directly; port 8088 must stay in sync across the nginx config and PROXY_PREFIXES

#### GIS Map（`gis`）

Site map: alarm/ticket distribution, topology lines, region polygons and multi-dimension filters (history/ticket view).

- Region dropdown + layer tags to filter; click a legend item to hide that layer; time supports segments and custom range
- Click a site to open the right drawer: four tabs, searchable, exportable to Excel
- The "Link Utilization" switch (on by default) overlays MW microwave link utilization from the same 15-min slot as the MW Realtime page, colored on a 4-level scale (>80% critical / ≥70% major / ≥60% minor / <60% healthy); thicker lines mean higher utilization
- Click a link to see its max/Tx/Rx utilization and the matched MW sites; a link showing "No KPI data" means it could not be matched to realtime metrics (it keeps its original KML color) — that is not 0%
- The overlay scope is explained below the legend: about 360 of the 844 KML links match realtime metrics; the rest are still viewable on the MW Realtime page

#### Realtime Alarm Map（`realtime_alarm`）

Realtime mode of the GIS map: current active-alarm sites on the map (red "realtime" badge).

- Interactions are identical to the GIS Map page
- Data comes from eFlow active alarms (eflow_active_alarm) synced every 30 minutes

#### Incident Overview（`incident_overview`, iframe page）

OLR incident overview board: cards, matrix, SLA charts, paginated details and a map.

- Data is fetched hourly by incident_overview_sync from the latest incident_overview.xlsx on the FineBI FTP (versioned files, resilient to the upstream file being locked)

#### Warehouse（`warehouse`, iframe page）

Spare-parts / consumables inventory board (Spare Management), identical to the original tool.

- Data comes from sp_data_sync (5 spare-part reports pulled from SFTP daily at 07:00)
- Browse inventory and details by warehouse / spare type

#### sp_material（`sp_material`）

Spare-parts material summary: inbound, outbound and inventory rolled up by domain / material.

- Data comes from the spare-part reports pulled by sp_data_sync
- Click any summary figure to drill into the matching material details

#### sp_details（`sp_details`）

SP Details Report: the same merged workbook that the email task sends, with Inventory / Inbound / Outbound / Transfer sheets.

- Paginate, filter and sort; "open" means Status does not contain Closed
- Only common columns are shown — click any row for all columns of that sheet
- Export covers the current filter (up to 5000 rows)

#### sp_report（`sp_report`）

Spare Parts Inbound & Outbound & Inventory summary: the same workbook emailed / sent over WhatsApp (produced daily at 05:15 by sp_report_generate), with Summary-Current / Summary-Changed / Inbound / Outbound / Inventory sheets.

- Stat cards show totals and replenishment alerts; clicking an alert card filters
- Summary-Changed renders as a day × warehouse matrix
- "Columns" is configurable per sheet and remembered locally; the row-detail modal always shows every column

#### com_report（`com_report`）

Consumables Inbound & Outbound & Inventory summary: same layout as the spare-parts page, reading the consumables workbook instead.

- Identical basis to the spare-parts page — see "Report basis" at the bottom
- When the page and Excel disagree, read the basis notes first; never change the basis in the page layer

#### warehouse_summary（`warehouse_summary`）

Warehouse Summary Report: mirrors WarehouseSummaryReport.xlsx — the tabs are its two sheets, Spars Parts / Consumables. Each tab has two sections: WH/DOP inventory & consumption (current inventory / total / this month / this week), and frequently used materials (10 rows per page, all materials reachable by paging).

- Switch tabs for spare parts vs consumables; every figure in both sections drills down
- Frequently used materials are paged by consumption descending, showing all of them; the Total row is the full-scope total and does not change when you page
- Consumption basis is Outbound Site Qty (site outbound), shown as a tag next to the second section title

### 4.3 Analysis & Tools

#### eFlow Knowledge Base（`eflow_qa`）

eFlow TT rule knowledge base: full-text search over rule/case documents, with built-in TT quick analysis.

- Search with space-separated keywords or pick an article from the catalog on the left
- Enter a TT number for one-click analysis: assignment, time gap, root-cause distribution and key conclusions
- Below the AI conclusion a "Rule match evidence" block (local rule engine, same source as Email Reports → eFlow TT Rules Check) lists the matched rule name/ID, per-condition match details, the rule source file eflow_TT_rules.xlsx (downloadable), the rule owner and the ticket handler
- When no model is reachable (local proxy down and Open WebUI unreachable) the page no longer just shows an error: it renders a "programmatic verdict" — severity verdict, matched rule, rule source and recommended actions all computed by the local rule engine
- Rule source & owners also lists the push order rule (TT Push Order Rule, triggerStep=FO Accept): Rule Name / Rule Type / Rule Trigger Step / Push Order Path / *Auto Operator / Target Handler — i.e. whether the TT is auto-pushed to a WO, to whom, and which operator acts automatically (source: eflow_push_rules.xlsx, downloadable)
- TT batch check: upload an xlsx/csv/txt list of TT numbers or paste them to judge each ticket severity (OK / needs adjustment / undetermined) and export to Excel
- The batch check supports a "download template → fill in → upload" loop: download the templated xlsx, fill in the numbers and upload the same file back

#### eflow_flow（`eflow_flow`）

eFlow process flow: enter an alarm (alarm ID / alarm code) or a TT number to draw the ticket's full eFlow process — the rule-driven state machine plus the path actually traversed, highlighted.

- Three input types: TT number (TT202609230060), alarm ID (the alarm table id/aid), or alarm code (e.g. 99933); querying by alarm code lists the most recent TTs carrying it so you can switch
- The base diagram is the rule-driven state machine: Alarm Raised → TT Created → Auto Dispatch → FO/BO Accept → FO/BO Process → 3rd Party Accept/Process → Confirm → Closed; the active/total count under each node is how many rules bind to that step
- Green node = a step the ticket actually traversed, amber node = the current step (taken from the operation_type field), grey = not involved; thick cyan edges = the actual path
- Click any node to switch the "Rule details" table below to the rules bound to that step (rule name / type / trigger step / status / priority / target handler / push path); "Show all" reveals every rule
- The "Actual path" table lists the milestones the ticket really went through, with operator and note; "TT ticket information" gives severity, current handler, SLA and root cause
- If the TT spawned a field work order, a "WO field sub-process" block shows the WO's own Accept → Process → Confirm → Closed pipeline plus per-step handling detail (from the eflow_wo *Detail columns)
- The "Related alarms" table lists the alarms that raised this TT (linked via realtime_alarm / history_alarm tt_id or alarm_id), with alarm code, site, network element, severity and raised time
- Verdicts share one source with "NOC analyst" and the single-TT postmortem report: rules are all read from ocrule_details, so the flow diagram and the postmortem can never disagree
- The rule tables are collected by the eflow_push_rules_collect / eflow_alarm_rules_collect jobs (every 3 days at 23:59); the diagram reflects rule updates automatically

#### Dashboard（`dashboard`）

Analysis dashboard: pick a table to auto-generate multi-dimension charts and conclusions, archiveable.

- Pick a table → rename → generate → archive
- With "linked filters" on, clicking a pie/bar applies it as a filter; click again to cancel

#### Archive（`archive`）

Analysis archive: search, view and delete past analysis results; pairs with the Dashboard.

- Keyword search + pagination; details include conclusion text and chart snapshots
- Deletion asks for confirmation — be careful

#### IP Trace（`ip_trace`, iframe page）

IP trace: probe link connectivity and path nodes from the server side to a target site.

- Enter a target and start; the result table/map refreshes live
- Tracing is a stoppable long task — stop it manually if it hangs

### 4.4 System

#### Settings（`settings`）

System settings: credentials, email recipients, remote host, and task configuration — four tabs.

- Credentials: 12 upstream account groups with connection test and plaintext reveal (masked by default; stored plaintext in the credentials table of db/app.db)
- Email recipients: edit groups, reset to defaults
- Remote host: takes effect immediately, no restart needed (written to backend/data/settings.json)
- Task config: business parameters (not schedules); priority: env var > config file > default

#### Portal Login（`portalLogin`）

One-click portal login: auto-logs into upstream portals with saved credentials (Playwright automation).

- Click "Login" then poll status until the portal window opens; "Close Window" ends the session
- Shares credentials with Settings; session cookies are cached under backend auth_cache/ — treat as sensitive

---

## 5. Ops & Troubleshooting

### 5.1 Processes & ports

| Port | Process | Kept alive by |
| --- | --- | --- |
| `7038` | uvicorn / FastAPI backend (/api/*, /docs) | backend_watchdog.py |
| `7090` | vite preview frontend (production via nginx /myapp/) | start_hidden.ps1 |
| `5432` | PostgreSQL 16 main DB | autostart scripts via pg_ctl |
| `8787 / 8790` | FMS / VMAX realtime proxies (127.0.0.1 only) | backend startup threads |
| `—` | workers × 5 groups (u/n/v/m/c consuming task_queue) | worker_watchdog.py |

### 5.2 Daily inspection (5 minutes)

- Task Manager: any failed? any long-standing pending? (the failure summary view beats scrolling the list)
- Header sync badges: are "last synced" labels on GIS / TT&WO / Dashboard within the expected window
- Overview page: table count & row counts clearly abnormal?
- CLI: are the five key processes alive and heartbeats (heartbeat_*.json) fresh (>3 min stale → force-restart)
- DB freshness is audited hourly at :15 by db_freshness_check; staleness logs include the call chain. The same audit alerts proactively (WeChat + email) when tasks themselves stall — ungrouped, no execution record, stuck queue, or overdue since the last success

### 5.3 Log files

| Log file (log/) | Content |
| --- | --- |
| `log/worker_runtime*.log` | Main task-execution log — first stop for troubleshooting; search by task_id for stacks (one file per worker group) |
| `log/backend_runtime.log` | Backend business log (API, scheduler, proxies) |
| `log/backend_watchdog.log / worker_watchdog.log` | Process spawn & crash-backoff records (gives up after 10 consecutive crashes) |
| `log/start_hidden_result.txt` | Per-step result of the last startup — check this first when startup fails |
| `log/heartbeat_*.json` | Backend & worker heartbeats (15s; >3 min stale = hung) |
| `log/*_console.log(.err)` | Child-process stdout/stderr |

> ⚠️ No log rotation exists — `log/` grows forever and needs manual cleanup; some error lines contain account names, scan before sharing.

### 5.4 Backup (all three, incomplete otherwise)

- **Remote PostgreSQL (main DB)**: pg_dump for business data + task_queue/task_execution_log/task_schedule_config; pg_to_sqlite_sync already mirrors it into db/app.db hourly at :45
- **db/app.db (SQLite)**: Hosts the plaintext credentials table — backing up only PG loses credentials, only app.db loses business data; back up both
- **data/ + backend/data/**: Task report artifacts and settings.json (losing it reverts the remote host to the built-in default)
- **backend/services/*.json**: Upstream connection params & TT rule sheets — code assets, travel with the repo

### 5.5 Cleanup: what to delete, what to keep

**Safe to clean**

- Runtime logs log/*.log (stop services before deleting large ones to release handles; no log rotation exists)
- One-off debug artifacts: log/edge_cleanup*.txt, killlog*.txt, backend/restart_dbg.log, etc.
- Empty legacy DBs data/app.db & data/my_app.db (0 bytes); old build dirs frontend/dist, dist2, dist3 (confirm nginx no longer points there first)

**Do NOT touch**

- db/app.db — hosts the plaintext credentials table + the PG snapshot mirror, ≈954MB, absolutely not garbage
- backend/services/auth_cache/ — upstream session cookies (equivalent to valid logins); never ship, commit or screenshot
- Task folders under data/ — report artifacts and per-task SQLite files
- backend/services/eflow_rules/eflow_TT_rules.xlsx — the authoritative TT rule sheet (the root-level same-name file is a copy)
- Historical spellings (data/packet_lost, battary_kpi_fetch, mw_ume_bw_ultilazation...) — string-referenced, never rename casually

### 5.6 Configuration & credentials

Three config layers, highest first: environment variables (backend/.env, 203 keys, restart required) > DB/config files (credentials, recipients, schedules, remote host, task params — edited via UI, effective immediately) > code defaults.

- 12 credential groups: zte_ume, vmax_cxo, ipran_ume, ccn_ume, eflow, fms_portal, fw_kpi, mw_ume, sftp_sp, mail_126, owa_mail, weixin (maintained in Settings → Credentials)
- Read priority: env var > DB > empty; the list API returns masks, with separate "reveal" and "test connection" endpoints
- Credentials are stored plaintext in the credentials table of db/app.db (credential_store opens SQLite directly, bypassing MY_APP_DB_MODE) — always include the file in backups, treat as sensitive media
- Session cookies under backend/services/auth_cache/ are equivalent to valid logins — never ship, commit or screenshot them

---

## 6. FAQ

**The board data is not updating?**

① Check the task's latest result and the failure summary in "Task Manager"; ② check whether the header "Auto refresh" was set to Off; ③ remember some data is inherently low-frequency: alarms every 30 min, microwave topology daily 05:15, packet loss daily 06:30, incident overview hourly. The "DB Data Freshness Check" task history also logs the call chain and direction when stale.

**Numbers do not match the expected criteria?**

Watch each page's definition: the battery board counts only readings ≤24h fresh by default; the MS SLA board follows the live calculation (snapshot files may differ); packet loss shows only the last 7 complete days; the CXO board embeds a snapshot refreshed only by re-running its sync task.

**A task stays pending forever?**

Most likely the task was never assigned to a worker group (GROUP_TASK_MAP) — nobody claims it from the queue. This accident happened four times in this project (finebi_report_sync, whatsapp_send_ext, sp_email_details, and on 2026-09-18 the olib_soc dashboard sync plus vmax_multi_data_sync). New tasks MUST be registered in GROUP_TASK_MAP in worker_watchdog.py; a stale pending row holding the single-flight slot is now auto-expired by the worker after 6 hours. Since 2026-09-18 such stalls no longer need a human to spot them: db_freshness_check (hourly) pushes the four health findings (ungrouped / no execution record / stuck queue / overdue since last success) through WeChat + email, deduplicated by state flips.

**A task keeps failing?**

Find the stack trace for the task_id in log/worker_runtime*.log (the first log to check; one file per worker group). Upstream unreachable → run "Test Connection" in Settings → Credentials; changed password → update credentials. auto_retry_failed retries every 10 min (MAX_ATTEMPTS=2, gives up after 24h) — no need to click Run repeatedly.

**A task stuck in "running"?**

The scheduler has no per-task timeout (known design gap). Zombie running states are recycled by the worker every 300s (30-min staleness + PID liveness) — no manual action needed; if the task genuinely runs long (e.g. Playwright probing), stop it manually from Task Manager.

**An email was not delivered?**

When the EWS mailbox is down, email tasks fail; email_recovery (every 20 min) re-sends those from the last 3 hours once EWS is back — check its history first instead of re-running the original task. Mailbox full is guarded by mailbox_cleanup (hourly).

**How to open a board on a wall screen / another tab?**

Right-click the menu item → "Open in new tab"; or open http://<host>/myapp/?page=<key> directly. Combine with the header auto refresh for unattended display.

**How do I verify uploaded data quality?**

The "Data Upload" page shows an issue panel and a quality score after ingestion; then inspect the data and column profiles in "Table Browser" and chart it in "Dashboard".

**Where are metric/term definitions?**

Most boards show a metric-explain icon next to indicators; the full glossary and per-page manual live in docs/manual/ (01-overview glossary, 11-feature-guide).

---

*See the project docs for more: docs/manual/ (01 overview & glossary · 04 task system · 11 feature guide · 13 operations · 14 integrations & data flows).*
