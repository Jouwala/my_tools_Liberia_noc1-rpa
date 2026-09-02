/* ==================== 使用帮助 → Markdown 导出（同源生成器） ====================
 * 站内「使用帮助」页与 docs/manual/15-user-help.md 共用此生成器：
 * - 浏览器端：Help.tsx 的「导出 Markdown」按钮调用 buildHelpMarkdown(locale) 下载
 * - 本地生成：scripts/generate-help-doc.mjs 用 rolldown 打包本模块后落盘到 docs/manual/
 * 改帮助内容请改 helpContent.ts / helpTaskDocs.ts，两端自动同步。
 * ================================================ */

import { PAGE_LIST, NAV_KEY_MAP, CATEGORIES, PAGE_DOCS, COMMON, OPS } from './pages/helpContent'
import { TASK_DOCS, WORKER_GROUP_INFO } from './pages/helpTaskDocs'
import type { Locale } from './pages/helpContent'

/** 生成完整使用帮助 Markdown（zh 或 en） */
export function buildHelpMarkdown(locale: Locale): string {
  const L = locale === 'zh'
  const common = COMMON[locale]
  const ops = OPS[locale]
  const docs = PAGE_DOCS[locale]
  const out: string[] = []
  const genDate = new Date().toISOString().slice(0, 10)

  // ---------- 头部 ----------
  out.push(L ? '# my_app 使用帮助' : '# my_app User Help & Guide')
  out.push('')
  out.push(L
    ? `> 面向使用者的平台功能与操作指南。本文件由「使用帮助」页面同源生成（frontend/src/helpMarkdown.ts），内容依据 docs/manual/ 各章与 backend/task_registry.py 整理。生成日期：${genDate}。`
    : `> User-facing platform features & operations guide. Generated from the same source as the in-app Help page (frontend/src/helpMarkdown.ts), compiled from docs/manual/ and backend/task_registry.py. Generated on ${genDate}.`)
  out.push('')
  out.push(L
    ? '> 站内入口：侧边栏「使用帮助」，或直链 `http://<host>/myapp/?page=help`。'
    : '> In-app entry: the "Help" sidebar item, or `http://<host>/myapp/?page=help` directly.')
  out.push('')
  out.push('---')
  out.push('')

  // ---------- 目录 ----------
  out.push('## 目录')
  out.push('')
  out.push(L ? '- [1. 平台简介](#1-平台简介)' : '- [1. Platform Overview](#1-platform-overview)')
  out.push(L ? '- [2. 通用操作](#2-通用操作)' : '- [2. General Usage](#2-general-usage)')
  out.push(L ? `- [3. 任务管理详解（${TASK_DOCS.length} 个任务）](#3-任务管理详解)` : `- [3. Task Manager Deep Dive (${TASK_DOCS.length} tasks)](#3-task-manager-deep-dive)`)
  out.push(L ? '- [4. 页面指南](#4-页面指南)' : '- [4. Pages Guide](#4-pages-guide)')
  out.push(L ? '- [5. 运维与排障](#5-运维与排障)' : '- [5. Ops & Troubleshooting](#5-ops-troubleshooting)')
  out.push(L ? '- [6. 常见问题](#6-常见问题)' : '- [6. FAQ](#6-faq)')
  out.push('')

  // ============ 1. 平台简介 ============
  out.push(L ? '## 1. 平台简介' : '## 1. Platform Overview')
  out.push('')
  common.intro.forEach(p => { out.push(p); out.push('') })
  out.push(L ? '**它做什么**' : '**What it does**')
  out.push('')
  common.caps.do.forEach(c => out.push(`- ${c}`))
  out.push('')
  out.push(L ? '**它不做什么（能力边界）**' : '**What it does NOT do (boundaries)**')
  out.push('')
  common.caps.dont.forEach(c => out.push(`- ${c}`))
  out.push('')

  // ============ 2. 通用操作 ============
  out.push('---')
  out.push('')
  out.push(L ? '## 2. 通用操作' : '## 2. General Usage')
  out.push('')
  out.push(L ? '| 操作 | 说明 |' : '| Operation | Description |')
  out.push('| --- | --- |')
  common.tips.forEach(tp => out.push(`| ${tp.title} | ${tp.body} |`))
  out.push('')

  // ============ 3. 任务管理详解 ============
  out.push('---')
  out.push('')
  out.push(L ? '## 3. 任务管理详解' : '## 3. Task Manager Deep Dive')
  out.push('')

  // 3.1 一条任务的一生
  out.push(L ? '### 3.1 一条任务的一生' : '### 3.1 Lifecycle of a task')
  out.push('')
  ops.lifecycle.forEach(s => {
    out.push(`**${s.title}** ${s.body}`)
    out.push('')
  })

  // 3.2 worker 分组
  out.push(L ? '### 3.2 Worker 分组：组内串行、组间并行' : '### 3.2 Worker groups: serial within, parallel across')
  out.push('')
  out.push(L ? '| 组 | 约束原因 |' : '| Group | Why grouped |')
  out.push('| --- | --- |')
  Object.entries(WORKER_GROUP_INFO).forEach(([g, info]) => {
    out.push(`| **${g}** | ${locale === 'zh' ? info.zh : info.en} |`)
  })
  out.push('')
  out.push(L
    ? '> ⚠️ **新增任务必须同时登记进 `worker_watchdog.py` 的 `GROUP_TASK_MAP`** —— 只写 `TASK_SPECS` 不分组 = 任务入队后永远 pending。这是本项目已发生过三次的事故模式（finebi_report_sync / whatsapp_send_ext / sp_email_details）。'
    : '> ⚠️ **New tasks MUST also be registered in `GROUP_TASK_MAP` in worker_watchdog.py** — declaring them only in TASK_SPECS leaves them pending forever. This accident happened three times (finebi_report_sync / whatsapp_send_ext / sp_email_details).')
  out.push('')

  // 3.3 全量任务清单
  out.push(L ? `### 3.3 全量任务清单（${TASK_DOCS.length} 个）` : `### 3.3 Full task catalog (${TASK_DOCS.length} tasks)`)
  out.push('')
  out.push(L ? '| 任务 | task_id | 默认 cron | 组 | 工作流脚本 |' : '| Task | task_id | Default cron | Group | Workflow script |')
  out.push('| --- | --- | --- | --- | --- |')
  TASK_DOCS.forEach(td => {
    const txt = td[locale]
    out.push(`| ${txt.name} | \`${td.id}\` | \`${td.cron}\` | ${td.group} | \`${td.script}\` |`)
  })
  out.push('')
  out.push(L ? '每个任务的工作流与维护要点：' : 'Workflow & maintenance notes per task:')
  out.push('')

  // 每个任务的详解
  TASK_DOCS.forEach(td => {
    const txt = td[locale]
    out.push(`#### ${txt.name}（\`${td.id}\`）`)
    out.push('')
    out.push(`- ${L ? '默认 cron' : 'Default cron'}: \`${td.cron}\`　|　${L ? 'worker 组' : 'worker group'}: **${td.group}**`)
    out.push(`- ${L ? '工作流脚本' : 'Workflow script'}: \`${td.script}\``)
    out.push('')
    out.push(`**${L ? '功能' : 'What it does'}**: ${txt.desc}`)
    out.push('')
    out.push(`**${ops.flowLabel}**:`)
    out.push('')
    txt.flow.forEach(f => out.push(`1. ${f}`))
    out.push('')
    out.push(`**${ops.maintainLabel}**:`)
    out.push('')
    txt.maintain.forEach(m => out.push(`- ${m}`))
    out.push('')
  })

  // 3.4 可靠性机制
  out.push(L ? '### 3.4 可靠性机制（超时 / 重试 / 自愈）' : '### 3.4 Reliability mechanisms (timeout / retry / self-healing)')
  out.push('')
  out.push(L ? '| 机制 | 说明 |' : '| Mechanism | Description |')
  out.push('| --- | --- |')
  ops.mechanisms.forEach(m => out.push(`| **${m.name}** | ${m.body} |`))
  out.push('')

  // 3.5 维护指南
  out.push(L ? '### 3.5 任务维护指南' : '### 3.5 How to maintain tasks')
  out.push('')
  ops.maintain.forEach(m => {
    out.push(`**${m.title}** ${m.body}`)
    out.push('')
  })

  // 3.6 上游不可用
  out.push(L ? '### 3.6 上游不可用时怎么表现' : '### 3.6 When upstreams go down')
  out.push('')
  out.push(`| ${ops.upstreamCols[0]} | ${ops.upstreamCols[1]} | ${ops.upstreamCols[2]} |`)
  out.push('| --- | --- | --- |')
  ops.upstreamDown.forEach(r => out.push(`| ${r.sys} | ${r.symptom} | ${r.heal} |`))
  out.push('')

  // ============ 4. 页面指南 ============
  out.push('---')
  out.push('')
  out.push(L ? '## 4. 页面指南' : '## 4. Pages Guide')
  out.push('')
  out.push(L
    ? '所有页面可用 `?page=<key>` 直链打开，例如 `http://<host>/myapp/?page=battery`；或右键菜单项「在新标签页打开」。标注 iframe 的页面实际界面在 `frontend/public/*.html`，样式与 React 页面略有差异。'
    : 'Every page opens via a `?page=<key>` direct link, e.g. `http://<host>/myapp/?page=battery`; or right-click a menu item → "Open in new tab". Pages marked iframe render `frontend/public/*.html` inside, with slightly different styling.')
  out.push('')

  CATEGORIES.forEach((cat, ci) => {
    out.push(`### 4.${ci + 1} ${common.categories[cat.id]}`)
    out.push('')
    cat.pages.forEach(k => {
      const meta = PAGE_LIST.find(p => p.key === k)
      const doc = docs[k]
      if (!meta || !doc) return
      const name = NAV_KEY_MAP[k] ? localeName(locale, k) : k
      out.push(`#### ${name}（\`${k}\`${meta.iframe ? L ? '，iframe 页' : ', iframe page' : ''}）`)
      out.push('')
      out.push(doc.desc)
      out.push('')
      doc.usage.forEach(u => out.push(`- ${u}`))
      out.push('')
    })
  })

  // ============ 5. 运维与排障 ============
  out.push('---')
  out.push('')
  out.push(L ? '## 5. 运维与排障' : '## 5. Ops & Troubleshooting')
  out.push('')

  // 5.1 端口
  out.push(L ? '### 5.1 进程与端口速查' : '### 5.1 Processes & ports')
  out.push('')
  out.push(`| ${ops.portCols[0]} | ${ops.portCols[1]} | ${ops.portCols[2]} |`)
  out.push('| --- | --- | --- |')
  ops.ports.forEach(r => out.push(`| \`${r.port}\` | ${r.proc} | ${r.guard} |`))
  out.push('')

  // 5.2 巡检
  out.push(L ? '### 5.2 日常巡检（5 分钟）' : '### 5.2 Daily inspection (5 minutes)')
  out.push('')
  ops.inspect.forEach(s => out.push(`- ${s}`))
  out.push('')

  // 5.3 日志
  out.push(L ? '### 5.3 日志速查' : '### 5.3 Log files')
  out.push('')
  out.push(`| ${ops.logCols[0]} | ${ops.logCols[1]} |`)
  out.push('| --- | --- |')
  ops.logs.forEach(l => out.push(`| \`${l.file}\` | ${l.body} |`))
  out.push('')
  out.push(L
    ? '> ⚠️ 全仓库没有日志轮转，`log/` 只会一直涨，需人工定期清理；部分日志报错原文含账号，外发前先扫一遍。'
    : '> ⚠️ No log rotation exists — `log/` grows forever and needs manual cleanup; some error lines contain account names, scan before sharing.')
  out.push('')

  // 5.4 备份
  out.push(L ? '### 5.4 备份（三处都要备，缺一不完整）' : '### 5.4 Backup (all three, incomplete otherwise)')
  out.push('')
  ops.backup.forEach(b => {
    out.push(`- **${b.obj}**: ${b.body}`)
  })
  out.push('')

  // 5.5 清理
  out.push(L ? '### 5.5 定期清理：什么能删、什么别动' : '### 5.5 Cleanup: what to delete, what to keep')
  out.push('')
  out.push(L ? '**可以清理**' : '**Safe to clean**')
  out.push('')
  ops.cleanupSafe.forEach(c => out.push(`- ${c}`))
  out.push('')
  out.push(L ? '**不要动**' : '**Do NOT touch**')
  out.push('')
  ops.cleanupKeep.forEach(c => out.push(`- ${c}`))
  out.push('')

  // 5.6 配置与凭据
  out.push(L ? '### 5.6 配置与凭据' : '### 5.6 Configuration & credentials')
  out.push('')
  out.push(ops.configPriority)
  out.push('')
  ops.credentialNote.forEach(c => out.push(`- ${c}`))
  out.push('')

  // ============ 6. FAQ ============
  out.push('---')
  out.push('')
  out.push(L ? '## 6. 常见问题' : '## 6. FAQ')
  out.push('')
  common.faq.forEach(f => {
    out.push(`**${f.q}**`)
    out.push('')
    out.push(f.a)
    out.push('')
  })

  // ---------- 尾注 ----------
  out.push('---')
  out.push('')
  out.push(L
    ? '*更多细节参见项目文档：docs/manual/（01 总览与术语表 · 04 任务系统 · 11 功能页手册 · 13 运维手册 · 14 外部系统与数据流）。*'
    : '*See the project docs for more: docs/manual/ (01 overview & glossary · 04 task system · 11 feature guide · 13 operations · 14 integrations & data flows).*')
  out.push('')

  return out.join('\n')
}

