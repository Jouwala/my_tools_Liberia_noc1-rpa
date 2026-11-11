# my_app User Help & Guide

> User-facing platform features & operations guide. Generated from the same source as the in-app Help page (frontend/src/helpMarkdown.ts), compiled from docs/manual/ and backend/task_registry.py. Generated on 2026-11-11.

> In-app entry: the "Help" sidebar item, or `http://<host>/myapp/?page=help` directly.

---

## Contents

- [1. Platform Overview](#1-platform-overview)
- [2. General Usage](#2-general-usage)
- [3. Task Manager Deep Dive (84 tasks)](#3-task-manager-deep-dive)
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
| Auto refresh | Off by default, and every page has its own setting: the header "Start Refresh" button plus the interval dropdown work on any page. Starting it lands on that page's suggested interval (1 min for real-time alarm pages, 5 min for boards, 15 min for reports whose upstream syncs daily, 30 min for configuration and operation pages); the dropdown offers 0/30s~30min and the choice is remembered per page in localStorage, so pages never affect each other. "Stop Refresh" turns it off at any time. While you are typing, a dialog is open, or the tab is in the background, the round is skipped to avoid interrupting you. |
| Theme & language | Switch dark/light theme and Chinese/English in the top-right; preferences are remembered locally (localStorage). |
| Data freshness | Some pages show a "last synced" time in the header. Boards are fed by scheduled tasks with different frequencies (alarms every minute, microwave topology daily 05:15, packet loss daily 06:30...). See "Task Manager Deep Dive" for the full catalog. |

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
| **u** | RAN UME single-account session; tasks run serially (parallel runs kick the session). Added 2026-11-07: ran_element_management_sync at 23:00 (RNM element table into PG), sharing the zte_ume session with ran_ume_daily at 02:00 |
| **n** | NMS / eFlow API / remote systems: independent but conservatively grouped |
| **v** | VMAX portal (local 8790 single-session proxy): the three tasks share one session and must serialize; split out of group n on 2026-09-18 so long tasks no longer block them |
| **m** | Housekeeping tasks: EWS mail session + screenshot/WhatsApp file dependencies |
| **c** | CN EMS dedicated session: cache sync & daily aggregation share _pmcache, serialized for mutual exclusion |
| **x** | Realtime alarm dedicated group: split out of group n on 2026-10-15 to run on its own lane, no longer queued behind long tasks like eflow_sync (worst observed queue wait 854s) |
| **g** | RAN Greenplum extract group (added 2026-10-19): upstream is a two-hop SSH via control1, sharing no session with eFlow/UME/VMAX GBase. It gets its own lane for blast-radius reasons, not duration (measured 72.6s per run) — any hop can wedge at the network layer, the same failure mode that once froze group s for 5.5h, while group m carries the per-minute WhatsApp alarm pushes |
| **s** | SP spare-parts SFTP: separate SFTP server + UNC mirror DB; split out of group n on 2026-09-27 (used to be group n's heaviest single load and a known hang source) |
| **w** | MW UME microwave NMS (credential group mw_ume): dedicated session; split out of group n on 2026-09-27 so the */15 realtime sync no longer queues behind long tasks |
| **p** | PG full-snapshot dedicated group (split out of group m on 2026-10-28): every hour at :45 it dumps the whole PG database into db/app.db (113 tables / 4.89M rows / 1.5GB, measured 577~1174s per run); in group m it blocked the per-minute alarm pushes |

> ⚠️ **New tasks MUST also be registered in `GROUP_TASK_MAP` in worker_watchdog.py** — declaring them only in TASK_SPECS leaves them pending forever. This accident happened four times (finebi_report_sync / whatsapp_send_ext / sp_email_details / the olib_soc and vmax_multi_data_sync tasks found on 2026-09-18).

### 3.3 Full task catalog (84 tasks)

| Task | task_id | Default cron | Group | Workflow script |
| --- | --- | --- | --- | --- |
| eFlow Data Sync | `eflow_sync` | `22 * * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")` |
| eFlow Daily Full Sync | `eflow_sync_full` | `0 1 * * *` | n | `services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")` |
| RAN UME Daily Report | `ran_ume_daily` | `0 2 * * *` | u | `services/ran_ume_service.py → run_ran_ume_full_task` |
| Site Outage Screenshot | `site_outage_screenshot` | `0 1 * * *` | m | `services/site_outage_service.py → run_site_outage_screenshot` |
| WhatsApp Message Send | `whatsapp_send` | `0 3 * * *` | m | `services/whatsapp_service.py → run_whatsapp_send` |
| WhatsApp Message Send (Extension) | `whatsapp_send_ext` | `0 3 * * *` | m | `services/whatsapp_ext_service.py → run_whatsapp_send_ext` |
| WhatsApp Message Send (Baileys) | `whatsapp_send_baileys` | `0 4 * * *` | m | `services/whatsapp_send_baileys_service.py → run_whatsapp_send_baileys` |
| eFlow P1 Alarm WhatsApp Push | `tt_alarm_whatsapp_alert` | `2-59/5 * * * *` | m | `services/tt_alarm_whatsapp_service.py → run_tt_alarm_whatsapp_alert` |
| MS SLA Full Sync | `ms_sla_full` | `0 5 * * *` | n | `services/ms_sla_service.py → run_full_sync` |
| DC Server Alarm WhatsApp Push | `ume_alarm_whatsapp_alert` | `* * * * *` | m | `services/ume_alarm_whatsapp_service.py → run_ume_alarm_whatsapp` |
| Fiber Break Alarm Auto Assign | `eflow_fiber_assign` | `3-59/5 * * * *` | m | `services/eflow_fiber/fiber_assign_service.py → run_fiber_assign` |
| 5G Site Alarm Auto Assign | `eflow_5g_assign` | `8-59/5 * * * *` | m | `services/eflow_5g/g5_assign_service.py → run_5g_assign` |
| CMDB Site Sync Diff | `eflow_site_update` | `0 7 * * *` | m | `services/eflow_site_update_task.py → run_eflow_site_update` |
| eFlow Realtime Alarm Sync | `eflow_active_alarm` | `*/1 * * * *` | x | `services/eflow_api_client.py → fetch_and_save_active_alarm` |
| eFlow History Alarm Sync | `eflow_history_alarm` | `0 */3 * * *` | n | `services/eflow_api_client.py → fetch_and_save_history_alarm` |
| eFlow TT Rules Collect & Match Check | `eflow_tt_rules_check` | `20 4 * * *` | n | `services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check` |
| RAN Main KPI Sync | `main_kpi_sync` | `0 4 * * *` | u | `services/ran_ume_main_kpi.py → run_main_kpi_sync` |
| RAN Cell Availability 1-Day Sync | `cell_availability_sync` | `30 4 * * *` | u | `services/ran_cell_availability_sync.py → run_cell_availability_sync` |
| RAN Cells KPI Sync | `cells_kpi_sync` | `50 4 * * *` | u | `services/ran_cells_kpi_sync.py → run_cells_kpi_sync` |
| RAN Network KPI Sync | `network_kpi_sync` | `0 5 * * *` | u | `services/ran_ume_network_kpi.py → run_network_kpi_sync` |
| Availability Recon Rebuild | `avail_recon_sync` | `10 6 * * *` | u | `services/avail_recon_sync.py → run_avail_recon_sync` |
| BP Cells Report Sync | `bp_report_sync` | `20 6 * * *` | u | `services/bp_report_sync.py → run_bp_report_sync` |
| CNN UME KPI Sync | `cnn_kpi_sync` | `0 6 * * *` | n | `services/ccn_ume_kpi_service.py → run_cnn_kpi_sync` |
| CNN UME KPI 5-Min Sync | `cnn_kpi_sync_5mins` | `*/15 * * * *` | n | `services/cnn_ume_kpi_5mins_service.py → run_cnn_kpi_sync_5mins` |
| SP Spare Data Sync | `sp_data_sync` | `10 * * * *` | s | `services/get_sp_table.py → run_sp_data_sync` |
| iPRAN UME KPI Sync | `ipran_kpi_sync` | `0 * * * *` | u | `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync` |
| Liberia Site-Down 1H Report Email | `liberia_email_1h` | `15 * * * *` | m | `services/liberia_email_report.py → run_1h_report` |
| Liberia Site-Down 8H Report Email | `liberia_email_8h` | `20 */8 * * *` | m | `services/liberia_email_report.py → run_8h_report` |
| MS Contract KPIs Daily Report Email | `kpi_ms_contract` | `30 5 * * *` | m | `services/kpi_email_report.py → run_ms_contract_kpi` |
| MS WOs SLA Daily Report Email | `kpi_ms_wo_sla` | `35 5 * * *` | m | `services/kpi_email_report.py → run_ms_wo_sla` |
| SpareParts Report Email | `kpi_sp_spareparts` | `45 9 * * *` | m | `services/kpi_email_report.py → run_sp_spareparts` |
| Comsumables Report Email | `kpi_sp_consumables` | `50 9 * * *` | m | `services/kpi_email_report.py → run_sp_consumables` |
| SP Report Generate | `sp_report_generate` | `15 5 * * *` | m | `services/kpi_email_report.py → run_sp_report_generate` |
| SP Weekly Report (Monday → Sunday) | `sp_weekly_report` | `0 7 * * mon` | m | `services/kpi_email_report.py → run_sp_weekly_report` |
| SP Spare Parts Details Report Email | `sp_email_details` | `5 7 * * *` | m | `services/kpi_email_report.py → run_sp_details_email` |
| SP Spare Parts Details Files Email | `sp_details_files_email` | `5 10 * * *` | m | `services/kpi_email_report.py → run_sp_details_files_email` |
| Comsumables&SpareParts Report Whatsapp | `sp_whatsapp_report` | `55 7 * * *` | m | `services/kpi_email_report.py → run_sp_whatsapp_report` |
| SP Material Stock & Consumption Report Email | `sp_material_report` | `45 7 * * *` | m | `services/kpi_email_report.py → run_sp_material_stock_consumption` |
| MS Network Availability Daily Report Email | `kpi_ran_availability` | `30 9 * * *` | m | `services/kpi_email_report.py → run_ran_availability` |
| Email Recovery after EWS Restored | `email_recovery` | `*/10 * * * *` | m | `services/email_recovery.py → run_email_recovery_task` |
| Packet Loss Sync | `packet_loss_sync` | `30 6 * * *` | u | `services/packet_loss_service.py → run_packet_loss_sync` |
| Packet Loss Daily Report Email | `packet_loss_email` | `45 6 * * *` | u | `services/kpi_email_report.py → run_packet_loss_email` |
| IP RAN M6K-FW Chart Email | `ipran_m6k_chart_email` | `45 6 * * *` | m | `services/ipran_chart_service.py → run_ipran_m6k_chart_email` |
| CNN Free Rating Chart Email | `ccn_free_rating_chart_email` | `45 7 * * *` | m | `services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email` |
| FW Throughput KPI Sync + Chart Email | `fw_kpi_sync` | `15 7 * * *` | n | `services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync` |
| Battery KPI Sync | `battery_kpi_sync` | `5 * * * *` | u | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync` |
| Battery KPI Email | `battery_email` | `10 7,19 * * *` | m | `services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email` |
| Mailbox Storage Guard | `mailbox_cleanup` | `0 * * * *` | m | `services/mailbox_cleanup.py → run_mailbox_cleanup` |
| Incident Overview Data Sync | `incident_overview_sync` | `20 * * * *` | m | `services/incident_overview_sync.py → run_incident_overview_sync` |
| FineBI Report Files Sync | `finebi_report_sync` | `10 * * * *` | m | `services/finebi_report_sync.py → run_finebi_report_sync` |
| DB Data Freshness Check | `db_freshness_check` | `15 * * * *` | m | `services/db_freshness_check.py → run_db_freshness_check` |
| MTTR/TT Wide Table Rebuild | `mttr_tt_sync` | `40 7 * * *` | m | `services/mttr_tt_sync.py → run_mttr_tt_sync` |
| Progress Wide Table Rebuild | `progress_sync` | `50 7 * * *` | m | `services/progress_sync.py → run_progress_sync` |
| Failed Task Auto Retry | `auto_retry_failed` | `*/10 * * * *` | m | `services/auto_retry.py → run_auto_retry_task` |
| RAN CM Cell Data Sync | `cm_data_sync` | `30 8 * * *` | u | `services/cm_data/cm_data_export.py → run_cm_data_sync` |
| PG→SQLite Data Snapshot | `pg_to_sqlite_sync` | `45 * * * *` | p | `backend/scripts/sync_pg_to_sqlite.py → main` |
| MW UME KPI Sync | `mw_ume_kpi_sync` | `15 5 * * *` | w | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync` |
| MW UME KPI Realtime Sync | `mw_ume_kpi_sync_rt` | `*/15 * * * *` | w | `services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt` |
| CN EMS KPI Cache Sync | `ems_kpi_cache_sync` | `*/15 * * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync` |
| CN EMS KPI Daily CSV | `ems_kpi_daily` | `20 0 * * *` | c | `services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily` |
| CXO Dashboard Cache Sync | `cxo_dashboard_cache_sync` | `*/10 * * * *` | v | `services/cxo_dashboard_cache.py → run_cxo_dashboard_cache_sync` |
| VMAX CXO Daily Value Archive | `vmax_cxo_daily_sync` | `15 * * * *` | v | `services/vmax_cxo_daily_cache.py → run_vmax_cxo_daily_sync` |
| VMAX Multi-Report KPI Collect | `vmax_multi_data_sync` | `45 * * * *` | v | `services/vmax_multi_data/vmax_multi_data_service.py → run_vmax_multi_data_sync` |
| SOC Multi-Dim Trend Sync | `soc_trend_sync` | `40 * * * *` | v | `services/soc_trend/soc_trend_sync.py → run_soc_trend_sync` |
| OLIB SOC Dashboard KPI Sync | `olib_soc_kpi_daily_sync` | `20 6 * * *` | m | `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_kpi_sync` |
| OLIB SOC VMAX Routine Report | `olib_soc_vmax_report` | `30 7 1 * *` | m | `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_report` |
| Customer Service KPI Sync | `ume_in_kpi_sync` | `45 5 * * *` | n | `services/ume_in/ume_in_kpi_service.py → run_ume_in_kpi_sync` |
| Customer Service KPI + OSG Weekly Report Email | `ume_in_osg_report` | `30 6 * * *` | n | `services/ume_in/osg_report_task.py → run_ume_in_osg_report（内部依次调 ume_in_kpi_service + t_osg_build.py）` |
| SP Online Ticket Sync | `sp_online_sync` | `35 */6 * * *` | n | `services/sp_online_sync.py → run_sp_online_sync` |
| SP Material Master Sync | `sp_material_sync` | `55 4 * * *` | n | `services/sp_material_sync.py → run_sp_material_sync` |
| SP Online Open Tickets Report Generate | `sp_online_report_generate` | `0 6 * * *` | m | `services/kpi_email_report.py → run_sp_online_report_generate` |
| SP Online Open Tickets Report Send | `sp_online_report_send` | `35 6 * * *` | m | `services/kpi_email_report.py → run_sp_online_report` |
| eFlow Alarm Rules Collect | `eflow_alarm_rules_collect` | `59 23 */3 * *` | n | `services/eflow_rules/eflow_Alarm_Rule_Collector.py → run_eflow_alarm_rules` |
| eFlow Push Rules Collect | `eflow_push_rules_collect` | `59 23 */3 * *` | n | `services/eflow_rules/eflow_Push_Rule_Collector.py → run_eflow_push_rules` |
| eFlow Push Rules Check | `eflow_push_rules_check` | `10 5 * * 2` | n | `services/eflow_rules/eflow_push_rules_check_task.py → run_eflow_push_rules_check` |
| WhatsApp KB Sync (Push Rules) | `whatsapp_kb_sync_push_rules` | `4 0 */3 * *` | n | `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_push_rules → whatsapp-kb-bot/scripts/sync-kb.mjs` |
| WhatsApp KB Sync (Alarm Rules) | `whatsapp_kb_sync_alarm_rules` | `4 0 */3 * *` | n | `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_alarm_rules → whatsapp-kb-bot/scripts/sync-kb.mjs` |
| WhatsApp KB Sync (TT Level Rules) | `whatsapp_kb_sync_tt_rules` | `35 4 * * *` | n | `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_tt_rules → whatsapp-kb-bot/scripts/sync-kb.mjs` |
| Log Files Cleanup | `log_cleanup` | `17 3 * * *` | m | `services/log_cleanup.py → run_log_cleanup` |
| TMP Directory Cleanup | `tmp_cleanup` | `47 3 * * *` | m | `services/tmp_cleanup.py → run_tmp_cleanup` |
| TTs and MTTR Report Generate | `tt_mttr_report_generate` | `20 7 * * *` | m | `services/tt_mttr_report.py → run_tt_mttr_report` |
| RAN User Identity Lists (VoLTE/N78) | `gp_ran_user_sync` | `20 13 * * *` | g | `services/gp_ran/gp_ran_sync.py → run_gp_ran_user_sync` |
| IPT Site Power Collect | `ipt_power_collect` | `*/5 * * * *` | m | `services/ipt_data/ipt_power_collector.py → run_ipt_power_collect` |
| RAN Element Management Sync | `ran_element_management_sync` | `0 23 * * *` | u | `services/RANElementManagement/ran_element_management_service.py → run_ran_element_management_sync` |

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

**What it does**: Full-window backfill (default since 2026-01-01) to cover delta gaps and refresh reports. Wide windows fetch TT/WO in segments; a missing TT/WO now fails the task

**Workflow & data flow**:

1. Daily 01:00 pull the full window
1. For wide windows TT/WO are fetched in **segments** (default 30 days each) then merged/deduped, avoiding a single huge export exceeding the 120s poll window and failing with 500
1. Write into the same dynamic tables with dedup
1. Refresh related report artifacts afterwards

**Maintenance**:

- First remedy when eFlow data is missing mid-day — run it manually from Task Manager
- The window start is configurable; mind the fetch duration. Segment length via EFLOW_FULL_SEGMENT_DAYS (default 30d)
- Fixed 2026-10-09: the TT/WO full export had been failing with 500 for days while the task still reported success=True (the missing key was silently skipped). Now a missing TT/WO writes an error → success=False

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

#### WhatsApp Message Send (Baileys)（`whatsapp_send_baileys`）

- Default cron: `0 4 * * *`　|　worker group: **m**
- Workflow script: `services/whatsapp_send_baileys_service.py → run_whatsapp_send_baileys`

**What it does**: Third WhatsApp image-sending channel: dispatches via the Baileys protocol directly (no browser/Playwright), parallel to the Playwright/extension versions; disabled by default — enable manually from the Task Manager page (Baileys violates WhatsApp ToS, so manual approval is required before enabling)

**Workflow & data flow**:

1. This task scans SITE_OUTAGE_DIR (shared with whatsapp_send / whatsapp_send_ext) and writes items (with absolute disk paths) into the job file data/whatsapp_send_baileys_job.json
1. The whatsapp-kb-bot/src/notify.js process polls and claims the job (sets running on claim + atomic write-back), then calls sock.sendMessage({ image|document, ... }) for each (group × file) pair
1. The server-acknowledged message id (res.key.id) is the only success criterion; a single failed send is not retried into the group (prevents duplicates); auto_retry_failed decides on retries
1. notify.js writes the result back to the job file; this task returns once it sees done/failed (task_runner records the run history)

**Maintenance**:

- enabled=False by default — the task will NOT auto-run on a fresh deployment. First confirm the whatsapp-kb-bot notify process is up and the auth-notify/ credentials are valid, then enable manually from the Task Manager page
- Exempted from the master switch (MASTER_SWITCH_EXEMPT_IDS); bulk toggles skip this task
- Coexists with whatsapp_send (Playwright 0 3 * * *) rather than excluding it; the 1-hour cron offset avoids two copies of the same images being delivered in the same window
- The server-side message id is the success criterion (not a guess), unlike the extension channel which counts DOM bubbles; this is the root-cause fix for the 2026-09-15 SP Details Report 1.5MB silent-drop incident
- Group-send rate limiting is controlled by whatsapp-kb-bot/config.json → notify.fileSend (default 6 images + 1 document per job)

#### eFlow P1 Alarm WhatsApp Push（`tt_alarm_whatsapp_alert`）

- Default cron: `2-59/5 * * * *`　|　worker group: **m**
- Workflow script: `services/tt_alarm_whatsapp_service.py → run_tt_alarm_whatsapp_alert`

**What it does**: Trigger-based push: every 5 min (phase 2-59/5, offset 2 min from the upstream sync) scan realtime_alarm for TT-linked P1 alarms inside the trigger window, live-fetch eFlow for each ticket, first-push, then re-notify every 20 min while the ticket has no update (with a REMINDER banner), and stop when the alarm clears. Send status (sent? how many times) is recorded in eflow_tt_whatsapp_alert_log

**Workflow & data flow**:

1. Scan realtime_alarm (synced by eflow_active_alarm — registry default */30, actual schedule from the task config page, currently */5): tt_id present, alarmraisedtime inside the trigger window, alarm code whitelisted, deduped by tt_id
1. Live-fetch each triggered ticket from eFlow (fetch_tt_live_batch, one paged walk) for the latest ticket_severity / last_modified_time / alarm_clear_time; fall back to the local eflow_tt mirror
1. Push only matching severities: first push carries the full analysis; re-notify when stalled ≥20 min and cooled ≥20 min (with a ⚠️ REMINDER #N banner); while the ticket progresses, only tracking fields are refreshed
1. Messages go through the Baileys push process (whatsapp-kb-bot/src/notify.js); send_status becomes Y only on the server-side ack (send_count counts confirmed sends)

**Maintenance**:

- 2026-10-05 redesign: trigger source moved from eflow_tt polling to realtime_alarm + live fetch, cutting first-notify latency from 45–75 min to minutes; window_minutes now means the trigger window
- Depends on eflow_active_alarm's sync cadence: if realtime_alarm._sync_time lags past 1.5× the actual schedule interval (adaptive — about 1.5 min under the current */1), the task result raises a warning (guards against a silently empty trigger set)
- The 99933 exclusion stays in Python — both '99933' and '99933.0' exist in the DB, so SQL predicates miss rows; empty whitelist = no filter
- Never-confirmed sends retry on the same throttle; a round with zero confirmed sends raises a warning via WeChat/email (root fix of the 2026-10-01 silent-outage incident)
- An empty group list falls back to the test group test123 with an explicit warning in the task result (group_fallback=true) — alerts never vanish silently

#### MS SLA Full Sync（`ms_sla_full`）

- Default cron: `0 5 * * *`　|　worker group: **n**
- Workflow script: `services/ms_sla_service.py → run_full_sync`

**What it does**: SLA metrics sync + Contract KPIs report update (self-contained, no external files)

**Workflow & data flow**:

1. Every 6h recompute NUR/SLA/WO metrics via the live nur_calc logic
1. Write to data/ms_sla/ms_sla_dashboard.sqlite3
1. Feeds the MS SLA board and two daily report emails

**Maintenance**:

- Board numbers follow this live calculation (snapshot files may differ)
- Adjust criteria in backend/services/nur_calc.py

#### DC Server Alarm WhatsApp Push（`ume_alarm_whatsapp_alert`）

- Default cron: `* * * * *`　|　worker group: **m**
- Workflow script: `services/ume_alarm_whatsapp_service.py → run_ume_alarm_whatsapp`

**What it does**: Pulls the current alarm snapshot from the ZTE UME NMS (10.121.8.2) every minute and pushes to the configured group only when an exact "alarm-code:severity" pair matches (default 89029:major, 89006:major); uncleared alarms are re-notified at the configured interval (with a REMINDER banner) and alarms that disappear upstream get a "recovered" notice; the first round only registers and sends nothing (to avoid flooding the group with the backlog)

**Workflow & data flow**:

1. Fetch the current UME alarm snapshot every minute
1. Filter on exact alarm-code:severity pairs
1. Push via WhatsApp; re-notify uncleared alarms at an interval and send a recovery notice when they disappear

**Maintenance**:

- The first round only registers and never sends, so the existing backlog is not dumped into the group
- Independent of the eFlow tt_alarm_whatsapp_alert channel (different upstream and alarm-code scheme)

#### Fiber Break Alarm Auto Assign（`eflow_fiber_assign`）

- Default cron: `3-59/5 * * * *`　|　worker group: **m**
- Workflow script: `services/eflow_fiber/fiber_assign_service.py → run_fiber_assign`

**What it does**: Queries eFlow active alarms; when the alarm code matches the whitelist (default 4758 Fiber Break, configurable), it has been alive for at least 15 minutes (assign delay, configurable), is within the trigger window AND the same site has no 99933 alarm in the same time window, resolves the ME name to site ID + site name and assigns a TT to the configured user group; after assigning, re-queries ttid to confirm the TT really exists (with retries) before notifying the WhatsApp group. Dry-run by default

**Workflow & data flow**:

1. Query eFlow active (uncleared) alarms
1. Filter by alarm code + alive for at least 15 minutes (assign delay) + trigger window + no 99933 on the same site (if the site names do not line up, treat it as "no correlation" and keep going)
1. Skip alarms that already carry an upstream TT (ttid) or were already assigned
1. Resolve the ME name to a site name then look up the numeric site ID in cmdb (exact -> normalized -> equal-length vowel-swap)
1. Call the assign API to create a TT -> re-query ttid to confirm -> notify WhatsApp

**Maintenance**:

- Assign delay of 15 minutes: the alarm must have been alive for at least 15 minutes before it is assigned and notified to WhatsApp (business rule: "assign only after the alarm has lasted more than 15 minutes") — it is NOT dispatched the moment it raises; the delay lets short transient breaks clear by themselves. Set it to 0 to restore immediate dispatch
- Dry-run (dry_run) by default: match + record only, no real assign; turn it off on the Task Config page once verified
- When the 99933 correlation cannot be determined (fiber only has an ME-derived site name that differs from cmdb, e.g. luogan/luogon) the alarm is treated as "no correlation" and still assigned, with the count logged under correlation_undetermined — never let a name mismatch silently block assignment indefinitely
- When site resolution fails (site absent from cmdb, e.g. Tokadeh) the TT cannot be created automatically: record N and post a "manual handling required in eFlow" notice to the group, once per alarm (suppressed via send_status) so nothing is silently dropped
- Fiber assign must carry the numeric site ID + site name; passing only the ME name makes the API return success without creating a TT (measured lesson)
- Fiber assign is intermittent, so it retries and only treats success as confirmed when ttid is found (never trusts status:true)
- Skip alarms whose upstream ttid is already set: eFlow's own assign rule may have created the TT first, otherwise duplicate TTs are created (measured: two Zardun alarms)
- The 99933 correlation compares site identity as a set of keys (numeric site id + site name): the site/mename shapes differ between 4758 and 99933, a single-key compare silently misses the match
- Site-name fuzzy matching only accepts "equal length + vowel swaps only" (e.g. luogan -> luogon): scanning all 830 sites in the production cmdb showed generic 0.9 similarity merges distinct sites such as Garplay/Gbarplay, Butuo/Buutuo and Sanniquillie 5/1. Phase sites (X vs X2) and ambiguous candidates are also rejected. Hits are reported in warnings and flagged in the notification for manual review
- A non-zero eFlow-side ttstatus no longer blocks assignment (2026-10-27 requirement: never let an unbound ME stop the assign): it still tries, but with a minimal budget (1 attempt x 2 re-queries); if no TT appears it records N and posts a single "manual handling required in eFlow" notice to the group, and picks the alarm up automatically once the ME-to-site binding is fixed
- One fiber cut means one TT (2026-10-27): a single cable break raises alarms on every site along the link (measured: 5 alarms within 9 seconds at 14:21, producing 5 duplicate TTs). Alarms raised within the merge window (group_window_minutes, default 10 minutes) are merged into ONE TT, created on the earliest alarm of the group (the most likely root cause); the others share the same TT number and the notification lists every site covered. Set it to 0 to disable merging (rollback switch). The window is used because no existing data source can prove "same fiber": probeid is one shared UUID, impact_site_list/link_path are empty, flm_database.fdn is shared by 96 sites (far too coarse), R.I.A and Tower Hill are not related in victim_topology (independent gateways), and eFlow relatedAlarms returns 0 rows
- State recorded in eflow_fiber_assign_log: Y = assigned / upstream TT already existed, D = dry-run (reprocessed once dry_run is off), N = failed and retried next round
- The TT title is auto-generated by eFlow as `<site>.[<site name>]<alarm>`; the API does not accept a custom title
- Notifications are English-only (2026-10-27 requirement): field labels, warning lines and failure reasons are all English; Chinese stays in the status table last_error, the result warnings and the logs, because the group is an English-speaking front line

#### 5G Site Alarm Auto Assign（`eflow_5g_assign`）

- Default cron: `8-59/5 * * * *`　|　worker group: **m**
- Workflow script: `services/eflow_5g/g5_assign_service.py → run_5g_assign`

**What it does**: Queries eFlow active alarms; when the alarm code matches the whitelist (MULTIPLE codes supported; default 200201001 DU cell out-of-service, 200201018 Super cell CP out-of-service, 200201041 gNodeB DU out-of-service, 200201043 NSA unavailable, 200201060 Super MIMO cell CP out-of-service, configurable), it has been alive for at least 15 minutes (assign delay), is within the trigger window AND the same site has no 99933 alarm in the same time window, assigns a TT to the configured user group; when several cells of the same gNB go out of service at once, the alarms are merged into ONE TT and the notification lists every cell covered; after assigning, re-queries ttid to confirm the TT really exists before notifying the WhatsApp group. Dry-run by default

**Workflow & data flow**:

1. Pull eFlow active alarms with server-side code filtering (measured 21 rows / 0.03s vs 6752 rows / 4.45s for a full scan)
1. Periodic full-scan audit: raises a warning if an alarm code is missed by the restype configuration (it would otherwise never trigger silently)
1. Filter by alarm code + alive for at least 15 minutes (assign delay) + trigger window + no 99933 on the same site
1. Skip alarms that already carry an upstream TT (ttid) or were already assigned
1. Merge the multi-cell alarms of one site by site + time window (cell 50/51/52)
1. Call the assign API to create a TT -> re-query ttid to confirm -> notify WhatsApp (the text lists the cells covered)

**Maintenance**:

- Multiple alarm codes are supported (explicit requirement); edit the comma-separated list on the Task Config page; leaving it empty falls back to the 5 default out-of-service codes
- Assign delay of 15 minutes: the alarm must have been alive for at least 15 minutes before it is assigned and notified to WhatsApp (requirement: "assign and push once the 5G site alarm has been up for 15 minutes") — it is NOT dispatched the moment it raises; the delay lets short transient jitter clear by itself. Set it to 0 to restore immediate dispatch
- Dry-run (dry_run) by default: match + record + render the notification that WOULD be sent (dry_run_preview in the task result, never delivered); turn it off on the Task Config page once the wording and the Cells line look right
- One-site multi-cell dedupe: several cells of the same gNB going out of service each raise their own alarm; without merging that is a pile of duplicate TTs. They are merged into ONE TT by site + time window, and the notification lists the cells covered
- Only alarms on the same site are merged — two different sites going out of service at the same time still get one TT each (those are two separate faults)
- The 5G site field is already the numeric site ID and sitename is already the site name (measured 4162/Liscr), so unlike Fiber there is no need to resolve the ME name against cmdb
- Server-side code filtering must carry a restype (alarmcode alone returns HTTP 499) and wildcard restypes are not supported (zte.ran.* returns 0 rows) → only explicit values can be enumerated; 12 common RAN restypes are configured by default
- The full-scan audit is the key guard against silent failure: a missed restype means an alarm code can never be fetched and raises no error at all; the audit reports it as a warning (measured: codes without live instances do not break the query — HTTP 200)
- When the 99933 correlation cannot be determined the alarm is treated as "no correlation" and still assigned, with the count logged under correlation_undetermined — never let a site-info mismatch silently block assignment indefinitely
- When site resolution fails the TT cannot be created automatically: record N and post a "manual handling required in eFlow" notice to the group, once per alarm (send_status suppression), so nothing is silently dropped
- A non-zero eFlow ttstatus does not block assignment: it is still attempted but with a minimal retry budget, and on failure a notice asks a human to fix the site binding in eFlow
- eFlow assign is intermittent, so it retries internally, and success is judged only by re-querying ttid (the API status:true is not trusted)
- Skip alarms that already carry an upstream ttid: eFlow own assign rules create some TTs first, and skipping avoids duplicate TTs

#### CMDB Site Sync Diff（`eflow_site_update`）

- Default cron: `0 7 * * *`　|　worker group: **m**
- Workflow script: `services/eflow_site_update_task.py → run_eflow_site_update`

**What it does**: Diffs the CMDB master data (newest ZTE OLR MS Master Site Database under my_app/db) against the eflow baseline and the PG master_site_db baseline, producing colour-coded A/M/D workbooks (eflow_site_update.xlsx / master_site_db .xlsx / import copies / sync report). Generates review files only - never writes to eflow or PostgreSQL

**Workflow & data flow**:

1. Scan the newest CMDB master source under my_app/db
1. Diff it field by field against the eflow baseline and the PG master_site_db baseline
1. Produce colour-coded A/M/D workbooks (eflow_site_update.xlsx / master_site_db .xlsx / import copies / sync report)
1. Downloadable from the Email Reports "Site Sync" tab for manual review

**Maintenance**:

- Review files only, never writes: the service explicitly passes --pg none --cmdb none; import is done manually after review
- Runs once daily at 07:00 as a fallback; disabling the schedule does not affect the page button (manual trigger stays available while the task is enabled)
- Can also be triggered manually from the Task Management page

#### eFlow Realtime Alarm Sync（`eflow_active_alarm`）

- Default cron: `*/1 * * * *`　|　worker group: **x**
- Workflow script: `services/eflow_api_client.py → fetch_and_save_active_alarm`

**What it does**: Fetch realtime alarms from eFlow FM Active API, save to CSV + SQLite (every minute)

**Workflow & data flow**:

1. Pull FM Active alarms every minute (both the registry default and production config are */1)
1. Dual-write app.db realtime_alarm and an eflow.sqlite3 copy (report-only)
1. Feeds the realtime alarm board / realtime map / alarm management board, and is the trigger source of the P1 alarm WhatsApp push

**Maintenance**:

- Pages read app.db only; "realtime" granularity = the actual schedule (now 1 minute), not second-level push
- Change the schedule in the Task Config page (persisted in task_schedule_config, which overrides the registry default)
- Split from group n into its own group x on 2026-10-15: it used to share a serial lane with eflow_sync, so even a tighter cron got blocked by long tasks (worst queue wait 854s)
- ⚠️ The 1-minute cadence relies on session reuse (ensure_login hits the in-process/disk cache instead of logging in); re-evaluate the frequency if that logic changes
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

#### CNN UME KPI 5-Min Sync（`cnn_kpi_sync_5mins`）

- Default cron: `*/15 * * * *`　|　worker group: **n**
- Workflow script: `services/cnn_ume_kpi_5mins_service.py → run_cnn_kpi_sync_5mins`

**What it does**: Same source and account as "CNN UME KPI Sync", but at fine granularity (5-minute for 5 templates, 15-minute for 3) with a yesterday-00:00-to-now window; writes into new 5mins_* tables in DB CNN for the Day0/Day1/Day7 overlay on the CN KPI 5-minute board. Daily/monthly tables are untouched

**Workflow & data flow**:

1. Log into CNN UME (shares the session cache with cnn_kpi_sync)
1. Query all 8 templates in parallel at 5-minute granularity (yesterday 00:00 to now)
1. Upsert into db_ps_cs_cn tables named 5mins_<original table>

**Maintenance**:

- WARNING: mixed granularity — Voice / VLR / Data / 4G FDD / Free Rating use the 5-minute tier (gr=300); xGW License, xGW CPU and 3G FDD had no 5-minute tier and now use the upstream 15-minute templates created 2026-10-19 (gr=900, see FIFTEEN_MIN_TEMPLATES)
- WARNING: the task keeps a "0 rows → skip this table and do not fail" fallback (the original cnn_kpi_sync raises on 0 rows — this task deliberately differs) so an upstream tier change cannot make it fail every 15 minutes
- WARNING: one run takes about 105 s (Free Rating alone has 14k rows/day); if it approaches 15 minutes, lower the concurrency or widen the schedule
- Runs in group n alongside cnn_kpi_sync so the two never log into the same account and kick each other off
- The only consumer is ?page=cn_kpi_5mins (services/cn_kpi_5mins_service.py reads the 5mins_* tables)

#### SP Spare Data Sync（`sp_data_sync`）

- Default cron: `10 * * * *`　|　worker group: **s**
- Workflow script: `services/get_sp_table.py → run_sp_data_sync`

**What it does**: Pull 5 spare-part reports from SFTP (Inbound/Outbound/Inventory/OC Rule/Transfer) into app.db, then mirror into FineBI WareHouseDashBoard inventory.db

**Workflow & data flow**:

1. Log into the spare-parts SFTP (credential group sftp_sp)
1. Fetch the 5 reports
1. Clean and write into the main DB for the warehouse board and SP reports; before writing, Material Name is resolved by Material No. from the sp_material master (latest name), so a renamed material no longer shows up in two spellings on the board
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

- Default cron: `0 * * * *`　|　worker group: **u**
- Workflow script: `services/ipran_ume_kpi_service.py → run_ipran_kpi_sync`

**What it does**: iPRAN UME M6000 router KPI sync (HQ M6K-FW etc.), export Excel + SQLite import + FTP upload

**Workflow & data flow**:

1. Log into iPRAN UME, query M6000 router KPIs
1. Export Excel, write data/ipran_ume/ipran_ume_kpi.sqlite3, FTP upload

**Maintenance**:

- Output also feeds ipran_m6k_chart_email (06:45), which reads whichever hourly round finished last; the hourly full pull is the intended cadence (confirmed with the user 2026-11-06, code default now matches)

#### Liberia Site-Down 1H Report Email（`liberia_email_1h`）

- Default cron: `15 * * * *`　|　worker group: **m**
- Workflow script: `services/liberia_email_report.py → run_1h_report`

**What it does**: Email the Liberia Orange Site Down hourly Report (inline charts + Excel) to recipient lists

**Workflow & data flow**:

1. Hourly :05 aggregate the last hour of site-down data
1. Build the inline-chart + Excel report
1. Send to the to/cc lists (managed in Settings)

**Maintenance**:

- When EWS is down, email_recovery (every 20 min) re-sends automatically once restored

#### Liberia Site-Down 8H Report Email（`liberia_email_8h`）

- Default cron: `20 */8 * * *`　|　worker group: **m**
- Workflow script: `services/liberia_email_report.py → run_8h_report`

**What it does**: Email the Liberia Orange Site Down 8-hour Report (inline charts + Excel) to recipient lists

**Workflow & data flow**:

1. Every 8 hours (:10 of 00/08/16) aggregate site-down data
1. Build and send the inline-chart + Excel report

**Maintenance**:

- Same script as the 1H version, different entry; recipient changes apply to both

#### MS Contract KPIs Daily Report Email（`kpi_ms_contract`）

- Default cron: `30 5 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_ms_contract_kpi`

**What it does**: Email the MS Contract KPIs Achievements Daily Report (local data + remote recipient list)

**Workflow & data flow**:

1. Read local ms_sla data produced by ms_sla_full (05:00)
1. Build the Contract KPIs daily report
1. Send to recipients from the remote list

**Maintenance**:

- Data comes from ms_sla_full (05:00 sync, ~05:11 done); this task sends at 05:30 using that same-day round

#### MS WOs SLA Daily Report Email（`kpi_ms_wo_sla`）

- Default cron: `35 5 * * *`　|　worker group: **m**
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

**What it does**: Refresh the sp_material master from eFlow first, then download spare-part data from SFTP and generate Comsumables & SpareParts Inbound&Outbound&Inventory reports into data/sp_email; Material Name in details and raw snapshots is resolved by Material No. from the master (latest name)

**Workflow & data flow**:

1. Step 0: call sp_material_sync to pull the full material master from eFlow into sp_material (on failure only warn and keep the existing table)
1. Log into SFTP, download raw spare data and keep an unfiltered *_source.xlsx snapshot
1. Exclude list → status filter → Canceled/Terminated filter (Operation Result Status) → **Material Name resolved from the master** (5 details + 5 snapshots, names only, no row changes)
1. Generate the Comsumables & SpareParts Inbound&Outbound&Inventory reports (incl. Summary-Current replenishment)
1. Save to data/sp_email for the 09:45/09:50 email tasks and the 07:05 details email

**Maintenance**:

- Upstream of 3 SP email tasks — its failure blanks all spare-part emails for the day

#### SP Weekly Report (Monday → Sunday)（`sp_weekly_report`）

- Default cron: `0 7 * * mon`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_weekly_report`

**What it does**: Every Monday 07:00 build the SP weekly report for the previous full natural week (last Monday 00:00 – Sunday 23:59) and email it; both the file name and the subject carry the period

**Workflow & data flow**:

1. Read the filtered inband / outband / inventory details under data/sp_email/data (produced by sp_report_generate at 05:15 daily)
1. Filter by the period window: end = the last finished Sunday, start = end minus 6 days, so it is always Monday 00:00:00 – Sunday 23:59:59; a Monday run covers last Monday – last Sunday. Site name and site ID come from the WO/TT/PMT ticket (Related Ticket Title / Site Id)
1. Build 8 sheets: Summary / Inventory / Inbound&Outbound Summary / Daily report (7 dynamic weekday+date columns) / Top 10 Consumed Spares / Replenishment / Details / Warehouse-info
1. Save data/sp_weekly/SP Weekly Report <start> to <end>.xlsx and email it as an attachment

**Maintenance**:

- Always write day_of_week as mon / sun, never as a number: APScheduler maps 0 to Monday and 6 to Sunday, the opposite of Linux cron
- The window is aligned to a natural week: --week-end must be a Sunday or it raises; never fall back to "yesterday minus 7 days", which drifts to Tuesday → Monday when re-run mid-week
- Quantities display their unit (7PCS / 50Meter) but stay numeric underneath; a cell mixing units is text (4PCS+50Meter) and cannot be summed
- The Replenishment sheet reuses gernarate_sp_report.build_replenishment on purpose; never re-implement the safety-stock rule
- Recipients live under Settings → Email Recipients → sp_weekly_report, falling back to the SP shared list

#### SP Spare Parts Details Report Email（`sp_email_details`）

- Default cron: `5 7 * * *`　|　worker group: **m**
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
- Since 2026-10-11 the WhatsApp side goes through "Baileys primary → Playwright fallback" (whatsapp_dispatch); the sender becomes the Baileys secondary account

#### SP Spare Parts Details Files Email（`sp_details_files_email`）

- Default cron: `5 10 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_details_files_email`

**What it does**: Daily 10:05: send the 6 spare-part detail files under data/sp_email/data to NOC as ONE EMAIL PER FILE, subject "Liberia OLR W.H <file name> <date time>"

**Workflow & data flow**:

1. Resolve each detail file: prefer the unfiltered *_source.xlsx raw snapshot (the SFTP snapshot sp_report_generate keeps at 05:15 before any filtering), falling back to the filtered *_details.xlsx
1. Check all 6 files up front: if any one is missing the whole run fails and NOTHING is sent (better no email at all than an incomplete set of reports)
1. Stage a copy of each under TMP using the OUTBOUND name (on disk they are inband/outband, recipients see inbound/outbound, and all 6 carry the _source suffix); the copies are removed after sending
1. Send one by one — each email carries exactly one attachment, subject "Liberia OLR W.H <attachment file name> <date time>" (e.g. Liberia OLR W.H inbound_details_source.xlsx 2026-09-30 10-05-00)
1. A single send failure does not stop the rest: the remaining files still go out, and the failures are reported by name so only those need a manual resend

**Maintenance**:

- Default To MS.NOC@zte.com.cn, Cc li.jing132@zte.com.cn / luo.wutao@zte.com.cn; overridable in Settings → Email Recipients, group sp_details_files
- Outbound file names differ from the on-disk source names (per user request): inband/outband become inbound/outbound, and all 6 carry the _source suffix, so attachments must be staged under the outbound name first (owa_mail_report uses Path(fp).name as the attachment name)
- Same data source as sp_email_details (05:00) but a different package: that one merges into a single multi-sheet workbook and posts to the WhatsApp group, this one sends one file per email to NOC — they do not affect each other
- One email per file means up to 6 EWS sessions per run, roughly 6x the duration of a single send; the task runs serially in group m, so a long run delays the other light tasks there
- On a single-send failure the error carries only the SEND_FAIL marker plus file names, never the raw exception text — otherwise an EWS keyword would make email_recovery resend all 6 and duplicate the ones that already went out; the details live in result.failed
- ocrule_details has no *_source snapshot and only the filtered version exists on disk, but per the user request (2026-10-09) its outbound name carries _source like the others; so "name has _source, content is filtered" is expected, not a wrong file
- Upstream is sp_report_generate (group m, 05:15): if detail files are missing, investigate that task rather than this one

#### Comsumables&SpareParts Report Whatsapp（`sp_whatsapp_report`）

- Default cron: `55 7 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_whatsapp_report`

**What it does**: Daily 07:55: send the same assets used by the Comsumables / SpareParts report emails (consolidated XLSX + report PNGs) to the WhatsApp group WH&SP Management

**Workflow & data flow**:

1. Pick the consolidated Comsumables / SpareParts XLSX under data/sp_email (excludes the " - Liberia" per-site files)
1. Collect the PNGs of both reports (main chart first, Summary-Changed last)
1. Send via whatsapp_dispatch: Baileys primary → Playwright fallback, to the group WH&SP Management

**Maintenance**:

- Upstream is sp_report_generate (group m, 05:15) — if it fails this task finds no report files
- No email is sent here; emails are handled by kpi_sp_consumables / kpi_sp_spareparts
- Since 2026-10-11 uses the "Baileys → Playwright" dual channel; this task sends 4 images + 2 xlsx, so the Baileys per-job document quota must be ≥2 (raised to 8 images / 3 documents)

#### SP Material Stock & Consumption Report Email（`sp_material_report`）

- Default cron: `45 7 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_material_stock_consumption`

**What it does**: Daily 07:45: export the SP material stock & consumption summary (same scope as the page=sp_material page) to a UNIFIED_EXCEL_V1 Excel attachment plus an inline PNG of the same table, and email it

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

- Default cron: `*/10 * * * *`　|　worker group: **m**
- Workflow script: `services/email_recovery.py → run_email_recovery_task`

**What it does**: Probes EWS every 10 minutes; once restored, re-sends email tasks that failed due to EWS timeouts in the last 3 hours

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

- Depends on the latest hourly ipran_kpi_sync round; empty charts or failure follow u-group sync failures

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

- Default cron: `10 7,19 * * *`　|　worker group: **m**
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

- Default cron: `20 * * * *`　|　worker group: **m**
- Workflow script: `services/incident_overview_sync.py → run_incident_overview_sync`

**What it does**: Hourly at minute 20: pull the latest incident_overview.xlsx from all subfolders of FineBI FTP /webroot/WEB-INF/schedule/TT_WO/, stored as versioned files + a current.json pointer

**Workflow & data flow**:

1. Scan all TT_WO/ subfolders on FineBI FTP at minute 20 each hour
1. Save the latest incident_overview.xlsx as a versioned file + current.json pointer
1. Best-effort refresh of the incident_overview.xlsx snapshot for the incident overview page

**Maintenance**:

- The versioned design survives the upstream Excel being locked open — a hard-won fix, do not revert to direct overwrite
- Keep the schedule at minute 20 — FineBI deletes the previous output folder at :53 and the new copy lands around :02–:05, so an on-the-hour run hits that gap and reports a false "incident_overview.xlsx not found" (seen in 2026-09); inside the gap it reuses a local copy younger than 90 minutes instead of failing

#### FineBI Report Files Sync（`finebi_report_sync`）

- Default cron: `10 * * * *`　|　worker group: **m**
- Workflow script: `services/finebi_report_sync.py → run_finebi_report_sync`

**What it does**: Hourly: pull the latest Excel from each subfolder of FineBI FTP /webroot/WEB-INF/schedule into data/finebi_reports for the Task Report Files page; a folder with no file this cycle is only recorded as missing instead of failing the whole task

**Workflow & data flow**:

1. Hourly :10 walk every subfolder under schedule
1. Download the latest Excel per folder into data/finebi_reports
1. Folder empty this cycle but a local copy exists → record as missing and continue
1. Listed & downloadable under Task Report Files → FINEBI report tab

**Maintenance**:

- Stuck pending and broke the chain when group mode enabled on 2026-08-25 (ungrouped); now in group m — always register new tasks in GROUP_TASK_MAP
- FineBI deletes the previous output folder at :53 and the new copy lands around :02–:05, so one empty folder is normal: only a folder with no local copy at all counts as an error, otherwise that gap reddens every other report that synced fine

#### DB Data Freshness Check（`db_freshness_check`）

- Default cron: `15 * * * *`　|　worker group: **m**
- Workflow script: `services/db_freshness_check.py → run_db_freshness_check`

**What it does**: Hourly freshness audit of remote DBs (via db_writer_api), local fallback DBs, and local file-based sources (FTP-pulled Excel files) by their on-disk age; outputs call chain and guidance when stale

**Workflow & data flow**:

1. Hourly :15 check the latest data date per table in remote & local fallback DBs
1. Also judge local file-based sources by the age of their newest file (e.g. incident_overview.xlsx for the incident overview page)
1. When stale, log the call chain and troubleshooting direction in the execution history

**Maintenance**:

- Suspect stalled data? Check this task's history first and follow its call chain — faster than browsing the task list
- A sync job succeeding and its data being hours old are two different facts: on 2026-09-30 the incident overview page sat 2h stale while only task alerts fired, so file age is now checked separately (FILE_CHECKS) — add an entry whenever a new page reads a file instead of a table

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

- Default cron: `45 * * * *`　|　worker group: **p**
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

- Shares the NMS session with the daily task — serialized in group n; the board's auto refresh is off by default (enable per page in the header, suggested 900s) and uses soft refresh when on

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

#### SOC Multi-Dim Trend Sync（`soc_trend_sync`）

- Default cron: `40 * * * *`　|　worker group: **v**
- Workflow script: `services/soc_trend/soc_trend_sync.py → run_soc_trend_sync`

**What it does**: Hourly read-only pulls from the VMAX GBase warehouse: traffic / TCP / per-service categories (traffic, video, web, game, OTT voice, OTT video) aggregated at hour and day granularity, feeding the SOC multi-dim trend dashboard (dual-baseline alarms, D/D-1/D-7 comparison)

**Workflow & data flow**:

1. At :40 hourly, open a dedicated pymysql connection to the VMAX GBase warehouse (read-only guard: SELECT / SHOW / DESC only)
1. Probe partitions with SHOW TABLES, then run ciservice (by area + targetid), spservice (by area x service) and the video-specific aggregates per partition
1. Delete-then-insert whole days into data/soc_trend/soc_trend.sqlite3 (hour table ~94 days, day table ~90 days; the last 2 days are re-pulled every run, other days are back-filled only when missing)

**Maintenance**:

- Same VMAX warehouse as olib_soc_* / vmax_cxo_daily_sync but on its own connection, so it does not consume the local 8790 portal proxy session; serializing within the group is enough and sessions do not collide
- When GBase is unreachable the run degrades gracefully (records the error, no exception); once the link is back the missing-partition back-fill resumes automatically, no manual reload needed
- Registered on 2026-10-30 with TASK_SPECS only and no worker group, so the first scheduled run (23:15:55) was never claimed and got expired as failed; group v was added on 2026-10-31

#### OLIB SOC Dashboard KPI Sync（`olib_soc_kpi_daily_sync`）

- Default cron: `20 6 * * *`　|　worker group: **m**
- Workflow script: `services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_kpi_sync`

**What it does**: Daily incremental fill of the 90-day CXO dashboard KPI store (daily_kpi): only the 7 dashboard blocks, missing days plus days whose key metrics are NULL plus the newest day re-read; also tops up the drill-down detail tables (per-app video/game + per-NE TCP), no Excel output

**Workflow & data flow**:

1. Daily 06:20 connect straight to the VMAX GBase DWH (10.123.255.12:5258, db zxvmax)
1. Run only the 7 board blocks (traffic/active users/cache/video/game/TCP/top services)
1. Fetch missing days, days with NULL key metrics and re-read the newest day (7-day lookback, idempotent) into daily_kpi in data/olib_soc_report/olib_soc_report.sqlite3
1. Top up the drill-down detail tables by their own gaps (any of video/game/tcp missing a day); per-NE TCP comes from pseudo-block tcp_ne (one read-only SELECT), disable via blocks.tcp_ne=false

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

- Default cron: `35 */6 * * *`　|　worker group: **n**
- Workflow script: `services/sp_online_sync.py → run_sp_online_sync`

**What it does**: Every 6 hours: fetch online tickets from the eFlow SP APIs (sp-outbound/sp-inbound/sp-transfer) into the matching tables. Takes the union of the original filter and the all-status filter so a filter contradicting its own results can never silently pick the wrong data. Tables mirror the upstream snapshot: a full rebuild removes tickets that have vanished upstream

**Workflow & data flow**:

1. At :35 every 6 hours call the three eFlow SP APIs, each once with the original filter and once with the all-status filter
1. Merge both result sets by woId and write tables sp_outbound / sp_inbound / sp_transfer
1. Full rebuild: after upserting, delete rows whose woId is not in this run; on an incomplete fetch it only upserts and never deletes
1. Warn when every returned row has a status outside the filter enumeration (filter contradicts results)
1. Queryable in Table Browser; the Outbound leg of sp_online_report_generate consumes sp_outbound directly

**Maintenance**:

- Upstream account comes from the eflow credential group; a kicked eFlow session shows up as consecutive failures in the group, covered by auto_retry_failed
- Changed 2026-09-30 from "fall back to the all-status filter only when the original returns 0 rows" to a union: the old test mistook "this filter simply has no matches" for "the filter is broken", which turned inbound into a closed-ticket query (282 rows, all Closed) with no warning
- Upstream does not truly honour filter narrowing (inbound returns the same data for a 4-status and a 15-status filter), so never rely on filter precision
- Added 2026-10-09: full rebuild. The old implementation only upserted and never deleted, so tickets that vanished upstream stayed forever (37 zombie WaitingForUpdate rows in sp_outbound, surfaced as-is by the sp_online report). Safety valve: delete only when both filters succeed and the result is non-empty, otherwise degrade to upsert-only

#### SP Material Master Sync（`sp_material_sync`）

- Default cron: `55 4 * * *`　|　worker group: **n**
- Workflow script: `services/sp_material_sync.py → run_sp_material_sync`

**What it does**: Fetch the full material master from the eFlow SP API (eflow-sp-material) into app.db table sp_material (upsert by materialNo). The table mirrors the upstream snapshot: a full rebuild removes materials that vanished upstream

**Workflow & data flow**:

1. Daily 04:55 pull the full eflow-sp-material master
1. Upsert into app.db table sp_material by materialNo
1. Full rebuild: delete rows whose materialNo is not in this run; on an incomplete fetch it only upserts and never deletes
1. Queryable in Table Browser; sp_material_report builds the stock/consumption report from it

**Maintenance**:

- sp_material_report (07:45) only reads the table: if this task stalls, the email still sends but with stale content (db_freshness_check now covers sp_material freshness)
- Added 2026-10-09: full rebuild. The old implementation only upserted and never deleted, so materials disabled/deleted upstream stayed forever (same shape as sp_online). Safety valve: delete only when fetch_all is complete (no MAX_PAGES cap hit, non-empty), otherwise degrade to upsert-only

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

- Default cron: `35 6 * * *`　|　worker group: **m**
- Workflow script: `services/kpi_email_report.py → run_sp_online_report`

**What it does**: Send the open-ticket report: email (inline Inbound/Outbound PNG + XLSX attachments, default SP shared recipient list) + WhatsApp groups

**Workflow & data flow**:

1. Daily 06:35 pick up the newest sp_online report files
1. Email with inline PNG plus XLSX attachments
1. Also push to WhatsApp groups via whatsapp_dispatch (Baileys → Playwright); recipients overridable under Settings → Email Recipients

**Maintenance**:

- Depends on the 06:00 generation task output — missing files make this one fail outright
- An email task: excluded from missed-run backfill by default, email_recovery replays it once EWS is back
- In EMAIL_TASK_IDS: on WhatsApp failure the error carries only a fixed marker, never the raw exception text (so it cannot trip an EWS keyword and duplicate the email)
- Since 2026-10-11 the WhatsApp side uses the "Baileys → Playwright" dual channel; the sender becomes the Baileys secondary account

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

**What it does**: Every 3 days at 23:59 pull all rules from the eFlow config-center (every rule type — push/escalation/grouping/auto-close, etc.; the exact count follows eFlow config, read it from the exported Rule_Type_Summary sheet), merging detail per rule into eflow_push_rules.xlsx

**Workflow & data flow**:

1. Every 3 days at 23:59 query the config-center with filter="" for all rules (count of types follows eFlow config, see the Rule_Type_Summary sheet)
1. Merge the detail of each rule
1. Export backend/services/eflow_rules/eflow_push_rules.xlsx (Push_Rules + Rule_Type_Summary)

**Maintenance**:

- Low-frequency (every 3 days), same group and cadence as the alarm-rules collector
- Lives in services/eflow_rules/ next to the rule sheet used by eflow_tt_rules_check — do not rename paths

#### eFlow Push Rules Check（`eflow_push_rules_check`）

- Default cron: `10 5 * * 2`　|　worker group: **n**
- Workflow script: `services/eflow_rules/eflow_push_rules_check_task.py → run_eflow_push_rules_check`

**What it does**: Weekly (Tue 05:10): evaluate the latest 1000 eflow_tt tickets against the current TT Push Order rules (FOAccept), compare rule decision vs actual dispatch per ticket, and keep a weekly snapshot for run-to-run comparison

**Workflow & data flow**:

1. Refresh eflow_push_rules.xlsx via the collector subprocess (falls back to the existing file on failure)
1. Load the same sample as eflow_tt_rules_check (newest 1000 by created_time with an alarm_code)
1. Evaluate each ticket against FOAccept push rules: matched rule / builds WO / target handler / push path
1. Parse the actual dispatch (wo_no plus Operator / Assignee Group from fo_accept_detail)
1. Classify into consistent / mismatch / undecidable / unmatched, export xlsx and keep a snapshot under push_rules_snapshots/

**Maintenance**:

- Keep the sample definition identical to eflow_tt_rules_check, otherwise the two tabs show different totals
- Shares group n with eflow_push_rules_collect: both log in with the same eFlow account and would kick each other across groups
- The historical WO-rate query passes a Python-computed cutoff — datetime('now') only exists in SQLite
- Only the latest 10 snapshots are kept (_SNAPSHOT_KEEP); archive elsewhere if long-term retention is needed

#### WhatsApp KB Sync (Push Rules)（`whatsapp_kb_sync_push_rules`）

- Default cron: `4 0 */3 * *`　|　worker group: **n**
- Workflow script: `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_push_rules → whatsapp-kb-bot/scripts/sync-kb.mjs`

**What it does**: Fired after the push-rules collect: compares rule xlsx fingerprints and only re-exports docs, rebuilds the index and restarts whatsapp-kb-bot when something actually changed

**Workflow & data flow**:

1. Compare size+mtime fingerprints of the four rule xlsx files
1. Exit immediately when unchanged (no bot restart, avoids racing live questions)
1. When changed: export-kb → ingest → restart bot → verify the index matches disk

**Maintenance**:

- Idempotent by design: most runs do nothing and never restart the bot
- Fingerprints cover the rule xlsx only; hand-edited markdown under knowledge/ is caught by the "@bot ping" stale-index warning instead
- The realtime channel (questions with a TT number) reads the xlsx directly, so it stays correct regardless of this task

#### WhatsApp KB Sync (Alarm Rules)（`whatsapp_kb_sync_alarm_rules`）

- Default cron: `4 0 */3 * *`　|　worker group: **n**
- Workflow script: `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_alarm_rules → whatsapp-kb-bot/scripts/sync-kb.mjs`

**What it does**: Triggers a KB sync after the alarm-rules collect; compression rules come from eflow_alarm_rules.xlsx and unchanged runs are skipped

**Workflow & data flow**:

1. Compare rule xlsx fingerprints
1. When changed, re-export the compression-rules doc, rebuild the index and restart the bot
1. Exit immediately when unchanged

**Maintenance**:

- Shares the same sync-kb.mjs logic as the push-rules sync; only the trigger timing differs
- Compression rules drive knowledge-base answers such as "what does this alarm code compress into"

#### WhatsApp KB Sync (TT Level Rules)（`whatsapp_kb_sync_tt_rules`）

- Default cron: `35 4 * * *`　|　worker group: **n**
- Workflow script: `services/whatsapp_kb_service.py → run_whatsapp_kb_sync_after_tt_rules → whatsapp-kb-bot/scripts/sync-kb.mjs`

**What it does**: Triggers a KB sync after the daily 04:20 TT level-rules collect; level rules come from eflow_TT_rules.xlsx

**Workflow & data flow**:

1. Fires at 04:35, 15 minutes after the 04:20 collect so the xlsx is already written
1. Compares fingerprints and only re-exports the level-rules doc + rebuilds the index + restarts the bot when changed

**Maintenance**:

- Level rules are collected daily, so this task runs on a daily cadence too
- Does nothing when unchanged — the bot is not restarted every day

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

#### TTs and MTTR Report Generate（`tt_mttr_report_generate`）

- Default cron: `20 7 * * *`　|　worker group: **m**
- Workflow script: `services/tt_mttr_report.py → run_tt_mttr_report`

**What it does**: Builds the TTs and MTTR (Hour) monthly workbook from the latest Site Down hourly Report, downloadable from the "TTs and MTTR" tab of the report files page

**Workflow & data flow**:

1. Daily 07:20 read the newest hourly Report under data/eflow/tt_reports (Processed Data sheet)
1. Tickets with a WO go to Raw Data; then filter on occur-to-clear < 48h + non-empty Site Category + month >= 2026-01 into the ZTE sheet
1. Summary tallies TTs and MTTR per month per P1-P4 with COUNTIFS/AVERAGEIFS formulas and inserts 4 combo charts (bars = TTs, cyan line = MTTR, red line = SLA target)
1. Output name carries a timestamp; only the newest single file is kept — the previous one is deleted as soon as the new report is written

**Maintenance**:

- SLA attainment is always the actual occur-to-clear duration, never the source table SLA Time column (that one holds the target, not the duration)
- Tickets with an empty Ticket Severity are tallied in a separate N/A block without a chart (no SLA target) — otherwise they would be dropped silently
- The MTTR axis max is left to Excel auto-scaling so out-of-range months (e.g. P1 2026-05 at 16.37h) are not clipped
- Re-pause Summary against an independent pandas recomputation before changing the filter; this output is not in _cleanup_old_tt_reports, its size is bounded by KEEP_FILES here

#### RAN User Identity Lists (VoLTE/N78)（`gp_ran_user_sync`）

- Default cron: `20 13 * * *`　|　worker group: **g**
- Workflow script: `services/gp_ran/gp_ran_sync.py → run_gp_ran_user_sync`

**What it does**: Two-hop SSH via control1 into the RAN Greenplum, runs psql as gpadmin and pulls distinct VoLTE / N78 IMSI lists for the last 7 complete UTC days, writing CSV plus run counters; strictly read-only, nothing lands on the warehouse

**Workflow & data flow**:

1. Daily 13:20 UTC: connect to control1 (10.100.29.12:22), then open a direct-tcpip channel from it to the DB master 193.168.0.6:22
1. On the master: sudo -S -> su - gpadmin -> psql (database netmaxdb); the SQL travels base64-encoded to survive three nested shells
1. Window is [today-7, today) of complete UTC days, excluding the still-accumulating current day; one COPY ... TO STDOUT WITH (FORMAT csv, HEADER true) per filter
1. CSV is written atomically into backend/data/gp_ran/ (volte_from_to.csv / n78_from_to.csv); the side-car sqlite keeps only counts and paths, and the read-only guard rejects writes and TO PROGRAM

**Maintenance**:

- The password lives in credential group gp_ran_control; leave gp_ran_master blank to reuse it — do not copy it into a second place
- The 13:20 UTC cron is driven by a measured ~10.5h warehouse lag (at 16:11 UTC the newest record was 05:44 UTC): yesterday is only complete around 10:30 UTC, running earlier silently loses a day
- D023 is the IMSI (618 = Liberia MCC, 15 digits), not a phone number; a MSISDN needs a separate mapping table — never hand this list over as dialable numbers
- 85% of detail rows have an empty D023; the SQL filters D023 <> ''. The manual statement from site does not, so it returns a blank identity
- The site-provided volte statement misses its parentheses: C031=1 OR C032=1 OR C033=1 AND <window> parses the window onto C033 only, i.e. full history. Parentheses are added here — do not revert (98% VoLTE coverage is expected, confirmed by the requester on 2026-10-19)
- This psql is 9.4 / Greenplum 6 and rejects --csv (added in PG 12); CSV must come from COPY ... TO STDOUT
- L_T216 is range-partitioned on D027 in 12-hour partitions going back ~62 days; GP_RAN_WINDOW_DAYS (default 7) beyond that returns nothing
- Moving datacenter: change GP_RAN_CONTROL_HOST / GP_RAN_MASTER_HOST / GP_RAN_DB only. The master IP is readable on control1 via cat /home/gpadmin/paas_hosts_master.cc
- Chain diagnostics: python -m backend.services.gp_ran.gp_ran_check --check (prints both hops, sudo, psql, table and partitions)

#### IPT Site Power Collect（`ipt_power_collect`）

- Default cron: `*/5 * * * *`　|　worker group: **m**
- Workflow script: `services/ipt_data/ipt_power_collector.py → run_ipt_power_collect`

**What it does**: Every 5 minutes, collect from the IPT Digital Platform (RMS energy monitoring, external AWS SaaS): (1) one filter-map request refreshes all ~500 sites’ connectivity (no power values in that response); (2) paged /sites backfills site attributes once; (3) full_kpi concurrently fetches the lightweight popup KPI for every site (8 threads; 32 threads measured 501 sites in 60s when the upstream is healthy) so every site gets a snapshot every 5 min; (4) full_shard rotates the full diagram detail in shards (3 threads, ≤60 sites per round, all sites in ~20 min, watch sites every round). Feeds the IPT Site Power page (?page=ipt_power)

**Workflow & data flow**:

1. OIDC implicit-flow login (client_id=rubix-web; simulates authorize -> login form -> callback fragment to get the access_token, cached 1h with auto renewal; see services/ipt_data/README.md)
1. POST /energy/sites/filter-map refreshes ipt_power_sites (online/offline connectivity; no power values)
1. GET /energy/sites?query=&page=N&pageSize=100 backfills internal_reference / organization / cluster / priority / configuration (~6 requests, only when values are missing and the last run was >1h ago)
1. The diagram pool starts first (background): watch sites (sites in watch_sites.json) + the shard_cursor ring-cursor shard, 3 threads
1. The popup KPI pool runs in the foreground: GET /popup for every site (8 threads, rotated via the kpi_cursor ring cursor so sites dropped at the hard deadline resume next round) concurrently with the diagram pool; both pools are bounded by the 240s round hard deadline (raised from 100s on 2026-11-06 to use the 200s freed by the */5 cadence; 300s period leaves 60s, no extra request pressure)
1. Resilience (11-05 review): pooled requests use a 20s per-request timeout (12s killed slow-but-valid requests and caused a timeout storm) + one bounded retry pass for failed popups; a round with <25% popup success is treated as an overloaded upstream and counts toward the circuit breaker; backoff is exponential (5/10/20 min, capped 30 min) and silently skips whole rounds without failure notifications, auto-clearing on the first successful round
1. Write one snapshot row per site per round (popup KPI as the base, sites with a diagram get the detail columns; source marks popup/diagram; popup rows store no raw JSON to control volume, diagram detail is kept per site in ipt_power_site_detail with device credentials stripped)
1. Prune snapshots older than 7 days (widened from 2 days on 2026-11-08; pruned history cannot be recovered); write the run result to ipt_power_meta.last_run and the next start position to ipt_power_meta.shard_cursor

**Maintenance**:

- WARNING: scope is set by backend/services/ipt_data/watch_sites.json — sites = watch sites (name / ref / site_id, full diagram every round); full_kpi = {"enabled": true, "workers": 8, "budget_s": 200} all-site popup tier; full_shard = {"enabled": true, "max_sites": 60, "budget_s": 70} diagram detail rotation. Do NOT set "*" (legacy meaning = all 500 diagrams in one round, extrapolated ~185s, guaranteed timeout)
- The upstream has no bulk power endpoint (filter-map has no values, events/recent only recent events); 2-min full-site resolution = concurrent per-site popup polling (2026-11-04: 32 threads, 501 sites in 60.1s / 0 errors); the 11-05 review showed sustained high concurrency drives the upstream into bulk timeouts, so it now runs at 8 threads with the kpi_cursor rotation, trading per-round coverage for stability (~2-6 min per site)
- Credentials: env IPT_USERNAME / IPT_PASSWORD take priority, otherwise the “user/password” header lines of the local url.txt; url.txt contains a plaintext password — already gitignored via the url*.txt rule
- The password grant is rejected upstream (unauthorized_client); only rubix-web allows code/implicit flows -> login is a form simulation; if the login page changes, the task reports a structure error
- A single-site failure only increments counters and never aborts the round (popup retries next round naturally, diagram sites are retried by the cursor); restart the m-group worker after collector code changes, watch_sites.json changes need no restart
- Snapshots are kept 7 days (RETENTION_DAYS, widened from 2 days on 2026-11-08 so the 72h/7d time windows actually show 7-day curves); PK (site_id, snap_time) dedupes re-runs; solar caliber: solarSets and rectifiers solarPower are the same mirrored value (max is taken), sites without solar have solar_available=0 and show "-", 0 W at night is normal
- Consumer: ?page=ipt_power (map on the left 3/5, site table on the right 2/5); its "Refresh now" button goes through routers/ipt_power.py /refresh (live query) and shares the login cache

#### RAN Element Management Sync（`ran_element_management_sync`）

- Default cron: `0 23 * * *`　|　worker group: **u**
- Workflow script: `services/RANElementManagement/ran_element_management_service.py → run_ran_element_management_sync`

**What it does**: Every day at 23:00, pull the full network-element list from GET /api/res/v1/ranmes - the single data endpoint behind the RNM Element Management table on RAN UME (10.100.28.27:28001) - measured 934 rows / 15 fields (ITBBU 812, SDR 111, MRNC 10, MEC 1), and store it in the PostgreSQL app schema: a current full table, a daily snapshot and a sync log

**Workflow & data flow**:

1. Source of truth is the browser capture at backend/services/RANElementManagement/url.txt: of 1080 cURL lines only line 852, /api/res/v1/ranmes?queryDn=model:subnetwork&operation=operation.rem.rnm.tools&includeAttr=..., is the real table endpoint; everything else is portal assets, login/refresh calls and WebSockets
1. Auth uses the project-standard auth_manager.get_auth(HOST, PORT, user, pwd, probe=...) with the zte_ume credential group. The probe must hit this business endpoint (not the login homepage) so an expired shared auth_cache session is detected and re-login happens automatically; the captured Z-AUTH-CODE-28001 / forgerydefense cookies expire and are never hardcoded
1. Parse the 200 JSON array and normalise 15 fields (nbiIdDn is a list and gets joined; connectionState / virtualizationId become integers), keeping the original row in raw_json
1. Fewer than RAN_EM_MIN_ROWS rows (default 100) fails the run without any write, so a partial upstream response cannot overwrite the good 934-row snapshot; 401/403 triggers one forced re-login and retry
1. PG writes run inside an explicit BEGIN/COMMIT/ROLLBACK transaction: delete today snapshot then bulk-insert into app.ran_element_management_daily (PK snapshot_date + ne_id, re-runs are idempotent), upsert by ne_id into app.ran_element_management and delete rows whose fetched_at is not this run, then log to app.ran_element_management_sync_log

**Maintenance**:

- WARNING: it belongs to group u because it shares the same UME host, the same zte_ume account and the same auth_cache session with ran_ume_daily / cm_data_sync - concurrent logins kick each other. 23:00 is off-peak for the group and a measured run takes under 1s. A new task MUST also be registered in GROUP_TASK_MAP (worker_watchdog.py), otherwise the queue row stays pending until it times out
- WARNING: call only /api/res/v1/ranmes. The capture also contains 10 /api/rncmoaction/v1/rnc/<uuid> detail calls whose responses carry ommFtpPasswd / ommFtpUser / ommSecretKeyId device credentials; they are not visible table columns and must not be stored
- get_raw_connection() is autocommit on PG and its cursor rewrites ? to %s, so the transaction must be an explicit BEGIN/COMMIT; on failure the whole batch rolls back with no half-written table
- The schema is created idempotently by DDL inside the service (CREATE TABLE IF NOT EXISTS) - no Alembic migration needed. When changing the FIELDS mapping, update the DDL and indexes too
- Troubleshooting order: check status / error in app.ran_element_management_sync_log first, then the task execution log; a sudden drop in rows usually means the minimum-row guard rejected a partial response; for session issues test the zte_ume credential in Settings -> Credentials

### 3.4 Reliability mechanisms (timeout / retry / self-healing)

| Mechanism | Description |
| --- | --- |
| **Zombie running recycling** | No per-task timeout (known gap). Worker scans every 300s: running rows older than 30 min (STALE_RUNNING_SECONDS) with a dead PID are marked failed. |
| **Auto retry** | auto_retry_failed scans every 10 min: a failed task is re-enqueued only if its data gap is not yet filled and attempts < MAX_ATTEMPTS=2; abandoned beyond the 24h hard cap. |
| **Missed-run backfill** | Tasks that should have fired but have no execution record at all are backfilled once (MISS_GRACE_MIN=15; email tasks excluded — handled by EWS recovery). |
| **Stale pending expiry** | A pending row unclaimed for over 6 hours (typical cause: the task was never registered in a worker group) is marked failed with an execution-log entry, freeing the single-flight slot it held — otherwise one stale row would block every later trigger of that task. |
| **Failure notification** | Failures notify via WeChat + email (services/weixin_notifier.py supports openclaw/wecom/serverchan/pushplus). |
| **Missed-run / stall alert** | db_freshness_check computes five health findings hourly (ungrouped / no execution record within the cron-scaled window / stuck queue / overdue since last success / succeeded but produced zero output); services/task_health_alert.py pushes them to WeChat + email, notifying once per new anomaly and once on recovery, re-raising after 24h (added 2026-09-18; the “succeeded but zero output” finding was added 2026-11-06 after vmax_multi_data_sync reported success every run while yielding 0 rows for 34 consecutive days, which the original four findings could not catch). |
| **Process self-healing** | backend_watchdog / worker_watchdog supervise processes: port probing, crash backoff (backend degrades to a 5-minute slow retry after 10 consecutive crashes instead of giving up; worker is still removed after 10); heartbeats in log/heartbeat_*.json stale >3 min → force kill & restart. |
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
- The "Master switch" enables or disables all tasks at once; tasks you stopped manually are skipped (their cards are tagged "Manually stopped") — enable those individually to restart them
- "Global History" searches runs across tasks; voice announcement on completion toggles here
- **Every number on the six status cards, the switch counter, group counts, the failure banner and the failure summary explains itself on hover** (2026-11-05): each task falls into exactly one bucket under a shared judgement (running comes from the frontend poll of /tasks/running, success/failed look only at the **latest** run record, not the window total), so the five status cards sum to "All"; in the master-switch x/N the denominator is every task row the API returns (**including exempt and manually stopped ones**), deliberately a different scope from what the switch itself checks; the failure summary is hard-capped — the endpoint SQL fetches only the newest 200 failure rows, and when that cap is hit a persistent banner makes clear the "N failures" means **at least** N

#### Task Report Files（`email_reports`）

Collects four kinds of task artifacts for download: latest email report attachments, FineBI FTP reports, eFlow rule check results, and the TTs and MTTR monthly workbook. The bottom of the eFlow tab lists **every rule sheet collected from eFlow** (TT severity rules / alarm correlation rules / push & config rules) plus this run's outputs (severity correction sheet / matching report).

- Switch categories via tabs; click a file name or "Download" to save; set how many recent files to keep per category
- The three "Run Now / Collect" buttons on the eFlow tab trigger the matching task manually: TT check + severity correction, alarm rule collection, push rule collection; each auto-refreshes once after 3s (refresh manually if the task is slow)
- Table at the bottom of the eFlow tab: blue tag = rule sheet (TT rules refresh with the daily 04:20 check; alarm/push rules normally refresh every 3 days at 23:59 — use the "Collect" buttons to refresh them on demand), grey = this run's outputs
- On the "TTs and MTTR" tab, "Generate now" submits one `tt_mttr_report_generate` run (scheduled daily at 07:20; raise the frequency from the Schedule column in Task Manager). The page polls the file timestamps and only reports success once a newer file appears. Scope: has a WO, alarm occur-to-clear under 48 hours, non-empty Site Category, occur month from 2026-01.

#### Data Upload（`upload`）

Drag-and-drop Excel/CSV ingestion with a data-quality score.

- Drop a file to upload; check the issue/conclusion panels before trusting the data
- The history list can be refreshed manually
- **Rows, columns, quality score, issue count and elapsed time all answer "how was this computed" on hover** (2026-11-05): quality score = 100 − (issues ÷ checks) × 100 with checks hard-coded at **5 per column** while a column can trigger at most 4 (outlier / null rate / constant / skewed), so the floor is 20, rounded to 1 decimal; null rate >50% is an error and >20% a warning (mutually exclusive); the number in "Quality Issues (N)" is the length of the backend issues_summary array but the API **sends only the first 10** entries, and when there are more a persistent line above the list states the gap (not sent, not lost)

#### Table Browser（`tables`）

Table Browser: browse any table without SQL, view column profiles, import & export — the go-to fallback tool.

- Pick a table → paginate & search (debounced); export xlsx / CSV
- Column visibility can be saved as view templates — save one when you always look at the same columns
- The "Profile" tab shows per-column statistics; Excel/CSV import supported
- **The funnel next to every column header filters rows** (2026-11-11): contains / equals / pick values (top 200 distinct values by frequency) / empty only. Filters run server-side and follow pagination and export; active ones stay visible as tags above the table and can be removed individually or all at once. Search, contains and equals are all **case-insensitive** (PostgreSQL LIKE is case-sensitive, so "totota" used to miss "Totota"); `%` and `_` in a search term are treated literally. The panel can also hide a column — that is display-layer, unlike filtering rows
- **The header row/column tags, the pagination total and the four Profile cards all explain themselves on hover** (2026-11-05): the header row count is a whole-table `SELECT COUNT(*)` unaffected by the search box below; the pagination total is COUNT(*) **with the search applied**, and search runs a LIKE over every column but **only the first 200 columns** (wider tables are cut off), so "0 rows found" does not mean the data is missing; the whole Profile tab is a **sample** — the backend SQL is hard-coded to `LIMIT 10000` with no ORDER BY (not random), a banner stays visible when the cap is hit, and quality score = 100 − (issues ÷ columns×5) × 100, which floors at 20 because a column can trigger at most 4 checks

#### Overview（`overview`）

Database health-check page: how many tables exist, rows per table, Top10 by size.

- Sort by the "Rows" column; the page is read-only — it only answers "is the data there and how big"
- **Every number explains itself on hover** (2026-11-04): the four cards carry an ⓘ on the title and a bubble on the big number (`StatCard.explainText`), and the Top10 bars and the share pie gained ⓘ on their titles
- Two calibers that the docs used to get wrong, corrected against `backend/routers/system.py:96-128`: **the table total does NOT exclude `_`-prefixed internal tables** (the old wording said it did), and **"core tables" is counted in the frontend** — the API never sends that field
- The row total is **`SELECT COUNT(*)` executed per table and added up** (not a `reltuples` estimate) and includes internal and archive tables, while Top10 excludes `_`-prefixed tables, `analysis_archive` and `uploaded_files` and is sorted and sliced in the frontend — so the charts adding up to less than the header total is a caliber difference, not lost data
- The project runs on PostgreSQL now: table names carry a schema prefix such as `app.`, so "does not start with _" is almost always true and **core tables equals total tables** (measured: both 115). The bubble says so explicitly so it is not read as a bug

### 4.2 Monitoring Boards

#### Alarm Dashboard（`alarm`）

Combined view of all current active network alarms: totals, severity, site-level multi-dimension statistics and trends.

- Click any number to open a searchable drill-down table
- "Realtime" data comes from eFlow active alarms (eflow_active_alarm synced every minute) — not second-level push
- **Region profiles and per-type counts explain themselves on hover** (2026-11-04): "N alarms ↗" opens into "row-counted alarms + how many of them have transmission_type=MW + sites counted by distinct site_id", plus the note that rows whose region code is outside the 15-county list are not counted in any region; the "Top Alarm Types" ⓘ states the name comes from alarm_title falling back to codename, that the backend sends the top 10 while the chart draws 8, so **those 8 do not sum to the alarm total**

#### TT&WO Dashboard（`ttwo`）

Processing volume, timeliness and backlog trends of trouble tickets (TT) and work orders (WO). All three TT statistics dimensions (ticket severity / SLA status / ticket status) are number cards you can click to drill down; the MTTR trend is split into 4 charts by ticket severity (P1/P2/P3/P4), each a dual-axis chart with bars = TT count and line = MTTR, with tabs switching day / week / month granularity. The default window is the last 30 days.

- Filter with selects + segmented control + date range; click a card or a chart point to drill down. The default window is the last 30 days (over a 7-day window the weekly/monthly views have only one or two buckets, which shows no trend)
- "All owners" switches ZTE / 3rd: a non-empty WO number means ZTE (dispatched by us), empty means 3rd (handled by a third party)
- The "Advanced filters" button reveals site-level filters (region / province-county / network type / site type / VIP / TRM / supervisor / FME / power source / power vendor / site category), fed from the site table
- The percentage on a TT statistics card uses that dimension's own total as denominator (its internal composition), not the overall TT total
- **Every number answers how it was computed on hover** (2026-11-03): hovering a severity / SLA card's big number or its share gives "this cell ÷ this dimension's visible total, the share is computed by the frontend from this page's payload (the API sends no pct field), the current scope (time window / region / owner / advanced filters) and what the click drills into". The summary badges next to the title (TT Total / WO Total / WO No. Unique) do the same and name their source fields `summary.tt_total` / `wo_total` / `wo_no_count`. **WO No. (Unique) is the count of distinct non-empty wo_no values on the TT rows**, not the WO row count — the two differing is normal
- Unknown never enters the severity or SLA dimensions: empty values, the literal unknown and the historical misspelling unkonw are all dropped by the backend, so the cards can sum to **less** than the TT total — that is not lost data
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
- The number hover explain on the statistics cards and the summary badges is the same set of wording as page=ttwo (same component, different slice)

#### TT Dashboard（`tt`）

The "TT only" cut of the TT&WO Dashboard (source table eflow_tt): summary card (TT Total only) → Statistics (severity / SLA status / status, all number cards that drill down on click) → MTTR trend (P1/P2/P3/P4 × day/week/month, each a dual-axis "bars = TT count, line = MTTR" chart). Everything below the MTTR trend is omitted: Domain & Root Cause, Work Order Analytics (WO by source / WO by status) and Site Information; the WO Total / WO No. (Unique) cards are gone too. The default window is the last 30 days.

- The section title reads "Statistics" and the severity dimension "Severity" (the full TT&WO Dashboard still uses "TT Statistics" and "Ticket Severity")
- Each MTTR chart is dual-axis: bars (ZTE blue #0072BC) are the TT count of that severity in the period, the line (orange) is the mean MTTR in minutes. The bar/line colours are fixed across all four charts — the severity is identified by the chart itself (four separate P1/P2/P3/P4 charts), while the colours only distinguish the two measures (volume vs duration). A period with no ticket of that severity draws neither a bar nor a point — it is not 0
- Filters (including the ZTE/3rd owner switch and advanced filters), card drill-down and the page-level Excel export are shared with the TT&WO Dashboard (same /tt-wo-dashboard/overview endpoint), so the numbers necessarily match; the export filename is prefixed TTWO_tt_
- Direct link http://<host>/myapp/?page=tt; the full version is page=ttwo, WO only is page=wo (same layout, sourced from eflow_wo)
- Statistics-card numbers, their shares and the summary badge are all hover-explainable with the same wording as page=ttwo; only the "TT Total" badge is issued on this page — the WO badges are not part of this slice

#### WO Dashboard（`wo`）

The eflow_wo-sourced twin of the TT Dashboard: the layout matches page=tt block for block, only the data comes from eflow_wo. Summary card (WO Total only) → Statistics (severity / SLA status / status) → MTTR trend (P1/P2/P3/P4 × day/week/month dual-axis charts). Everything below the MTTR trend (Domain & Root Cause, Work Order Analytics, Site Information) is omitted, exactly as on page=tt. The default window is the last 30 days.

- Click a statistics card or a point on an MTTR chart to open a searchable WO drill-down table
- SLA status comes from the linked TT (eflow_wo has no such column — SLA is a TT-side concept): joined on wo.tt_no = tt.tt_no. **Unmatched rows fall into Unknown, and Unknown is dropped from this dimension**, so the SLA cards can sum to **less** than the WO total (the previous wording "the cards still sum to the WO total" contradicted the code; corrected 2026-11-03)
- Statistics-card numbers and shares are hover-explainable with the same wording as page=ttwo; the severity dimension reads the same-named ticket_severity column of the source table on each page
- MTTR uses the WO's own alarm_occur_time / alarm_clear_time, so this page shows the WO turnaround time — a different number from the TT figure on page=tt
- Only the "WO Total" summary card remains: every row on this page is itself a WO, so "WO No. (Unique)" would print the same number twice, and "TT Total" counts rows of a different table and is meaningless here
- The ZTE/3rd owner switch is hidden on this page: that ownership is defined on the TT's wo_no, a concept the WO table does not have
- Filters (region / advanced filters), drill-down and the page-level Excel export are shared with the TT&WO Dashboard, but the data endpoint is /wo-dashboard/overview; the export filename is prefixed TTWO_wo_
- Direct link http://<host>/myapp/?page=wo; the full version is page=ttwo, TT only is page=tt

#### NUR Dashboard（`nur`）

Network Unavailability Rate (NUR) daily/weekly/monthly trends, multi-dimension analysis and site compliance.

- Switch granularity and date range, filter by dimensions
- **Every figure explains itself on hover** (2026-11-03, sharing the wording with the MS Operation KPI dashboard): hovering a number in the NUR and SLA tables first states how that table is computed (NUR = Σ(cells × MTTR minutes) × 60 ÷ (denominator cells × period seconds), displayed ×100000; only tickets with 0 < MTTR < 43200 minutes that are already cleared enter the sample; Global is the sum of numerators over the sum of cells, not the mean of the per-technology figures), then which metric and which period that cell is
- Site dimensions can be narrowed by TRM type / Site category / Province-County / Region / Starlink migrated (attributes come from the site master, exact match; numerator and denominator share the same scope, so NUR still means this subset of sites)
- Click numbers to drill into a detail table (in-column filters & sorting); export to Excel — the drill-down inherits every active filter

#### NUR Dashboard (NUR only)（`ms_nur_only`）

The "NUR only" cut of the NUR Dashboard: identical to the NUR half of page=nur (NUR daily/weekly/monthly tables + trends), with the three SLA blocks removed — handy for a NUR-only desk or wall screen.

- Filters, drill-down and Excel export are shared with the NUR Dashboard, so usage is identical (including site dimensions: TRM type / Site category / Province-County / Region / Starlink migrated)
- Direct link http://<host>/myapp/?page=ms_nur_only; the other half is page=ms_sla_only (SLA scope, from the MS Operation KPI Dashboard)

#### MS Operation KPI Dashboard（`ms_sla`）

MS contract KPIs and WO SLA attainment: NUR / Network KPI / Per-Site / WO SLA (metrics as rows, periods as columns).

- Three granularity tabs: day / week / month; Network KPIs and Per-Site KPIs only exist at day/month (they come from the snapshot DB), so they are hidden at week granularity with an explanatory banner
- Switching day/week/month resets the time range to that tab default (day = current month to date, week = last 12 weeks, month = last 9 calendar months); the banner states the active range
- SLA attainment (TTR / TTR_P1~P4) is presented once, by the WOs SLA block as table + trend; there is no separate KPI List SLA card
- Drill-down reuses the NUR detail table; numbers come from the live nur_calc calculation (driven by ms_sla_full every 6h) and may differ from historical snapshot files — trust this page
- **Every figure explains itself on hover** (2026-11-03): hovering a number in the NUR / Network KPIs / Per-Site / WO SLA tables first states how that table is computed (NUR = Σ(cells × MTTR minutes) × 60 ÷ (denominator cells × period seconds), displayed ×100000; Network takes the raw snapshot value with no division; PS_* = rows meeting the threshold ÷ total rows, with PS_NUR_2G/3G using the site-NUR<350 site share instead; Achieve = Pass ÷ Total, and Total 0 gives no value rather than 0%), then the cell itself (metric · period · value). The ⓘ on the WOs SLA card title states that TTR_P1~P4 are only severity groupings with no 4h/8h/16h/2Days deadline test, so they cannot be reconciled with the identically named metrics on the MS WOs SLA Daily Report page
- **Colour does not mean off-target**: DCR metrics (2G_DCR / 3G_DCR / 3G_DCR_HSDPA) are lower-is-better, but the page colours everything by "≥95% green", so those columns are permanently red - a known defect, stated in the bubble

#### MS KPI Dashboard (SLA only)（`ms_sla_only`）

The "SLA only" cut of the MS Operation KPI Dashboard: the WOs SLA block with WO SLA attainment (TTR / TTR_P1~P4 Total / Within SLA / Achieve + trend), without NUR, Network or Per-Site.

- Attainment ≥95% is green, below target is red — same scope as page=ms_sla
- Three granularity tabs: day (default = current month to date), week (default = last 12 weeks) and month (default = January 2026 to date); switching a tab resets the time range (explained by the banner)
- Click cells and data points to drill into TT details and export to Excel
- Total / Within SLA / Achieve each explain themselves on hover (same wording as page=ms_sla): Total = tickets of that period, Within SLA = tickets whose sla_status is Pass, Achieve = Pass ÷ Total (computed by the backend, only scaled here); when Total is 0, Achieve shows a dash rather than 0%

#### ms_wo_sla（`ms_wo_sla`）

MS WOs SLA Daily Report: daily detail matrix of WO SLA attainment (Total / Within SLA / Achieve), reading the same file that the daily "MS WOs SLA Daily Report" email is built from.

- Data source: data/ms_sla/ZTE OLR MS WOs SLA Achievements Daily Report_<date>.xlsx (landed daily by the kpi_ms_wo_sla task); the page does no further processing — see backend/services/ms_kpi_report_service.py for the parsing caliber
- Layout: overview cards (monthly tickets / meeting SLA / attainment / failing metrics) -> 5 TTR metric cards -> daily attainment trend (with each target line) -> daily detail matrix (same layout as the Excel)
- Click a matrix column header to open the trend drill-down for that metric
- **Every figure explains itself on hover** (2026-11-03): the overview cards, the monthly value and the "N/M days met" of each metric card, and the trend dialog can all be hovered. Three points that are most often misread - the monthly value is the **raw** Month row of the workbook (no division is recomputed); the denominator of "N/M days met" is the **number of day rows in the matrix**, not the days of the calendar month (undelivered days are not counted); and Total / Within SLA / Achieve in the overview are **three independent raw columns**, so Achieve is not necessarily Within ÷ Total
- The page can be exported to Excel with the same layout as the emailed attachment

#### ms_contract_kpi（`ms_contract_kpi`）

MS Contract KPIs & WOs Achievement auto-reports: the full report page for contract KPIs (27 KPIs across Operation / Network / PerSite) and WO SLA attainment.

- Data source: data/ms_sla/ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx — the auto-report workbook itself, updated in place by the ms_sla_full task (daily at 05:00)
- Layout: overview cards -> category attainment -> 27 KPI cards (grouped into Operation / Network / PerSite tabs; click a KPI card for its daily trend) -> 4 tabs (KPI matrix / WO SLA matrix / FineBI plan / auto-report inventory; the last two support search + filter + pagination)
- The FineBI plan and auto-report inventory are *process ledgers*, not run metrics, so their entries were hidden on the page from 2026-09-27 (the backend still parses them and the data APIs remain)
- Same source as page=ms_wo_sla: the WO SLA matrix is word-for-word identical to that page
- **Every figure explains itself on hover** (2026-11-03): the overview cards, the monthly value and days-met of the 27 KPI cards, and the trend dialog are all hoverable. Four points - the overview cards count **metrics**, and a metric whose backend met is null (no target) counts on **neither** side, so the figures can sum to less than the metric total; the monthly value is the raw workbook value; **the 90% target of PerSite metrics is hard-coded in the parser** (target_source=persite_ratio), not a target taken from the contract report; and the "worst" ranking is ordered by relative gap to target, so **metrics with no target or a target of 0 get gap 0 and never appear**

#### CXO Dashboard（`cxoDashboard`, iframe page）

Service / Network / Summary three-tier executive dashboard (from the VMAX assurance board).

- The iframe embeds a full data snapshot: it renders even when the upstream is down, but may not show the latest data
- Re-run the sync task to refresh; credentials live in Settings → Credentials → vmax_cxo

#### vmaxCxoDashboard（`vmaxCxoDashboard`, iframe page）

VMAX CXO original board (15-minute granularity executive screen): a fully independent implementation from page=cxoDashboard — changing one does not affect the other.

- A faithful visual replica of public/vmax_cxo_dashboard.html (an iframe shell), not a React component
- Data comes from the VMAX CXO portal session (credential group vmax_cxo) via the sync task vmax_multi_data_sync
- Renaming the display title requires editing 4 places at once: the i18n entries here (zh/en) plus the HTML <title> / #appTitle / inline I18N

#### vmaxCxoDashboard_Daily（`vmaxCxoDashboard_Daily`, iframe page）

VMAX CXO daily detail (Daily): three day-granularity curves for Monday~Sunday × this week / last week / two weeks ago.

- Data comes from data/vmax_cxo_daily/daily.json written by the task vmax_cxo_daily_sync (VMAX has no native daily granularity — daily values are aggregated locally from the 1-hour detail)
- Upstream hourly detail is kept for roughly 8 days only; dates older than that floor show as grey empty cells with a hover note (not a fault)
- Renaming the display title requires editing 4 places at once: the i18n entries here (zh/en) plus public/vmax_cxo_dashboard_daily.html <title> / #appTitle / inline I18N

#### vmaxCxoDashboard_90Days（`vmaxCxoDashboard_90Days`, iframe page）

CXO Daily Dashboard (90 Days): a 90-day executive-view screen for the CEO.

- Data comes from the daily_kpi table in data/olib_soc_report/olib_soc_report.sqlite3, written by the tasks olib_soc_vmax_report / olib_soc_kpi_daily_sync
- Read-only endpoint /api/olib-soc-dashboard/overview (daily/weekly trends + yesterday card + 90-day extremes)
- When gap days exist a banner shows "data complete x/y days · n missing"; the matching detail rows are flagged as incomplete
- Renaming the display title requires editing 6 places at once: the i18n entries here (zh/en) plus public/vmax_cxo_dashboard_90days.html <title> / #appTitle / inline I18N (zh+en)

#### socTrendDashboard（`socTrendDashboard`, iframe page）

SOC multi-dimensional trend board: hourly and daily trends for traffic / TCP / per-service categories (traffic, video, web, gaming, OTT voice, OTT video), drillable by region and SGW network element.

- Data is pulled hourly at :40 by the task soc_trend_sync, read-only from the VMAX GBase data warehouse, and stored in data/soc_trend/soc_trend.sqlite3
- Only raw counters are stored — ratios are computed on the read side (backend/services/soc_trend/soc_trend_metrics.py is the single source of caliber)
- The "Metric Dictionary" dialog shows the alarm and attribution rules (same source as the backend)
- The page is public/soc_trend_dashboard.html (React shell: pages/SocTrendDashboard.tsx)

#### MW UME Topology（`mwUmeTopology`, iframe page）

ZXMW microwave network topology & bandwidth utilization NOC board (daily granularity).

- Data is written daily at 05:15 by mw_ume_kpi_sync into mw_ume_bw_ultilazation — the page changes once a day
- Risk ranking, drawer and trend chart are all interactive

#### ipranTopo（`ipranTopo`）

UME topology in four layers (IP RAN Fiber / IP Core / Metro Ring / DWDM): all four share the same UME endpoints and differ only by layer lid and caliber; switching tabs changes the data source while the canvas, stat cards, drill-downs and export are reused. The IP RAN Fiber layer measured 93 NEs and 167 physical links folded into 141 edges; the other three layers have per-device-model caliber that awaits field verification (all concrete figures below refer to the IP RAN Fiber layer).

- The "Topology layer" tabs hold 4 graphs: IP RAN Fiber (measured caliber) / IP Core / Metro Ring / DWDM. Switching clears the previous layer data and focus, then refetches; each layer caches independently for 120s and auto refresh only hits the current layer. Append &layer=ipcore to the URL to open a single layer directly
- Labels avoid collisions automatically: they are placed by importance (focused node / tier / degree / fault), trying alternating above/below slots; when space runs out they are hidden and the count is shown at the canvas top right — hidden is preferred over overlapping text. Names are shortened by tier; hover for the full name
- The three layouts answer different questions: **force (default)** shows rings and clusters and pulls access nodes toward their primary parent; **geographic** shows which city an outage hits; **tiered** shows the hierarchy and is the better export view. Layouts are deterministic. The older force scan of 42 crossings on the real graph is kept as layoutForceClassic
- Three color modes: tier (default) / online state / highest alarm severity. **Alarms are deliberately not a fill color**: 74/93 NEs (80%) carry critical alarms, so filling by severity would paint the whole map red; alarms are a small corner dot instead
- Bandwidth is shown by **line width** only (100G / 25G / 10G / others); down links are red dashed and links with alarms turn orange. The "Fold parallel links" switch expands ×N into a fan
- The right rail (about 25%) puts the stat cards in one row above "NEs with most critical alarms"; both are the same width. The breakdown under each number stays hidden until the number is clicked; the card title still drills. The topology canvas takes the left 75% and all height left under the toolbar. Click a node or a name in that list to focus: other nodes dim and only one-hop neighbors stay lit, and the detail drawer slides in from the right (Overview / Interfaces / Alarms / Impact). Click again, click empty space, click the mask, or press Esc to close. Use the wheel to zoom and drag empty space to pan
- Impact analysis lists **root-cause candidates**, not a confirmed root cause: only a down device with no failed device further upstream is listed, and the API has no alarm timestamp. Utilization stays N/A when traffic is absent; port speed is never used as a substitute
- Geographic layout also opens a site map on the same PMTiles basemap as GIS. Exact and approximate coordinates are drawn differently; devices without coordinates are not plotted
- All four stat cards (NEs / folded links / down NEs / NEs with critical alarms) **open a drill table** built from the same arrays as the card numbers
- The 7 external upstream devices (e.g. 89MW01/89MW02, HQ-RAN-SW5960) are referenced by links; their names come from the UME attribute API. They act as endpoints only, are excluded from the NE count, and have no online state
- Geographic coordinates come from local PG table kml_mw_links: 74 exact, 3 approximate (a banner at the bottom of the page asks for confirmation) and 16 missing — **positions are never guessed**; they sit in the "no coordinates" band at the bottom. Missing coordinates, fuzzy matches, alarm saturation and the caliber note all sit at the bottom of the page, not between the toolbar and the canvas
- The backend merges each layer's 8 UME calls into one response cached **per layer** for 120 seconds; "Refetch" bypasses only the current layer cache. Header auto-refresh is off by default and suggests 300s here; when on it refreshes in place (canvas not rebuilt, focus kept). On upstream failure the last successful snapshot is shown with a persistent banner
- "Export Excel" writes two sheets (NEs and links) including alarm counts, coordinate source and port names

#### MW Realtime（`mwRealTime`, iframe page）

15-minute realtime variant of the microwave topology board (same skeleton, risk ranking, drawer and trends).

- Shows only the latest 15-minute slot by default; the slider reviews the last 2 hours
- Auto refresh is off by default; enable it per page in the header (suggested 900s for this page). When on, it uses soft refresh (no iframe reload, no flicker)

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
- **Every number explains itself on hover** (2026-11-05): the six summary stat cards and the three rank column headers carry notes; the null-coalescing to 0 was removed — a missing value now shows —, because "a real zero" and "the API sent nothing" mean different things on this page
- Caliber essentials: **SLA achievement = (Pass + Within SLA) ÷ (Pass + Failed)**, and records whose `sla_status` is empty or another value enter **neither side** — so the denominator is not "every order of the month"; the y in the `x/y` line under the card is the real denominator. The WO window is "first of month ≤ t < first of next month", the time column is detected from the schema, and attribution prefers `site_id` with a **normalised site name** fallback (whitespace collapsed, lower-cased), so **changing the month moves these figures as a batch — they are not cumulative**
- **All ranks now come from the backend** (corrected 2026-11-05): availability descending (ties broken first by SLA rate, then by name), `wo_rank` **ascending with #1 = fewest WOs**, and `sla_rank` descending with FMEs under 5 samples excluded. The cards used to mark #1 by the highest WO count, the opposite of the column on the same page — two different "number ones" on one screen. So the "Top 3 by WO count" cards now show late badges such as #41/#42/#43; they are not "first place"
- The "open" figure is one of **three** definitions of open on the platform (this page tests the row status field, the spare-parts report de-duplicates by document number with a word list, the warehouse board compares exactly), so the three are not meant to reconcile

#### site_avail（`site_avail`）

Site availability board: per-site availability ranking and target compliance.

- Click a site name to drill into its availability details
- Availability uses the same per-site calculation as the FME ranking page
- **Every figure explains itself on hover** (2026-11-03): the six headline statistics and the monthly-average / minimum / days-below / week column headers each carry a ⓘ, and hovering a number lists that cell - days with data, how many are below the threshold, the lowest value and its day, whether a daily value is a raw UME reading or a TDD conversion. A native title hint used to be the only aid and was not copyable, so it was replaced by the shared bubble
- **The three headline numbers follow the search box**: monthly average / sites with data / sites below target are computed over the **filtered** site set, not the backend network-wide summary - clear the search box to get the whole-network value. In "Sites", the number before the slash is the filtered row count and the one after is the total in scope for the month
- The threshold (default 99.65%) is a page input: changing it recomputes "below target" immediately without a new query, so days-below is not a fixed backend value
- This page is a **site-level** measure and cannot be reconciled against the cell-level ranking (RanCellsKpi) or the site-day weighted matrix (MS Availability)

#### avail_ms（`avail_ms`）

MS Availability (availability matrix): network availability presented across three dimensions — region / technology / site type — with day, week and month granularity on tabs. Data comes from the local derived database avail_recon.sqlite3 (rebuilt daily at 06:10 by the avail_recon_sync task; the measure is site-weighted availability, SUM(numerator)/SUM(denominator)).

- Each matrix has a trend chart above it (30 periods for day, 12 for week, 12 for month, following the active tab): one line per dimension value, every point weighted as SUM(numerator)/SUM(denominator) and therefore identical to the table figures
- Chart points are clickable too, and they open **that point's own period** (e.g. when the month tab sits on 2026-09, clicking the 2026-08 point opens 2026-08 detail)
- The region chart omits the "unmatched master data" line (its magnitude would flatten the y-axis); a note under the chart points to the last table row, where it is shown
- Click any availability figure to drill down: the dialog holds a 30-period trend, the daily detail and a breakdown by dispatch group; the second tab lists the related TT tickets for that combination
- **Every figure explains itself on hover** (2026-11-03): the three matrix card titles and the four KPI card titles carry a ⓘ stating how that column is computed (SUM(numerator)/SUM(denominator), which table it comes from, that the ALL card includes unmatched sites); hovering an availability number in a matrix lists **that cell** — its numerator and denominator, what the denominator means (site-day observations in the period, one per site per day with data), that the ratio is therefore site-day weighted rather than a plain site average, the change and the drill hint. Bubbles are copyable; the previous native title hint showed two bare numbers and was neither copyable nor themed, so it was replaced by the shared component
- The threshold input (default 99.65%) drives the "below target" flag: values under it turn red and re-evaluate instantly — the figures themselves do not change
- The ALL row under Region includes sites not matched to master data, so ALL is not the sum of the regions; that bucket gets its own last row — it can show availability detail but not TT tickets (the derived DB holds no site list for it)
- 4G NERA is an unmapped dispatch group: counted in the 4G technology total, shown separately as "Other" under site type, and only present in the 2025-12 ~ 2026-01 months; a yellow note appears on the page then
- Missing data renders as "—" (never 0); the "Data through" label at the top makes a stalled derived database obvious

#### avail_flm（`avail_flm`）

FLM availability: regions as rows, technology (2G/3G/4G) and site type (Regular / Cooli / ERA; the column keeps the raw data value, the requirement writes Cool.i) as columns; day / week / month granularity on tabs. The region list is NOT hard-coded: it comes from the region column of the site master data (master_site_db), so whatever regions the master data holds are the ones shown — renames and new regions need no code change. The data is the same source as the Availability Matrix (local derived database avail_recon.sqlite3, measure SUM(numerator)/SUM(denominator)), and the "TTs affecting availability" list is shown right on the page.

- Each table has a trend chart above it: the upper one tracks the regions (one line per region), the lower one the three site types; 30 periods for day, 12 for week, 12 for month, following the active tab
- Chart points are clickable and open **that point's own period**; the dashed threshold line (default 99.65%) is the same value that turns table figures red
- Click any availability figure to drill down: the dialog holds a 30-period trend, the daily detail and a breakdown by dispatch group; the second tab lists every TT ticket of that slice
- Each region also has a KPI card (all technologies combined) that can be clicked to drill down
- **Every figure explains itself on hover** (2026-11-03, sharing the wording with the Availability Matrix): the two matrix card titles and every region KPI card carry a ⓘ, and hovering an availability number lists that cell numerator, denominator, what the denominator means (site-day observations) and the weighting. The region card wording differs from the per-technology card of the matrix: a region card is SUM(numerator)/SUM(denominator) over **all technologies and all site types** of that region, not a mean of the per-technology figures, and this page has no ALL row — unmatched sites sit in no region card
- Site type is not scope-restricted: every region shows all of its site-type columns (Regular / Cooli / ERA, raw data value). The requirement note claiming that one region carries only Regular/Cool.i contradicted both data sources (that region had 123 ERA sites and an ERA denominator of 65k in the derived database), so leaving cells blank would wrongly suggest the region has no ERA sites
- The last row "unmatched master data" is the part whose site names failed to match: it belongs to no region and is not plotted (its magnitude would flatten the y-axis); it is listed for reconciliation only and can show availability detail but not TT tickets
- The page-level "TTs affecting availability" list shows **every TT of the period** with no "impacted service" judgement (that field and site_outage agree on every row of this period, so using either would make the definition look more precise than it is); each row carries the 2G/3G/4G down-site counts and MTTR so you can judge relevance yourself
- The TT list can be filtered by region (all / any region); a month can hold 3600+ tickets, and a yellow note appears when the display limit is hit — only the detail row count is affected, never the availability figures
- Click a ticket number to look up the availability of its region × site type together with all tickets of that slice
- 4G NERA is an unmapped dispatch group: counted in the 4G technology total, but this page lists only the three site types, so the 4G row will exceed the sum of the three columns and a yellow note appears
- Missing data renders as "—" (never 0); the "Data through" label at the top makes a stalled derived database obvious

#### avail_county（`avail_county`）

County-level availability: views the current month's availability by province_county (**county**, the 15 counties of Liberia) from the site master data eflow_site, with counties as rows and 2G / 3G / 4G availability as columns; day / week granularity on tabs. The data comes from the UME MS SLA **site-level daily tables** (2G = TCH in service rate, 3G = Cell Validity Rate, 4G = [FDD]Cell Availability); sites are linked to the master data by **site name** (site_id does not line up — measured overlap is only 0-15%).

- **The measure differs from the Availability Matrix and FLM Availability pages**: those use SUM(numerator)/SUM(denominator), while this page averages the site-level ratios UME provides directly, so only a **site-weighted average** is possible (arithmetic mean of the days that have values per site, then an equal-weight mean across the sites of a county). The collapsible "About this measure" note at the top states it and is **collapsed by default since 2026-11-02** — the figures of the two sets of pages are not expected to match
- Filters at the top: month (the day and week tabs each remember their own last selected period), day / week tabs, threshold (default 99.65%, decides which figures turn red), trend subject (a specific county or the whole network), refresh and export to Excel
- The page opens on the **last day of the month that actually has data** (not the calendar last day): UME sync lags, so the current month may hold only one or two days of data; two labels ("Data through" and "N/M days synced this month") make that visible instead of leaving an empty page
- The three KPI cards (whole-network 2G / 3G / 4G) show the availability of the current period and how many counties are off target; clicking a card drills down to the site detail of the whole network for that technology
- **Every figure explains itself on hover** (added 2026-11-03): the three KPI card titles, the 2G/3G/4G column headers of the main table and the availability / days / daily headers inside the drill-down dialog each carry a ⓘ that states how that **column** is computed (including the exact UME metric name: TCH in service rate / Cell Validity Rate / [FDD]Cell Availability). Hovering an availability number in the table lists **that cell**: sites averaged with equal weight, how many are off target, the site-day sample and the site range. Bubbles are copyable and clicking the ⓘ never opens the drill dialog. The whole-network card is the arithmetic mean of the 15 county values (**one vote per county**, the unmatched row excluded), so it equals the average of that table column rather than a site-weighted figure
- The main table has 16 rows (15 counties plus a last row "Unmatched sites"): every cell shows the availability, the site count and the change against the previous period in percentage points. Click any availability figure to drill down; the dialog has three tabs — site detail / daily detail / related TT tickets
- "Unmatched sites" are the sites in PG that cannot be matched to eflow_site (measured around 9%); they are listed on the last row for reconciliation only and **count towards no county**; an orange label on the page points this out
- Drill-down chain: county × technology -> site detail (sorted by availability, worst first) -> click a site -> that site's daily detail (one column per technology); the third tab holds the TT tickets of that county (with down-site counts and root cause), where the county is derived by matching **site_id exactly** against eflow_site
- Every point on the curve is clickable too and opens **that point's own period**; the curve follows the "trend subject" dropdown (county / whole network)
- Out-of-range values (above 1.5) are discarded as dirty data; missing data renders as "—" (never 0)
- Export to Excel writes the current page (summary + county matrix + trend, three sheets); the drill-down dialog can export its current tab on its own

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
- **Every number explains itself on hover** (2026-11-04): the score card ⓘ gives the normalisation and weighting (speed: own divided by the larger, latency: the smaller divided by own, weights 0.35/0.20/0.30/0.15 hard-coded in the caliber), and the big numbers, part tags, win rates and P50/P90 all carry bubbles; **the percentiles are `PERCENTILE_CONT` interpolated inside the sample**, not a frequency count
- The two figures most likely to be reconciled wrongly are stated in the bubbles: the mean is an **equal-weight average of rows, not weighted by test count**, and the header N rows is the **whole speedtest_data table** (a raw API field), not the count after this range filter
- The Tests and Devices cards now show — when the range has no rows (previously a null-coalescing to 0, which turned not-measured into zero); the device total is **a device-day sum across rows**: one device on two days counts twice, so it is not a unique-device count

#### bm_meta（`bm_meta`）

Meta Benchmark Report: based on meta_data (imported from Meta_20260923.xlsx, 612 rows, 2025-01-18 ~ 2026-09-23) it answers two questions — (1) "between Orange and MTN, who has the higher speed, by how much, and is the gap widening or narrowing"; (2) "what level are the network-side KPIs (BP / FDD DL IP throughput / DL and UL PRB utilization / traffic volume / RRC users) at over the same period". These two are **deliberately kept apart**: only "speed" is a head-to-head between the two operators, while the other six are network-side KPIs belonging to neither. The page has two layers: a head-to-head layer (composite score -> speed cards -> dual-line trend -> daily win/loss -> monthly and daily tables) and a network-KPI layer (summary cards + single-line trend).

- Quick ranges at the top (90 / 180 / 365 days / all time) plus date pickers; the window is **half-open** internally while the UI shows a closed range. The default is 365 days rather than 90 because this table spans 612 days and a short window would cut off the long-term trend
- The competitiveness score is **relative between the two operators**: the leader scores 100 and the other scales proportionally. It answers "who is stronger and by how much", not whether the absolute level is good
- **Why the network KPIs are excluded from scoring**: mixing "how much faster Orange is than MTN" with "how high network-wide PRB utilization is" into one score would treat two different things as two contestants in the same contest, producing a false conclusion. So the six network KPIs only get trends and averages — no wins, no score
- "Speed" is the download-speed comparison between the two operators (the fixed columns orange_liberia / mtn_liberia in the database), one row per day; when the two are equal it counts as a "tie" and is **not credited as a win to either side** (a note at the top states how many such days there are)
- Every figure is clickable: click an operator value or "leads N of M days" for **the days that operator led** (row count equals the win count, computed by the same comparison logic); click any cell in the daily or monthly table for that day's raw records
- The segmented control on the trend card switches among seven metrics (speed plus the six network KPIs) and the dropdown sets the moving-average window (3/7/14/30/60 days). Switching to a network KPI turns the chart into a single line with **no operator legend**, because it belongs to neither operator
- BP and the DL/UL PRB utilization rates are stored as **decimal ratios** (e.g. 0.1956) and are converted to percentages for display (19.56%); win/loss and scoring use the raw ratios, so the display conversion does not affect results
- Traffic (GB) and RRC user counts are shown with thousands separators; missing data renders as "—" (never 0)
- Excel export has three sheets (summary / monthly / daily); the summary sheet groups the head-to-head and the network KPIs separately so they are not read as one thing
- **Every number explains itself on hover** (2026-11-04): an ⓘ plus bubbles across the verdict, score, speed, range and network cards; the network cards dropped their **native title= attribute** (not copyable, outside the theme)
- One reversed caliber was corrected: `bmm.hint.bp` used to say higher is better while the rule is `kind: lower` (BP is the share of bad-performance cells, so lower is better). Both dictionaries were fixed; the same text also appears under the trend chart and in export headers
- The bubbles also state three ways this page differs from the Speedtest page: **the score is decided by speed alone** (`SCORE_WEIGHTS = {speed: 1.0}`, network KPIs do not take part), **paired days exclude ties from the denominator** (Speedtest keeps them), and `days` is the row count of the whole table in the range (one number for both operators) rather than each operator own days-with-data
- The drill applies the 3000-row cap before filtering winners in Python (`bm_meta_service.py:419-423`): rows match the card while the range stays under the cap and fall short only beyond it, which the bubble states as such

#### noc_analyst（`noc_analyst`）

NOC operator analysis: quantifies each NOC operator's root-cause mismatch rate, average handling time, night-ticket share and SLA pass rate from eflow_tt.last_processer, and raises red flags. Built around "drill down wherever possible" — from the person to the ticket, then to the alarm chain.

- Scope: tickets are attributed to a month by alarm occurrence time (alarm_occur_time), not last-modified time; night = Accept operation time between 22:00 and 06:00
- Mismatch rate = mismatched tickets / tickets with a filed root cause (**the denominator is not all their tickets**, and operators who filed none are excluded from the average). The system side is read from eflow_tt.alarm_reason_type and, when that column is empty, falls back to a static alarm-code semantics table (the previous wording claimed history_alarm.reason_type was authoritative, which the code does not do; corrected 2026-11-03)
- **The six summary cards and the Top3/Bottom3 numbers explain themselves on hover** (2026-11-03): each bubble gives the value, its denominator, the month window and scanned row count, and the active owner / name filters. The three rate cards **do not share one caliber, so do not compare them side by side**: mismatch rate and average handling time are **arithmetic means of the per-operator values (one vote each)**, while the SLA pass rate is a **pooled ratio** ΣPass ÷ Σ(Pass+Failed), weighted by ticket volume. Red-flag count is the number of **people** hitting any threshold (mismatch ≥30% or average handling ≥12h or SLA fail ≥50%), counted once each
- A known implementation defect is stated in the interface rather than hidden: the mismatch check intends to exempt Auto-recovery / Uknown / Force Majeure / Planned work, but the exemption tuple is mixed case while the filed value is upper-cased, so **it never matches** — those tickets still count as mismatches and the mismatch rate is systematically inflated. Fixing it changes a business metric, so it was left for a business decision
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
- **Every number answers how it was computed on hover** (2026-11-03): each of the four summary cards carries an ⓘ on the title (what the metric means) and a bubble on the big number (window, row count, dropped rows, that peak day's site count and series length); the "Occurrences" and "Down days" column headers and every cell in the ranking table behave the same, as do the Events / Sites / Repeat days tags in the drill-down. The page-level caliber sits in a collapsed "How site outages are counted" note
- What the four numbers really are: **occurrences = one TT row counts once** (three tickets for the same site on the same day count three times); **affected sites** dedupe on site ID first and fall back to the normalised site name, and rows with neither collapse into **one** Unknown site; **repeat-down sites** = sites with more than one calendar day holding an outage (**consecutive not required**); the **peak day** takes the earliest day when several tie
- Not the same caliber as the alarm board's "affected sites": that one dedupes on site_id only, whereas this page falls back to the site name, so the two site counts cannot be reconciled directly
- The site box is an **ILIKE substring match** while the drill-down uses **exact equality**; picking a region matches the site table's region column exactly, so **rows that fail to join a site are excluded** — the cards can then read lower than the database
- Rows whose occurrence time does not start with YYYY-MM-DD are dropped by the backend, and a **standing** warning at the top states how many (that is "incomplete", not an explanation, so it is never collapsed)

#### cr_analysis（`cr_analysis`）

CR Change Analysis: shows both where changes are stuck right now (status mix, workflow dwell) and how they performed historically (plan completion, on-time, closure), answering "how many are still open, at which step, and who is slowest".

- Data comes from eflow_cr (synced from eFlow); the default range covers the full data span
- The top bar is the **Workflow milestones**, in exactly the order of eFlow's Workflow History: Create → BO/FO Head Approval → Domain TD Approval → CM Head Approval → Start to Implement → Result Feedback → Closed. Each node shows "Done" and "Waiting"; the node with the most CRs waiting is marked **Bottleneck** and shows how many days the slowest one has waited
- Milestones group by workflow node: a CR sent back with "Waiting for Update" counts under BO/FO Head Approval rather than forming its own loop. For the exact spread over the 7 raw statuses, see the "Status Distribution" pie below
- Status names are upstream values and are not translated; "Waiting for Implement" means all approvals are done and implementation is pending — not "waiting for approval"
- Four core counts: "Planned" = has a planned start time; "Executed" = has an actual start time; "Not Executed" = planned but never started; "On Time / Delayed" = actual start before / after planned start
- **Every number explains itself on hover** (2026-11-04): the eight buckets are decided in the backend SQL (**"on time" is a lexicographic text comparison**, which relies on upstream timestamps being formatted consistently — the code comment admits the assumption); ⚠ **Planned ≠ Executed + Not Executed** — a row with an actual start but no planned start lands only on the Executed side
- ⚠ Category filtering now happens on the server: when categories are selected the page sends them as a `categories` parameter and the backend narrows **inside the same SQL** (values are bound parameters), so the overview, the rates, the category table, the status mix and the monthly / sub-category blocks all come from **one and the same set**; the frontend no longer adds the counts or duplicates the rate formula (2026-11-04). ⚠ The **three rates have three different denominators** (÷ planned / ÷ executed / ÷ total), so comparing those percentages side by side is meaningless; only the 80/50 colour thresholds live in the frontend
- Each rate shows its denominator: Plan Completion Rate = executed ÷ planned, On-Time Rate = on time ÷ executed, Closure Rate = closed ÷ total. Shows "—" instead of 0 when the denominator is zero
- "Approval Workflow & Dwell Time" parses the step records in the source table: Arrived = CRs that passed the step; Avg/Max Dwell = how long they took there; In Step = CRs still sitting there; Longest Wait = how long the slowest one has waited. Steps follow the **real flow order** (Created → BO/FO Head → Domain TD → CM Head → Implementation → Result Feedback), not the source column alphabetical order
- The "In Step" column is often the most useful signal: a step with many CRs waiting a long time is the bottleneck
- Every number is clickable: status cards, pie slices, KPI cards, rate cards, the category table, chart bars, workflow steps, the monthly trend and the sub-category table all drill into details, and the detail row count matches the card figure exactly
- A yellow banner appears when drill-down results are truncated — narrow the date range and retry rather than ignoring it

#### pm_analysis（`pm_analysis`）

PM Execution Analysis: shows preventive-maintenance work orders (PMT) by PM plan number (pmp_no), answering "how far has each plan progressed, how many are overdue, and where are they stuck".

- Data comes from eflow_pm (synced from eFlow); the default range covers the full data span
- Four core counts: "Closed" = status is Closed; "Open" = not yet Closed; "Overdue" = the source column pmt_overdue is Yes (the upstream verdict is used as-is, never recomputed from dates); "Not Started" = completed item count is 0
- Two finer breakdowns: "Closed & Overdue" = back-filled / late delivery; "Open & Overdue" = genuinely still unfinished — look at this one first
- Each rate shows its denominator: Closure Rate = closed ÷ total, Overdue Rate = overdue ÷ total (lower is better), Started Rate = share of work orders with at least one item completed. Shows "—" instead of 0 when the denominator is zero
- The "Workflow Milestones" bar at the top of the page strictly follows the eFlow Workflow History: Create → Schedule → Accept → Process → PM Manager Approve → FLM Leader Approve → Closed. Each node shows "Done" (work orders that passed it) and "Waiting" (work orders stuck there awaiting the next step); the node with the most waiting work orders is tagged "Bottleneck". Click any number to see those work orders and how long they have waited
- ⚠️ The source column names are misleading: last_process_time is the moment of ENTERING Process and precedes the PM Manager approve time — never infer the order from the column names
- With exactly one plan number selected, milestones follow that plan; with several selected, milestones cover all plans (the page says so) and may differ from the plan table subtotal
- Every number is clickable: KPI cards, rate cards, chart bars, the monthly trend, the site bar chart and the plan table all drill into details, and the detail row count matches the card figure exactly
- A yellow banner appears when drill-down results are truncated — narrow the date range and retry rather than ignoring it
- **Every number explains itself on hover** (2026-11-04): the ⓘ on each of the eight count cards states the SQL predicate behind that field, while the bubble on the number says "this figure = the matching field of the API summary" and that the backend counted it with SUM(CASE WHEN …) in a single query. The three rate cards' bubbles name the denominator (closure and overdue both divide by the total; started rate = (total − not started) ÷ total) and note that **a zero denominator returns null from the backend → the UI shows —, never 0%**
- The two easiest misreadings are in the ⓘ: **"Overdue" takes the source table's own pmt_overdue verdict as-is — the page never recomputes it from plan versus actual dates**, so when upstream leaves that column empty this card stays 0 even though orders may really be late; and because the dynamically created eflow_pm table holds both cases of status, every predicate normalises with UPPER(TRIM(…)) first

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
- The "BP cells (latest period)" card shows that period's BP cell count and its share of evaluated cells; the "Latest period verdict" card gives yes/no for week/month, and when undecidable it states the cause — a week still in progress (just wait) versus a month with too few full weeks (2026-09 has only 3 full weeks against the required 4, so that month can never be decided; a caliber-vs-calendar mismatch, not missing data)
- Regions (Cluster1~6 / Rural / ERA) can only be maintained in Excel; RAN_UME has no such dimension, and new cells missing from the dictionary fall back to Unknown
- The trend switches between day / week / month granularity; if the chart looks empty on week or month, first check that the date range covers periods that actually have data
- ⚠️ The four drill-down columns PRB utilization / DL throughput / Active users (busy hour) / DL traffic exist only from 2026-07-22 onward: BP Report.xlsx itself stores only date / NE / cell / cluster / layer and never carried these metrics, so they must be re-fetched upstream — and upstream retains nothing for the 21 days 2026-07-01~07-21 (UME likewise only goes back to 07-02), so that range shows — and cannot be filled
- For 2026-07-22~09-21 the four metrics have been backfilled from upstream, so those days now hold whole-network cells rather than only the cells umlaut reported; BP counts run about 13~14% below that period's original Excel values, and the share denominator follows the same caliber change
- Data is incrementally refreshed from RAN_UME by the bp_report_sync task daily at 06:20
- **Every number explains itself on hover** (2026-11-04): the ⓘ on the "share" column header says it is **that period's own stored bp_ratio** (the page never re-divides BP by all cells), and each share cell carries a bubble with that period's numerator, denominator and the difference against its detail rows. The "BP cells (latest period)", "Periods" and "Average BP share" cards put an ⓘ on the title and a bubble on the number
- The "Average BP share" card is the easiest to misread, so its bubble prints both figures side by side: it is the **arithmetic mean of the per-period shares (one vote per period, AVG(bp_ratio))**, **not** ΣBP ÷ Σall — the two disagreeing is a caliber difference, not a bug. A period with very few cells weighs exactly as much as one with many
- "Periods" = how many periods in the selected range **actually have data** at this grain (one row per period), not the number of natural periods; it changes with the grain, so check the date range covers periods that have data

#### ran_cells_kpi（`ran_cells_kpi`）

RAN Cells KPI: per-technology (2G/3G/4G) daily availability matrices for cells, plus monthly compliance.

- The daily matrix is laid out as "metrics as rows, dates as columns", and only dates that actually have data are shown
- The technology filter decides which tables are rendered; the threshold decides the meeting/below verdict (99.65% by default, matching the backend)
- The page-level export contains `Summary` (one row per technology: monthly average availability / cell roster / days with data / total cells / meeting / below / both ratios) plus one `<tech>_Cells_KPI` daily matrix per technology
- Sheet1 is deliberately named `Summary` rather than `<tech>_Cells_KPI`: otherwise a name clash would rewrite it to `Summary_2` and users would see two sheets that both look like a summary
- Percentages are written as numbers (e.g. `99.65`) rather than strings (`99.65%`) so they are directly computable in Excel
- The drill-down modal has its own export button (detail rows) — that is separate from the page-level entry
- **Every number answers how it was computed on hover** (2026-11-04): the monthly card title carries an ⓘ for the algorithm while the number itself carries a bubble with the composition (how many valid days were averaged equally, cell-day observations, roster size, threshold, and the **actual data source** — whether the materialised daily table or a live computation, decided by the API meta.source). Each of the seven matrix rows has an ⓘ in its header and every cell a bubble (how many meeting, how many below, how many cells had no data that day)
- The two easiest misreadings are stated in the bubbles: **the monthly figure is the arithmetic mean of the daily availabilities (one vote per day, not weighted by the number of cells that day)** — a day with 3 cells counts as much as a day with 300; and **the meeting / below shares divide by the cells that had a value that day, excluding cells without data** — so heavy upstream gaps inflate the meeting share
- This page is **cell-level** availability (2G = available channels ÷ (available + unavailable), 3G/4G = service time ÷ 86400) and is **not the same caliber** as the site-level UME values on the site availability page — the two cannot be compared directly

#### Packet Loss（`packet_loss`）

LTE packet loss board (RAN UME SDR / IPRAN IPPD): last 7 complete calendar days at hourly granularity; the ongoing day is hidden.

- Criteria match the Packet_Loss automation Excel report exactly; the Popover explains them
- The switch controls whether OK sites are included; supports drill-down and topology overlay
- Desktop layout (re-laid-out 2026-11-11 per wireframe): the map card takes the left 2/3, the right 1/3 stacks the status pie / daily trend / region charts, and a full-width Top sites table sits at the bottom; narrow screens stack vertically
- The map carries county fills (opacity 0.2, i.e. 80% transparent) and county name labels (wide screens only); roads and place labels are off by default. **Click a site dot to drill down**: the unified modal shows that site's daily Max / median PL over the last 7 complete days plus an hourly table for the last complete day, with search and Excel export
- **Every number explains itself on hover** (2026-11-04): the six status cards share one text between the ⓘ and the number bubble (the verdict is written in the collection layer as FinalStatus: STATUS≠OK with Last 1 day Max PL ≥5 / [1,5) / [0.5,1) / [0.1,0.5) = Critical/Major/Minor/Warning, and STATUS=OK is forced into No Packet loss); the header Affected Sites and granularity tags carry bubbles too
- The three easiest misreadings are stated in the bubbles: **the status pie includes sites without coordinates, the region bars count non-OK sites only (Minor and Warning included), and the header Affected Sites is Critical + Major only** — three different sets that were never meant to reconcile
- The daily-trend median **uses only readings above 0 for that day** (about 59% of hourly readings are 0, so a full median collapses to zero and stops being meaningful), while Top sites use a **per-site median that includes zeros** (otherwise "half a day fully down" and "fully down all day" both become 100 and the ranking loses its point) — the same word "median" for two calibers, each stated where it is used
- This page used to carry two hand-written popovers (their own copy button, theme colours and emphasis rendering); both were deleted in favour of `components/MetricExplain`. The drill "N rows" bubble now states that it is the count after the search-box filter and that the API truncates at a cap

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
- **The seven overview cards and the resource lines explain themselves on hover** (2026-11-04): the most important sentence is that **every KPI card aggregates the latest day only**, so the overview totals (attempts / failed / system-side / user-side) are **those latest-day values added up — not the selected day window**. A header reading "last 30 days" does not make it a 30-day total; each bubble names the day the number came from. Resource "daily avg / peak" are likewise the mean and maximum of that latest day's SERVICE rows
- Colouring follows the **system side only**: KPIs with reason columns are judged by system-side failures ÷ attempts, others by success rate, and non-alarm KPIs stay info. User-side failures never turn a card red — they only appear as an info note, so "nothing is red" does not mean "the user side is fine"
- Thresholds come from the API (defaults: 99% success, 0.1% system-side failure, 80% resource; overridable via UME_IN_* variables). The alerts count is produced by the frontend dropping info-level rows from the alert list
- **Every number explains itself on hover** (2026-11-05): the eight KPI cards share one text between the corner ⓘ and the big number (hovering the number works too); the three alarm badges and the four distribution chart titles gained their own notes
- Those eight cards **are** computed in the frontend, deliberately and with approval: the API `kpi` block is the **unfiltered total**, while the six on-page filters require the cards to react instantly. Reconciled value by value on 2026-11-05 and written into the bubbles: fresh count / fresh rate / discharging / SOC-critical / degraded / stale and all five distributions are **identical bucket by bucket**, and the averages differ only in precision (frontend 1 decimal, API 2). **Only "batteries" and "sites" are two different semantics** — with "fresh only" on the cards show 352 / 48 while the API total is 1532 / 208. A mismatch normally means a filter is active, not that the data is wrong
- Two "same name, different source" traps are stated in the distribution ⓘ: **the SOC bucket boundaries are hard-coded in the frontend (20 / 50 / 80) and do not follow the configurable `soc_critical`** (the two "20%" on this page come from different places — only the card moves when the setting changes), and **health buckets follow the thresholds while their label text is hard-coded** (`80-90%` / `90-95%`), so changing a threshold makes the labels wrong — trust the ⓘ wording
- The three alarm badges count alarms over the **filtered site set**, while the API also returns an `alarm_summary` that never follows the filters; the alarm list is capped at 2000 rows, so once the cap is hit these counts are low

#### cn_kpi（`cn_kpi`）

CN KPI dashboard: a native rebuild of the original FineBI "CN KPI" board, with 18 widgets (VLR / Voice / Data subscribers, USSD success rate, location-update success rate, USPP / MSC / xGW utilisation, FDD / TDD traffic, RG-6/11/12/30 and more). Data is read from db_ps_cs_cn through the remote read-only SQL API and does not depend on the my-finebi process. Note: this page draws on two independent pipelines — manually exported _EMS tables (which stall, and whose granularity follows the export range) and auto-synced _UME tables — so fetching degrades gracefully and the granularity is labelled on both the card and the page header.

- The default range is the last 31 days; after changing the range and querying, month-granularity widgets automatically widen to the last 13 months
- An orange "Monthly" tag on a card means each point is one month, not one day; a gold "Switched" tag means the original table stalled and an auto-synced source of the same name is being used
- The orange banner in the page header lists every degraded widget and why — if you see it, check whether someone needs to re-run the NMS export
- "Export Excel" writes each widget's data plus the exact SQL used, so figures can be reconciled against the NMS side
- **Every number answers how it was computed on hover** (2026-11-04): the card-title ⓘ and the header "latest data date" figures state that **each point is the raw value returned by the backend SQL and the page performs no secondary computation** (no gap filling, no smoothing, no unit conversion), then list rows returned, **actual granularity**, whether a downgrade happened (naming the original table) and **the SQL actually executed, copyable with one click**
- Granularity is **inferred from the dates in the returned rows**, never hard-coded (only the monthly tier is recorded as month directly). So before reading 1–2 points as "the last two days", check the granularity line in the bubble
- The header statistics expand into three facts on hover: the source is a remote read-only HTTP API (not a local database), the widget count and fetch time including whether the cache was hit, and the failure count covering **only widgets whose three source tiers all errored** (empty widgets do not count)

#### cn_kpi_5mins（`cn_kpi_5mins`）

CN KPI 5-minute dashboard: overlays today (Day0), yesterday (Day1) and 7 days ago (Day7, the same weekday) on one chart so the same clock time can be compared. The cnn_kpi_sync_5mins task collects it every 15 minutes (window: yesterday 00:00 to now) into new 5mins_* tables in db_ps_cs_cn, independent of the daily/monthly CN KPI board. WARNING: granularity is MIXED — Voice / VLR / Data / 4G FDD / Free Rating are 5-minute; xGW License, xGW CPU and 3G FDD use the upstream 15-minute templates (created 2026-10-19) because their original templates had no 5-minute tier.

- Up to three lines per chart: Day0 today, Day1 yesterday, Day7 seven days ago (the same weekday — it answers "is this hour up or down versus the same hour last week", which is less misleading than comparing with yesterday alone because weekday/weekend shapes differ); the x axis is the clock time (HH:MM), so the same x value is the same time of day
- Day7 depends on history already sitting in the tables: the sync window only covers "yesterday -> now", but writes are upserts with no purge, so every day is kept permanently once it is collected the next day — Day7 needs 8 days of accumulated history, and when it is not there yet the header lists only the days that exist and says so. Older days require a backfill
- No date picking is needed: the window is fixed to today + yesterday + 7 days ago and refreshes every 15 minutes as the task runs (auto-refresh is available in the top bar)
- The xGW License / xGW CPU / 3G FDD cards have points every 15 minutes (3x sparser than the others) — that is the upstream template tier, not missing data; the blue banner in the header says so
- **Every widget title explains how its values are computed on hover** (2026-11-04): the ⓘ spells out the aggregate per widget — VLR / Voice / Data / 4G·3G·RG use **SUM** (RG-6/11/12/30 split one table by "Measurement Object", so the four cards never overlap; byte columns are already /1e9 converted to GB in the SQL), while **xGW License and xGW CPU use AVG — an arithmetic mean of percentages, not traffic-weighted and not a peak**. Day bucketing and the x-axis both read End Time (not Begin Time), and the window holds only **today / yesterday / 7 days ago**, not a continuous week
- The "vs yesterday ±%" tag opens with the admission that it is computed **by the frontend** (the API sends no pct): today's mean from 00:00 to now against yesterday's mean truncated to the same clock time, ±10% grey and beyond orange. It disappears entirely when either day has no point in that span, or yesterday's mean is 0
- The header tags "N/N widgets with data", "elapsed / cache" and "N failed" are hover-explainable too: empty and failed widgets are both **excluded** from "with data", and the failure count covers query errors only
- "Export Excel" writes one sheet per widget, expanded as Day0 / Day1 / Day7 columns by time of day (only the days that widget actually has)

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
- The first cell of the "Advanced Filter" panel is a "Site Name" input: fuzzy match on a name fragment (case-insensitive); the rest are dropdowns for region/grade/form/FME etc.
- Statistics follow the filter: site total and the ERA/COOL/NORMAL grades, the map legend, the county block colors and county labels, and the "MAINTENANCE ALERTS" county ranking panel are all recomputed from the filtered sites instead of showing the full-set numbers;
- Click a site to open the right drawer: four tabs, searchable, exportable to Excel
- The drawer "Basic Info" includes **power status** (same source as ?page=ipt_power): connectivity refreshes for all sites every 2 minutes; SOC / voltage / load etc. come from the latest snapshot (all-site popup KPI collection each round; under upstream stress a ring cursor rotates coverage, ~2-6 min per site); shows — when the site name does not match any IPT site; see the ⓘ note on the label for details
- The "Link Utilization" switch (on by default) overlays MW microwave link utilization from the same 15-min slot as the MW Realtime page, colored on a 4-level scale (>80% critical / ≥70% major / ≥60% minor / <60% healthy); thicker lines mean higher utilization
- Click a link to see its max/Tx/Rx utilization and the matched MW sites; a link showing "No KPI data" means it could not be matched to realtime metrics (it keeps its original KML color) — that is not 0%
- The overlay scope is explained below the legend: about 360 of the 844 KML links match realtime metrics; the rest are still viewable on the MW Realtime page
- Each of the "2G KPI / 3G KPI / 4G KPI" tabs now shows **two charts**: network quality (availability, setup and handover success rates — ratios sharing one % axis) and **traffic volume trend** (CS traffic in Erl, data volume in GB, throughput in Mbps, 4G RRC users, outage minutes — **one y-axis per unit**). Each chart has its own metric picker, and the volume chart already plots 3 series by default instead of hiding them in a dropdown
- The volume chart follows the drawer's "Statistics range" (since 2026-11-04). Before that the KPI series was fixed at 60 days and ignored the 7/30/90/180 switch — now fixed
- When a site sits under several BSC/RNC the upstream writes one row per ID per day: the API folds them by calendar day, **summing traffic** into the site total and **averaging ratios**. The ⓘ on each chart title, the table column headers and every number in the daily table are hover-explainable, and the text comes from API fields — nothing is recalculated in the browser

#### Realtime Alarm Map（`realtime_alarm`）

Realtime mode of the GIS map: current active-alarm sites on the map (red "realtime" badge), with Root Cause Aggregation.

- Interactions are identical to the GIS Map page
- Data comes from eFlow active alarms (eflow_active_alarm) synced every minute
- The "Root Cause Aggregation" card clusters the down sites within your current advanced-filter scope — topology roots (an upstream site is down, so the sites hanging off its link path go down with it) and same-cause clusters (sites without a link path grouped by alarm problem + a 10-minute time window), each with cause type, affected-site count and a confidence score; click an entry to see member details and evidence (link paths, time window, eFlow impact list); member site names open the site drill-down drawer
- The "attributed/total" counter in the title uses the same **site** unit as Site Stats: attributed = sites that share a root cause with peers; the rest are isolated failures (upstream healthy, no same-window peers — the site itself is its own cause) — click the footnote to open the unattributed **alarm details**, the same project-standard detail table as clicking an entry in Alarm Stats (site / TT / priority / alarm time / duration / overdue), and verify against the map
- A root site may fall outside your filter scope (flagged "Out of scope") — outage causes often sit outside your current view; this is expected and is exactly the value of the analysis
- The "AI Insights" button generates a natural-language conclusion using your own LLM key (stored only in your browser); when AI is unavailable it degrades to a local rule-based summary and is clearly marked — the cluster list itself is unaffected

#### person（`person`）

Person Location Map: the registered position of field staff (map pins) + the distribution of sites each person actually handled, with per-person WO / TT statistics and open PMT counts.

- Two-column layout: map on the left, KPI 2x2 + two charts on the right; `?maponly=1` leaves the map alone
- Click a person to select them and slide open the drill-down drawer from the right; clicking blank map area or anywhere outside cancels the selection (search / paging / tab switches inside the drawer do not close it accidentally)
- The persistent pin badge has two lines: name + phone on the first, "sites handled | open WOs | open PMTs" on the second
- Phone numbers are shown in full (not masked); some upstream records were already stored as `231****7417`, and the backend restores them uniquely by "same name + same last 4 digits" from the site master — the ones it cannot restore stay masked, which is a data fact
- Site coloring is fully aligned with `?page=realtime_alarm` (same color source and same grading): both pages look at the same sites from the same snapshot
- PMT shows — rather than 0 when unavailable; the per-person badge sum is not the full set (see the filter-bar info note for the caliber)
- Table rows and map selection are two-way linked; only rows with coordinates are clickable, others use the "View tickets" button
- **The four KPI cards and the four numeric table columns all explain themselves on hover** (2026-11-05): the People card takes both numbers from the API coverage **FE scope** (staff with person.isfe=Yes, and of those those with valid coordinates) and deliberately not from with_coords / total_all (map pins and table rows, which include non-FE staff); the Uncleared / Unclosed / Total cards **sum the API per-person fields over the rows currently in the table** — each person value comes from one backend scan (uncleared = alarm_clear_time empty **and** status not closed, a different concept from "unclosed tickets"); the Sites card shows a dash until a person is selected (the API never publishes a de-duplicated all-staff site count); the TT column counts **WO rows carrying a tt_no**, per row, not distinct TT numbers

#### Incident Overview（`incident_overview`, iframe page）

OLR incident overview board: cards, matrix, SLA charts, paginated details and a map.

- Data is fetched at minute 20 each hour by incident_overview_sync from the latest incident_overview.xlsx on the FineBI FTP (versioned files, resilient to the upstream file being locked). It runs at minute 20 on purpose: FineBI deletes the previous output folder at :53 and the new copy only lands around :02–:05

#### Warehouse（`warehouse`, iframe page）

Spare-parts / consumables inventory board (Spare Management), identical to the original tool.

- Data comes from sp_data_sync (5 spare-part reports pulled from SFTP daily at 07:00)
- Browse inventory and details by warehouse / spare type

#### sp_material（`sp_material`）

Spare-parts material summary: inbound, outbound and inventory rolled up by domain / material.

- Data comes from the spare-part reports pulled by sp_data_sync
- Click any summary figure to drill into the matching material details
- **Every number explains itself on hover** (2026-11-04): the ⓘ on a column header states the bucketing for the whole group (status = damage goes to "needs repair", otherwise Material Type is matched on spare / consum; a row joins a group by exact or prefix warehouse-name match, misses fall into Others), while a cell bubble gives that cell's composition (the raw opening / current snapshot values, consumption = opening − current, whether the total includes damage) and reminds that **these are SUM(Stock Qty) quantities, not counts of distinct materials**
- Two traps are spelled out in the bubbles: **"Repair Outbound" comes from a different table and a different window than the stock snapshots, so it must not be subtracted from a stock column**; and **a negative consumption is legitimate** — inbound or transfer back-fill can make stock rise, while the measure is only "opening − current" and never nets the replenishment (when it happens a standing notice names the groups)
- The "Total" at the bottom of the drill-down modal is summed client-side over the **rows currently matching the search box** (the API does not send it); the bubble also states how many rows the drill returned, so the two agree once the search box is empty

#### sp_details（`sp_details`）

SP Details Report: the same merged workbook that the email task sends, with Inventory / Inbound / Outbound / Transfer sheets.

- Paginate, filter and sort; "open" means Status does not contain Closed
- Only common columns are shown — click any row for all columns of that sheet
- Export covers the current filter (up to 5000 rows)
- **All eight cards explain themselves on hover** (2026-11-04): records = row counts added across sheets with **no cross-sheet de-duplication**; "Materials" is Material No. **de-duplicated over the union** (structurally different from the same-named row count on the spare-parts report); "Warehouses" counts the transfer sheet's **original and target** names on both sides, so reading higher than the number of storage locations is by design; open tickets use the "status does not contain closed" test
- ⚠ This page reads the *_source.xlsx snapshots taken **before any filtering**, while the summary pages read the filtered workbook — same-named metrics are systematically larger here, which is a caliber difference, not lost data
- ⚠ The whole site has three definitions of "open" (this page: per-row substring match / spare-parts report: distinct document number + word list / warehouse board: exact equality), so the three figures are not meant to reconcile
- Material Name here is also resolved from the sp_material master (values only, no row changes, since 2026-11-06), so this page, the spare/consumables summary pages, the 07:05 merged email and the 10:05 per-file attachments all show the same name; row counts still match SFTP upstream line for line
- This page resolves the master **at read time** (the merged workbook itself is still the 07:05 snapshot): a rename after 07:05 shows up here the same day, while the spare/consumables summary pages wait for the next day’s report to be regenerated — because their Summary-Current aggregates by material name, so a live rename would put two spellings on one page; this page has no name-keyed aggregate, so it cannot

#### sp_report（`sp_report`）

Spare Parts Inbound & Outbound & Inventory summary: the same workbook emailed / sent over WhatsApp (produced daily at 05:15 by sp_report_generate), with Summary-Current / Summary-Changed / Inbound / Outbound / Inventory sheets.

- Stat cards show totals and replenishment alerts; clicking an alert card filters
- Summary-Changed renders as a day × warehouse matrix
- "Columns" is configurable per sheet and remembered locally; the row-detail modal always shows every column
- **Every number explains itself on hover** (2026-11-04): the seven quantity cards say "this value = the raw Total-row cell of Summary-Current · some column", and warn that **a missing or non-numeric column comes back as 0.0 from the backend** — so a 0 can be a real zero or an empty column; "Materials" is a **row count, not de-duplicated material numbers**; "Urgent" counts **rows** whose Alert Level equals Urgent Replenish, a different unit from its Qty neighbours — do not subtract one from the other
- The "open documents" bubble states it comes from the **live database** (same caliber as the SPMS figure on the MsPortal QC panel), because the workbook is a 05:55 snapshot while the DB lands at 07:00; all other statistics stay on the Excel snapshot so the page matches the emailed attachment
- **Material Name comes from the sp_material master (latest name)**, effective 2026-11-06: in the upstream detail this column is the name captured when the document was exported, and eFlow renames never rewrite history, so one material splits into two Summary-Current rows with inbound/outbound/inventory broken apart. Step 0 refreshes the master from eFlow and Step 2.5 overwrites the five details plus the five raw snapshots by Material No. (implementation: backend/services/sp_material_name.py). Consequence: a rename after 05:15 lands in the next day’s report — the page reads that same report, so a single page never shows two spellings.

#### com_report（`com_report`）

Consumables Inbound & Outbound & Inventory summary: same layout as the spare-parts page, reading the consumables workbook instead.

- Identical basis to the spare-parts page — see "Report basis" at the bottom
- When the page and Excel disagree, read the basis notes first; never change the basis in the page layer
- **Every number explains itself on hover** (2026-11-04, same wording as the spare-parts page)
- The "open documents" figure has a **different source** here than on the spare-parts page: the live-database override applies to spare parts only, and consumables tables are landed by another sync job whose names we do not guess, so this page keeps the Excel snapshot caliber (fixed 2026-11-04 — previously consumables were wrongly overridden with **spare-parts** numbers)

#### warehouse_summary（`warehouse_summary`）

Warehouse Summary Report: mirrors WarehouseSummaryReport.xlsx — the tabs are its two sheets, Spars Parts / Consumables. Each tab has two sections: WH/DOP inventory & consumption (current inventory / total / this month / this week), and frequently used materials (10 rows per page, all materials reachable by paging).

- Switch tabs for spare parts vs consumables; every figure in both sections drills down
- Frequently used materials are paged by consumption descending, showing all of them; the Total row is the full-scope total and does not change when you page
- Consumption basis is Outbound Site Qty (site outbound), shown as a tag next to the second section title
- **The six KPI cards explain themselves on hover** (2026-11-04): the warehouse set is the **union of Outbound and Inventory** — a warehouse on one side only still gets a row and the missing side counts 0; the month/week time column **falls back dynamically** by priority (the column name comes from the API, the page does not guess), weeks start on **Monday**, and window starts use the host clock (UTC)
- ⚠ Rows whose time cannot be parsed are **excluded from the month/week windows but still counted in total consumption**, so "this month + previous months ≠ total" is expected
- Needs restock reads the API field `overview.urgent` (the backend counts Alert Level matches over the **whole** Summary-Current sheet), i.e. the same field and caliber as the same-named card on the spare-parts report, so the two should agree; when they do not, the pages are reading different workbook runs (check the header file name and generation time). Before 2026-11-04 this card was reduced client-side over the frequent rows; that has been changed

### 4.3 Analysis & Tools

#### eFlow Knowledge Base（`eflow_qa`）

eFlow TT rule knowledge base: full-text search over rule/case documents, with built-in TT quick analysis.

- Search with space-separated keywords or pick an article from the catalog on the left
- Enter a TT number for one-click analysis: assignment, time gap, root-cause distribution and key conclusions
- The verdict card and the "Rule match evidence" block below it are both computed by the local rule engine (same source as Email Reports → eFlow TT Rules Check): matched rule name/ID, per-condition match details, the rule source file eflow_TT_rules.xlsx (downloadable), the rule owner and the ticket handler
- No model is called (since 2026-10-19): the verdict returns in milliseconds — severity verdict, matched rule, rule source and recommended actions are all derived by the local rule engine from the eFlow "TT Update Severity Rule" table, word-for-word consistent with the daily 04:20 eflow_tt_rules_check job
- Rule source & owners also lists the push order rule (TT Push Order Rule, triggerStep=FO Accept): Rule Name / Rule Type / Rule Trigger Step / Push Order Path / *Auto Operator / Target Handler — i.e. whether the TT is auto-pushed to a WO, to whom, and which operator acts automatically (source: eflow_push_rules.xlsx, downloadable)
- TT batch check: upload an xlsx/csv/txt list of TT numbers or paste them to judge each ticket severity (OK / needs adjustment / undetermined) and export to Excel
- The batch check supports a "download template → fill in → upload" loop: download the templated xlsx, fill in the numbers and upload the same file back
- **Every count on this page answers "how is this computed" on hover** (2026-11-05): the UME history "N matched" reads API history.total (UME totalcount), while this lookup queries **the same site ± 2 minutes around the alarm time and returns at most 30 rows per call**, so the table usually holds fewer rows than N (a dash when unavailable, never a fake 0); all six batch-check chips read the API summary / input fields (the endpoint also returns invalid, duplicated and truncated, which this page does not display); the rule count comes from the backend reading eflow_TT_rules.xlsx; same-site cell counts and search hits are frontend array lengths, and the cell tags render **at most 60**

#### eflow_flow（`eflow_flow`）

eFlow process flow: enter an alarm (alarm ID / alarm code) or a TT number to draw the ticket's full eFlow process — the rule-driven state machine plus the path actually traversed, highlighted.

- Three input types: TT number (TT202609230060), alarm ID (the alarm table id/aid), or alarm code (e.g. 99933); querying by alarm code lists the most recent TTs carrying it so you can switch
- The base diagram is the rule-driven state machine: Alarm Raised → TT Created → Auto Dispatch → FO/BO Accept → FO/BO Process → 3rd Party Accept/Process → Confirm → Closed; the active/total count under each node is how many rules bind to that step
- Green node = a step the ticket actually traversed, amber node = the current step (taken from the operation_type field), grey = not involved; thick cyan edges = the actual path
- Click any node to switch the "Rule details" table below to the rules bound to that step; **by default only rules related to this ticket are shown** (conditions evaluate true for it, including empty-condition fallback rules); the "Related only / All" toggle reveals the full attached set, and "All nodes" lists every node's rules at once
- **Click a rule name to open its detail** (2026-11-10): the dialog shows the rule basics (ID / severity / owner / updater), the raw condition text, per-condition ✓/✗ evidence, and this ticket's value frame (alarm code / VIP / HUB / site type / down-site count…); the verdict comes from the same engine as the eFlow knowledge base and assignment attribution — no second judgment source; rules whose conditions reference locally unavailable fields are marked Undecidable rather than unrelated
- **Multi-condition simulation** (2026-11-10): switch the query card to "Multi-condition sim" to skip the concrete ticket and give a set of conditions (alarm code / severity / VIP / HUB / site sub type / site type / network type / current down sites / downstream sites / root cause / alarm description), then see how every rule would judge — same engine and normalization as the ticket query (YES→1/0); **empty fields join as "no value"** so conditions referencing them fail; e.g. "HUB site P1" also requires current down sites ≥ 5, so leaving that blank keeps it unmatched — the evidence column in the rule detail states exactly which condition failed. A simulation has no ticket, so the TT info / actual path / related-alarms blocks are hidden
- The "Actual path" table lists the milestones the ticket really went through, with operator and note; "TT ticket information" gives severity, current handler, SLA and root cause
- If the TT spawned a field work order, a "WO field sub-process" block shows the WO's own Accept → Process → Confirm → Closed pipeline plus per-step handling detail (from the eflow_wo *Detail columns)
- The "Related alarms" table lists the alarms that raised this TT (linked via realtime_alarm / history_alarm tt_id or alarm_id), with alarm code, site, network element, severity and raised time
- Verdicts share one source with "NOC analyst" and the single-TT postmortem report: rules are all read from ocrule_details, so the flow diagram and the postmortem can never disagree
- The rule tables are collected by the eflow_push_rules_collect / eflow_alarm_rules_collect jobs (every 3 days at 23:59); the diagram reflects rule updates automatically
- **Every number answers how it was computed on hover** (2026-11-03): the "Steps taken" and "Process rules" cards, the "N active / N total" tags on the node rule header, and the diagram's own node tooltip all expand into the rule; the page-level caliber now sits in a collapsed "How the eFlow graph is computed" note
- Three things these counts require you to know: ① "Process rules" = **all rows of ocrule_details** with no WHERE and no time filter — it is today's snapshot, not the rules this ticket met; ② a node's "total" is the **deduped attachment count** by (name + type + trigger step), and one rule can attach to several nodes, so summing the nodes exceeds the table rows; ③ "active" requires status **exactly ACTIVE** (case sensitive), so an upstream value of Active counts in the total but not in the active figure
- "Steps taken" only counts **TT main-flow nodes** (Alarm Raised and TT Created are marked unconditionally, so it starts at 2); the WO field sub-flow is a separate lane and is excluded. "Matched this ticket" counts rules across **all nodes** whose conditions evaluate true for this ticket (including empty-condition fallbacks), deduped by (rule name, node) — the same scope as "Related only", and it does not move as the ticket advances
- The rule table is a **current snapshot**: for a ticket that has been in flow for months, the diagram shows **today's** rules, which may not be the ones that actually routed it — keep that in mind when using it to explain a historical ticket

#### Dashboard（`dashboard`）

Analysis dashboard: pick a table to auto-generate multi-dimension charts and conclusions, archiveable.

- Pick a table → rename → generate → archive
- With "linked filters" on, clicking a pie/bar applies it as a filter; click again to cancel
- **Every chart carries an ⓘ saying how it is computed** (2026-11-04): pie = `value_counts().head(10)` (ranks 11+ are not in the denominator, so 100% is not "all rows of that column"); bar = `groupby().mean()` over the category then `head(15)` (a mean, not a sum, unweighted); line = `groupby().size()` per date then `tail(60)` (the axis counts rows, no metric is summed); radar = the **heuristic** quality score `100 − null_rate − min(issue_count × 10, 50)`, not a business compliance rate; heatmap = `crosstab().head(15)` row counts per combination
- The single most important caveat sits in the header ⓘ: **every chart is computed over a sample of at most 10000 rows** (`SELECT * FROM table LIMIT 10000`, no ORDER BY, i.e. the first 10k rows in storage order, `routers/analysis.py:60`), while the "N rows" in the dropdown is a full-table `COUNT(*)` — on a big table the two cannot add up, and that is the sampling caliber, not lost data
- "Linked filters" is **frontend highlighting only**: clicking does not refetch, so the figures stay whole-sample; and a 0 in the bar or heat charts has two possible sources, because the backend maps NaN to 0 (`analysis.py:280` / `:331`) — it can mean "genuinely zero" or "nothing numeric to average"

#### Archive（`archive`）

Analysis archive: search, view and delete past analysis results; pairs with the Dashboard.

- Keyword search + pagination; details include conclusion text and chart snapshots
- Deletion asks for confirmation — be careful

#### IP Trace（`ip_trace`, iframe page）

IP trace: probe link connectivity and path nodes from the server side to a target site.

- Enter a target and start; the result table/map refreshes live
- Tracing is a stoppable long task — stop it manually if it hangs

#### vmax_user_query（`vmax_user_query`）

VMAX complaint diagnosis: enter a subscriber number and time window to answer "why is this user complaining?". The page pulls four Talon XDR sources in one shot (user plane 1300 / signaling 1100 / video 1301 / RAN 32), scores the network on four dimensions, names a conclusion, and drills down to the minute-level evidence chain. Built for voice, OTT voice/video, video stall, gaming and slow-data complaints.

- Use the full number with the 231 prefix (e.g. 231777777322), digits only; the local 9-digit format is not matched upstream (verified 2026-10-24)
- **Complaint-type tabs** (not a dropdown) come first: All / Voice / OTT voice & video / Video / Game / Slow data. Switching them **does not re-query** — it only changes the weighting and which chain gets judged, so switching is instant
- The three-line layout is deliberate: query bar → complaint-type tabs (what the user is complaining about) → view tabs (diagnosis / traffic / connection / radio). The hint under the complaint tabs always states which chain is being judged right now
- The "Voice" tab judges **CSFB and VoLTE**. The 1100 SGs interface records are the evidence source: SGs location update count, CS Fallback Triggered, Extended Service Request, paging, timeout/failure and QCI=1 bearers are all counted, plus the fallback chain (S1-MME / SGs interleaved by time) and the fallback duration
- CSFB fallback time over 2 s is flagged; when the window has CSFB activity but **zero SGs records**, the card raises an explicit warning instead of quietly reporting success — that usually means the SGs interface is not reporting
- The "Game" tab is kept on purpose: XDR bills really do carry app names such as egame / E-GAME. Game detection is keyword-based (so new titles can be added without code changes), and **app stores are blacklisted** (palmplaystore / googleplay / app store / huawei_appgallery) — otherwise "opened the store" would be counted as "played a game"
- **Capability boundary — OTT voice/video (WeChat, WhatsApp) cannot be judged at the application layer**: this platform has no SIP/RTP signaling. The OTT card therefore answers only "was there a call" and "how good was the network during the call" (duration, downlink RTT, RTT jitter, retransmission) and **cannot answer "the other side rejected me / my call failed to connect"**. That banner is rendered above the conclusion on purpose — please do not read the OTT card as a call-failure verdict
- Four-dimension scoring: Availability / Latency / Transport quality / Radio quality. Each is 0–100 with a colour band (≥80 green, 50–79 amber, <50 red); the dimension matching the complaint type carries an orange dot. A dimension with no data shows "—", **never 0** (0 would look like a real failure)
- Click any scoring card to open that dimension's full evidence (every raw metric with its threshold); click any cell in the minute-level evidence timeline to open the underlying XDR rows
- The evidence timeline aligns the four sources into minute buckets, so a stall shows up as one row where traffic is normal but latency, radio and the conclusion all go bad — that is what you paste into the ticket
- **Manual override is allowed and encouraged**: click "Override conclusion", pick the severity, enter the reason (at least 10 characters, required) and submit. The override renders **above** the system verdict with a blue left border, so the human judgement is what the reader sees first; the system verdict stays visible for comparison
- Overrides are scoped to one operator + one masked number + one time window, so the same window can only hold one active override (re-submitting updates the same row). Every change is kept in the override history for audit
- "Export Excel" produces four sheets (verdict / scoring + evidence / voice chain / timeline) and "Export PDF" prints the page for pasting straight into a complaint ticket
- The page-level time window is minute-precise (5-minute step) and defaults to the last 3 hours; **max 24 hours per query** — the RAN radio source only retains 24 hours upstream, and a longer window would make the radio dimension silently empty
- All four sources are fetched **serially** on purpose: they reuse one VMAX portal session, and hitting upstream in parallel makes the account hit "The maximum number of connections for the user is reached" and all sources fail at once. One slow source is much better than four dead ones
- A single failed source never blanks the page: it is reported in the "data source hit" line with its own error, and the other dimensions still score. If the portal session is exhausted, wait about 30 minutes or stop clicking for a while
- RAN (32) is queried by **IMSI, not by number** — the upstream subscriber-number column in the RAN table is empty for every row. The IMSI is taken from the 1300/1100 results first; when neither has one, the radio dimension says "no IMSI mapping" out loud instead of silently returning zero rows
- The **"Radio quality" tab aggregates the radio data already fetched for this window — you do not need to query again**. It consumes the same RAN(32) rows behind the radio score, so the tab can never contradict the scorecard (no "score 62 but the tab says coverage is fine"). Top to bottom: verdict bar (one line + reasons), five KPI cards, level/quality trend chart, per-cell breakdown table, and a raw-record drill-down collapsed at the bottom
- Read the **edge value (P10, worst 10% of samples), not the average**: a good average does not mean calls work — the edge level drives complaint experience. That is why the cards, the chart and the table all put P10 next to the average. The per-cell table is sorted by edge RSRP ascending, so **the worst cell is first**
- The trend chart is dual-axis: RSRP average (solid) and RSRP P10 (red dashed) share the left axis, SINR uses the right axis. Read both together to tell weak coverage from interference — looking at only one line invites a wrong call
- When there is no radio data the page **distinguishes three cases**: the query failed (with the backend error text), there are simply no measurement reports in this window, and there are radio rows but RSRP/SINR are all empty (the upstream table shape or permissions changed). The last case is never reported as "coverage is fine"
- This page is **fully bilingual**: switch the language in the top-right corner. Every name coming from the backend (data sources, KPIs, app categories) carries both a translation key and a Chinese fallback, and units (万 / K) plus punctuation (：/ (n)) follow the active language
- RAN (32) is queried by **IMSI, not MSISDN** — the RAN table's user-number column is entirely empty strings upstream. The IMSI is resolved from the 1300/1100 results first; if neither returns one, the radio dimension says "no IMSI mapping" instead of silently reporting 0 records
- Results are read-only passthrough and nothing is persisted, but the number and current view are written into the URL — refreshing or sharing the link re-runs the same number
- The link carries the number; check that the recipient is allowed to see that number before forwarding
- **The four dimension scores and every figure on the voice / OTT / game / radio cards explain themselves on hover** (2026-11-05): these statistics are **computed in the frontend from the rules file** (the API sends neither scores nor counters); their input is exactly the row sets listed under "Source coverage", each source is paged with a cap (1300=1200 rows, 1100=800, 32=600, 1301=200) and a trailing `*` means the API flagged truncated, i.e. **rows were left unfetched** so every number is a sample; the voice "timeout/failure" counter used to add a PAGING row twice (PAGING branch plus the generic one) — fixed on 2026-11-05, so older screenshots show a larger value; the number in the game card header is named sessions in the code but is actually the **sum of xDR rows**, not a session count

#### vmax_user_cca（`vmax_user_cca`）

VMAX Intelligent Diagnosis Workspace: complaint-driven single-page narrative — conclusion first, then follow the evidence. Zone 1 diagnosis card (verdict + four scores with hover caliber notes + source row counts with truncation marks + Excel/PDF export + manual override), Zone 2 fault analysis (terminal→RAN→transport→core→OTT chain + explainable metrics: observation inline, rationale behind the ⓘ icon, each row links to the evidence drawer), Zone 3 root cause & recommendations (CCA corroboration + template suggestions + evidence library; a failed CCA query shows a persistent red banner, never mistaken for "no causes").

- Use the full number with the 231 prefix (e.g. 231777777322), digits only; the local 9-digit format is not matched upstream
- Complaint type defaults to "All", switching only re-weights and reorders — it never hides cross-module evidence
- Chain node status takes the worst of its metrics: no data shows "no data to judge", never "normal"
- Every metric answers five parts: why it matters / what was observed / when it occurred / possible impact / what needs verification
- Raw XDR / remote radio records / TCP load only when "View evidence" is clicked
- The verdict comes from deterministic rules (buildVerdict); CCA is correlation evidence only
- **Root-cause hypothesis ranking (2026-11-08)**: below the verdict, zone 3 opens with a hypothesis table ordered by evidence strength (billing/subscription > access rejection > radio classification > transport/latency > OTT text), each row carrying supporting evidence, missing evidence and a suggested owner; "missing evidence" lists the unchecked items explicitly (billing not checked, no neighbor samples, DNS not checked), never silently skipped
- Common causes such as arrears are classified from 1100 `fail_cause` (billing is only judged on strong keywords; a numeric EPS reject code does not equal arrears); WhatsApp messaging uses the OTT text judge (TCP layer only — DNS/TLS/delivery ack are not in XDR); weak coverage is further split into late handover (a good neighbor exists but was never camped on) / suspected site outage (step-shaped disappearance) / true weak coverage / interference, using the UEMR `neighbor_*` columns
- Zone 2 also has a **terminal profile card** (IMEI/model/RAT/APN/main QCI — identity only, it cannot prove carrier aggregation/MIMO capability) and a **rate-ceiling inference card** (the observed ceiling of 1300 `throughput_max`; when samples are insufficient it says so explicitly — Gx/Gy authorised bandwidth is not collected in this deployment, so no direct value is readable)
- The number is stored under ccaMsisdn and does not interfere with the legacy page
- Fully bilingual

#### ipt_power（`ipt_power`）

IPT Site Power: integrates the IPT Digital Platform (RMS energy monitoring) to show connectivity and power details (battery SOC/voltage, load, solar, generator, fuel) for all ~500 sites. Collector task ipt_power_collect ingests every 2 minutes; this page only reads the local DB.

- Layout: left **3/5 site map** (Leaflet + self-hosted PMTiles basemap), right **2/5 site table**; **click a map dot or the row "Detail" button and the power-detail drawer slides in from the right**. The drawer only covers the table column, so the map and the dot you just clicked stay in view
- The "County fill" dropdown at the right of the map card title has three modes: **By county (default)** = 15 counties each get a distinct category colour plus a county-name label and site count, using the **same palette as the person map** (?page=person) — the colours only say which county it is and carry no numeric meaning; **Mean SOC** = the mean SOC of that county’s sites **that have a SOC snapshot** — ≥80% green / 60-80% yellow / <60% red, grey when fewer than 3 sites feed the average; **None** = plain basemap. Hover a county for its site count and mean SOC; the full caliber is the 4th section of "Data caliber notes"
- Main table = all sites + each site’s **latest** power snapshot; "Connectivity" comes from the platform’s filter-map (refreshed every 2 min) and reflects gateway reachability
- ⚡ icon = watch site: sites in watch_sites.json get full diagram detail every round; all other sites are covered by the full_shard sharded rotation (~20 min for full detail); all sites get a KPI snapshot each round, with the kpi_cursor ring cursor resuming coverage under upstream stress (~2-6 min per site). Config: backend/services/ipt_data/watch_sites.json; **do NOT set "*" in sites** (500 sites in one round times out)
- "Watched only" toggles the main table; the search box matches site name / ref / area (press Enter to search)
- Single-site detail is a **full-height right-side drawer** (same shape as clicking an MW link or a GIS site: slides in from the right, dimmed mask, as wide as the GIS drilldown drawer (~810px on desktop), its own scroll). The title bar has "Refresh now" and ×; close with Esc, a mask click, or ×. Inside: a compact site-info strip (ref / area / cluster / priority / configuration / connectivity / snapshot time / connectivity updated), six stat cards (three per row: SOC / battery voltage / charging state / load / solar / generator), device detail cards (two per row: generator / battery set / fuel tank / mains + rectifier), active alarms, and a trend chart (load, solar on the left W axis, SOC on the right % axis) over 6h/24h/72h/7d
- **"Refresh now" queries the platform live** (bypassing both the 2-minute cadence and the shard rotation) and appends a snapshot after the query — works on any site immediately
- An empty chart usually means the site has not had its turn in the shard rotation yet (all sites get covered within ~20-25 min of enabling it); one "Refresh now" starts accumulating snapshots immediately
- A yellow banner appears at the top when the collector has never run or the last round failed; snapshots are kept for 7 days and pruned automatically
- "Export Excel" exports the main table with SOC / load / solar / snapshot time
- Search keyword, time range and selected site are persisted in the URL (iptKw / iptHrs / iptSite) so refresh and shared links restore the view

### 4.4 Workflow

#### ap_center（`ap_center`）

Action Plan (AP) workbench: turn problems, risks or management requirements into trackable, reviewable corrective tasks. The flow is "Dispatch -> Acknowledge -> Update progress -> Submit for review -> Approved and closed" - an assignee cannot close a task by themselves; a reviewer must approve it. The org structure comes from the Escalation Matrix (4 levels, 21 people), so assigning by name automatically carries the position, email and escalation path.

- Three tabs: My AP (owned by me + created by me), To Review, All AP (admin / AP Manager only)
- The four stat cards are clickable: Open / In progress / Pending review / Overdue - clicking filters the list by that criterion
- Only role=admin or an AP Manager whitelist can create an AP; everyone else can only handle tasks assigned to them
- Assignee: Accept -> Start -> Update progress (repeatable) -> Submit for review (completion note required, images/PDF evidence allowed)
- Reviewer: Approve (closes the task) or Return (reason required); after a return, the assignee updating progress moves it back to In progress automatically
- "WhatsApp groups" defaults to lbr_assistant (test group); separate multiple groups with commas. Email goes to the owner and reviewer using the addresses in the Escalation Matrix
- Overdue is a computed attribute: it never changes the task status, it only marks the row/detail in red and is counted on its own stat card
- Every status transition is validated server-side; duplicate submissions or unauthorized actions are rejected instead of corrupting data
- **All four stat cards, the progress bars and attachment sizes explain themselves on hover** (2026-11-05): ⚠ the four cards are hard-scoped to **mine** by the backend (owner_username or created_by equals the current account), so **switching the tabs above does not change the card numbers** — only the list follows the tab; "Open" sums DRAFT/ASSIGNED/ACKNOWLEDGED/IN_PROGRESS/PENDING_REVIEW/REJECTED (COMPLETED and CANCELLED excluded) while "Overdue" is a **separate** COUNT(*) (due_at before the server clock and still open), not a re-filter of "Open"; progress % comes straight from the API progress field (clamped 0-100 on submit) and 0% cannot distinguish "never submitted" from "someone typed 0"; the list **fetches only page 1 with 100 rows**, and a persistent banner appears when more rows match

#### feedback（`feedback`）

Issue report (user feedback): any intranet user can submit a system problem or improvement suggestion with screenshots/attachments; the admin side can filter by status/type/priority and record a resolution.

- Reporter, contact, type, priority, page, title and description are required; up to 5 attachments, 10MB each
- The list supports keyword search, status/type/priority filters and Excel export
- Statuses: open -> processing -> resolved / rejected
- **The four stat cards and the pagination total use two different scopes, spelled out on hover** (2026-11-05): the cards read the **whole-table** COUNT(*) from /feedback/stats (no filters, and the endpoint does not read the login session), while the "N records" under the list is COUNT(*) **with the current filters** — the two not matching is expected; when a status has no row in the table the API omits that key and the page renders 0, which means "there really are none", not "could not fetch"

### 4.5 System

#### Settings（`settings`）

System settings: credentials, email recipients, remote host, AI model, WhatsApp login, and task configuration — six tabs.

- Credentials: 12 upstream account groups with connection test and plaintext reveal (masked by default; stored plaintext in the credentials table of db/app.db)
- Email recipients: edit groups, reset to defaults
- Remote host: takes effect immediately, no restart needed (written to backend/data/settings.json)
- WhatsApp login: web QR login for the two "linked devices" (notify / bot); clicking generates a QR code that takes effect after scanning (old credentials are backed up by rename, not deleted)
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
| `log/backend_watchdog.log / worker_watchdog.log` | Process spawn & crash-backoff records (backend degrades to slow retry after 10 consecutive crashes; worker is removed after 10) |
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

① Check the task's latest result and the failure summary in "Task Manager"; ② check whether the header "Auto refresh" is enabled (it is off by default — the page will not reload on its own; refresh manually or click "Start Refresh"); ③ remember some data is inherently low-frequency: alarms every minute, microwave topology daily 05:15, packet loss daily 06:30, incident overview at minute 20 each hour. The "DB Data Freshness Check" task history also logs the call chain and direction when stale (including the on-disk age of file-based sources).

**Numbers do not match the expected criteria?**

Watch each page's definition: the battery board counts only readings ≤24h fresh by default; the MS SLA board follows the live calculation (snapshot files may differ); packet loss shows only the last 7 complete days; the CXO board embeds a snapshot refreshed only by re-running its sync task.

**A task stays pending forever?**

Most likely the task was never assigned to a worker group (GROUP_TASK_MAP) — nobody claims it from the queue. This accident happened four times in this project (finebi_report_sync, whatsapp_send_ext, sp_email_details, and on 2026-09-18 the olib_soc dashboard sync plus vmax_multi_data_sync). New tasks MUST be registered in GROUP_TASK_MAP in worker_watchdog.py; a stale pending row holding the single-flight slot is now auto-expired by the worker after 6 hours. Since 2026-09-18 such stalls no longer need a human to spot them: db_freshness_check (hourly) pushes the five health findings (ungrouped / no execution record / stuck queue / overdue since last success / succeeded but zero output) through WeChat + email, deduplicated by state flips.

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
