/* ==================== 任务清单详解数据（供 Help 页「任务管理详解」使用） ====================
 * 内容依据 backend/task_registry.py 的 TASK_SPECS（60 条声明）、
 * backend/worker_watchdog.py 的 GROUP_TASK_MAP（worker 分组 u/n/v/m/c）以及
 * docs/manual/04-task-system.md、14-integrations.md、03-data-layer.md 整理。
 * 改动后端任务注册表时请同步更新本文件（字段：cron / group / script / flow / maintain）。
 * 2026-09-18：补齐此前注册表有、本清单缺的 13 个任务，现与 GROUP_TASK_MAP 一一对应。
 * ================================================ */

export interface TaskDocText {
  name: string
  desc: string
  /** 工作流：上游 → 处理 → 落地/出口 */
  flow: string[]
  /** 维护要点 */
  maintain: string[]
}

export interface TaskDoc {
  id: string
  // 分组键；2026-09-27 由 n 组拆出 s（SP 备件 SFTP）/ w（MW UME），与后端
  // worker_watchdog.GROUP_TASK_MAP 的键一一对应（守卫 tests/test_worker_group_coverage.py 校验）
  group: 'u' | 'n' | 's' | 'w' | 'v' | 'm' | 'c'
  cron: string
  /** 工作流脚本（backend/services/ 下的模块） */
  script: string
  zh: TaskDocText
  en: TaskDocText
}

export const WORKER_GROUP_INFO: Record<string, { zh: string; en: string }> = {
  u: {
    zh: 'RAN UME 单账号会话，组内必须串行（并发会被踢会话）',
    en: 'RAN UME single-account session; tasks run serially (parallel runs kick the session)',
  },
  n: {
    zh: '网管 / eFlow API / 远程系统：彼此独立但保守同组',
    en: 'NMS / eFlow API / remote systems: independent but conservatively grouped',
  },
  v: {
    zh: 'VMAX 门户（本机 8790 单会话代理）：三个任务共用同一会话必须串行；2026-09-18 从 n 组拆出，不再被 1.5~2h 长任务堵住',
    en: 'VMAX portal (local 8790 single-session proxy): the three tasks share one session and must serialize; split out of group n on 2026-09-18 so long tasks no longer block them',
  },
  m: {
    zh: '内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖',
    en: 'Housekeeping tasks: EWS mail session + screenshot/WhatsApp file dependencies',
  },
  c: {
    zh: 'CN EMS 独立会话：缓存同步与日聚合共享 _pmcache，同组保证互斥',
    en: 'CN EMS dedicated session: cache sync & daily aggregation share _pmcache, serialized for mutual exclusion',
  },
}