/** 页面菜单名（i18n 字典不进打包，这里内置 zh/en 菜单名映射，与 App.tsx menuItems/i18n.tsx 保持一致） */
function localeName(locale: Locale, key: string): string {
  const ZH: Record<string, string> = {
    sync: '任务管理', email_reports: '任务报告文件', alarm: '实时告警看板', ttwo: 'TT&WO 看板',
    eflow_qa: 'eFlow 知识库', nur: 'NUR 看板', ms_sla: 'MS Operation KPI 看板', cxoDashboard: 'CXO 经营看板',
    mwUmeTopology: 'MW 微波拓扑', mwRealTime: 'MW 微波实时', gis: 'GIS地图', realtime_alarm: '实时告警地图',
    alarmManagement: '告警管理看板', packet_loss: '丢包看板', battery: '电池看板', ip_trace: 'IP 链路探测',
    incident_overview: '事件总览', warehouse: '仓库看板', overview: '数据总览', tables: '表浏览器',
    upload: '数据上传', archive: '分析归档', dashboard: '分析仪表盘', settings: '系统设置', portalLogin: '门户一键登录',
  }
  const EN: Record<string, string> = {
    sync: 'Task Manager', email_reports: 'Task Report Files', alarm: 'Alarm Dashboard', ttwo: 'TT&WO Dashboard',
    eflow_qa: 'eFlow Knowledge Base', nur: 'NUR Dashboard', ms_sla: 'MS Operation KPI Dashboard', cxoDashboard: 'CXO Dashboard',
    mwUmeTopology: 'MW UME Topology', mwRealTime: 'MW Realtime', gis: 'GIS Map', realtime_alarm: 'Realtime Alarm Map',
    alarmManagement: 'Alarm Management', packet_loss: 'Packet Loss', battery: 'Battery Dashboard', ip_trace: 'IP Trace',
    incident_overview: 'Incident Overview', warehouse: 'Warehouse', overview: 'Overview', tables: 'Table Browser',
    upload: 'Data Upload', archive: 'Archive', dashboard: 'Dashboard', settings: 'Settings', portalLogin: 'Portal Login',
  }
  return locale === 'zh' ? (ZH[key] ?? key) : (EN[key] ?? key)
}
