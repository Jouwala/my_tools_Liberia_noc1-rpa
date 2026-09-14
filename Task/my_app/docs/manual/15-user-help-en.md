# my_app User Help & Guide

> User-facing platform features & operations guide. Generated from the same source as the in-app Help page (frontend/src/helpMarkdown.ts), compiled from docs/manual/ and backend/task_registry.py. Generated on 2026-09-14.

> In-app entry: the "Help" sidebar item, or `http://<host>/myapp/?page=help` directly.

---

## 目录

- [1. Platform Overview](#1-platform-overview)
- [2. General Usage](#2-general-usage)
- [3. Task Manager Deep Dive (47 tasks)](#3-task-manager-deep-dive)
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
| **m** | Housekeeping tasks: EWS mail session + screenshot/WhatsApp file dependencies |
| **c** | CN EMS dedicated session: cache sync & daily aggregation share _pmcache, serialized for mutual exclusion |

> ⚠️ **New tasks MUST also be registered in `GROUP_TASK_MAP` in worker_watchdog.py** — declaring them only in TASK_SPECS leaves them pending forever. This accident happened three times (finebi_report_sync / whatsapp_send_ext / sp_email_details).

### 3.3 Full task catalog (47 tasks)

| Task | task_id | Default cron | Group | Workflow script |
| --- | --- | --- | --- | --- |
| eFlow Data Sync | `eflow_sync` | `22 * * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")` |
| eFlow Daily Full Sync | `eflow_sync_full` | `0 1 * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")` |
| RAN UME Daily Report | `ran_ume_daily` | `0 2 * * *` | u | `services/ran_ume_service.py → run_ran_ume_full_task` |
| Site Outage Screenshot | `site_outage_screenshot` | `0 1 * * *` | m | `services/site_outage_service.py → run_site_outage_screenshot` |
| WhatsApp Message Send | `whatsapp_send` | `0 3 * * *` | m | `services/whatsapp_service.py → run_whatsapp_send` |
| WhatsApp Message Send (Extension) | `whatsapp_send_ext` | `0 3 * * *` | m | `services/whatsapp_ext_service.py → run_whatsapp_send_ext` |
| MS SLA Full Sync | `ms_sla_full` | `0 */6 * * *` | n | `services/ms_sla_service.py → run_full_sync` |
| eFlow Realtime Alarm Sync | `eflow_active_alarm` | `*/30 * * * *` | n | `services/eflow_api_client.py → fetch_and_save_active_alarm` |
| eFlow History Alarm Sync | `eflow_history_alarm` | `0 */3 * * *` | n | `services/eflow_api_client.py → fetch_and_save_history_alarm` |
| eFlow TT Rules Collect & Match Check | `eflow_tt_rules_check` | `20 4 * * *` | n | `services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check` |
| RAN Main KPI Sync | `main_kpi_sync` | `0 4 * * *` | u | `services/ran_ume_main_kpi.py → run_main_kpi_sync` |
| RAN Cell Availability 1-Day Sync | `cell_availability_sync` | `30 4 * * *` | u | `services/ran_cell_availability_sync.py → run_cell_availability_sync` |
| RAN Cells KPI Sync | `cells_kpi_sync` | `50 4 * * *` | u | `services/ran_cells_kpi_sync.py → run_cells_kpi_sync` |
| RAN Network KPI Sync | `network_kpi_sync` | `0 5 * * *` | u | `services/ran_ume_network_kpi.py → run_network_kpi_sync` |
| CNN UME KPI Sync | `cnn_kpi_sync` | `0 6 * * *` | n | `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync` |
| SP Spare Data Sync | `sp_data_sync` | `0 7 * * *` | n | `services/get_sp_table.py → run_sp_data_sync` |
| iPRAN UME KPI Sync | `ipran_kpi_sync` | `0 8 * * *` | u | `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync` |
| Liberia Site-Down 1H Report Email | `liberia_email_1h` | `5 * * * *` | m | `services/liberia_email_report.py → run_1h_report` |
| Liberia Site-Down 8H Report Email | `liberia_email_8h` | `10 */8 * * *` | m | `services/liberia_email_report.py → run_8h_report` |
| MS Contract KPIs Daily Report Email | `kpi_ms_contract` | `30 17 * * *` | m | `services/kpi_email_report.py → run_ms_contract_kpi` |
| MS WOs SLA Daily Report Email | `kpi_ms_wo_sla` | `35 17 * * *` | m | `services/kpi_email_report.py → run_ms_wo_sla` |
| SpareParts Report Email | `kpi_sp_spareparts` | `45 9 * * *` | m | `services/kpi_email_report.py → run_sp_spareparts` |
| Comsumables Report Email | `kpi_sp_consumables` | `50 9 * * *` | m | `services/kpi_email_report.py → run_sp_consumables` |
| SP Report Generate | `sp_report_generate` | `15 5 * * *` | m | `services/kpi_email_report.py → run_sp_report_generate` |
| SP Spare Parts Details Report Email | `sp_email_details` | `0 7 * * *` | m | `services/kpi_email_report.py → run_sp_details_email` |
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
| Failed Task Auto Retry | `auto_retry_failed` | `*/10 * * * *` | m | `services/auto_retry.py → run_auto_retry_task` |
| RAN CM Cell Data Sync | `cm_data_sync` | `30 8 * * *` | u | `services/cm_data/cm_data_export.py → run_cm_data_sync` |
| PG→SQLite Data Snapshot | `pg_to_sqlite_sync` | `45 * * * *` | m | `backend/scripts/sync_pg_to_sqlite.py → main` |
| MW UME KPI Sync | `mw_ume_kpi_sync` | `15 5 * * *` | n | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync` |
| MW UME KPI Realtime Sync | `mw_ume_kpi_sync_rt` | `*/15 * * * *` | n | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt` |
| CN EMS KPI Cache Sync | `ems_kpi_cache_sync` | `*/15 * * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync` |
| CN EMS KPI Daily CSV | `ems_kpi_daily` | `20 0 * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily` |

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

- Default cron: `0 7 * * *`　|　worker group: **n**
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

- Default cron: `15 5 * * *`　|　worker group: **n**
- Workflow script: `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync`

**What it does**: MW UME (ZXMW microwave) KPI history sync (FINBI 1-day template), in-memory export without disk, direct write to app.db table mw_ume_bw_ultilazation

**Workflow & data flow**:

1. Daily 05:15 export 1-day KPI via the FINBI template (in-memory, no temp files)
1. Dedup by Begin Time + identity columns, write mw_ume_bw_ultilazation

**Maintenance**:

- The microwave topology board changes once a day (after 05:15); the misspelling ultilazation in the table name is historical — do not rename

#### MW UME KPI Realtime Sync（`mw_ume_kpi_sync_rt`）

- Default cron: `*/15 * * * *`　|　worker group: **n**
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

### 3.4 Reliability mechanisms (timeout / retry / self-healing)

| Mechanism | Description |
| --- | --- |
| **Zombie running recycling** | No per-task timeout (known gap). Worker scans every 300s: running rows older than 30 min (STALE_RUNNING_SECONDS) with a dead PID are marked failed. |
| **Auto retry** | auto_retry_failed scans every 10 min: a failed task is re-enqueued only if its data gap is not yet filled and attempts < MAX_ATTEMPTS=2; abandoned beyond the 24h hard cap. |
| **Missed-run backfill** | Tasks that should have fired but have no execution record at all are backfilled once (MISS_GRACE_MIN=15; email tasks excluded — handled by EWS recovery). |
| **Failure notification** | Failures notify via WeChat + email (services/weixin_notifier.py supports openclaw/wecom/serverchan/pushplus). |
| **Process self-healing** | backend_watchdog / worker_watchdog supervise processes: port probing, crash backoff (give up & alert after 10 consecutive crashes); heartbeats in log/heartbeat_*.json stale >3 min → force kill & restart. |
| **Retention** | task_queue & task_execution_log are kept 3 days (auto-cleaned), no manual work. |

### 3.5 How to maintain tasks

**Change schedule (cron)** Task Manager → "Schedule" dialog; persisted into task_schedule_config, effective immediately, survives restarts — no code change needed.

**Change task parameters** Settings → "Task Config" tab (it lives under Settings, not Task Manager). Priority: env var > config file > default.

**Change upstream credentials** Settings → Credentials, pick the group, update, then "Test Connection" (plaintext in db/app.db credentials table; 30s cache).

**Change recipients** Settings → Email Recipients, edit groups or reset to defaults; applies to all kpi_* / *_email tasks.

**Run / stop manually** "Run" enqueues immediately, "Stop" interrupts a long task. After changing a schedule or script, run once manually and check the history.

**Add a new task** ① Append an entry to TASK_SPECS in task_registry.py; ② register it in GROUP_TASK_MAP in worker_watchdog.py (missing = forever pending, three accidents so far); ③ business function in backend/services/, throw exceptions; ④ restart via stop.bat → start.bat; ⑤ verify manually and update docs (04-task-system.md list & this help).

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

Collects three kinds of task artifacts for download: latest email report attachments, FineBI FTP reports, and eFlow TT rule check results (rules / corrections / report).

- Switch categories via tabs; click a file name or "Download" to save; set how many recent files to keep per category
- The eFlow rule tab supports "Run Now" to trigger a check manually (auto-refreshes once after 3s; refresh manually if the task is slow)

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

Processing volume, timeliness and backlog trends of trouble tickets (TT) and work orders (WO).

- Filter with selects + segmented control + date range; click numbers to drill down
- The header shows the latest sync time; data comes from hourly eflow_sync plus the nightly eflow_sync_full backfill

#### NUR Dashboard（`nur`）

Network Unavailability Rate (NUR) daily/weekly/monthly trends, multi-dimension analysis and site compliance.

- Switch granularity and date range, filter by dimensions
- Click numbers to drill into a detail table (in-column filters & sorting); export to Excel

#### MS Operation KPI Dashboard（`ms_sla`）

MS contract KPIs and WO SLA attainment: NUR / SLA / Network KPI / Per-Site / WO SLA (metrics as rows, periods as columns).

- Granularity is daily/monthly only; drill-down reuses the NUR detail table
- Numbers come from the live nur_calc calculation (driven by ms_sla_full every 6h) and may differ from historical snapshot files — trust this page

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

#### Packet Loss（`packet_loss`）

LTE packet loss board (RAN UME SDR / IPRAN IPPD): last 7 complete calendar days at hourly granularity; the ongoing day is hidden.

- Criteria match the Packet_Loss automation Excel report exactly; the Popover explains them
- The switch controls whether OK sites are included; supports drill-down and topology overlay

#### Battery Dashboard（`battery`）

Site battery health / SOC / charge-discharge status and alarm details.

- The first dimension is data freshness: by default only readings ≤24h old are counted (battery_kpi_sync hourly :05); turning off "fresh only" mixes in stale data
- Click a site name to drill into batteries and history; export to Excel supported

#### GIS Map（`gis`）

Site map: alarm/ticket distribution, topology lines, region polygons and multi-dimension filters (history/ticket view).

- Region dropdown + layer tags to filter; click a legend item to hide that layer; time supports segments and custom range
- Click a site to open the right drawer: four tabs, searchable, exportable to Excel

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

### 4.3 Analysis & Tools

#### eFlow Knowledge Base（`eflow_qa`）

eFlow TT rule knowledge base: full-text search over rule/case documents, with built-in TT quick analysis.

- Search with space-separated keywords or pick an article from the catalog on the left
- Enter a TT number for one-click analysis: assignment, time gap, root-cause distribution and key conclusions

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
| `—` | workers × 4 groups (u/n/m/c consuming task_queue) | worker_watchdog.py |

### 5.2 Daily inspection (5 minutes)

- Task Manager: any failed? any long-standing pending? (the failure summary view beats scrolling the list)
- Header sync badges: are "last synced" labels on GIS / TT&WO / Dashboard within the expected window
- Overview page: table count & row counts clearly abnormal?
- CLI: are the five key processes alive and heartbeats (heartbeat_*.json) fresh (>3 min stale → force-restart)
- DB freshness is audited hourly at :15 by db_freshness_check; staleness logs include the call chain

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

Three config layers, highest first: environment variables (backend/.env, 147 keys, restart required) > DB/config files (credentials, recipients, schedules, remote host, task params — edited via UI, effective immediately) > code defaults.

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

Most likely the task was never assigned to a worker group (GROUP_TASK_MAP) — nobody claims it from the queue. This accident happened three times in this project (finebi_report_sync, whatsapp_send_ext, sp_email_details). New tasks MUST be registered in GROUP_TASK_MAP in worker_watchdog.py.

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