export const TASK_DOCS: TaskDoc[] = [
  {
    id: 'eflow_sync', group: 'n', cron: '22 * * * *',
    script: 'services/sync_from_eflow_api.py → sync_from_eflow_api(mode="delta")',
    zh: {
      name: 'eFlow 数据同步',
      desc: '从 ZTE eFlow API 增量同步 TT/WO/CR/PM/Site/Person 六类数据',
      flow: ['每小时 :22 调 eFlow API 增量拉取 TT/WO/CR/PM/Site/Person', '清洗后写主库动态 eFlow 表（运行时按上游字段建表，不进 Alembic）', '为 TT&WO / 告警 / GIS / eFlow 知识库等页面供数'],
      maintain: ['增量只拉新变更；发现漏数据靠次日 eflow_sync_full 全量兜底', '凭据分组 eflow；会话被踢会连续 failed，由 auto_retry_failed 自动重试'],
    },
    en: {
      name: 'eFlow Data Sync',
      desc: 'Incrementally sync TT/WO/CR/PM/Site/Person from the ZTE eFlow API',
      flow: ['Hourly :22 pull delta TT/WO/CR/PM/Site/Person from eFlow API', 'Clean and write into dynamic eFlow tables in the main DB (runtime-created, not in Alembic)', 'Feeds TT&WO / alarms / GIS / eFlow knowledge base pages'],
      maintain: ['Delta mode only fetches changes; gaps are backfilled next night by eflow_sync_full', 'Credential group eflow; kicked sessions cause consecutive failures, auto-retried by auto_retry_failed'],
    },
  },
  {
    id: 'eflow_sync_full', group: 'n', cron: '0 1 * * *',
    script: 'services/sync_from_eflow_api.py → sync_from_eflow_api(mode="full")',
    zh: {
      name: 'eFlow 每日全量同步',
      desc: 'eFlow 全量兜底：拉全量窗口（默认自 2026-01-01），补齐增量遗漏并刷新报告。大窗口下 TT/WO 分段拉取，避免单次大导出失败；TT/WO 缺失即判任务失败',
      flow: ['每天 01:00 按全量窗口拉取全部记录', '窗口跨度大时 TT/WO **分段拉取**（默认 30 天/段）后合并去重，避免单次大导出超过 120s 轮询窗口而 500 失败', '与增量写同一批主库表，去重覆盖', '完成后刷新相关报告产物'],
      maintain: ['白天发现 eFlow 缺数的首要修复手段，可在任务管理页手动执行一次', '全量窗口起点可配置，调整时注意拉取时长；段长由 EFLOW_FULL_SEGMENT_DAYS 控制（默认 30 天）', '2026-10-09 修复：此前 TT/WO 全量导出连续多日 500 失败，而任务仍报 success=True（缺失键被静默 continue）。现 TT/WO 缺失即写 errors → success=False'],
    },
    en: {
      name: 'eFlow Daily Full Sync',
      desc: 'Full-window backfill (default since 2026-01-01) to cover delta gaps and refresh reports. Wide windows fetch TT/WO in segments; a missing TT/WO now fails the task',
      flow: ['Daily 01:00 pull the full window', 'For wide windows TT/WO are fetched in **segments** (default 30 days each) then merged/deduped, avoiding a single huge export exceeding the 120s poll window and failing with 500', 'Write into the same dynamic tables with dedup', 'Refresh related report artifacts afterwards'],
      maintain: ['First remedy when eFlow data is missing mid-day — run it manually from Task Manager', 'The window start is configurable; mind the fetch duration. Segment length via EFLOW_FULL_SEGMENT_DAYS (default 30d)', 'Fixed 2026-10-09: the TT/WO full export had been failing with 500 for days while the task still reported success=True (the missing key was silently skipped). Now a missing TT/WO writes an error → success=False'],
    },
  },
  {
    id: 'ran_ume_daily', group: 'u', cron: '0 2 * * *',
    script: 'services/ran_ume_service.py → run_ran_ume_full_task',
    zh: {
      name: 'RAN UME 日报',
      desc: 'RAN UME PM 数据获取 + Daily Availability KPI 报表生成 + FTP 上传',
      flow: ['RSA 加密登录 RAN UME 网管查询 PM 数据', '生成 Daily Availability KPI 报表', '报表经 FTP 上传远程主机，供后续邮件/看板使用'],
      maintain: ['凭据分组 zte_ume；u 组内串行，前序任务卡住会顺延', '查询模板与回溯天数在 services/ran_ume_config.json'],
    },
    en: {
      name: 'RAN UME Daily Report',
      desc: 'Fetch RAN UME PM data, generate the Daily Availability KPI report, upload via FTP',
      flow: ['RSA-encrypted login to RAN UME NMS, query PM data', 'Generate the Daily Availability KPI report', 'Upload the report via FTP for later mail/board consumption'],
      maintain: ['Credential group zte_ume; serial within group u — a stuck predecessor delays this task', 'Query templates and days_back live in services/ran_ume_config.json'],
    },
  },
  {
    id: 'site_outage_screenshot', group: 'm', cron: '0 1 * * *',
    script: 'services/site_outage_service.py → run_site_outage_screenshot',
    zh: {
      name: 'Site Outage 截图',
      desc: '对告警管理看板（Site Outage Monitor）的 ERA/Regular/ALL 三个视图自动截图',
      flow: ['Playwright 打开告警管理看板页面', '分别对 ERA / Regular / ALL 视图截图落盘', '产出供 03:00 的 whatsapp_send 发送'],
      maintain: ['截图对象是 iframe 页 alarm-management.html——改该页 DOM 前先确认截图选择器仍找得到', '与 whatsapp_send 同在 m 组，靠 cron 时间顺序（01:00 → 03:00）保证先后'],
    },
    en: {
      name: 'Site Outage Screenshot',
      desc: 'Auto-screenshot the ERA/Regular/ALL views of the Site Outage Monitor board',
      flow: ['Playwright opens the Alarm Management board', 'Screenshots each of ERA / Regular / ALL views to disk', 'Output is consumed by whatsapp_send at 03:00'],
      maintain: ['Screenshots the iframe page alarm-management.html — before changing its DOM, verify the screenshot selectors still resolve', 'Shares group m with whatsapp_send; ordering is guaranteed by cron times (01:00 → 03:00)'],
    },
  },
  {
    id: 'whatsapp_send', group: 'm', cron: '0 3 * * *',
    script: 'services/whatsapp_service.py → run_whatsapp_send',
    zh: {
      name: 'WhatsApp 消息发送',
      desc: '发送 Site Outage 截图和文件到 WhatsApp 群组（Playwright 自动化）',
      flow: ['读取 01:00 site_outage_screenshot 产出的截图', 'Playwright 操作 WhatsApp Web 发送到群组'],
      maintain: ['依赖截图任务先成功；WhatsApp Web 登录态失效时需人工重新扫码'],
    },
    en: {
      name: 'WhatsApp Message Send',
      desc: 'Send Site Outage screenshots and files to WhatsApp groups (Playwright automation)',
      flow: ['Reads screenshots produced by site_outage_screenshot at 01:00', 'Drives WhatsApp Web via Playwright to send to groups'],
      maintain: ['Depends on the screenshot task finishing first; re-scan QR manually when the WhatsApp Web session expires'],
    },
  },
  {
    id: 'whatsapp_send_ext', group: 'm', cron: '0 3 * * *',
    script: 'services/whatsapp_ext_service.py → run_whatsapp_send_ext',
    zh: {
      name: 'WhatsApp 消息发送（扩展）',
      desc: 'WhatsApp 发送（扩展版）：投递发送作业，由浏览器扩展在已登录的 WhatsApp Web 中发送，与 Playwright 版并存',
      flow: ['投递发送作业到队列', '浏览器扩展（whatsapp_sender_extension）在已登录的 WhatsApp Web 标签页中实际发送'],
      maintain: ['2026-08-31 上线时曾漏登记 worker 分组导致 pending 卡死，后补入 m 组——新增任务务必同步登记 GROUP_TASK_MAP'],
    },
    en: {
      name: 'WhatsApp Message Send (Extension)',
      desc: 'Extension-based WhatsApp sending: dispatches a send job; a browser extension sends it in the logged-in WhatsApp Web (coexists with the Playwright version)',
      flow: ['Dispatch a send job to the queue', 'The browser extension (whatsapp_sender_extension) actually sends it in the logged-in WhatsApp Web tab'],
      maintain: ['Missed its worker-group registration on 2026-08-31 and stuck pending; now in group m — always register new tasks in GROUP_TASK_MAP'],
    },
  },
  {
    id: 'whatsapp_send_baileys', group: 'm', cron: '0 4 * * *',
    script: 'services/whatsapp_send_baileys_service.py → run_whatsapp_send_baileys',
    zh: {
      name: 'WhatsApp 消息发送（Baileys）',
      desc: '第三种 WhatsApp 发图通道：走 Baileys 协议直发（不依赖浏览器/Playwright），与 Playwright/扩展版并存；默认禁用，必须在「任务管理」页手动启用（Baileys 违反 WhatsApp ToS，启用前须走人工审批）',
      flow: [
        '本任务扫 SITE_OUTAGE_DIR（与 whatsapp_send / whatsapp_send_ext 共享同一份图片目录与 GROUPS 配置）并把 items（含磁盘绝对路径）写进作业文件 data/whatsapp_send_baileys_job.json',
        'whatsapp-kb-bot/src/notify.js 进程的轮询器认领（claim 即置 running + 原子写回），按 (群 × 文件) 调 sock.sendMessage({ image|document, ... })',
        '服务端回执（res.key.id）确认送达才计入 sent；单条失败不重试到群（避免重复），由 my_app 的 auto_retry_failed 决定',
        'notify.js 回写 result 到作业文件；本任务轮询到 done/failed 后返回（task_runner 据此记任务历史）',
      ],
      maintain: [
        '默认 enabled=False——新部署不会自动跑，必须先确认 whatsapp-kb-bot notify 进程在跑、auth-notify/ 凭据有效，再在「任务管理」页手动启用',
        '已被主开关豁免（MASTER_SWITCH_EXEMPT_IDS），批量切换不参与',
        '与 whatsapp_send（Playwright 0 3 * * *）默认并存而非互斥；时间错开 1 小时避免同时投递双份图',
        '回执是服务端 message id（不是猜的），与扩展通道的「数 DOM 气泡」判据不同；这是治本 2026-09-15 SP Details Report 1.5MB 静默漏发事故的根因',
        '群发限频由 whatsapp-kb-bot/config.json 的 notify.fileSend 控制（默认 6 图 + 1 文档 / 作业）',
      ],
    },
    en: {
      name: 'WhatsApp Message Send (Baileys)',
      desc: 'Third WhatsApp image-sending channel: dispatches via the Baileys protocol directly (no browser/Playwright), parallel to the Playwright/extension versions; disabled by default — enable manually from the Task Manager page (Baileys violates WhatsApp ToS, so manual approval is required before enabling)',
      flow: [
        'This task scans SITE_OUTAGE_DIR (shared with whatsapp_send / whatsapp_send_ext) and writes items (with absolute disk paths) into the job file data/whatsapp_send_baileys_job.json',
        'The whatsapp-kb-bot/src/notify.js process polls and claims the job (sets running on claim + atomic write-back), then calls sock.sendMessage({ image|document, ... }) for each (group × file) pair',
        'The server-acknowledged message id (res.key.id) is the only success criterion; a single failed send is not retried into the group (prevents duplicates); auto_retry_failed decides on retries',
        'notify.js writes the result back to the job file; this task returns once it sees done/failed (task_runner records the run history)',
      ],
      maintain: [
        'enabled=False by default — the task will NOT auto-run on a fresh deployment. First confirm the whatsapp-kb-bot notify process is up and the auth-notify/ credentials are valid, then enable manually from the Task Manager page',
        'Exempted from the master switch (MASTER_SWITCH_EXEMPT_IDS); bulk toggles skip this task',
        'Coexists with whatsapp_send (Playwright 0 3 * * *) rather than excluding it; the 1-hour cron offset avoids two copies of the same images being delivered in the same window',
        'The server-side message id is the success criterion (not a guess), unlike the extension channel which counts DOM bubbles; this is the root-cause fix for the 2026-09-15 SP Details Report 1.5MB silent-drop incident',
        'Group-send rate limiting is controlled by whatsapp-kb-bot/config.json → notify.fileSend (default 6 images + 1 document per job)',
      ],
    },
  },
  {
    id: 'tt_alarm_whatsapp_alert', group: 'm', cron: '2-59/5 * * * *',
    script: 'services/tt_alarm_whatsapp_service.py → run_tt_alarm_whatsapp_alert',
    zh: {
      name: 'eFlow P1 告警 WhatsApp 推送',
      desc: '触发制推送：每 5 分钟（相位 2-59/5，与上游同步错开 2 分钟）扫 realtime_alarm 实时告警表，发现「带 TT + 触发窗口内 + 告警码白名单」的 P1 告警后实时回 eFlow 查单，首推后按双档重报（无更新满 10 分钟催报、有更新满 30 分钟才报，均带 REMINDER 横幅），告警清除即止损。发送状态（是否已发/发了几次）落 eflow_tt_whatsapp_alert_log',
      flow: [
        '扫 realtime_alarm（由 eflow_active_alarm 同步，注册表默认 */30、实际周期以任务配置页为准，生产已配 */5）：tt_id 非空、alarmraisedtime 在触发窗口内、告警码过白名单，按 tt_id 去重',
        '对触发单实时回 eFlow 查单（fetch_tt_live_batch，一次分页遍历），拿最新 ticket_severity / last_modified_time / alarm_clear_time；实时查不到回退本地 eflow_tt 镜像',
        '级别命中才推：首推发精简分析（分析引擎 --brief），重报双档——自上次发送后工单无更新满 10 分钟催报、有更新满 30 分钟才报（均带 ⚠️ REMINDER #N 横幅），未满间隔只记跟踪字段不打扰群里',
        '消息经 Baileys 推送进程（whatsapp-kb-bot/src/notify.js）发出，服务端回执确认后才把该单 send_status 置 Y（send_count 记发送次数）',
      ],
      maintain: [
        '2026-10-05 机制切换：触发源由 eflow_tt 定时扫描改为 realtime_alarm 触发 + 实时查单，首推时延从 45~75 分钟压到分钟级；window_minutes 语义变为「触发窗口」',
        '依赖 eflow_active_alarm 的同步周期：realtime_alarm 的 _sync_time 滞后超过「实际调度周期 × 1.5」（自适应，生产 */5 下约 7.5 分钟）会在任务结果里告警（触发面静默变空的预防项）',
        '99933 的排除在 Python 侧做——告警码 \'99933\' 与 \'99933.0\' 并存，写进 SQL 会漏；白名单留空 = 不过滤',
        '从未确认送达的单按同一节流重试；一轮全部未确认会通过 warnings 走微信/邮件主动喊人（2026-10-01「群内静默」事故的治本项）',
        '群组留空会回退测试群 test123 并在任务结果里显式告警（group_fallback=true），不会静默消失',
      ],
    },
    en: {
      name: 'eFlow P1 Alarm WhatsApp Push',
      desc: 'Trigger-based push: every 5 min (phase 2-59/5, offset 2 min from the upstream sync) scan realtime_alarm for TT-linked P1 alarms inside the trigger window, live-fetch eFlow for each ticket, first-push, then re-notify every 20 min while the ticket has no update (with a REMINDER banner), and stop when the alarm clears. Send status (sent? how many times) is recorded in eflow_tt_whatsapp_alert_log',
      flow: [
        'Scan realtime_alarm (synced by eflow_active_alarm — registry default */30, actual schedule from the task config page, currently */5): tt_id present, alarmraisedtime inside the trigger window, alarm code whitelisted, deduped by tt_id',
        'Live-fetch each triggered ticket from eFlow (fetch_tt_live_batch, one paged walk) for the latest ticket_severity / last_modified_time / alarm_clear_time; fall back to the local eflow_tt mirror',
        'Push only matching severities: first push carries the full analysis; re-notify when stalled ≥20 min and cooled ≥20 min (with a ⚠️ REMINDER #N banner); while the ticket progresses, only tracking fields are refreshed',
        'Messages go through the Baileys push process (whatsapp-kb-bot/src/notify.js); send_status becomes Y only on the server-side ack (send_count counts confirmed sends)',
      ],
      maintain: [
        '2026-10-05 redesign: trigger source moved from eflow_tt polling to realtime_alarm + live fetch, cutting first-notify latency from 45–75 min to minutes; window_minutes now means the trigger window',
        'Depends on eflow_active_alarm\'s sync cadence: if realtime_alarm._sync_time lags past 1.5× the actual schedule interval (adaptive — about 7.5 min under the production */5), the task result raises a warning (guards against a silently empty trigger set)',
        'The 99933 exclusion stays in Python — both \'99933\' and \'99933.0\' exist in the DB, so SQL predicates miss rows; empty whitelist = no filter',
        'Never-confirmed sends retry on the same throttle; a round with zero confirmed sends raises a warning via WeChat/email (root fix of the 2026-10-01 silent-outage incident)',
        'An empty group list falls back to the test group test123 with an explicit warning in the task result (group_fallback=true) — alerts never vanish silently',
      ],
    },
  },
  {
    id: 'ms_sla_full', group: 'n', cron: '0 */6 * * *',
    script: 'services/ms_sla_service.py → run_full_sync',
    zh: {
      name: 'MS SLA 完整同步',
      desc: 'SLA 指标同步 + Contract KPIs 报表更新（项目自包含，无需外部文件）',
      flow: ['每 6 小时按 nur_calc 实时口径重算 NUR/SLA/WO 指标', '写 data/ms_sla/ms_sla_dashboard.sqlite3', '供 MS SLA 看板与两份日报邮件使用'],
      maintain: ['看板数字以本任务的实时计算为准（与历史快照文件可能不一致）', '口径调整改 backend/services/nur_calc.py'],
    },
    en: {
      name: 'MS SLA Full Sync',
      desc: 'SLA metrics sync + Contract KPIs report update (self-contained, no external files)',
      flow: ['Every 6h recompute NUR/SLA/WO metrics via the live nur_calc logic', 'Write to data/ms_sla/ms_sla_dashboard.sqlite3', 'Feeds the MS SLA board and two daily report emails'],
      maintain: ['Board numbers follow this live calculation (snapshot files may differ)', 'Adjust criteria in backend/services/nur_calc.py'],
    },
  },
  {
    id: 'eflow_active_alarm', group: 'n', cron: '*/5 * * * *',
    script: 'services/eflow_api_client.py → fetch_and_save_active_alarm',
    zh: {
      name: 'eFlow 实时告警同步',
      desc: '从 eFlow FM Active 接口获取实时告警，保存 CSV + SQLite',
      flow: ['按配置周期拉 FM Active 活跃告警（注册表默认 */30，生产已在任务配置页改为 */5）', '双写 app.db 的 realtime_alarm 与 eflow.sqlite3 副本（副本仅供报表）', '供实时告警看板 / 实时告警地图 / 告警管理看板使用，同时是 P1 告警 WhatsApp 推送的触发源'],
      maintain: ['页面只读 app.db；「实时」粒度 = 实际调度周期（生产 5 分钟），并非秒级推送', '改调度请在「任务配置」页操作（写 task_schedule_config 表），注册表里的 */30 只是默认值', '告警字段映射在 services/eflow_alarm_config.json'],
    },
    en: {
      name: 'eFlow Realtime Alarm Sync',
      desc: 'Fetch realtime alarms from eFlow FM Active API, save to CSV + SQLite',
      flow: ['Pull FM Active alarms on the configured schedule (registry default */30, changed to */5 in the task config page)', 'Dual-write app.db realtime_alarm and an eflow.sqlite3 copy (report-only)', 'Feeds the realtime alarm board / realtime map / alarm management board, and is the trigger source of the P1 alarm WhatsApp push'],
      maintain: ['Pages read app.db only; "realtime" granularity = the actual schedule (5 min in production), not second-level push', 'Change the schedule in the Task Config page (persisted in task_schedule_config); */30 in the registry is only the default', 'Field mapping lives in services/eflow_alarm_config.json'],
    },
  },
  {
    id: 'eflow_history_alarm', group: 'n', cron: '0 */3 * * *',
    script: 'services/eflow_api_client.py → fetch_and_save_history_alarm',
    zh: {
      name: 'eFlow 历史告警同步',
      desc: '从 eFlow FM History 接口获取近 7 天历史告警，过滤 TT ID，保存 CSV + SQLite',
      flow: ['每 3 小时拉近 7 天 FM History 告警', '过滤出关联 TT 的记录后入库 history_alarm'],
      maintain: ['7 天窗口固定；更早的历史需查主库保留数据'],
    },
    en: {
      name: 'eFlow History Alarm Sync',
      desc: 'Fetch last-7-day history alarms from eFlow FM History API, filter by TT ID, save to CSV + SQLite',
      flow: ['Pull last 7 days of FM History alarms every 3h', 'Keep only TT-associated records into history_alarm'],
      maintain: ['The 7-day window is fixed; older history must be queried from retained DB data'],
    },
  },
  {
    id: 'eflow_tt_rules_check', group: 'n', cron: '20 4 * * *',
    script: 'services/eflow_rules/eflow_tt_rules_check_task.py → run_eflow_tt_rules_check',
    zh: {
      name: 'eFlow TT 规则收集与匹配检查',
      desc: '每天 04:20 从 eFlow 拉取激活的 TT Update Severity Rule，对最新 1000 条 eflow_tt 记录做规则匹配与级别矫正',
      flow: ['拉取最新规则生成 eflow_TT_rules.xlsx（正式规则表）', '对最新 1000 条 eflow_tt 记录做规则匹配与级别矫正', '规则/矫正表/报告落盘，供任务报告文件页下载'],
      maintain: ['正式规则表是 backend/services/eflow_rules/eflow_TT_rules.xlsx——根目录同名文件只是副本，改它不生效', '「任务报告文件」页的 eFlow 规则页签可「立即执行」手动触发一次'],
    },
    en: {
      name: 'eFlow TT Rules Collect & Match Check',
      desc: 'Daily 04:20: collect active TT Update Severity Rules from eFlow, then match the latest 1000 eflow_tt records and produce severity corrections',
      flow: ['Fetch rules and regenerate eflow_TT_rules.xlsx (the authoritative rule sheet)', 'Match the latest 1000 eflow_tt records and correct severities', 'Rules/corrections/report saved for download on the Task Report Files page'],
      maintain: ['The authoritative rule sheet is backend/services/eflow_rules/eflow_TT_rules.xlsx — the root-level copy is a draft, editing it has no effect', 'The eFlow tab on the Task Report Files page supports "Run Now" to trigger manually'],
    },
  },
  {
    id: 'main_kpi_sync', group: 'u', cron: '0 4 * * *',
    script: 'services/ran_ume_main_kpi.py → run_main_kpi_sync',
    zh: {
      name: 'RAN Main KPI 同步',
      desc: 'RAN UME Main KPI 历史指标同步（2G/3G/4G × Cells/Sites/Group/NW），导出 Excel 并增量更新 SQLite + FTP 上传',
      flow: ['登录 RAN UME 按 2G/3G/4G 模板查询 Main KPI 历史', '导出 Excel、增量更新 SQLite、FTP 上传远程主机'],
      maintain: ['查询模板与回溯天数在 services/main_kpi_config.json（days_back）', 'u 组串行，04:00 执行，前面任务（02:00 日报）卡住会顺延'],
    },
    en: {
      name: 'RAN Main KPI Sync',
      desc: 'RAN UME Main KPI history sync (2G/3G/4G × Cells/Sites/Group/NW), export Excel + incremental SQLite update + FTP upload',
      flow: ['Log into RAN UME, query Main KPI history per 2G/3G/4G templates', 'Export Excel, incrementally update SQLite, FTP upload'],
      maintain: ['Templates & days_back in services/main_kpi_config.json', 'Serial in group u at 04:00 — a stuck 02:00 daily task delays it'],
    },
  },
  {
    id: 'cell_availability_sync', group: 'u', cron: '30 4 * * *',
    script: 'services/ran_cell_availability_sync.py → run_cell_availability_sync',
    zh: {
      name: 'RAN 小区可用性 1-Day 同步',
      desc: 'RAN UME 小区可用性天粒度 KPI 同步（FDD/UMTS/GSM/TDD 4 模板），写 ran_kpi_avalability_1day.sqlite3 + FTP 上传',
      flow: ['按 FDD/UMTS/GSM/TDD 4 个模板查询小区可用性天粒度 KPI', '写 data/ran_kpi_avalability_1day.sqlite3', 'FTP 上传远程主机'],
      maintain: ['库名 ran_kpi_avalability_1day.sqlite3 的 avalability 是历史拼写，多处按字符串引用，不要改名'],
    },
    en: {
      name: 'RAN Cell Availability 1-Day Sync',
      desc: 'RAN UME cell availability daily KPI sync (FDD/UMTS/GSM/TDD templates), writes ran_kpi_avalability_1day.sqlite3 + FTP upload',
      flow: ['Query daily cell availability KPI via 4 templates (FDD/UMTS/GSM/TDD)', 'Write data/ran_kpi_avalability_1day.sqlite3', 'FTP upload to the remote host'],
      maintain: ['The misspelling "avalability" in the DB filename is historical and string-referenced — do NOT rename'],
    },
  },
  {
    id: 'cells_kpi_sync', group: 'u', cron: '50 4 * * *',
    script: 'services/ran_cells_kpi_sync.py → run_cells_kpi_sync',
    zh: {
      name: 'RAN Cells KPI 同步',
      desc: 'RAN UME 小区数据（2G/3G/4G）每日同步，聚合 Cells KPI（达标值 99.65%）物化写 ran_cells_kpi.sqlite3，只保留当月',
      flow: ['复用小区可用性同步的 UME 获取方法拉取 GSM/UMTS/FDD 小区数据', '按小区逐条折算可用率并统计达标/未达标/无数据', '物化写 data/ran_cells_kpi.sqlite3（表 cells_kpi_daily，只保留当月）'],
      maintain: ['口径与达标值定义在 services/ran_cells_kpi_service.py 顶部；2G 用信道折算，3G/4G 用服务时长/86400', '看板 RAN 小区 KPI 优先读物化库，缺失时回退实时聚合 ran_kpi_avalability_1day.sqlite3'],
    },
    en: {
      name: 'RAN Cells KPI Sync',
      desc: 'Daily RAN UME cell data sync (2G/3G/4G), aggregate Cells KPI (target 99.65%) into ran_cells_kpi.sqlite3, current month only',
      flow: ['Reuse the availability sync UME fetch to pull GSM/UMTS/FDD cell data', 'Derive per-cell availability and count meeting/below/blank', 'Materialize into data/ran_cells_kpi.sqlite3 (table cells_kpi_daily, current month only)'],
      maintain: ['Definitions live at the top of services/ran_cells_kpi_service.py; 2G uses channel ratio, 3G/4G use service time / 86400', 'The RAN Cells KPI dashboard reads the materialized DB first, falling back to live aggregation of ran_kpi_avalability_1day.sqlite3'],
    },
  },
  {
    id: 'network_kpi_sync', group: 'u', cron: '0 5 * * *',
    script: 'services/ran_ume_network_kpi.py → run_network_kpi_sync',
    zh: {
      name: 'RAN Network KPI 同步',
      desc: 'RAN UME Network KPI（Zeenshan）历史指标同步（2G/3G/4G × Group/NW），导出 Excel 并导入 SQLite + FTP 上传',
      flow: ['登录 RAN UME（Zeenshan）按 Group/NW 维度查 Network KPI 历史', '导出 Excel、导入 SQLite、FTP 上传'],
      maintain: ['查询模板在 services/network_kpi_config.json'],
    },
    en: {
      name: 'RAN Network KPI Sync',
      desc: 'RAN UME Network KPI (Zeenshan) history sync (2G/3G/4G × Group/NW), export Excel + SQLite import + FTP upload',
      flow: ['Log into RAN UME (Zeenshan), query Network KPI history by Group/NW', 'Export Excel, import into SQLite, FTP upload'],
      maintain: ['Query templates in services/network_kpi_config.json'],
    },
  },
  {
    id: 'avail_recon_sync', group: 'u', cron: '10 6 * * *',
    script: 'services/avail_recon_sync.py → run_avail_recon_sync',
    zh: {
      name: '可用率核对宽表重建',
      desc: '重建 avail_recon 可用率核对宽表（远端 Site_Daily × Master_Site_Database Region 近似聚合），写本机 data/avail_recon.sqlite3，供 Daily Availability KPI / Availability(TT) 看板',
      flow: ['读远端 olbr_ms_master_database 的站点主数据（Site_Name → Region）', '按 Region 把站点名单内联进 SQL，在远端聚合 2G/3G/4G_Main_Kpi_Site_Daily 的 AVG(可用率)', '原子替换本机 data/avail_recon.sqlite3（表 availability_daily）'],
      maintain: ['口径在 services/avail_recon_sync.py 顶部：Cell_Availability=AVG(rate)，不是「达标站点占比」（v1 曾算错，值域 40~100%）', '看板侧经 dashboard_service.DB_ALIASES 把 avail_recon.sqlite3 解析到本机库；新增派生库照此登记', '本任务 2026-09-21 上线前，该表由已退役的 my-finebi 手工 ETL 维护，无人调度导致冻结在 2026-09-13、看板静默停更'],
    },
    en: {
      name: 'Availability Recon Rebuild',
      desc: 'Rebuild the avail_recon availability reconciliation table (approx. aggregate of remote Site_Daily x Master_Site_Database region) into local data/avail_recon.sqlite3 for the Daily Availability KPI / Availability(TT) boards',
      flow: ['Read site master data from remote olbr_ms_master_database (Site_Name -> Region)', 'Inline each region\'s site list into SQL and aggregate AVG(availability) of 2G/3G/4G_Main_Kpi_Site_Daily remotely', 'Atomically replace local data/avail_recon.sqlite3 (table availability_daily)'],
      maintain: ['Definitions live at the top of services/avail_recon_sync.py: Cell_Availability=AVG(rate), NOT the share of sites meeting the target (v1 got this wrong, range 40-100%)', 'The board resolves avail_recon.sqlite3 to the local file via dashboard_service.DB_ALIASES; register new derived DBs the same way', 'Before 2026-09-21 this table was maintained by a manual ETL in the retired my-finebi project; with no scheduler it froze at 2026-09-13 and the board went silently stale'],
    },
  },
  {
    id: 'bp_report_sync', group: 'u', cron: '20 6 * * *',
    script: 'services/bp_report_sync.py → run_bp_report_sync',
    zh: {
      name: 'BP Cells Report 更新',
      desc: '从 RAN_UME 读取 4G 小区级 PRB/吞吐/流量与小时级活跃用户数，按 umlaut 忙时口径重算 BP 劣化小区（日/周/月），更新本机 data/bp_report.sqlite3 并与 Excel 真值对账',
      flow: ['按天从远端读 4G_Main_Kpi_Cell_Daily 的 PRB 利用率 / DL IP 吞吐 / DL+UL 流量（逐日一条 SQL，避免撞远端 5 万行上限被静默截断）', '经独立小时粒度通道取 Average DL Active User Number 与同小时的 PRB/吞吐（该指标日粒度不可用），按「活跃用户最大的那个小时」聚合出当天三值', '关联 bp_cell_dict 补上 Cluster/Layer（RAN_UME 无此维度，字典来自 Excel 的 BP Cells List）', '按口径重算每小区每日 is_bp，并重算日/周/月汇总（周 4/7 天、月 3/4 个完整周）；周/月为纯 INSERT（只写新周期，不动 Excel 既存行），判定列另由 backfill_period_verdicts 填空', '与 Excel 的 bp_cells_excel 逐日对账，差异与口径说明一并写入 bp_sync_meta'],
      maintain: ['口径唯一真相源在 services/bp_caliber.py：日（忙时三值）、周 4/7、月 3/4', '⚠️ Average DL Active User Number 只在**小时粒度**可用：日粒度下 UME 返回 HTTP 200 + 合法 queryid 但**静默丢弃该列**、无任何报错，故走 services/bp_active_user.py 的独立通道（C373384373 + 1638004469342 + 1638004469332）。取不到时该日 is_bp=NULL（不可判定），**绝不当 0**', '⚠️ UME 返回的数值是字符串且 PRB 带百分号（如 "2.46%"），必须去 % 再 /100；且 itemsposition 必须全为 0，写成 [0,1,2] 会返回 0001619999 拒绝查询', '⚠️ PRB 利用率在源表里是**小数**（0~1，实测 max 0.9751），阈值是 0.80 不是 80；写成 80 会让条件永不成立且不报错', '⚠️ 源表列名 "E-UTRAN\\xa0FDD\\xa0Cell Name" 里的分隔符是**不换行空格**；写成普通空格时 SQLite 不报错，而是把双引号标识符当字符串字面量返回，整列变成列名文本（bp_caliber.assert_columns_exist / assert_no_literal_fallback 就是为此加的守卫）', 'Excel 的 BP Cells List 最后一天（2026-09-26）只有 53 行、远少于当日真值 486，属导出未完成；对账时不要把该日差异当实现缺陷', '⚠️ 周/月重算**必须是纯 INSERT**（先查该周期是否已存在，存在就跳过）：曾经按整月聚合 + ON CONFLICT DO UPDATE，把 Excel 的 2026-W39/W40/2026-09 三行覆盖成 bp_cells=0；既存 Excel 行的指标真值一律不动，判定列为 NULL 时由 backfill_period_verdicts 单独填空', '⚠️ 周/月判定需要的完整周数：week_days_in_month 实测 2026-09 只有 3 个完整周、而 MONTH_TOTAL_WEEKS=4，故该月 is_bp_month 恒为 NULL（口径与日历错配，非缺数据）；界面显示成因而非仅「不可判定」'],
    },
    en: {
      name: 'BP Cells Report Sync',
      desc: 'Read per-cell 4G PRB/throughput/traffic plus hourly active users from RAN_UME, recompute Bad Performance cells by the umlaut busy-hour caliber (daily/weekly/monthly), refresh local data/bp_report.sqlite3 and reconcile against the Excel ground truth',
      flow: ['Read PRB utilization / DL IP throughput / DL+UL traffic from remote 4G_Main_Kpi_Cell_Daily one day per SQL (avoids hitting the remote 50k row cap and being silently truncated)', 'Fetch Average DL Active User Number together with the same hour\'s PRB/throughput over a dedicated hourly channel (that metric is unavailable at daily grain) and aggregate the day\'s three values from the hour with the highest active users', 'Join bp_cell_dict to attach Cluster/Layer (RAN_UME has no such dimension; the dictionary comes from the Excel BP Cells List sheet)', 'Recompute per-cell daily is_bp and the daily/weekly/monthly rollups (weekly 4/7 days, monthly 3/4 full weeks); weekly/monthly are INSERT-only (new periods only, existing Excel rows untouched), while the verdict columns are filled in separately by backfill_period_verdicts', 'Reconcile day by day against the Excel bp_cells_excel values; store differences and caliber notes in bp_sync_meta'],
      maintain: ['The single source of truth for the caliber is services/bp_caliber.py: daily (busy-hour three values), weekly 4/7, monthly 3/4', 'WARNING: Average DL Active User Number is available ONLY at hourly granularity. At daily grain UME returns HTTP 200 with a valid queryid but SILENTLY DROPS that column and raises no error, hence the dedicated channel in services/bp_active_user.py (C373384373 + 1638004469342 + 1638004469332). When it cannot be fetched the day stays is_bp=NULL (undecidable) and is NEVER counted as 0', 'WARNING: UME returns numeric values as strings and PRB carries a percent sign (e.g. "2.46%"), so strip the % and divide by 100; also itemsposition must be all zeros -- using [0,1,2] makes UME reject the query with 0001619999', 'WARNING: PRB utilization is a FRACTION in the source table (0-1, observed max 0.9751), so the threshold is 0.80, not 80; using 80 makes the condition never fire and raises no error', 'WARNING: the source column name "E-UTRAN\\xa0FDD\\xa0Cell Name" uses NO-BREAK SPACEs; with plain spaces SQLite does not error but treats the double-quoted identifier as a string literal, turning the whole column into its own name text (bp_caliber.assert_columns_exist / assert_no_literal_fallback guard exactly this)', 'The Excel BP Cells List sheet holds only 53 rows for its final day (2026-09-26) versus a true 486, i.e. an incomplete export; do not treat that day\'s difference as an implementation defect', 'WARNING: weekly/monthly recomputation MUST be INSERT-only (skip a period that already exists). An earlier version aggregated a whole month with ON CONFLICT DO UPDATE and overwrote the Excel rows for 2026-W39/W40/2026-09 with bp_cells=0. Never touch the metric ground truth of existing Excel rows; when a verdict column is NULL, backfill_period_verdicts fills it in separately', 'WARNING: week_days_in_month yields only 3 full weeks for 2026-09 while MONTH_TOTAL_WEEKS=4, so is_bp_month is permanently NULL for that month (a caliber-vs-calendar mismatch, not missing data); the UI shows the cause instead of a bare "Undecidable"'],
    },
  },
  {
    id: 'cnn_kpi_sync', group: 'n', cron: '0 6 * * *',
    script: 'services/ccn_ume_kpi_service.py → run_cnn_kpi_sync',
    zh: {
      name: 'CNN UME KPI 同步',
      desc: 'CNN UME 核心网 KPI 同步（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating），API 写入 DB CNN',
      flow: ['登录 CNN UME 查核心网 KPI（xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating）', '经 API 写入远程 DB CNN'],
      maintain: ['Free Rating 数据同时供 ccn_free_rating_chart_email 出图'],
    },
    en: {
      name: 'CNN UME KPI Sync',
      desc: 'CNN UME core-network KPI sync (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating), API write to DB CNN',
      flow: ['Log into CNN UME, query core KPIs (xGW License/CPU/Voice/VLR/Data/3G/4G/Free Rating)', 'Write to remote DB CNN via API'],
      maintain: ['Free Rating output also feeds the ccn_free_rating_chart_email charts'],
    },
  },
  {
    id: 'sp_data_sync', group: 's', cron: '10 * * * *',
    script: 'services/get_sp_table.py → run_sp_data_sync',
    zh: {
      name: 'SP 备件数据同步',
      desc: '从 SFTP 拉取 5 份备件报表（Inbound/Outbound/Inventory/OC Rule/Transfer）写入 app.db，并镜像写入 FineBI WareHouseDashBoard inventory.db',
      flow: ['登录备件 SFTP（凭据分组 sftp_sp）', '拉取 Inbound/Outbound/Inventory/OC Rule/Transfer 5 份报表', '清洗后写主库，供仓库看板与 SP 报表使用', '全部落库后镜像写入 FineBI inventory.db（UNC 路径；普通表整表替换、Inventory 只追加新行）', '最后按保留期清理 Inventory 历史快照（app.db 与镜像库同口径，默认 180 天）'],
      maintain: ['仓库看板 iframe 读的就是这批数据；报表缺失先看本任务是否成功', '镜像失败会在任务消息提示但影响不到 app.db；路径/开关在 Settings → 任务配置（mirror_db_path / mirror_enabled）', 'inventory_details 只追加不覆盖，靠保留期控制体积：Settings → 任务配置 inventory_retention_days（默认 180）。清理基准取表内最新 update_date，上游断流时不会清空整表', '仓库看板「Inventory Quantity Trend」直接读取本表全部日期（无日期参数时返回全量），调小保留天数会直接缩短趋势图历史', '2026-09-20 起由每天 07:00 改为每小时 :10：上游 SFTP 本就每小时 :00:03 导出一份，而 MsPortal 的 QC 面板 SPMS 卡读本任务写的 inband_details/outband_details，按天同步时那个数字最长滞后 24 小时。排 :10 是为了避开同组的 eflow_sync(:00) 与 sp_online_sync(:35)', '单次耗时被末尾的 FineBI 镜像拖长（UNC inventory.db 偶发 database is locked，实测 1~9min）；队列有单飞保护，上一轮没跑完会跳过本轮触发，不会堆叠，但那一小时的数据就是旧的。若 QC 面板其它指标（TT/WO/CR/PMT）跟着一起变慢，先查本任务是否占住了 n 组 worker'],
    },
    en: {
      name: 'SP Spare Data Sync',
      desc: 'Pull 5 spare-part reports from SFTP (Inbound/Outbound/Inventory/OC Rule/Transfer) into app.db, then mirror into FineBI WareHouseDashBoard inventory.db',
      flow: ['Log into the spare-parts SFTP (credential group sftp_sp)', 'Fetch the 5 reports', 'Clean and write into the main DB for the warehouse board and SP reports', 'After all tables are stored, mirror into the FineBI inventory.db (UNC path; full replace for normal tables, append-only for Inventory)', 'Finally prune Inventory snapshots older than the retention window (same policy for app.db and the mirror, default 180 days)'],
      maintain: ['The warehouse board iframe reads exactly this data — if reports are missing, check this task first', 'Mirror failures are reported in the task message without affecting app.db; path/toggle in Settings → Task Config (mirror_db_path / mirror_enabled)', 'inventory_details is append-only and bounded by retention: Settings → Task Config, inventory_retention_days (default 180). The cutoff is based on the newest update_date in the table, so an upstream outage never wipes the table', 'The warehouse board\'s "Inventory Quantity Trend" reads every date in this table (no date filter = full history), so lowering the retention window directly shortens the trend chart', 'Since 2026-09-20 this runs hourly at :10 instead of daily 07:00: the upstream SFTP already exports every hour at :00:03, and the MsPortal QC panel\'s SPMS card reads the inband_details/outband_details this task writes — a daily sync left that number up to 24h stale. :10 avoids eflow_sync (:00) and sp_online_sync (:35) in the same worker group', 'A run is lengthened by the trailing FineBI mirror (UNC inventory.db occasionally reports "database is locked"; observed 1-9 min). The queue has single-flight protection, so an unfinished run makes the next trigger skip — no pile-up, but that hour keeps the old data. If other QC metrics (TT/WO/CR/PMT) slow down too, check whether this task is occupying the group-n worker'],
    },
  },
  {
    id: 'ipran_kpi_sync', group: 'u', cron: '0 8 * * *',
    script: 'services/ipran_ume_kpi_service.py → run_ipran_kpi_sync',
    zh: {
      name: 'iPRAN UME KPI 同步',
      desc: 'iPRAN UME M6000 路由器 KPI 同步（HQ M6K-FW 等），导出 Excel 并导入 SQLite + FTP 上传',
      flow: ['登录 iPRAN UME 查 M6000 路由器 KPI', '导出 Excel、写 data/ipran_ume/ipran_ume_kpi.sqlite3、FTP 上传'],
      maintain: ['产出同时供 ipran_m6k_chart_email（06:45）出图；u 组内排在 08:00'],
    },
    en: {
      name: 'iPRAN UME KPI Sync',
      desc: 'iPRAN UME M6000 router KPI sync (HQ M6K-FW etc.), export Excel + SQLite import + FTP upload',
      flow: ['Log into iPRAN UME, query M6000 router KPIs', 'Export Excel, write data/ipran_ume/ipran_ume_kpi.sqlite3, FTP upload'],
      maintain: ['Output also feeds ipran_m6k_chart_email (06:45); runs at 08:00 within group u'],
    },
  },
  {
    id: 'liberia_email_1h', group: 'm', cron: '5 * * * *',
    script: 'services/liberia_email_report.py → run_1h_report',
    zh: {
      name: 'Liberia 宕站 1小时报告邮件',
      desc: '发送 Liberia Orange Site Down hourly Report（内嵌图 + Excel）到主送/抄送名单',
      flow: ['每小时 :05 汇总最近 1 小时宕站数据', '生成内嵌图 + Excel 报表', '发送到主送/抄送名单（收件人在系统设置维护）'],
      maintain: ['EWS 不可用时漏发由 email_recovery（每 20 分钟）自动补发'],
    },
    en: {
      name: 'Liberia Site-Down 1H Report Email',
      desc: 'Email the Liberia Orange Site Down hourly Report (inline charts + Excel) to recipient lists',
      flow: ['Hourly :05 aggregate the last hour of site-down data', 'Build the inline-chart + Excel report', 'Send to the to/cc lists (managed in Settings)'],
      maintain: ['When EWS is down, email_recovery (every 20 min) re-sends automatically once restored'],
    },
  },
  {
    id: 'liberia_email_8h', group: 'm', cron: '10 */8 * * *',
    script: 'services/liberia_email_report.py → run_8h_report',
    zh: {
      name: 'Liberia 宕站 8小时报告邮件',
      desc: '发送 Liberia Orange Site Down 8 hours Report（内嵌图 + Excel）到主送/抄送名单',
      flow: ['每 8 小时（00/08/16 时 :10）汇总窗口内宕站数据', '生成内嵌图 + Excel 报表并发送'],
      maintain: ['与 1 小时版同一脚本不同入口；收件人名单改动后两种报表同时生效'],
    },
    en: {
      name: 'Liberia Site-Down 8H Report Email',
      desc: 'Email the Liberia Orange Site Down 8-hour Report (inline charts + Excel) to recipient lists',
      flow: ['Every 8 hours (:10 of 00/08/16) aggregate site-down data', 'Build and send the inline-chart + Excel report'],
      maintain: ['Same script as the 1H version, different entry; recipient changes apply to both'],
    },
  },
  {
    id: 'kpi_ms_contract', group: 'm', cron: '30 17 * * *',
    script: 'services/kpi_email_report.py → run_ms_contract_kpi',
    zh: {
      name: 'MS Contract KPIs 日报邮件',
      desc: '发送 MS Contract KPIs Achievements Daily Report（本地数据 + 远程名单）',
      flow: ['读取 ms_sla_full（每 6 小时）产出的本地 ms_sla 数据', '生成 Contract KPIs 日报', '发送到远程名单中的收件人'],
      maintain: ['数据来自 ms_sla_full；17:30 发送时用的是 16:00 那一轮同步的数'],
    },
    en: {
      name: 'MS Contract KPIs Daily Report Email',
      desc: 'Email the MS Contract KPIs Achievements Daily Report (local data + remote recipient list)',
      flow: ['Read local ms_sla data produced by ms_sla_full (every 6h)', 'Build the Contract KPIs daily report', 'Send to recipients from the remote list'],
      maintain: ['Data comes from ms_sla_full; the 17:30 send uses the 16:00 sync round'],
    },
  },
  {
    id: 'kpi_ms_wo_sla', group: 'm', cron: '35 17 * * *',
    script: 'services/kpi_email_report.py → run_ms_wo_sla',
    zh: {
      name: 'MS WOs SLA 日报邮件',
      desc: '发送 MS WOs SLA Achievements Daily Report（本地数据 + 远程名单）',
      flow: ['读取本地 ms_sla 数据', '生成 WOs SLA 日报并发送到远程名单'],
      maintain: ['与 kpi_ms_contract 同一脚本不同入口，只差 5 分钟错峰'],
    },
    en: {
      name: 'MS WOs SLA Daily Report Email',
      desc: 'Email the MS WOs SLA Achievements Daily Report (local data + remote recipient list)',
      flow: ['Read local ms_sla data', 'Build and send the WOs SLA daily report to the remote list'],
      maintain: ['Same script as kpi_ms_contract with a different entry; 5 minutes apart to avoid overlap'],
    },
  },
  {
    id: 'kpi_sp_spareparts', group: 'm', cron: '45 9 * * *',
    script: 'services/kpi_email_report.py → run_sp_spareparts',
    zh: {
      name: 'SpareParts 备件报表邮件',
      desc: '发送 SpareParts 报表（本地 sp_email 数据 + 远程共享名单）',
      flow: ['读取 sp_report_generate（05:15）生成到 data/sp_email 的报表', '发送 SpareParts 报表到远程共享名单'],
      maintain: ['报表文件缺失说明 05:15 的生成任务失败，先修上游再重发本任务'],
    },
    en: {
      name: 'SpareParts Report Email',
      desc: 'Email the SpareParts report (local sp_email data + remote shared recipient list)',
      flow: ['Read reports generated into data/sp_email by sp_report_generate (05:15)', 'Send the SpareParts report to the remote shared list'],
      maintain: ['Missing report files mean the 05:15 generation failed — fix upstream first, then re-run this task'],
    },
  },
  {
    id: 'kpi_sp_consumables', group: 'm', cron: '50 9 * * *',
    script: 'services/kpi_email_report.py → run_sp_consumables',
    zh: {
      name: 'Comsumables 耗材报表邮件',
      desc: '发送 Comsumables 报表（本地 sp_email 数据 + 远程共享名单）',
      flow: ['读取 data/sp_email 下 sp_report_generate 产出的耗材报表', '发送到远程共享名单'],
      maintain: ['任务名 Comsumables 是历史拼写（实为 Consumables），注册表按此引用，勿改'],
    },
    en: {
      name: 'Comsumables Report Email',
      desc: 'Email the Comsumables (consumables) report (local sp_email data + remote shared list)',
      flow: ['Read the consumables report generated under data/sp_email', 'Send to the remote shared list'],
      maintain: ['The task name "Comsumables" is a historical misspelling referenced by the registry — do not rename'],
    },
  },
  {
    id: 'sp_report_generate', group: 'm', cron: '15 5 * * *',
    script: 'services/kpi_email_report.py → run_sp_report_generate',
    zh: {
      name: 'SP 备件报表生成',
      desc: '从 SFTP 下载备件数据，生成 Comsumables & SpareParts Inbound&Outbound&Inventory 报表到本地 data/sp_email',
      flow: ['登录 SFTP 下载备件原始数据', '生成 Comsumables & SpareParts Inbound&Outbound&Inventory 报表', '落盘 data/sp_email 供 09:45/09:50 两个邮件任务与 07:00 明细邮件使用'],
      maintain: ['是 3 个 SP 邮件任务的上游，失败会导致当天备件邮件整体缺报'],
    },
    en: {
      name: 'SP Report Generate',
      desc: 'Download spare-part data from SFTP and generate Comsumables & SpareParts Inbound&Outbound&Inventory reports into data/sp_email',
      flow: ['Log into SFTP and download raw spare data', 'Generate the Comsumables & SpareParts Inbound&Outbound&Inventory reports', 'Save to data/sp_email for the 09:45/09:50 email tasks and the 07:00 details email'],
      maintain: ['Upstream of 3 SP email tasks — its failure blanks all spare-part emails for the day'],
    },
  },
  {
    id: 'sp_email_details', group: 'm', cron: '0 7 * * *',
    script: 'services/kpi_email_report.py → run_sp_details_email',
    zh: {
      name: 'SP 备件明细报表邮件',
      desc: '把 data/sp_email/data 下 4 份备件明细（inventory/inband/outband/transfer）合并为一个 Excel（sheet: Inventory/Inbound/Outbound/Transfer）发送邮件，邮件发出后把同一份 Excel 作为文档发到 WhatsApp 群 WH&SP Management',
      flow: [
        '合并 data/sp_email/data 下 4 份 *_details.xlsx（inventory/inband/outband/transfer）为一个工作簿，附件名与主题带时间戳',
        '邮件发送（默认收件人为固定地址，可在系统设置 → 邮件收件人覆盖）',
        '邮件之后把同一份合并 Excel 作为文档发到 WhatsApp 群 WH&SP Management（2026-09-14 新增）',
      ],
      maintain: [
        '2026-09-01 上线时曾漏分组导致 pending 卡死，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP',
        '本任务在 EMAIL_TASK_IDS 内：WhatsApp 侧失败时 error 只写 WHATSAPP_FAIL 固定标记，不拼底层异常原文，避免命中 EWS 关键字触发 email_recovery 整链补发（11 位收件人重复收报表）',
        '上游是 sp_report_generate（05:15）：它不产出明细文件，本任务合并即失败，邮件与群都不发',
      ],
    },
    en: {
      name: 'SP Spare Parts Details Report Email',
      desc: 'Merge the 4 spare-part detail files (inventory/inband/outband/transfer) under data/sp_email/data into one Excel (sheets: Inventory/Inbound/Outbound/Transfer) and email it; after the email, send the same Excel as a document to the WhatsApp group WH&SP Management',
      flow: [
        'Merge the 4 *_details.xlsx (inventory/inband/outband/transfer) under data/sp_email/data into one workbook with a timestamped filename and subject',
        'Send the email (default fixed recipients, overridable in Settings → Email Recipients)',
        'After the email, send the same merged Excel as a document to the WhatsApp group WH&SP Management (added 2026-09-14)',
      ],
      maintain: [
        'Missed its worker-group registration on 2026-09-01 and stuck pending; now in group m — always register new tasks in GROUP_TASK_MAP',
        'This task is in EMAIL_TASK_IDS: on a WhatsApp-side failure the error carries only the WHATSAPP_FAIL marker, never the raw exception text — otherwise an EWS keyword would make email_recovery replay the whole chain and email the report twice to 11 recipients',
        'Upstream is sp_report_generate (05:15): without the detail files the merge fails and neither channel sends',
      ],
    },
  },
  {
    id: 'sp_details_files_email', group: 'm', cron: '5 10 * * *',
    script: 'services/kpi_email_report.py → run_sp_details_files_email',
    zh: {
      name: 'SP 备件明细分文件邮件',
      desc: '每天 10:05 把 data/sp_email/data 下的 6 份备件明细**一份文件一封邮件**逐个发给 NOC，主题 Liberia OLR W.H <文件名> <日期时间>',
      flow: [
        '逐份选取明细：优先未过滤的 *_source.xlsx 原始快照（sp_report_generate 05:15 在任何过滤之前留的 SFTP 快照），缺失时回退过滤后的 *_details.xlsx',
        '先整体校验 6 份是否齐全：缺任一份即整体失败、**一封都不发**（宁可一封不发，也不让收件人拿到不完整的一套报表）',
        '按**对外文件名**在 TMP 下各落一份副本（磁盘上是 inband/outband，对外写成 inbound/outbound），发完即清',
        '逐个发送，每封只挂 1 个附件，主题为「Liberia OLR W.H <附件文件名> <日期时间>」（例：Liberia OLR W.H inbound_details_source.xlsx 2026-09-30 10-05-00）',
        '单封发送失败不中断后续：已成功的继续发完，最后把失败项汇总进 error 供人工只补发缺的那几封',
      ],
      maintain: [
        '默认主送 MS.NOC@zte.com.cn，抄送 li.jing132@zte.com.cn / luo.wutao@zte.com.cn，可在系统设置 → 邮件收件人 的 sp_details_files 分组覆盖',
        '对外文件名与磁盘源名不同（用户指定）：inband/outband → inbound/outbound，且 6 份一律带 _source 后缀，故附件需先按对外名落副本再发（owa_mail_report 取 Path(fp).name 作附件名）',
        '与 sp_email_details（05:00）同数据源但打包方式不同：那个合并成一个多 sheet 工作簿并发 WhatsApp 群，本任务一文件一邮件发 NOC，互不影响',
        '一文件一邮件 => 一次任务最多 6 次 EWS 会话，耗时约为单封的 6 倍；任务在 m 组串行，长时间占用会推迟同组其它轻任务',
        '单封失败时 error 只写 SEND_FAIL 固定标记 + 文件名，**不拼底层异常原文**——否则命中 EWS 关键字会让 email_recovery 把 6 封全部补发，已成功的重复投递；底层细节在 result.failed 里',
        'ocrule_details 没有 *_source 快照，磁盘上只读过滤版；但对外名按用户要求统一带 _source（2026-10-09），故「名字带 _source、内容是过滤版」是预期行为，不是取错文件',
        '上游是 sp_report_generate（m 组 05:15）：明细文件缺失先查它，而不是本任务',
      ],
    },
    en: {
      name: 'SP Spare Parts Details Files Email',
      desc: 'Daily 10:05: send the 6 spare-part detail files under data/sp_email/data to NOC as ONE EMAIL PER FILE, subject "Liberia OLR W.H <file name> <date time>"',
      flow: [
        'Resolve each detail file: prefer the unfiltered *_source.xlsx raw snapshot (the SFTP snapshot sp_report_generate keeps at 05:15 before any filtering), falling back to the filtered *_details.xlsx',
        'Check all 6 files up front: if any one is missing the whole run fails and NOTHING is sent (better no email at all than an incomplete set of reports)',
        'Stage a copy of each under TMP using the OUTBOUND name (on disk they are inband/outband, recipients see inbound/outbound, and all 6 carry the _source suffix); the copies are removed after sending',
        'Send one by one — each email carries exactly one attachment, subject "Liberia OLR W.H <attachment file name> <date time>" (e.g. Liberia OLR W.H inbound_details_source.xlsx 2026-09-30 10-05-00)',
        'A single send failure does not stop the rest: the remaining files still go out, and the failures are reported by name so only those need a manual resend',
      ],
      maintain: [
        'Default To MS.NOC@zte.com.cn, Cc li.jing132@zte.com.cn / luo.wutao@zte.com.cn; overridable in Settings → Email Recipients, group sp_details_files',
        'Outbound file names differ from the on-disk source names (per user request): inband/outband become inbound/outbound, and all 6 carry the _source suffix, so attachments must be staged under the outbound name first (owa_mail_report uses Path(fp).name as the attachment name)',
        'Same data source as sp_email_details (05:00) but a different package: that one merges into a single multi-sheet workbook and posts to the WhatsApp group, this one sends one file per email to NOC — they do not affect each other',
        'One email per file means up to 6 EWS sessions per run, roughly 6x the duration of a single send; the task runs serially in group m, so a long run delays the other light tasks there',
        'On a single-send failure the error carries only the SEND_FAIL marker plus file names, never the raw exception text — otherwise an EWS keyword would make email_recovery resend all 6 and duplicate the ones that already went out; the details live in result.failed',
        'ocrule_details has no *_source snapshot and only the filtered version exists on disk, but per the user request (2026-10-09) its outbound name carries _source like the others; so "name has _source, content is filtered" is expected, not a wrong file',
        'Upstream is sp_report_generate (group m, 05:15): if detail files are missing, investigate that task rather than this one',
      ],
    },
  },
  {
    id: 'sp_whatsapp_report', group: 'm', cron: '15 7 * * *',
    script: 'services/kpi_email_report.py → run_sp_whatsapp_report',
    zh: {
      name: 'Comsumables&SpareParts Report Whatsapp',
      desc: '每天 07:15 把 Comsumables / SpareParts 两个邮件任务的同一批产物（合并总表 XLSX + 报表 PNG）发送到 WhatsApp 群 WH&SP Management',
      flow: ['在 data/sp_email 下选取 Comsumables / SpareParts 的合并总表 XLSX（不含 " - Liberia" 分站点）', '收集两类报表的 PNG（主图在前、Summary-Changed 在后）', '复用 whatsapp_service 的 Playwright 发送机制发到群 WH&SP Management'],
      maintain: ['上游是 sp_report_generate（m 组 05:15），它失败会导致本任务找不到报表文件', '不发送邮件——邮件由 kpi_sp_consumables / kpi_sp_spareparts 负责'],
    },
    en: {
      name: 'Comsumables&SpareParts Report Whatsapp',
      desc: 'Daily 07:15: send the same assets used by the Comsumables / SpareParts report emails (consolidated XLSX + report PNGs) to the WhatsApp group WH&SP Management',
      flow: ['Pick the consolidated Comsumables / SpareParts XLSX under data/sp_email (excludes the " - Liberia" per-site files)', 'Collect the PNGs of both reports (main chart first, Summary-Changed last)', 'Send via the Playwright mechanism in whatsapp_service to the group WH&SP Management'],
      maintain: ['Upstream is sp_report_generate (group m, 05:15) — if it fails this task finds no report files', 'No email is sent here; emails are handled by kpi_sp_consumables / kpi_sp_spareparts'],
    },
  },
  {
    id: 'sp_material_report', group: 'm', cron: '33 7 * * *',
    script: 'services/kpi_email_report.py → run_sp_material_stock_consumption',
    zh: {
      name: 'SP 物料库存与消耗报表邮件',
      desc: '每天 07:33 把 SP 物料库存与消耗汇总（同「SP 物料库存与消耗统计」页面 page=sp_material 的口径）导出为 UNIFIED_EXCEL_V1 版式 Excel 附件 + 同内容 PNG 内嵌正文并邮件发送',
      flow: ['调用 sp_material_summary_service.get_material_summary()（inventory_details 每日快照 + outband_details 报修出库）', '生成 UNIFIED_EXCEL_V1 版式 Excel（标题 / 副标题 / 两行合并表头 / 合计行在前 / 13 列 + Info 页），与页面「导出 Excel」逐格一致', '用 Pillow 把同一张汇总表画成 PNG（手法同 SP 报表图片：蓝表头 + 橙色区块条 + 斑马纹）', '落盘 data/sp_material_report（只保留最新一份）：Excel 作附件、PNG 内嵌正文发送'],
      maintain: ['默认 15 主送 + 2 抄送，可在系统设置 → 邮件收件人 覆盖', '汇总表无数据行时跳过发送并记为失败（多为上游 SP 数据同步未跑）', 'PNG 生成失败只告警不阻断，邮件仍带 Excel 发出'],
    },
    en: {
      name: 'SP Material Stock & Consumption Report Email',
      desc: 'Daily 07:33: export the SP material stock & consumption summary (same scope as the page=sp_material page) to a UNIFIED_EXCEL_V1 Excel attachment plus an inline PNG of the same table, and email it',
      flow: ['Call sp_material_summary_service.get_material_summary() (inventory_details daily snapshots + outband_details repair outbound)', 'Build a UNIFIED_EXCEL_V1 workbook (title / subtitle / two-row merged header / total row above the data / 13 columns + Info sheet), cell-for-cell identical to the page "Export Excel"', 'Draw the same summary table as a PNG with Pillow (same method as the SP report images: blue header + orange section bands + zebra rows)', 'Save to data/sp_material_report (keeps only the latest): the Excel as attachment, the PNG inlined in the body'],
      maintain: ['Default 15 To + 2 Cc, overridable in Settings → Email Recipients', 'Skips sending and reports failure when the summary has no data rows (usually the upstream SP data sync did not run)', 'If PNG rendering fails it only warns and does not block the email — the Excel is still sent'],
    },
  },
  {
    id: 'kpi_ran_availability', group: 'm', cron: '30 9 * * *',
    script: 'services/kpi_email_report.py → run_ran_availability',
    zh: {
      name: 'MS Network Availability 日报邮件',
      desc: '发送 MS Network Availability Daily Report（远程 FTP 图片 + 远程名单，无 Excel）',
      flow: ['从远程 FTP 拉取已生成的可用性图片（由 ran_ume_daily 02:00 产出并上传）', '组装日报（无 Excel 附件）发送到远程名单'],
      maintain: ['图片缺失通常是 ran_ume_daily（u 组 02:00）失败——查它而不是本任务'],
    },
    en: {
      name: 'MS Network Availability Daily Report Email',
      desc: 'Email the MS Network Availability Daily Report (remote FTP images + remote list, no Excel attachment)',
      flow: ['Fetch availability images from remote FTP (produced & uploaded by ran_ume_daily at 02:00)', 'Assemble the report (no Excel) and send to the remote list'],
      maintain: ['Missing images usually mean ran_ume_daily (group u, 02:00) failed — investigate that task instead'],
    },
  },
  {
    id: 'email_recovery', group: 'm', cron: '*/20 * * * *',
    script: 'services/email_recovery.py → run_email_recovery_task',
    zh: {
      name: 'EWS 恢复后邮件补发',
      desc: '每 20 分钟探测 EWS 是否恢复；恢复后自动补发近 3 小时内因 EWS 超时失败的邮件任务',
      flow: ['探测 Exchange（EWS）连通性', '扫描近 3 小时内因 EWS 超时失败的邮件任务', '恢复后逐个补发'],
      maintain: ['邮件没收到先查它的执行历史，而不是手动重跑原邮件任务'],
    },
    en: {
      name: 'Email Recovery after EWS Restored',
      desc: 'Probes EWS every 20 minutes; once restored, re-sends email tasks that failed due to EWS timeouts in the last 3 hours',
      flow: ['Probe Exchange (EWS) reachability', 'Scan email tasks failed by EWS timeout within the last 3h', 'Re-send them one by once EWS is back'],
      maintain: ['For missing emails check this task\'s history first instead of manually re-running the original email task'],
    },
  },
  {
    id: 'packet_loss_sync', group: 'u', cron: '30 6 * * *',
    script: 'services/packet_loss_service.py → run_packet_loss_sync',
    zh: {
      name: 'Packet Loss 丢包同步',
      desc: 'RAN UME 丢包率（SDR/IPRAN IPPD）同步，入库 lte_pl.sqlite3 并生成丢包报告；只展示最近 7 个完整自然日',
      flow: ['登录 RAN UME 拉丢包率（SDR/IPRAN IPPD）', '计算 STATUS（0~23 小时标志块）与 FINAL_STATUS 五级分类', '写 data/packet_lost/lte_pl.sqlite3（注意目录名是 packet_lost）并生成报告'],
      maintain: ['看板与报告口径与 Packet_Loss 自动化 Excel 完全一致；当天没过完不展示', '目录名 packet_lost 是历史拼写，不要改名'],
    },
    en: {
      name: 'Packet Loss Sync',
      desc: 'Sync packet loss rate (SDR/IPRAN IPPD) from RAN UME into lte_pl.sqlite3 and generate the report; only the last 7 complete days are shown',
      flow: ['Log into RAN UME and pull packet loss (SDR/IPRAN IPPD)', 'Compute STATUS (0-23 hourly flag blocks) and FINAL_STATUS five-level classification', 'Write data/packet_lost/lte_pl.sqlite3 (note the folder name) and generate the report'],
      maintain: ['Criteria match the Packet_Loss automation Excel exactly; the unfinished current day is hidden', 'The folder name packet_lost is historical — do not rename'],
    },
  },
  {
    id: 'packet_loss_email', group: 'u', cron: '45 6 * * *',
    script: 'services/kpi_email_report.py → run_packet_loss_email',
    zh: {
      name: 'Packet Loss 丢包日报邮件',
      desc: '发送 Packet Loss 丢包看板日报邮件（本地截图 + 最新报告 xlsx + 远程收件人清单），经 OWA 账户发送',
      flow: ['截取丢包看板画面 + 取 06:30 同步生成的最新报告 xlsx', '经 OWA 账户发送到远程收件人清单'],
      maintain: ['排在 06:45，紧跟 06:30 同步任务（同在 u 组串行，顺序有保证）'],
    },
    en: {
      name: 'Packet Loss Daily Report Email',
      desc: 'Send the Packet Loss dashboard daily email (local screenshot + latest report xlsx + remote recipients) via the OWA account',
      flow: ['Screenshot the packet-loss board + pick the latest report from the 06:30 sync', 'Send via OWA to the remote recipient list'],
      maintain: ['Runs 06:45 right after the 06:30 sync (same group u, serialized — order guaranteed)'],
    },
  },
  {
    id: 'ipran_m6k_chart_email', group: 'm', cron: '45 6 * * *',
    script: 'services/ipran_chart_service.py → run_ipran_m6k_chart_email',
    zh: {
      name: 'IP RAN M6K-FW 图表邮件',
      desc: '从 ipran_ume_kpi.sqlite3 查询 HQ_M6K_FW_bnctp_15mins，按 ME+SmartGroup 生成 3 张利用率折线图并发送',
      flow: ['查询 ipran_ume_kpi.sqlite3 的 HQ_M6K_FW_bnctp_15mins 表', '按 ME+SmartGroup 生成 3 张利用率折线图', '发送图表邮件'],
      maintain: ['依赖前一天 08:00 ipran_kpi_sync 的数据；u 组任务失败时本邮件会出空图或失败'],
    },
    en: {
      name: 'IP RAN M6K-FW Chart Email',
      desc: 'Query HQ_M6K_FW_bnctp_15mins from ipran_ume_kpi.sqlite3, generate 3 utilization line charts by ME+SmartGroup and email them',
      flow: ['Query HQ_M6K_FW_bnctp_15mins in ipran_ume_kpi.sqlite3', 'Generate 3 utilization line charts by ME+SmartGroup', 'Send the chart email'],
      maintain: ['Depends on the previous day\'s 08:00 ipran_kpi_sync; empty charts or failure follow u-group sync failures'],
    },
  },
  {
    id: 'ccn_free_rating_chart_email', group: 'm', cron: '45 7 * * *',
    script: 'services/ccn_free_rating_chart_service.py → run_ccn_free_rating_chart_email',
    zh: {
      name: 'CNN Free Rating 图表邮件',
      desc: '从 db_ps_cs_cn.sqlite3 查询 FREE_RATING_GROUP_TEMPLATE_OSS_update_UME，按 MO 生成 4 张柱状图并发送',
      flow: ['查询 db_ps_cs_cn.sqlite3 的 FREE_RATING 模板表', '按 MO 生成 4 张柱状图并发送'],
      maintain: ['数据来自 cnn_kpi_sync（n 组，每天 06:00）写入的 DB CNN'],
    },
    en: {
      name: 'CNN Free Rating Chart Email',
      desc: 'Query FREE_RATING_GROUP_TEMPLATE_OSS_update_UME from db_ps_cs_cn.sqlite3, generate 4 bar charts by MO and email them',
      flow: ['Query the FREE_RATING template table in db_ps_cs_cn.sqlite3', 'Generate 4 bar charts by MO and send'],
      maintain: ['Data comes from cnn_kpi_sync (group n, daily 06:00) writing into DB CNN'],
    },
  },
  {
    id: 'fw_kpi_sync', group: 'n', cron: '15 7 * * *',
    script: 'services/fw_kpi/fw_kpi_services.py → run_fw_kpi_sync',
    zh: {
      name: 'FW 吞吐 KPI 同步+图表邮件',
      desc: '从 DPtech UMC 拉取整机吞吐数据，经 API 写入远程 fw_db.sqlite，生成近 14 天吞吐折线图并邮件发送',
      flow: ['登录 DPtech UMC（凭据分组 fw_kpi）拉整机吞吐', '经 API 写入远程 fw_db.sqlite', '生成近 14 天吞吐折线图并发送'],
      maintain: ['同步与出图发信在同一个任务里完成，失败时整链路（入库+邮件）都停'],
    },
    en: {
      name: 'FW Throughput KPI Sync + Chart Email',
      desc: 'Fetch whole-device throughput from DPtech UMC, write to remote fw_db.sqlite via API, generate a 14-day chart and email it',
      flow: ['Log into DPtech UMC (credential group fw_kpi), pull throughput', 'Write to remote fw_db.sqlite via API', 'Generate the 14-day throughput chart and send it'],
      maintain: ['Sync, chart and email happen in one task — a failure stops the whole chain (DB write + email)'],
    },
  },
  {
    id: 'battery_kpi_sync', group: 'u', cron: '5 * * * *',
    script: 'services/battary_kpi_fetch/battery_kpi_service.py → run_battery_kpi_sync',
    zh: {
      name: '电池 KPI 同步',
      desc: '从 UME 拉取电池实时 KPI（健康度/SOC/充放电状态），全程内存不落盘，写入 battery_kpi.sqlite3 供电池看板使用',
      flow: ['每小时 :05 登录 UME 拉电池实时 KPI', '全程内存处理（中间不落盘）', '写 data/battery/battery_kpi.sqlite3'],
      maintain: ['电池看板默认只统计 24h 内新鲜读数（BATT_FRESH_HOURS 等环境变量控制阈值）', '注意模块目录名是 battary_kpi_fetch（历史拼写），勿改'],
    },
    en: {
      name: 'Battery KPI Sync',
      desc: 'Fetch battery realtime KPI (health/SOC/charge status) from UME, in-memory only, write to battery_kpi.sqlite3 for the battery board',
      flow: ['Hourly :05 log into UME and pull battery KPI', 'Process fully in memory (no intermediate files)', 'Write data/battery/battery_kpi.sqlite3'],
      maintain: ['The battery board counts only readings ≤24h fresh by default (thresholds via BATT_FRESH_HOURS etc.)', 'The module folder battary_kpi_fetch is a historical misspelling — do not rename'],
    },
  },
  {
    id: 'battery_email', group: 'm', cron: '0 7,19 * * *',
    script: 'services/battary_kpi_fetch/battery_kpi_service.py → run_battery_email',
    zh: {
      name: '电池 KPI 邮件',
      desc: '将电池 KPI 报表（Excel）发送至远程名单中的邮箱，每日 07:00 与 19:00 各一次',
      flow: ['从 battery_kpi.sqlite3 生成 Excel 报表', '发送到远程名单中的邮箱（每天两次）'],
      maintain: ['与同步任务同脚本不同入口；收件人来自远程 FTP 名单'],
    },
    en: {
      name: 'Battery KPI Email',
      desc: 'Email the battery KPI report (Excel) to recipients from the remote list, daily at 07:00 & 19:00',
      flow: ['Generate the Excel report from battery_kpi.sqlite3', 'Send to the remote recipient list (twice daily)'],
      maintain: ['Same script as the sync task, different entry; recipients come from the remote FTP list'],
    },
  },
  {
    id: 'mailbox_cleanup', group: 'm', cron: '0 * * * *',
    script: 'services/mailbox_cleanup.py → run_mailbox_cleanup',
    zh: {
      name: '邮箱空间清理',
      desc: '每小时检查 Exchange 邮箱：邮件数 >500 且空间 >70% 时，硬删除最旧 200 封邮件，避免 storage limit 告警',
      flow: ['每小时 :00 检查 Exchange 邮箱（exchangelib/EWS）', '邮件数 >500 且空间 >70% 时硬删除最旧 200 封'],
      maintain: ['删除的是发件箱历史（含已发报表邮件），是防止报表发不出去的守卫任务，不要停用'],
    },
    en: {
      name: 'Mailbox Storage Guard',
      desc: 'Hourly Exchange mailbox guard: when count >500 AND usage >70%, hard-delete the 200 oldest emails to avoid the storage-limit warning',
      flow: ['Hourly :00 inspect the Exchange mailbox (exchangelib/EWS)', 'Hard-delete the 200 oldest emails when count >500 and usage >70%'],
      maintain: ['It deletes sent-mail history (including old report emails) — it is the guard keeping report delivery alive, do not disable'],
    },
  },
  {
    id: 'incident_overview_sync', group: 'm', cron: '20 * * * *',
    script: 'services/incident_overview_sync.py → run_incident_overview_sync',
    zh: {
      name: 'Incident Overview 数据同步',
      desc: '每小时第 20 分钟从 FineBI FTP /webroot/WEB-INF/schedule/TT_WO/ 所有子目录取最新 incident_overview.xlsx，版本化落盘 + current.json 指针',
      flow: ['每小时第 20 分钟扫描 FineBI FTP 的 TT_WO/ 全部子目录', '取最新 incident_overview.xlsx 落盘为版本化文件 + current.json 指针', 'best-effort 刷新 incident_overview.xlsx 快照，供事件总览页使用'],
      maintain: ['版本化设计使上游 Excel 被打开占用时也不会取数失败——这是历史踩坑后的修复，勿改回直接覆盖', '调度必须留在 :20，不要改回整点——FineBI 每小时 :53 会先删掉上一轮输出目录，新副本约 :02–:05 才落盘，整点取数正好撞空档（2026-09 曾因此每小时误报「未找到 incident_overview.xlsx」）；撞上空档时只要本地副本不超过 90 分钟就沿用上、不判失败'],
    },
    en: {
      name: 'Incident Overview Data Sync',
      desc: 'Hourly at minute 20: pull the latest incident_overview.xlsx from all subfolders of FineBI FTP /webroot/WEB-INF/schedule/TT_WO/, stored as versioned files + a current.json pointer',
      flow: ['Scan all TT_WO/ subfolders on FineBI FTP at minute 20 each hour', 'Save the latest incident_overview.xlsx as a versioned file + current.json pointer', 'Best-effort refresh of the incident_overview.xlsx snapshot for the incident overview page'],
      maintain: ['The versioned design survives the upstream Excel being locked open — a hard-won fix, do not revert to direct overwrite', 'Keep the schedule at minute 20 — FineBI deletes the previous output folder at :53 and the new copy lands around :02–:05, so an on-the-hour run hits that gap and reports a false "incident_overview.xlsx not found" (seen in 2026-09); inside the gap it reuses a local copy younger than 90 minutes instead of failing'],
    },
  },
  {
    id: 'finebi_report_sync', group: 'm', cron: '10 * * * *',
    script: 'services/finebi_report_sync.py → run_finebi_report_sync',
    zh: {
      name: 'FineBI 报表文件同步',
      desc: '每小时从 FineBI FTP /webroot/WEB-INF/schedule 的每个子文件夹取最新一份 Excel，下载到本地 data/finebi_reports 供任务报告文件页下载；某个目录本轮没有 Excel 只记缺失，不把整任务判失败',
      flow: ['每小时 :10 遍历 schedule 下每个子文件夹', '各取最新一份 Excel 下载到 data/finebi_reports', '目录本轮无文件且本机有历史副本 → 记入 missing 继续跑下一个', '「任务报告文件 → FINEBI report」页签展示与下载'],
      maintain: ['2026-08-25 分组模式启用时曾因未归组而 pending 卡死断档，后补入 m 组——新增任务务必登记 GROUP_TASK_MAP', 'FineBI 每小时 :53 会先删掉上一轮输出目录、新副本约 :02–:05 才落盘，单个目录取不到文件是常态：只有本机连历史副本都没有才算 error，否则一个目录的空档会把其余已同步成功的报表一起拖红'],
    },
    en: {
      name: 'FineBI Report Files Sync',
      desc: 'Hourly: pull the latest Excel from each subfolder of FineBI FTP /webroot/WEB-INF/schedule into data/finebi_reports for the Task Report Files page; a folder with no file this cycle is only recorded as missing instead of failing the whole task',
      flow: ['Hourly :10 walk every subfolder under schedule', 'Download the latest Excel per folder into data/finebi_reports', 'Folder empty this cycle but a local copy exists → record as missing and continue', 'Listed & downloadable under Task Report Files → FINEBI report tab'],
      maintain: ['Stuck pending and broke the chain when group mode enabled on 2026-08-25 (ungrouped); now in group m — always register new tasks in GROUP_TASK_MAP', 'FineBI deletes the previous output folder at :53 and the new copy lands around :02–:05, so one empty folder is normal: only a folder with no local copy at all counts as an error, otherwise that gap reddens every other report that synced fine'],
    },
  },
  {
    id: 'db_freshness_check', group: 'm', cron: '15 * * * *',
    script: 'services/db_freshness_check.py → run_db_freshness_check',
    zh: {
      name: '数据库数据新鲜度巡检',
      desc: '每小时巡检远程 DB（db_writer_api）、本地回退库各表最新数据日期，以及本机文件型数据源（FTP 落盘的 Excel）的落盘年龄，滞后时输出调用链路与检查方向',
      flow: ['每小时 :15 巡检远程库与本地回退库各表的最新数据日期', '同时按最新文件的落盘年龄判定本机文件型源（如事件总览的 incident_overview.xlsx）', '滞后时在执行日志输出调用链与排查方向'],
      maintain: ['怀疑「某类数据停更」时先看它的执行历史，按给出的调用链排查，比翻任务列表快', '取数任务"成功/失败"和数据"几小时没更新"是两件事：2026-09-30 事件总览滞后 2 小时却只表现为任务告警，因此文件年龄单独进巡检（FILE_CHECKS），新增文件型看板数据源时在这里补一条'],
    },
    en: {
      name: 'DB Data Freshness Check',
      desc: 'Hourly freshness audit of remote DBs (via db_writer_api), local fallback DBs, and local file-based sources (FTP-pulled Excel files) by their on-disk age; outputs call chain and guidance when stale',
      flow: ['Hourly :15 check the latest data date per table in remote & local fallback DBs', 'Also judge local file-based sources by the age of their newest file (e.g. incident_overview.xlsx for the incident overview page)', 'When stale, log the call chain and troubleshooting direction in the execution history'],
      maintain: ['Suspect stalled data? Check this task\'s history first and follow its call chain — faster than browsing the task list', 'A sync job succeeding and its data being hours old are two different facts: on 2026-09-30 the incident overview page sat 2h stale while only task alerts fired, so file age is now checked separately (FILE_CHECKS) — add an entry whenever a new page reads a file instead of a table'],
    },
  },
  {
    id: 'mttr_tt_sync', group: 'm', cron: '40 7 * * *',
    script: 'services/mttr_tt_sync.py → run_mttr_tt_sync',
    zh: {
      name: 'MTTR/TT 宽表重建',
      desc: '重建 mttr_tt 宽表（Eflow_TT_FB + OLR_CELLS/Site_Maintainer_Category 参考库），写本机 data/mttr_tt.sqlite3，供 MTTR 看板（日/周/月）',
      flow: ['读本机参考库 data/excel_ds.sqlite3（Site ID→Site Category、Site Name→各制式小区数）', '经只读 API 读远端 Eflow_TT_FB 全量', '推导 Vender/MTTR1/MTTR2/MTTR_RANG_2H/Month/WK/Outage_Mins 后原子替换 data/mttr_tt.sqlite3'],
      maintain: ['口径解析自 FineDB 数据集 4bc5a679，定义在 services/mttr_tt_sync.py 顶部；MTTR2 只在 0<MTTR1<48h 时非空', '参考库 excel_ds.sqlite3 是从 my-finebi 固化的静态文件（114KB，2026-08-31 后未变）；FineBI 侧 Excel 数据集若更新需重新导出覆盖', '2026-09-21 上线前该表由已退役 my-finebi 的手工 ETL 维护，无调度 → 冻结在 2026-08-31'],
    },
    en: {
      name: 'MTTR/TT Wide Table Rebuild',
      desc: 'Rebuild the mttr_tt wide table (Eflow_TT_FB + OLR_CELLS/Site_Maintainer_Category reference) into local data/mttr_tt.sqlite3 for the MTTR board (daily/weekly/monthly)',
      flow: ['Read local reference DB data/excel_ds.sqlite3 (Site ID->Site Category, Site Name->per-RAT cell counts)', 'Read the full remote Eflow_TT_FB via the read-only API', 'Derive Vender/MTTR1/MTTR2/MTTR_RANG_2H/Month/WK/Outage_Mins then atomically replace data/mttr_tt.sqlite3'],
      maintain: ['Definitions parsed from FineDB dataset 4bc5a679, documented at the top of services/mttr_tt_sync.py; MTTR2 is non-null only when 0<MTTR1<48h', 'excel_ds.sqlite3 is a static 114KB reference frozen from my-finebi (unchanged since 2026-08-31); re-export it if the FineBI Excel datasets ever change', 'Before 2026-09-21 a manual ETL in the retired my-finebi project maintained this table; with no scheduler it froze at 2026-08-31'],
    },
  },
  {
    id: 'progress_sync', group: 'm', cron: '50 7 * * *',
    script: 'services/progress_sync.py → run_progress_sync',
    zh: {
      name: 'Progress 宽表重建',
      desc: '重建 progress 宽表（Eflow_TT_FB LEFT JOIN Eflow_WO_FB，复刻 FineBI Progress 计算列），写本机 data/progress.sqlite3，供 Progress / Progress V3 看板',
      flow: ['经只读 API 读远端 Eflow_TT_FB 与 Eflow_WO_FB（按 WO No. 1:1 关联）', '逐行复刻 FineDB 数据集 4bc5a679 的 Progress 计算列（各环节 ORG/STATUS、FB_* 级联、ORG_Handler、Month、MTTR1/2、clear_null）', '原子替换 data/progress.sqlite3'],
      maintain: ['Duration(Hours)/SLA(%) 依赖「当前时间」，刻意不落库，组件 SQL 用 julianday(\'now\',\'localtime\') 实时算', '口径在 services/progress_sync.py 的 _derive()；SWITCH 级联逐字移植，改动前先对照原脚本 TMP/etl_progress.py', '2026-09-21 上线前该表由已退役 my-finebi 的手工 ETL 维护，无调度 → 冻结在 2026-08-31'],
    },
    en: {
      name: 'Progress Wide Table Rebuild',
      desc: 'Rebuild the progress wide table (Eflow_TT_FB LEFT JOIN Eflow_WO_FB, replicating FineBI Progress computed columns) into local data/progress.sqlite3 for the Progress / Progress V3 boards',
      flow: ['Read remote Eflow_TT_FB and Eflow_WO_FB via the read-only API (1:1 join on WO No.)', 'Replicate FineDB dataset 4bc5a679 Progress columns per row (per-stage ORG/STATUS, FB_* cascade, ORG_Handler, Month, MTTR1/2, clear_null)', 'Atomically replace data/progress.sqlite3'],
      maintain: ['Duration(Hours)/SLA(%) depend on the current time and are deliberately NOT stored; widget SQL computes them live via julianday(\'now\',\'localtime\')', 'Definitions live in _derive() of services/progress_sync.py; the SWITCH cascades are a verbatim port — compare with the original TMP/etl_progress.py before changing', 'Before 2026-09-21 a manual ETL in the retired my-finebi project maintained this table; with no scheduler it froze at 2026-08-31'],
    },
  },
  {
    id: 'auto_retry_failed', group: 'm', cron: '*/10 * * * *',
    script: 'services/auto_retry.py → run_auto_retry_task',
    zh: {
      name: '失败任务自动重试',
      desc: '每 10 分钟扫描：失败任务若数据缺口尚未被后续成功执行补上则自动重投（MAX_ATTEMPTS=2，超 24h 放弃）；漏跑任务在时效窗口内无任何执行记录时补投一次',
      flow: ['每 10 分钟扫描最近 24 小时执行记录', '失败任务：先判断数据缺口是否已被后续成功执行补上，未补上且未超次数上限才重投', '漏跑任务：时效窗口内应触发却无任何执行记录时补投（15 分钟宽限）；邮件任务默认排除（归 EWS 补发）'],
      maintain: ['重试不是「失败就重跑」——缺口已被补上就不重投；环境变量 AUTO_RETRY_* 可调'],
    },
    en: {
      name: 'Failed Task Auto Retry',
      desc: 'Scans every 10 min: re-enqueues failed tasks whose data gap is not yet filled (MAX_ATTEMPTS=2, give up after 24h); backfills missed tasks with no execution record at all',
      flow: ['Scan the last 24h of execution records every 10 min', 'Failed tasks: re-enqueue only if the data gap is unfilled and under the attempt budget', 'Missed tasks: backfill once when nothing ran in the time window (15-min grace); email tasks excluded (handled by EWS recovery)'],
      maintain: ['Retry is not "rerun on any failure" — filled gaps are skipped; tune via AUTO_RETRY_* env vars'],
    },
  },
  {
    id: 'cm_data_sync', group: 'u', cron: '30 8 * * *',
    script: 'services/cm_data/cm_data_export.py → run_cm_data_sync',
    zh: {
      name: 'RAN CM 小区数据同步',
      desc: '从 RAN UME 获取 GSM/UMTS/LTE/NR 小区配置数据，经 API 全量替换写入远程 db.sqlite3（cm_cell_data/cm_site_summary），本地仅保留一份最新 Excel',
      flow: ['登录 RAN UME 按 services/cm_data/cm_flows.json 定义的流程导出小区配置', '经远程主机 API 全量替换 db.sqlite3 的 cm_cell_data / cm_site_summary', '本地仅保留一份最新 Excel'],
      maintain: ['导出流程（flows/payload/moc）在 services/cm_data/cm_flows.json 维护；网管界面改版后优先检查这里'],
    },
    en: {
      name: 'RAN CM Cell Data Sync',
      desc: 'Fetch GSM/UMTS/LTE/NR cell config from RAN UME, full-replace write to remote db.sqlite3 (cm_cell_data/cm_site_summary) via API, keep only the latest local Excel',
      flow: ['Log into RAN UME and export cell config per flows defined in services/cm_data/cm_flows.json', 'Full-replace cm_cell_data / cm_site_summary in remote db.sqlite3 via the host API', 'Keep only the latest Excel locally'],
      maintain: ['Export flows (flows/payload/moc) live in services/cm_data/cm_flows.json — check there first when the NMS UI changes'],
    },
  },
  {
    id: 'pg_to_sqlite_sync', group: 'm', cron: '45 * * * *',
    script: 'backend/scripts/sync_pg_to_sqlite.py → main',
    zh: {
      name: 'PG→SQLite 数据快照',
      desc: '把远程 PostgreSQL 全库数据同步到本地 db/app.db 作为离线备份/回退快照',
      flow: ['每小时 :45 全量同步远程 PG 到本地 db/app.db', 'app.db 兼作凭据表（credentials，明文）宿主'],
      maintain: ['app.db 里的业务表是「上一小时的镜像」，别在它上面做实时假设；也不要把它当垃圾删除（含凭据 + 快照，≈954MB）'],
    },
    en: {
      name: 'PG→SQLite Data Snapshot',
      desc: 'Sync all remote PostgreSQL data into local db/app.db as an offline backup / fallback snapshot',
      flow: ['Hourly :45 full-sync remote PG into local db/app.db', 'app.db also hosts the plaintext credentials table'],
      maintain: ['Business tables in app.db are a one-hour-stale mirror — never assume realtime; do not delete the file (credentials + snapshot, ≈954MB)'],
    },
  },
  {
    id: 'mw_ume_kpi_sync', group: 'w', cron: '15 5 * * *',
    script: 'services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync',
    zh: {
      name: 'MW UME KPI 同步',
      desc: 'MW UME（ZXMW 微波）KPI 历史指标同步（FINBI 模板 1 天粒度），内存导出不落盘，直接写入 app.db 表 mw_ume_bw_ultilazation',
      flow: ['每天 05:15 经 FINBI 模板导出 1 天粒度 KPI（内存处理，不落临时文件）', '按 Begin Time + 元素标识列联合去重后写主库 mw_ume_bw_ultilazation'],
      maintain: ['微波拓扑看板一天只变一次（05:15 后）；表名 ultilazation 是历史拼写，勿改'],
    },
    en: {
      name: 'MW UME KPI Sync',
      desc: 'MW UME (ZXMW microwave) KPI history sync (FINBI 1-day template), in-memory export without disk, direct write to app.db table mw_ume_bw_ultilazation',
      flow: ['Daily 05:15 export 1-day KPI via the FINBI template (in-memory, no temp files)', 'Dedup by Begin Time + identity columns, write mw_ume_bw_ultilazation'],
      maintain: ['The microwave topology board changes once a day (after 05:15); the misspelling ultilazation in the table name is historical — do not rename'],
    },
  },
  {
    id: 'mw_ume_kpi_sync_rt', group: 'w', cron: '*/15 * * * *',
    script: 'services/mw_ume/mw_ume_kpi_service.py → run_mw_ume_kpi_sync_rt',
    zh: {
      name: 'MW UME KPI 实时同步',
      desc: 'MW UME KPI 实时同步（FINBI 模板 15 分钟粒度），每 15 分钟取最近 2 小时数据，直写 app.db 表 mw_ume_bw_ultilazation_rt',
      flow: ['每 15 分钟经 FINBI 模板（gr=900）取最近 2 小时数据', '内存导出直写 mw_ume_bw_ultilazation_rt（覆盖窗口内槽位）', '微波实时看板默认只取最新一个 15 分钟槽位，滑杆可回看'],
      maintain: ['与日粒度任务共用网管会话，同在 n 组串行；看板默认 900 秒自动刷新且支持软刷新'],
    },
    en: {
      name: 'MW UME KPI Realtime Sync',
      desc: 'MW UME realtime KPI sync (FINBI 15-min template): every 15 min fetch the last 2 hours, direct write to app.db table mw_ume_bw_ultilazation_rt',
      flow: ['Every 15 min fetch the last 2 hours via FINBI (gr=900)', 'In-memory export, write mw_ume_bw_ultilazation_rt (overwrites slots in window)', 'The realtime board uses only the latest 15-min slot; the slider reviews history'],
      maintain: ['Shares the NMS session with the daily task — serialized in group n; the board auto-refreshes every 900s with soft refresh'],
    },
  },
  {
    id: 'ems_kpi_cache_sync', group: 'c', cron: '*/15 * * * *',
    script: 'services/cn_ems/ems_kpi_service.py → run_ems_kpi_cache_sync',
    zh: {
      name: 'CN EMS KPI 缓存同步',
      desc: '每 15 分钟增量下载 CN EMS 当日（UTC）原始 PM 测量文件到本地 _pmcache（服务器仅保留约 1 天；只下载缺失文件不解析）',
      flow: ['每 15 分钟经 SFTP 增量下载当日 UTC 原始 PM 文件', '只下载缺失文件，不做解析（轻量）', '落到本地 _pmcache 缓存'],
      maintain: ['CN EMS 服务器只保留约 1 天原始文件——本任务是把整天数据在服务端清理前抢回来的关键，不要停用'],
    },
    en: {
      name: 'CN EMS KPI Cache Sync',
      desc: 'Every 15 min, incremental download of today\'s (UTC) raw PM measurement files from CN EMS SFTP into local _pmcache (server retains ~1 day; fetch-only, no parsing)',
      flow: ['Incrementally download today\'s UTC raw PM files via SFTP every 15 min', 'Fetch-only, no parsing (lightweight)', 'Store into the local _pmcache'],
      maintain: ['The CN EMS server keeps raw files ~1 day — this task is what rescues the full day before server cleanup; do not disable'],
    },
  },
  {
    id: 'ems_kpi_daily', group: 'c', cron: '20 0 * * *',
    script: 'services/cn_ems/ems_kpi_service.py → run_ems_kpi_daily',
    zh: {
      name: 'CN EMS KPI 日粒度CSV',
      desc: '聚合前一个完整 UTC 日的 CN EMS KPI 并生成 csv_out/<模板名>.csv（VLR/USSD/语音/位置更新/License/TDD/Data 订阅者 7 模板）',
      flow: ['每天 00:20 UTC（北京 08:20）先 best-effort 补抓前一日窗口', '纯本地 _pmcache 缓存聚合（不再依赖服务端）', '按 Query_Template.xml + samples 公式输出 csv_out/<模板名>.csv，共 7 个模板'],
      maintain: ['与缓存同步共享 _pmcache/daily_raw.json，同在 c 组串行保证互斥'],
    },
    en: {
      name: 'CN EMS KPI Daily CSV',
      desc: 'Aggregate the previous complete UTC day of CN EMS KPIs into csv_out/<TEMPLATE>.csv per Query_Template.xml (7 templates: VLR/USSD/voice/location update/License/TDD/data subscribers)',
      flow: ['Daily 00:20 UTC (08:20 Beijing): best-effort refetch of the previous-day window', 'Aggregate purely from the local _pmcache (server-independent)', 'Emit csv_out/<TEMPLATE>.csv per Query_Template.xml + samples formulas (7 templates)'],
      maintain: ['Shares _pmcache/daily_raw.json with the cache sync — serialized in group c for mutual exclusion'],
    },
  },
  // ==================== 2026-09-18 补齐：注册表里有、本页此前缺失的 13 个任务 ====================
  {
    id: 'cxo_dashboard_cache_sync', group: 'v', cron: '*/10 * * * *',
    script: 'services/cxo_dashboard_cache.py → run_cxo_dashboard_cache_sync',
    zh: {
      name: 'CXO 看板数据缓存同步',
      desc: '每 10 分钟经本机 8790 VMAX 代理拉取 CXO 看板全量接口，按接口粒度合并为 last-known-good 缓存（空值保留旧值），供看板兜底展示',
      flow: ['每 10 分钟经 127.0.0.1:8790 VMAX 代理拉取 CXO 看板全部接口', '按接口粒度合并 last-known-good：某接口本轮取空只保留旧值，不把看板打成空白', '落盘 data/cxo_dashboard/last_known_good.json'],
      maintain: [
        '2026-09-18 与另两个 8790 任务一起从 n 组拆到 v 组：同会话必须串行，但不再排在 sp_data_sync（1.5~2h）后面',
        '上线时曾漏登记 GROUP_TASK_MAP → 队列 pending 卡死、看板停在旧日期（第四次踩坑）',
        '8790 会话失效时本任务失败，而看板会继续用 last-known-good 展示（看着正常其实已停更）——以任务执行历史为准',
      ],
    },
    en: {
      name: 'CXO Dashboard Cache Sync',
      desc: 'Every 10 min pull all CXO dashboard APIs via the local 8790 VMAX proxy and merge them per-endpoint into a last-known-good cache (empty fetch keeps the old value) as the dashboard fallback',
      flow: ['Pull every CXO dashboard endpoint via 127.0.0.1:8790 every 10 min', 'Merge per endpoint: an empty fetch keeps the old value instead of blanking the board', 'Persist data/cxo_dashboard/last_known_good.json'],
      maintain: [
        'Split out of group n into group v on 2026-09-18 with the other two 8790 tasks: still serialized on the shared session, no longer queued behind sp_data_sync (1.5-2h)',
        'Missed its GROUP_TASK_MAP registration at launch → stuck pending and the board froze on a stale date (the fourth such accident)',
        'When the 8790 session dies this task fails but the board keeps showing last-known-good (looks fine, actually stalled) — trust the execution history',
      ],
    },
  },
  {
    id: 'vmax_cxo_daily_sync', group: 'v', cron: '15 * * * *',
    script: 'services/vmax_cxo_daily_cache.py → run_vmax_cxo_daily_sync',
    zh: {
      name: 'VMAX CXO 天粒度日值归档',
      desc: '每小时经 8790 VMAX 代理按监控批量拉取最近 8 天的 1hour 明细（50 个指标压成 8 个多列请求），聚合为日值落盘，供页签化天粒度看板累积回看约三周',
      flow: ['每小时 :15 按监控批量拉最近 8 天的 1hour 明细（6 个 CXO 趋势 + 14 个网络 KPI + 30 个服务/OTT KPI）', '按流量 SUM / 用户 PEAK / 速率 AVG 聚合为日值', '落盘 data/vmax_cxo_daily/daily.json'],
      maintain: [
        '与 cxo_dashboard_cache_sync、vmax_multi_data_sync 共用 8790 单会话，同在 v 组串行',
        '日值由小时明细聚合：错过几个小时可由 8 天窗口自动补回，无需人工回填',
      ],
    },
    en: {
      name: 'VMAX CXO Daily Value Archive',
      desc: 'Hourly: batch-pull the last 8 days of 1-hour detail for 50 KPIs (compressed into 8 multi-column requests) via the 8790 VMAX proxy, aggregate to daily values for the tabbed daily board (~3 weeks of review)',
      flow: ['At :15 every hour pull 8 days of 1-hour detail (6 CXO trend + 14 network + 30 service/OTT KPIs)', 'Aggregate per day: SUM for volume, PEAK for users, AVG for rates', 'Persist data/vmax_cxo_daily/daily.json'],
      maintain: [
        'Shares the single 8790 session with cxo_dashboard_cache_sync and vmax_multi_data_sync — serialized in group v',
        'Daily values are aggregated from hourly detail: missing hours are refilled from the 8-day window automatically',
      ],
    },
  },
  {
    id: 'vmax_multi_data_sync', group: 'v', cron: '45 * * * *',
    script: 'services/vmax_multi_data/vmax_multi_data_service.py → run_vmax_multi_data_sync',
    zh: {
      name: 'VMAX 多报表指标采集',
      desc: '每小时经 8790 VMAX 代理抓取 url.txt 记录的 vreport 报表（5GSA 流量 / 5GSA 视频）指标明细，落盘 latest.json 与 vmax_multi_data.sqlite3',
      flow: ['每小时 :45 经 8790 代理请求 vreport 报表（sys_5gsa_traffic_ciservice / sys_5gsa_video_ciservice）', 'report_query 参数走 RSA 分块加密', '落盘 data/vmax_multi_data/<报表>_latest.json 与 vmax_multi_data.sqlite3（kpi_rows 明细 + sync_runs 运行记录）'],
      maintain: [
        '2026-09-18 补登记分组前从未执行过（第四次踩坑），现与另两个 8790 任务同属 v 组',
        '页面取的是 latest.json 快照，任务失败时页面仍显示上一次数据，不会报错',
      ],
    },
    en: {
      name: 'VMAX Multi-Report KPI Collect',
      desc: 'Hourly: fetch the vreport reports listed in url.txt (5GSA traffic / 5GSA video) via the 8790 proxy and persist latest.json plus vmax_multi_data.sqlite3',
      flow: ['At :45 every hour request the vreport reports (sys_5gsa_traffic_ciservice / sys_5gsa_video_ciservice) via the 8790 proxy', 'report_query parameters are RSA block-encrypted', 'Persist data/vmax_multi_data/<key>_latest.json and vmax_multi_data.sqlite3 (kpi_rows + sync_runs)'],
      maintain: [
        'Never ran before its group registration on 2026-09-18 (the fourth accident); now in group v with the other two 8790 tasks',
        'Pages read the latest.json snapshot, so a failing task still shows the previous run without any error',
      ],
    },
  },
  {
    id: 'olib_soc_kpi_daily_sync', group: 'm', cron: '20 6 * * *',
    script: 'services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_kpi_sync',
    zh: {
      name: 'OLIB SOC 看板 KPI 增量',
      desc: '每日增量补齐 VMAX 90 天经营看板的 KPI 库（daily_kpi 表）：只跑 7 个看板块，只取缺的日期 + 重取最新 1 天，不出 Excel',
      flow: ['每天 06:20 直连 VMAX 数仓 GBase（10.123.255.12:5258，库 zxvmax）', '只跑流量/活跃用户/缓存/视频/游戏/TCP/TOP 业务 7 个块', '只取缺失日期 + 重取最新 1 天（默认回看 7 天，幂等自愈），写 data/olib_soc_report/olib_soc_report.sqlite3 的 daily_kpi'],
      maintain: [
        '数仓分区只保留约 90 天，回看窗口必须落在保留期内',
        'GBase 不可达时本任务失败；链路恢复后 days_back=7 会自动补齐断档，无需人工回填',
        '上线时漏登记分组→ 90 天看板停在旧日期（2026-09-18 补录 m 组）',
      ],
    },
    en: {
      name: 'OLIB SOC Dashboard KPI Sync',
      desc: 'Daily incremental fill of the 90-day CXO dashboard KPI store (daily_kpi): only the 7 dashboard blocks, missing days plus the newest day re-read, no Excel output',
      flow: ['Daily 06:20 connect straight to the VMAX GBase DWH (10.123.255.12:5258, db zxvmax)', 'Run only the 7 board blocks (traffic/active users/cache/video/game/TCP/top services)', 'Fetch missing days plus re-read the newest day (7-day lookback, idempotent) into daily_kpi in data/olib_soc_report/olib_soc_report.sqlite3'],
      maintain: [
        'DWH partitions are kept ~90 days, so the lookback window must stay inside that retention',
        'When GBase is unreachable the task fails; once the link returns, days_back=7 refills the gap by itself',
        'Missed its group registration at launch, freezing the 90-day board on a stale date (added to group m on 2026-09-18)',
      ],
    },
  },
  {
    id: 'olib_soc_vmax_report', group: 'm', cron: '30 7 1 * *',
    script: 'services/olib_soc_report/olib_soc_report_service.py → run_olib_soc_report',
    zh: {
      name: 'OLIB SOC VMAX 例行报表',
      desc: '直连 VMAX 数仓 GBase 按日分区跑 notebook 移植的 9 段 SQL，生成多 sheet Excel 与运行记录；默认出上一个自然月',
      flow: ['每月 1 日 07:30 直连 GBase 按日分区跑 9 段 SQL（traffic/Active_user/cache/GUW/Video/game/TCP/TOP 业务/TOP 视频）', '生成多 sheet Excel 与运行记录，默认窗口为上一个自然月（可配 last_n_days/weekly/explicit）', '窗口自动截断到数仓约 90 天保留期内'],
      maintain: [
        '低频任务（每月一次）：健康巡检按 cron 间隔判定，不会因为“24h 没跑”被误报',
        '配置在 services/olib_soc_report/ 的 json（range_mode/days/mail.enabled）；GBase 口令走凭据分组 vmax_gbase',
      ],
    },
    en: {
      name: 'OLIB SOC VMAX Routine Report',
      desc: 'Direct GBase DWH queries on daily partitions for the 9 notebook report blocks, producing a multi-sheet Excel plus run records; default window = previous calendar month',
      flow: ['Monthly on the 1st at 07:30 run the 9 SQL blocks against GBase daily partitions', 'Emit a multi-sheet Excel and run records; default window is the previous calendar month (last_n_days/weekly/explicit configurable)', 'The window is clamped to the ~90-day partition retention'],
      maintain: [
        'Low-frequency (monthly): the health check scales its window by cron, so it is not falsely reported as “silent for 24h”',
        'Config lives in the JSON files under services/olib_soc_report/ (range_mode/days/mail.enabled); the GBase password comes from credential group vmax_gbase',
      ],
    },
  },
  {
    id: 'ume_in_kpi_sync', group: 'n', cron: '45 5 * * *',
    script: 'services/ume_in/ume_in_kpi_service.py → run_ume_in_kpi_sync',
    zh: {
      name: '客户业务 KPI 同步',
      desc: '从 UME 门户 172.17.208.1:28808 抓取 Dong customer 周期业务 KPI（IVR/P4M/VC/USSD/PPS/CPU/Memory 共 7 个模板，1 天粒度，默认回看 7 天），直写主库表 ume_in_customer_kpi',
      flow: ['每天 05:45 登录 UME 门户抓 7 个模板的 1 天粒度 KPI', '内存导出不落盘', '直写主库表 ume_in_customer_kpi（Begin Time + KPI + NE + SERVICE 联合去重）'],
      maintain: [
        '与其它网管类任务同在 n 组串行',
        '默认回看 7 天幂等：门户侧延迟出数会自动补回',
      ],
    },
    en: {
      name: 'Customer Service KPI Sync',
      desc: 'Fetch Dong customer service KPIs from the UME portal 172.17.208.1:28808 (7 templates: IVR/P4M/VC/USSD/PPS/CPU/Memory, 1-day granularity, 7-day lookback) and write table ume_in_customer_kpi',
      flow: ['Daily 05:45 log into the UME portal and fetch the 7 templates at 1-day granularity', 'In-memory export, nothing written to disk', 'Direct write to ume_in_customer_kpi (dedup by Begin Time + KPI + NE + SERVICE)'],
      maintain: [
        'Serialized in group n with the other NMS tasks',
        'Idempotent thanks to the 7-day lookback: late-arriving portal data is refilled automatically',
      ],
    },
  },
  {
    id: 'ume_in_osg_report', group: 'n', cron: '30 6 * * *',
    script: 'services/ume_in/osg_report_task.py → run_ume_in_osg_report（内部依次调 ume_in_kpi_service + t_osg_build.py）',
    zh: {
      name: '客户业务 KPI + OSG 周报邮件',
      desc: '每天早上分步执行：先做一次 ume_in KPI 同步，再按 ume_in_customer_kpi 最新 7 天生成 OSG Weekly QoS Analysis Report Excel，最后把该 Excel 作为附件发给 djoumene.reussite1@zte.com.cn（抄送 dong.xinmin@zte.com.cn）',
      flow: [
        '06:30 ① 调 ume_in_kpi_service.run_ume_in_kpi_sync() 同步 7 个模板到 ume_in_customer_kpi（与 ume_in_kpi_sync 同一门户会话）',
        '② 调 services/ume_in/t_osg_build.py 取表里最新 7 天填充 OSG 模板，产出 data/in_data/OSG Weekly QoS Analysis Report_<起>_<止>.xlsx（图表/条件格式/样式不动；派生列按原模板公式写入公式+缓存值：PPS 的 C/E/J、USSD 的 C/E/I、VC 的 H、IVR 的 E）',
        '③ 附件经 Orange EWS 发给主送 djoumene.reussite1@zte.com.cn、抄送 dong.xinmin@zte.com.cn',
      ],
      maintain: [
        '与 ume_in_kpi_sync 同组 n 串行：同一步骤共用 UME Dong 门户单会话',
        '第 1 步同步失败即中止，不会把上一窗口的旧数据当新报告发出去',
        '收件人可在 Settings → Email Recipient Settings 的 ume_in_osg_report 组覆盖；产物只保留最近 10 份',
      ],
    },
    en: {
      name: 'Customer Service KPI + OSG Weekly Report Email',
      desc: 'Every morning, step by step: run the ume_in KPI sync, build the OSG Weekly QoS Analysis Report Excel from the latest 7 days in ume_in_customer_kpi, then email that Excel to djoumene.reussite1@zte.com.cn (cc dong.xinmin@zte.com.cn)',
      flow: [
        '06:30 ① call ume_in_kpi_service.run_ume_in_kpi_sync() to sync the 7 templates into ume_in_customer_kpi (same portal session as ume_in_kpi_sync)',
        '② call services/ume_in/t_osg_build.py to fill the OSG template with the latest 7 days, producing data/in_data/OSG Weekly QoS Analysis Report_<start>_<end>.xlsx (charts/conditional formatting/styles untouched; derived columns get both formula and cached value, per the original template formulas: PPS C/E/J, USSD C/E/I, VC H, IVR E)',
        '③ attach it to an Orange EWS mail to djoumene.reussite1@zte.com.cn, cc dong.xinmin@zte.com.cn',
      ],
      maintain: [
        'Serialized in group n with ume_in_kpi_sync: step ① shares the UME Dong portal session',
        'A failed sync aborts the run — a stale previous-window report is never emailed as the new one',
        'Recipients are editable under Settings → Email Recipient Settings (group ume_in_osg_report); only the latest 10 artifacts are kept',
      ],
    },
  },
  {
    id: 'sp_online_sync', group: 'n', cron: '35 */6 * * *',
    script: 'services/sp_online_sync.py → run_sp_online_sync',
    zh: {
      name: 'SP Online 工单同步',
      desc: '每 6 小时从 eFlow SP 接口拉在线工单（sp-outbound / sp-inbound / sp-transfer），写库表对应三张表。取「原始 filter」与「状态全集 filter」两份结果的并集，避免 filter 与其返回结果自相矛盾时静默取错数据。表语义=上游当前快照：全量重建，删除上游已消失的单据',
      flow: ['每 6 小时 :35 请求 eFlow SP 三个接口，同一接口用原始 filter 与状态全集 filter 各拉一次', '两份结果按 woId 合并去重后写库表 sp_outbound / sp_inbound / sp_transfer', '全量重建：upsert 后删除表中不在本轮 woId 集合里的行（表=上游快照）；拉取不完整时只 upsert、不删除', '返回行的状态若全不在 filter 枚举内则告警（过滤条件与结果自相矛盾）', '「表浏览器」可直查；sp_online_report_generate 的 Outbound 支路直接消费 sp_outbound 表'],
      maintain: [
        '上游账号走 eflow 凭据分组；eFlow 会话被踢时表现为该组任务连续 failed，由 auto_retry_failed 兜底',
        '2026-09-30 由「原始 filter 取到 0 行才回退全集」改为取并集：旧判据会把「该 filter 本就没有匹配」误判成「filter 坏了」，inbound 因此把「查在途」变成了「查历史关闭单」（282 行全 Closed）且无告警',
        '实测上游并不真正遵循 filter 的收窄语义（inbound 用 4 个在途态与 15 态全集请求返回同一份数据），故不要依赖 filter 精确性',
        '2026-10-09 增加全量重建：旧实现只 upsert 从不删除，上游已消失的单据会永久残留（sp_outbound 积了 37 条僵尸 WaitingForUpdate，被 sp_online 报表原样呈现）。安全阀：仅当端点两份 filter 全部成功且结果非空才删除，否则退化为只 upsert',
      ],
    },
    en: {
      name: 'SP Online Ticket Sync',
      desc: 'Every 6 hours: fetch online tickets from the eFlow SP APIs (sp-outbound/sp-inbound/sp-transfer) into the matching tables. Takes the union of the original filter and the all-status filter so a filter contradicting its own results can never silently pick the wrong data. Tables mirror the upstream snapshot: a full rebuild removes tickets that have vanished upstream',
      flow: ['At :35 every 6 hours call the three eFlow SP APIs, each once with the original filter and once with the all-status filter', 'Merge both result sets by woId and write tables sp_outbound / sp_inbound / sp_transfer', 'Full rebuild: after upserting, delete rows whose woId is not in this run; on an incomplete fetch it only upserts and never deletes', 'Warn when every returned row has a status outside the filter enumeration (filter contradicts results)', 'Queryable in Table Browser; the Outbound leg of sp_online_report_generate consumes sp_outbound directly'],
      maintain: [
        'Upstream account comes from the eflow credential group; a kicked eFlow session shows up as consecutive failures in the group, covered by auto_retry_failed',
        'Changed 2026-09-30 from "fall back to the all-status filter only when the original returns 0 rows" to a union: the old test mistook "this filter simply has no matches" for "the filter is broken", which turned inbound into a closed-ticket query (282 rows, all Closed) with no warning',
        'Upstream does not truly honour filter narrowing (inbound returns the same data for a 4-status and a 15-status filter), so never rely on filter precision',
        'Added 2026-10-09: full rebuild. The old implementation only upserted and never deleted, so tickets that vanished upstream stayed forever (37 zombie WaitingForUpdate rows in sp_outbound, surfaced as-is by the sp_online report). Safety valve: delete only when both filters succeed and the result is non-empty, otherwise degrade to upsert-only',
      ],
    },
  },
  {
    id: 'sp_material_sync', group: 'n', cron: '55 4 * * *',
    script: 'services/sp_material_sync.py → run_sp_material_sync',
    zh: {
      name: 'SP 物料主数据同步',
      desc: '从 eFlow SP 物料接口（eflow-sp-material）拉全量物料主数据，按 materialNo 唯一键 upsert 写 app.db 表 sp_material。表语义=上游当前快照：全量重建，删除上游已消失的物料',
      flow: ['每天 04:55 拉 eflow-sp-material 全量物料主数据', '按 materialNo upsert 写 app.db 表 sp_material', '全量重建：删除表中不在本轮 materialNo 集合里的行（表=上游快照）；拉取不完整时只 upsert、不删除', '「表浏览器」可查，下游 sp_material_report 出库存与消耗报表'],
      maintain: [
        '下游 sp_material_report（07:33）只读表不拉接口：本任务停更时邮件仍会正常发，但内容是旧数据（db_freshness_check 已覆盖 sp_material 新鲜度）',
        '2026-10-09 增加全量重建：旧实现只 upsert 从不删除，上游停用/删除的物料会永久残留（与 sp_online 同型）。安全阀：仅当 fetch_all 完整拉取（未达 MAX_PAGES 上限、非 0 行）才删除，否则退化为只 upsert',
      ],
    },
    en: {
      name: 'SP Material Master Sync',
      desc: 'Fetch the full material master from the eFlow SP API (eflow-sp-material) into app.db table sp_material (upsert by materialNo). The table mirrors the upstream snapshot: a full rebuild removes materials that vanished upstream',
      flow: ['Daily 04:55 pull the full eflow-sp-material master', 'Upsert into app.db table sp_material by materialNo', 'Full rebuild: delete rows whose materialNo is not in this run; on an incomplete fetch it only upserts and never deletes', 'Queryable in Table Browser; sp_material_report builds the stock/consumption report from it'],
      maintain: [
        'sp_material_report (07:33) only reads the table: if this task stalls, the email still sends but with stale content (db_freshness_check now covers sp_material freshness)',
        'Added 2026-10-09: full rebuild. The old implementation only upserted and never deleted, so materials disabled/deleted upstream stayed forever (same shape as sp_online). Safety valve: delete only when fetch_all is complete (no MAX_PAGES cap hit, non-empty), otherwise degrade to upsert-only',
      ],
    },
  },
  {
    id: 'sp_online_report_generate', group: 'm', cron: '0 6 * * *',
    script: 'services/kpi_email_report.py → run_sp_online_report_generate',
    zh: {
      name: 'SP 在线未关闭单报表生成',
      desc: '生成 sp_online 下未关闭单报表（PNG+XLSX，Create Time 倒序）：Inbound 读明细 xlsx 未关闭单，Outbound 读库表 sp_outbound 跟踪 WaitingForUpdate / WaitingForReturn / WaitingForConfirm',
      flow: ['每天 06:00 生成 data/sp_email/sp_online 的 Inbound/Outbound 报表（PNG + XLSX）', 'Inbound：读 data/sp_email/data 最新 inband_details.xlsx，过滤未关闭单', 'Outbound：读库表 sp_outbound（sp_online_sync 每小时拉 eFlow），取等待更新/等待归还/等待确认三类在途单'],
      maintain: [
        '纯生成不发信，发送由 06:20 的 sp_online_report_send 负责——两者拆开后重跑发送不必重新取数',
        'Outbound 曾读 SFTP 明细 xlsx，因该导出不含 WaitingForUpdate（等待更新）而于 2026-09-30 改读库表 sp_outbound，见 sp_report_gen/README.md',
      ],
    },
    en: {
      name: 'SP Online Open Tickets Report Generate',
      desc: 'Build the open-ticket Inbound/Outbound reports (PNG+XLSX, sorted by Create Time desc): Inbound from the details xlsx, Outbound from table sp_outbound tracking WaitingForUpdate / WaitingForReturn / WaitingForConfirm',
      flow: ['Daily 06:00 emit Inbound/Outbound PNG + XLSX into data/sp_email/sp_online', 'Inbound: read the newest inband_details.xlsx under data/sp_email/data, keep open tickets', 'Outbound: read table sp_outbound (sp_online_sync pulls eFlow hourly) for the three in-flight statuses'],
      maintain: [
        'Generates only — sp_online_report_send (06:20) delivers, so re-sending never requires regenerating',
        'Outbound used to read the SFTP details xlsx; switched to table sp_outbound on 2026-09-30 because that export carries no WaitingForUpdate — see sp_report_gen/README.md',
      ],
    },
  },
  {
    id: 'sp_online_report_send', group: 'm', cron: '20 6 * * *',
    script: 'services/kpi_email_report.py → run_sp_online_report',
    zh: {
      name: 'SP 在线未关闭单报表发送',
      desc: '发送 sp_online 未关闭单报表：邮件（PNG 内嵌 + XLSX 附件，默认复用 SP 报表远程名单）+ WhatsApp 群',
      flow: ['每天 06:20 取 sp_online 最新报表文件', '邮件：Inbound/Outbound PNG 内嵌 + XLSX 附件', '同时发到 WhatsApp 群，收件人可在「系统设置 → 邮件收件人」覆盖'],
      maintain: [
        '依赖 06:00 的 sp_online_report_generate 产物，上游缺文件时本任务直接失败',
        '属邮件类任务：默认不参与漏跑补投，EWS 恢复后由 email_recovery 补发',
      ],
    },
    en: {
      name: 'SP Online Open Tickets Report Send',
      desc: 'Send the open-ticket report: email (inline Inbound/Outbound PNG + XLSX attachments, default SP shared recipient list) + WhatsApp groups',
      flow: ['Daily 06:20 pick up the newest sp_online report files', 'Email with inline PNG plus XLSX attachments', 'Also push to WhatsApp groups; recipients overridable under Settings → Email Recipients'],
      maintain: [
        'Depends on the 06:00 generation task output — missing files make this one fail outright',
        'An email task: excluded from missed-run backfill by default, email_recovery replays it once EWS is back',
      ],
    },
  },
  {
    id: 'eflow_alarm_rules_collect', group: 'n', cron: '59 23 */3 * *',
    script: 'services/eflow_rules/eflow_Alarm_Rule_Collector.py → run_eflow_alarm_rules',
    zh: {
      name: 'eFlow 告警规则收集',
      desc: '每 3 天 23:59 从 eFlow 拉取规则类型目录与告警关联规则（correlation-mgt），导出 eflow_alarm_rules.xlsx',
      flow: ['每 3 天 23:59 拉 eFlow 规则类型目录与告警关联规则（correlation-mgt）', '导出 backend/services/eflow_rules/eflow_alarm_rules.xlsx（Alarm_Rules + Rule_Types 两个 Sheet）'],
      maintain: [
        '低频任务（每 3 天）：健康巡检按 cron 间隔判定，不会因“24h 未执行”被误报',
        '导出的 xlsx 是下游规则比对的输入，属代码资产，不要手工改动',
      ],
    },
    en: {
      name: 'eFlow Alarm Rules Collect',
      desc: 'Every 3 days at 23:59 pull rule types and alarm correlation rules from eFlow into eflow_alarm_rules.xlsx (sheets Alarm_Rules + Rule_Types)',
      flow: ['Every 3 days at 23:59 pull the rule-type catalog and correlation rules (correlation-mgt)', 'Export backend/services/eflow_rules/eflow_alarm_rules.xlsx'],
      maintain: [
        'Low-frequency (every 3 days): the health check scales its window by cron, so “no run in 24h” is not a false alarm',
        'The exported xlsx feeds downstream rule matching — treat it as a code asset, never hand-edit',
      ],
    },
  },
  {
    id: 'eflow_push_rules_collect', group: 'n', cron: '59 23 */3 * *',
    script: 'services/eflow_rules/eflow_Push_Rule_Collector.py → run_eflow_push_rules',
    zh: {
      name: 'eFlow 推单规则收集',
      desc: '每 3 天 23:59 从 eFlow config-center 拉取全部规则（推单/升级/分组/自动关闭等 28 种类型），逐条合并 detail 后导出 eflow_push_rules.xlsx',
      flow: ['每 3 天 23:59 以 query filter="" 拉 config-center 全部规则（28 种类型）', '逐条合并规则 detail', '导出 backend/services/eflow_rules/eflow_push_rules.xlsx（Push_Rules + Rule_Type_Summary）'],
      maintain: [
        '低频任务（每 3 天），与告警规则收集同组同周期',
        '与 eflow_tt_rules_check 用的规则表同处 services/eflow_rules/，目录与文件名不要改名',
      ],
    },
    en: {
      name: 'eFlow Push Rules Collect',
      desc: 'Every 3 days at 23:59 pull all rules from the eFlow config-center (28 types: push/escalation/grouping/auto-close...), merging detail per rule into eflow_push_rules.xlsx',
      flow: ['Every 3 days at 23:59 query the config-center with filter="" for all rules (28 types)', 'Merge the detail of each rule', 'Export backend/services/eflow_rules/eflow_push_rules.xlsx (Push_Rules + Rule_Type_Summary)'],
      maintain: [
        'Low-frequency (every 3 days), same group and cadence as the alarm-rules collector',
        'Lives in services/eflow_rules/ next to the rule sheet used by eflow_tt_rules_check — do not rename paths',
      ],
    },
  },
  {
    id: 'log_cleanup', group: 'm', cron: '17 3 * * *',
    script: 'services/log_cleanup.py → run_log_cleanup',
    zh: {
      name: '日志文件清理',
      desc: '每天清理 my_app/log 下超过保留期（默认 7 天，LOG_RETENTION_DAYS 可调）的日志，并把已无进程写入的旧命名日志补上日期后缀',
      flow: ['每天 03:17 扫描 log/ 下符合日志特征的文件', '删除超过保留期的（LOG_CLEANUP_DRY_RUN=1 只报告不删）', '给已无进程写入的旧命名日志补日期后缀，与各 watchdog 的按日期命名配合滚动保留'],
      maintain: [
        'Windows 下被进程占用的日志无法外部重命名/删除，只能由写入方按日期分文件——这就是日志名带日期的原因',
        'db/app.db（含凭据表）、backend/services/auth_cache/、data/ 下任务产物不在清理范围',
      ],
    },
    en: {
      name: 'Log Files Cleanup',
      desc: 'Daily purge of log files older than the retention window (7 days by default, LOG_RETENTION_DAYS) under my_app/log, plus date-suffixing of legacy names no process writes to',
      flow: ['Daily 03:17 scan log/ for log-shaped files', 'Delete those past retention (LOG_CLEANUP_DRY_RUN=1 reports without deleting)', 'Add date suffixes to legacy names so they roll with the date-based watchdog log names'],
      maintain: [
        'On Windows a file held open cannot be renamed/deleted from outside — that is why the writers split logs by date',
        'db/app.db (credentials), backend/services/auth_cache/ and data/ task outputs are out of scope',
      ],
    },
  },
  {
    id: 'tmp_cleanup', group: 'm', cron: '47 3 * * *',
    script: 'services/tmp_cleanup.py → run_tmp_cleanup',
    zh: {
      name: 'TMP 目录清理',
      desc: '两段式回收 my_app/TMP 下超过保留期（默认 7 天）的临时产物：先同盘移进 TMP/_quarantine_YYYYMMDD/（可还原），隔离再满 7 天才真删',
      flow: ['每天 03:47 扫描 TMP/ 下超过保留期的条目', '同盘 mv 进 _quarantine_<日期>/ 隔离（不直接删，留一次反悔机会）', '隔离期满 7 天后彻底删除；服务在用路径按 WHITELIST 跳过'],
      maintain: [
        'TMP/ 是临时产物的固定去处，但体积没人管（上线首日实测 462MB）——清理是必需的',
        'charts/dl/状态文件等服务在用路径在 WHITELIST 里，永不处理；新增此类路径要补白名单',
        '与 log_cleanup（03:17）错峰，避免同一时段两次全盘扫描',
      ],
    },
    en: {
      name: 'TMP Directory Cleanup',
      desc: 'Two-stage reclaim of temp artifacts older than the retention window (7 days) under my_app/TMP: same-volume move into TMP/_quarantine_YYYYMMDD/ first (restorable), real delete only after another 7 days',
      flow: ['Daily 03:47 scan TMP/ for entries past retention', 'Same-volume mv into _quarantine_<date>/ (nothing deleted outright)', 'Purge after another 7 days in quarantine; service paths in WHITELIST are skipped'],
      maintain: [
        'TMP/ is the designated place for temp artifacts but nothing bounded its size (462MB on day one) — cleanup is required',
        'Service paths (charts/dl/state files) are whitelisted and never touched; add new ones to WHITELIST',
        'Staggered against log_cleanup (03:17) so the two full scans do not overlap',
      ],
    },
  },
  {
    id: 'tt_mttr_report_generate', group: 'm', cron: '20 7 * * *',
    script: 'services/tt_mttr_report.py → run_tt_mttr_report',
    zh: {
      name: 'TTs and MTTR 报表生成',
      desc: '从最新一份 Site Down hourly Report 生成 TTs and MTTR (Hour) 月粒度工作簿，供邮件报告页「TTs and MTTR」页签下载',
      flow: ['每天 07:20 读 data/eflow/tt_reports 下最新的 hourly Report（Processed Data 页）', '筛出有 WO 的工单进 Raw Data，再按「告警发生→告警清除历时 < 48 小时 + Site Category 非空 + 告警月份 ≥ 2026-01」进 ZTE 页', 'Summary 页用 COUNTIFS/AVERAGEIFS 公式分月统计 P1~P4 的 TTs 与 MTTR，并插 4 张组合图（柱=TTs、青线=MTTR、红线=SLA 目标）', '产物文件名带时间戳，同目录只保留最新 1 份：新报告写出后自动删掉旧的'],
      maintain: [
        'SLA 达成一律按「告警发生 → 告警清除」的实际历时算，不看源表的 SLA Time 目标列（那是目标值不是耗时）',
        '未填 Ticket Severity 的工单单列 N/A 块统计，不出图（无 SLA 目标），否则这部分工单会被静默丢掉',
        'MTTR 纵轴上限交给 Excel 自动缩放：超标月份（如 P1 2026-05 的 16.37h）不能被裁掉',
        '口径改动前先跑一次并把 Summary 与 pandas 独立复算对拍；产物不在 _cleanup_old_tt_reports 的清理名单里，靠本任务自己的 KEEP_FILES 控制体积',
      ],
    },
    en: {
      name: 'TTs and MTTR Report Generate',
      desc: 'Builds the TTs and MTTR (Hour) monthly workbook from the latest Site Down hourly Report, downloadable from the "TTs and MTTR" tab of the report files page',
      flow: ['Daily 07:20 read the newest hourly Report under data/eflow/tt_reports (Processed Data sheet)', 'Tickets with a WO go to Raw Data; then filter on occur-to-clear < 48h + non-empty Site Category + month >= 2026-01 into the ZTE sheet', 'Summary tallies TTs and MTTR per month per P1-P4 with COUNTIFS/AVERAGEIFS formulas and inserts 4 combo charts (bars = TTs, cyan line = MTTR, red line = SLA target)', 'Output name carries a timestamp; only the newest single file is kept — the previous one is deleted as soon as the new report is written'],
      maintain: [
        'SLA attainment is always the actual occur-to-clear duration, never the source table SLA Time column (that one holds the target, not the duration)',
        'Tickets with an empty Ticket Severity are tallied in a separate N/A block without a chart (no SLA target) — otherwise they would be dropped silently',
        'The MTTR axis max is left to Excel auto-scaling so out-of-range months (e.g. P1 2026-05 at 16.37h) are not clipped',
        'Re-pause Summary against an independent pandas recomputation before changing the filter; this output is not in _cleanup_old_tt_reports, its size is bounded by KEEP_FILES here',
      ],
    },
  },
]
