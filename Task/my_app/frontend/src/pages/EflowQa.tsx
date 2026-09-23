import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Checkbox,
  Collapse,
  Drawer,
  Empty,
  Input,
  message,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Tree,
  Typography,
  Upload,
  Button,
  Tabs,
  Spin as SpinIcon,
} from 'antd'
import {
  BookOutlined,
  ClearOutlined,
  DownloadOutlined,
  FileExcelOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FolderOutlined,
  MenuOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import * as XLSX from 'xlsx'

import api from '../api'
import { useI18n } from '../i18n'
import TtPostmortemPanel from '../components/TtPostmortemPanel'
import { useIsMobile, useTheme } from '../theme'
import { exportAoaReport, exportReport } from '../utils/excelReport'

const { Text, Title } = Typography

interface DocItem {
  path: string
  title: string
  status: string
  source: string
  size: number
  mtime: number
}

interface TreeItem {
  key: string
  title: React.ReactNode
  children?: TreeItem[]
  isLeaf?: boolean
}

interface SearchHit {
  path: string
  title: string
  status: string
  match_count: number
  term_lines: Record<string, number[]>
  snippets: { line: number; text: string }[]
}

/* ---------- TT 快速分析请求：瞬时故障自动重试 ----------
 * 背景（2026-09-15 修复「首次点分析失败、再点一次就好」）：
 * TT 快速分析一进来就并发打三个接口。若首次请求赶上后端刚重启的几秒空窗 /
 * 网关抖动 / 连接被重置，axios 直接 reject，页面只留一句「分析失败」，
 * 用户再点一次（此时后端已恢复）就成功 —— 表现为「首次失败、重试成功」。
 * 这类失败在服务端不留任何访问日志，属传输层瞬时故障，重试即可自愈。
 * 只对「网络错误 / 超时 / 5xx」重试；4xx（单号非法、未登录等）是确定性错误，
 * 重试无意义，直接抛出。延迟取 0.8s + 2s + 4s：累计覆盖约 7 秒，
 * 足够跨过「后端重启空窗」（看门狗检测 ≤3s + 进程启动 3~4.5s）。 */
const TT_RETRY_DELAYS = [800, 2000, 4000]

function isRetriable(err: any): boolean {
  const status = err?.response?.status
  if (!status) return true            // 无响应 = 网络错误/超时/连接被重置
  return status === 408 || status === 429 || status >= 500
}

/** 带瞬时故障重试的 GET（TT 快速分析专用）。 */
async function ttGet(url: string, params: Record<string, any>) {
  for (let i = 0; ; i++) {
    try {
      return await api.get(url, { params })
    } catch (e) {
      if (i >= TT_RETRY_DELAYS.length || !isRetriable(e)) throw e
      await new Promise(r => setTimeout(r, TT_RETRY_DELAYS[i]))
    }
  }
}

/** 失败原因摘要（展示在「分析失败」旁，便于用户反馈 / 排查）。 */
function ttFailReason(err: any, t: (k: string) => string): string {
  const status = err?.response?.status
  if (status) return `HTTP ${status}`
  if (err?.code === 'ECONNABORTED') return t('qa.tt.timeout')
  return t('qa.tt.netError')
}

/** 状态 → Tag 颜色（与 CONTRIBUTING.md 的状态语义对应） */
function statusColor(status: string): string | undefined {
  if (status.includes('已过时')) return 'red'
  if (status.includes('部分待验证')) return 'orange'
  if (status.includes('已验证')) return 'green'
  if (status.includes('待验证')) return 'orange'
  return 'default'
}

/** 状态 → 当前语言文案（文档内容是中文，UI 层做状态值映射） */
function statusLabel(status: string, t: (k: string) => string): string {
  if (status.includes('已过时')) return t('qa.tag.outdated')
  if (status.includes('部分待验证')) return t('qa.tag.partiallyVerified')
  if (status.includes('已验证')) return t('qa.tag.verified')
  if (status.includes('待验证')) return t('qa.tag.pending')
  return status
}

/**
 * 双语文档解析：知识库约定英文版 = 同名 `.en.md`（README.md → README.en.md）。
 * - lang=en：同名文档优先英文版，未翻译的回退中文原文，同一文档只出一条；
 * - 其它：只保留中文原文（隐藏 .en.md）。
 * 适用于 tree items / search hits 等一切带 path 的列表。
 */
function resolveLang<T extends { path: string }>(rows: T[], lang: string): T[] {
  const byBase = new Map<string, { en?: T; zh?: T }>()
  for (const it of rows) {
    const isEn = it.path.toLowerCase().endsWith('.en.md')
    const base = isEn ? it.path.slice(0, -6) + '.md' : it.path
    const slot = byBase.get(base) || {}
    if (isEn) slot.en = it
    else slot.zh = it
    byBase.set(base, slot)
  }
  const out: T[] = []
  for (const key of [...byBase.keys()].sort()) {
    const slot = byBase.get(key)!
    const picked = lang === 'en' ? (slot.en || slot.zh) : slot.zh
    if (picked) out.push(picked)
  }
  return out
}

/** 路径显示：英文环境下去掉中文段（纯展示，真实请求仍用原路径） */
function displayPath(path: string, lang: string): string {
  if (lang !== 'en') return path
  return path
    .replace(/[\u4e00-\u9fff]+/g, '')
    .replace(/[_\-\s]{2,}/g, '_')
    .replace(/\/[_\-\s]+/g, '/')
    .replace(/^[_\-\s]+|[_\-\s]+$/g, '') || path
}

const TT_SECTION_EN: Record<string, string> = {
  '站点': 'Site',
  '工单': 'Ticket',
  '告警': 'Alarm',
  '时间': 'Time',
  '根因': 'Root Cause',
  '派单': 'Assignment',
  '制式掉站': 'Network Outage',
  '状态': 'Status',
  '其他': 'Other',
}

function ttSectionLabel(section: string, lang: string): string {
  if (lang !== 'en') return section
  const normalized = String(section || '').trim()
  return TT_SECTION_EN[normalized] || normalized
}

/** 检索词高亮：把 text 中出现的词包上 mark */
function Highlight({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>
  // 构造正则：所有词 join，转义特殊字符
  const escaped = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(${escaped.join('|')})`, 'gi')
  const parts = text.split(re)
  return (
    <>
      {parts.map((p, i) =>
        re.test(p) && terms.some(t => p.toLowerCase() === t.toLowerCase()) ? (
          <mark key={i} style={{ background: 'rgba(19,194,194,0.25)', color: 'inherit', padding: '0 2px', borderRadius: 2 }}>{p}</mark>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  )
}

/** 站点/小区信息、告警概览等「键-值」列表 */
function KvRows({ rows, isDark, isMobile, labelWidth = 180 }: {
  rows: [string, any][]
  isDark: boolean
  isMobile: boolean
  labelWidth?: number
}) {
  return (
    <div style={{ fontSize: 13, lineHeight: 1.9 }}>
      {rows.map(([k, v]) => (
        <div key={k} style={isMobile
          ? { display: 'flex', flexDirection: 'column', padding: '2px 0' }
          : { display: 'flex', gap: 10 }}>
          <Text type="secondary" style={isMobile
            ? { fontFamily: 'monospace', fontSize: 11 }
            : { width: labelWidth, flexShrink: 0, fontFamily: 'monospace', fontSize: 12 }}>{k}</Text>
          <span style={{ wordBreak: 'break-all' }}>
            {v === '' || v === null || v === undefined ? '—' : String(v)}
          </span>
        </div>
      ))}
    </div>
  )
}

function severityColor(sev: string): string | undefined {
  const s = String(sev || '').toLowerCase()
  if (s.includes('critical')) return 'red'
  if (s.includes('major')) return 'orange'
  if (s.includes('minor')) return 'gold'
  if (s.includes('warning')) return 'blue'
  return 'default'
}

/** 工单级别 P1~P4 → Tag 颜色（TT 批量核查用） */
function levelColor(sev: string): string | undefined {
  const s = String(sev || '').trim().toUpperCase()
  if (s === 'P1') return 'red'
  if (s === 'P2') return 'orange'
  if (s === 'P3') return 'gold'
  if (s === 'P4') return 'blue'
  return undefined
}

/** 批量核查判定 → Tag 颜色 */
function verdictColor(status: string): string {
  if (status === 'ok') return 'green'
  if (status === 'adjust') return 'red'
  return 'default'
}

/* ---------- AI 分析结论：规则命中证据（本地规则引擎，确定性） ----------
 * 数据来自 GET /api/eflow-qa/tt-ai 的 ai.rules
 * （后端 backend/services/eflow_rules/tt_rule_evidence.py）。
 * 判定与每天 04:20 的 eflow_tt_rules_check 定时任务、Email Reports →
 * eFlow TT Rules Check 页签的矫正表**同源**（内部复用 eflow_rules_matcher），
 * 所以这里的「命中规则 / 目标级别 / 匹配详情」与那两处逐字一致。
 * 作用：在 AI 文本之外给出可核对的事实，并指明规则来自哪个文件、谁维护、
 * 工单当前谁在处理 —— 避免结论只说级别却说不清依据。 */
function TtRuleEvidence({ ev, t, isDark, isMobile, border, onOpenRule }: {
  ev: any
  t: (k: string, params?: Record<string, string | number>) => string
  isDark: boolean
  isMobile: boolean
  border: string
  onOpenRule?: () => void
}) {
  if (!ev) return null
  const rf = ev.rules_file || {}
  const xlsx = rf.xlsx || {}
  const m = ev.matched || null
  const h = ev.handler || {}
  const verdictKey = ev.level_status === 'adjust' ? 'qa.tt.verdictAdjust'
    : ev.level_status === 'ok' ? 'qa.tt.verdictOk' : 'qa.tt.verdictUnknown'

  // 规则元信息（规则表原始列）：优先级 / 目标级别 / 工单类型 / 触发步骤 / 维护人
  const ruleKv: [string, any][] = []
  if (m) {
    ruleKv.push([t('qa.tt.ruleId'), m.rule_id || '—'])
    ruleKv.push([t('qa.tt.rulePriority'), m.priority || '—'])
    if (m.ticket_type) ruleKv.push([t('qa.tt.ruleTicketType'), m.ticket_type])
    if (m.trigger_step) ruleKv.push([t('qa.tt.ruleTriggerStep'), m.trigger_step])
    if (m.creator || m.updater) {
      ruleKv.push([t('qa.tt.ruleOwner'),
        `${t('qa.tt.ruleCreatedBy')} ${m.creator || '—'} / ${t('qa.tt.ruleUpdatedBy')} ${m.updater || '—'}`
        + (m.updated_at ? ` · ${m.updated_at}` : '')])
    }
    if (m.status) ruleKv.push([t('qa.tt.ruleStatus'), m.status])
  }
  const handlerText = [
    h.last_processer || '',
    h.last_processer_group || '',
    h.last_process_time || '',
    h.vendor || '',
    h.organization_id || '',
  ].filter(Boolean).join(' · ')

  // 推单规则（TT Push Order Rule，触发步骤 FOAccept）：决定「是否自动推 WO、推给谁、谁自动处理」。
  // 字段名沿用 eFlow 规则页签的英文写法（Rule Name / Push Order Path / *Auto Operator …）。
  const pr = ev.push_rules || {}
  const prHit: any[] = pr.matched || []
  const prFile = pr.rules_file || {}
  const pushKv = (r: any): [string, any][] => [
    [t('qa.tt.fRuleName'), `${r.rule_name || '—'}${r.rule_id ? ` (ID ${r.rule_id})` : ''}`],
    [t('qa.tt.fRuleType'), r.rule_type_text || r.rule_type || '—'],
    [t('qa.tt.fRuleStep'), r.trigger_step_text || r.trigger_step || '—'],
    [t('qa.tt.fRulePath'), r.push_path || '—'],
    [t('qa.tt.fRuleAutoOp'), r.auto_operator || '—'],
    [t('qa.tt.fRuleTarget'), r.target_handler || '—'],
  ]

  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px dashed ${border}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
        <Text strong style={{ fontSize: 13 }}>{t('qa.tt.ruleEvidence')}</Text>
        {ev.available
          ? <Tag color={verdictColor(ev.level_status)}>{t(verdictKey)}</Tag>
          : <Tag>{t('qa.tt.ruleUnavailable')}</Tag>}
        {!!ev.current_severity && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('qa.tt.ruleCurrent')}<b>{ev.current_severity}</b>
            {' → '}{t('qa.tt.ruleTarget')}<b>{ev.expected_severity || '—'}</b>
          </Text>
        )}
      </div>

      {m ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
            <Tag color="purple">{t('qa.tt.ruleHit')}</Tag>
            {!!m.severity && <Tag color={levelColor(m.severity)}>{m.severity}</Tag>}
            <Text strong>{m.rule_name || '—'}</Text>
            {!!m.rule_id && <Text type="secondary" style={{ fontSize: 12 }}>ID {m.rule_id}</Text>}
            {onOpenRule && (
              <a onClick={onOpenRule} style={{ fontSize: 12 }}>
                <BookOutlined style={{ marginRight: 4 }} />{t('qa.tt.openRule')}
              </a>
            )}
          </div>
          {!!m.match_details && (
            <div style={{ fontSize: 12, marginBottom: 4, wordBreak: 'break-all' }}>
              <Text type="secondary">{t('qa.tt.ruleMatch')}</Text>
              <span style={{ fontFamily: 'monospace' }}>{m.match_details}</span>
            </div>
          )}
          <KvRows rows={ruleKv} isDark={isDark} isMobile={isMobile} labelWidth={150} />
          {!!m.condition && (
            <Collapse
              ghost
              size="small"
              items={[{
                key: 'cond',
                label: <Text type="secondary" style={{ fontSize: 12 }}>{t('qa.tt.ruleCondition')}</Text>,
                children: (
                  <div style={{ fontFamily: 'monospace', fontSize: 12, lineHeight: 1.8, wordBreak: 'break-all' }}>
                    {m.condition}
                  </div>
                ),
              }]}
            />
          )}
        </>
      ) : (
        !!ev.error && <Alert type="info" showIcon style={{ marginTop: 4 }} message={ev.error} />
      )}

      {(xlsx.name || rf.report?.name) && (
        <div style={{ marginTop: 6, fontSize: 12, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <Text type="secondary">{t('qa.tt.ruleFile')}</Text>
          {!!xlsx.name && (
            <a href={xlsx.download_url} download={xlsx.name} title={xlsx.rel_path}>
              <FileExcelOutlined style={{ marginRight: 4, color: '#1d6f42' }} />{xlsx.name}
            </a>
          )}
          {!!rf.report?.name && (
            <a href={rf.report.download_url} download={rf.report.name} title={rf.report.rel_path}>
              <FileTextOutlined style={{ marginRight: 4 }} />{rf.report.name}
            </a>
          )}
          <Text type="secondary">
            {rf.rules_count != null ? t('qa.tt.ruleCount', { n: rf.rules_count }) : ''}
            {rf.rules_updated_at ? ` · ${t('qa.tt.ruleUpdatedAt')} ${rf.rules_updated_at}` : ''}
            {rf.collected_at ? ` · ${t('qa.tt.ruleCollectedAt')} ${rf.collected_at}` : ''}
          </Text>
        </div>
      )}

      {!!handlerText && (
        <div style={{ marginTop: 4, fontSize: 12 }}>
          <Text type="secondary">{t('qa.tt.handler')}</Text>
          <span>{handlerText}</span>
        </div>
      )}

      {/* 推单规则：谁推单、推给谁、谁自动处理（与级别规则相互独立） */}
      {(pr.available || pr.error) && (
        <div style={{ marginTop: 10, paddingTop: 8, borderTop: `1px dashed ${border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            <Text strong style={{ fontSize: 13 }}>{t('qa.tt.pushRule')}</Text>
            {prHit.length
              ? <Tag color="blue">{t('qa.tt.pushRuleHit', { n: prHit.length })}</Tag>
              : <Tag>{t('qa.tt.pushRuleNone')}</Tag>}
          </div>
          {prHit.slice(0, 3).map((r: any, i: number) => (
            <div key={`${r.rule_id}-${i}`} style={{ marginBottom: 6 }}>
              <KvRows rows={pushKv(r)} isDark={isDark} isMobile={isMobile} labelWidth={150} />
              {!!r.match_details && (
                <div style={{ fontSize: 12, wordBreak: 'break-all' }}>
                  <Text type="secondary">{t('qa.tt.ruleMatch')}</Text>
                  <span style={{ fontFamily: 'monospace' }}>{r.match_details}</span>
                </div>
              )}
            </div>
          ))}
          <div style={{ marginTop: 2, fontSize: 12, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            {!!prFile.name && (
              <a href={prFile.download_url} download={prFile.name} title={prFile.rel_path}>
                <FileExcelOutlined style={{ marginRight: 4, color: '#1d6f42' }} />{prFile.name}
              </a>
            )}
            <Text type="secondary">
              {t('qa.tt.pushRuleHint')}
              {prFile.rules_count != null ? ` · ${t('qa.tt.ruleCount', { n: prFile.rules_count })}` : ''}
              {prFile.mtime_text ? ` · ${t('qa.tt.ruleUpdatedAt')} ${prFile.mtime_text}` : ''}
            </Text>
          </div>
          {!!pr.other_steps_count && (
            <div style={{ marginTop: 2, fontSize: 12 }}>
              <Text type="secondary">{t('qa.tt.pushRuleOtherSteps', { n: pr.other_steps_count })}</Text>
            </div>
          )}
          {!!pr.undecidable && (
            <div style={{ marginTop: 2, fontSize: 12 }}>
              <Text type="warning">{t('qa.tt.pushRuleUndecidable', { n: pr.undecidable })}</Text>
            </div>
          )}
          {!pr.available && !!pr.error && (
            <Alert type="info" showIcon style={{ marginTop: 4 }} message={pr.error} />
          )}
        </div>
      )}
    </div>
  )
}

/* ---------- TT 批量核查：清单解析 ----------
 * 前端只做「预览用」的粗筛（含数字、长度 >= 5、去重），
 * 权威清洗在后端 tt_batch_severity.normalize_tt_list，两边规则保持一致。 */
const TT_TOKEN_SPLIT = /[\s,;，；\t|]+/

/** 从任意单元格值里取出可能的 TT 单号（同一格含多个时也拆开） */
function pickTtTokens(value: unknown): string[] {
  if (value === null || value === undefined) return []
  return String(value)
    .split(TT_TOKEN_SPLIT)
    .map(s => s.trim().toUpperCase())
    .filter(s => s.length >= 5 && /^[A-Z0-9_-]+$/.test(s) && /\d/.test(s))
}

/** 解析上传的清单文件（xlsx/xls/csv/txt）→ 去重后的 TT 单号数组 */
async function parseTtListFile(file: File): Promise<string[]> {
  const name = (file.name || '').toLowerCase()
  const out: string[] = []
  if (name.endsWith('.txt') || name.endsWith('.csv')) {
    const text = await file.text()
    for (const tok of pickTtTokens(text)) out.push(tok)
  } else {
    const buf = await file.arrayBuffer()
    const wb = XLSX.read(buf, { type: 'array' })
    for (const sheetName of wb.SheetNames) {
      const grid: unknown[][] = XLSX.utils.sheet_to_json(wb.Sheets[sheetName], {
        header: 1, blankrows: false, raw: false, defval: '',
      })
      for (const row of grid) for (const cell of row) for (const tok of pickTtTokens(cell)) out.push(tok)
    }
  }
  // 保序去重
  return [...new Set(out)]
}

function dedupeTokens(tokens: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of tokens) {
    for (const tok of pickTtTokens(raw)) {
      if (seen.has(tok)) continue
      seen.add(tok)
      out.push(tok)
    }
  }
  return out
}

function HistoryTable({ h, t, isDark, isMobile }: { h: any; t: (k: string) => string; isDark: boolean; isMobile: boolean }) {
  const items = h?.items || []
  const columns = [
    { title: t('qa.ume.col.raised'), dataIndex: 'raised_time', width: 155, fixed: 'left' as const },
    { title: t('qa.ume.col.code'), dataIndex: 'alarmcode', width: 100 },
    { title: t('qa.ume.col.name'), dataIndex: 'name' },
    { title: t('qa.ume.col.severity'), dataIndex: 'severity', width: 90,
      render: (v: string) => <Tag color={severityColor(v)} style={{ margin: 0 }}>{v || '—'}</Tag> },
    { title: t('qa.ume.col.object'), dataIndex: 'object' },
    { title: t('qa.ume.col.state'), dataIndex: 'clear_state', width: 100 },
    { title: t('qa.ume.col.duration'), dataIndex: 'duration', width: 110 },
  ]
  return (
    <>
      <div style={{ marginBottom: 6, fontSize: 12, color: isDark ? '#aebbd4' : '#64748b' }}>
        {h?.position} · {t('qa.ume.totalRows')} {h?.total ?? 0}
        {items.length < (h?.total ?? 0) ? `（${t('qa.ume.totalRows')} ${items.length}）` : ''}
      </div>
      {items.length === 0
        ? <Empty description={t('qa.ume.noHistory').replace('{days}', String(h?.days ?? 30))} style={{ margin: '12px 0' }} />
        : <Table
            size="small"
            columns={columns}
            dataSource={items}
            rowKey={(r: any, i?: number) => `${i}-${r?.alarmkey || r?.raised_time || ''}`}
            pagination={{ pageSize: 10, size: 'small', showSizeChanger: false }}
            scroll={{ x: isMobile ? 900 : undefined }}
          />}
    </>
  )
}

/** RAN UME 告警分析结果视图：告警概览 / 站点小区信息 / 处理建议 / 历史告警 */
/** 关系链全量下级告警建议：每个下级告警一个页签（同名用 AID 尾号区分） */
function RelAlarmTabs({ t, isDark, isMobile, border, rel }: {
  t: (k: string) => string
  isDark: boolean
  isMobile: boolean
  border: string
  rel: any
}) {
  if (!rel || !rel.items?.length) return null
  const okItems = rel.items.filter((it: any) => it?.ume?.ok)
  const innerCard = { border, borderRadius: 8, padding: '10px 12px', margin: 0, background: isDark ? 'rgba(82,196,26,0.05)' : '#f7fdf6' }
  // 同名告警（如 Cell interruption ×N）用 AID 尾号区分页签
  const nameCount: Record<string, number> = {}
  okItems.forEach((it: any) => {
    const k = it.codename || `AID ${it.aid}`
    nameCount[k] = (nameCount[k] || 0) + 1
  })
  const items = okItems.map((it: any, i: number) => {
    const u = it.ume
    const base = it.codename || `AID ${it.aid}`
    const label = nameCount[base] > 1 ? `${base} #${String(it.aid).slice(-4)}` : base
    return {
      key: `${it.aid}-${i}`,
      label,
      children: (
        <div style={innerCard}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 4 }}>
            {u?.alarm?.alarmcode != null && <Tag>{u.alarm.alarmcode}</Tag>}
            {u?.alarm?.title_en ? <Tag color="geekblue">{u.alarm.title_en}</Tag> : (!!it.codename && <Tag color="geekblue">{it.codename}</Tag>)}
            {!!it.site_name && <Text type="secondary" style={{ fontSize: 12 }}>{it.site_name}</Text>}
          </div>
          <div style={{ marginBottom: 2 }}>
            <Text type="secondary" style={{ fontSize: 12, fontFamily: 'monospace', wordBreak: 'break-all' }}>
              AID: {it.aid}
            </Text>
          </div>
          {!!u?.suggestion?.default && (
            <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0', fontFamily: 'inherit', fontSize: 13, lineHeight: 1.7 }}>{u.suggestion.default}</pre>
          )}
          {!!u?.suggestion?.customer && (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>customermaintenancename</Text>
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0', fontFamily: 'inherit', fontSize: 13, lineHeight: 1.7 }}>{u.suggestion.customer}</pre>
            </>
          )}
        </div>
      ),
    }
  })
  return (
    <div style={{ marginTop: 10, borderTop: `1px dashed ${isDark ? '#2f3747' : '#dbe4ee'}`, paddingTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <ThunderboltOutlined style={{ color: '#52c41a' }} />
        <Text strong style={{ fontSize: 13 }}>{t('qa.tt.umeRelTitle')}</Text>
        <Tag color="green">{t('qa.tt.umeRelSource')}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>{t('qa.tt.umeRelTips')}</Text>
      </div>
      {/* 完整链路下钻：根 → 压缩 → 原始 UME（与 eFlow 手动下钻一致） */}
      {(() => {
        const chain = rel.chain || []
        if (!chain.length) return null
        const byDepth: Record<number, any[]> = {}
        chain.forEach((n: any) => {
          const d = n.depth ?? 0
          ;(byDepth[d] = byDepth[d] || []).push(n)
        })
        return (
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('qa.tt.umeRelPath')}</Text>
              <Text type="secondary" style={{ fontSize: 11, color: isDark ? '#aebbd4' : '#64748b' }}>{t('qa.tt.umeRelTips2')}</Text>
            </div>
            {Object.keys(byDepth).sort((a, b) => +a - +b).map(ds => {
              const d = +ds
              const nodes = byDepth[d]
              const agg: Record<string, { codename: string; count: number; orig: boolean; rel: number }> = {}
              nodes.forEach((n: any) => {
                const cn = n.codename || `id ${n.id}`
                const key = `${n.is_ume_orig ? 'o' : 'c'}|${cn}`
                const g = agg[key] || (agg[key] = { codename: cn, count: 0, orig: !!n.is_ume_orig, rel: n.relationflag })
                g.count++
              })
              const comps = Object.values(agg).filter(g => !g.orig)
              const oris = Object.values(agg).filter(g => g.orig)
              return (
                <div key={ds} style={{ display: 'flex', gap: 6, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 3 }}>
                  <Text type="secondary" style={{ fontSize: 12, width: isMobile ? undefined : 64, flexShrink: 0, paddingTop: 1 }}>
                    {d === 0 ? t('qa.tt.umeRelRoot') : '↳'}
                  </Text>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                    {!!comps.length && (
                      <Text type="secondary" style={{ fontSize: 11, color: isDark ? '#aebbd4' : '#64748b', marginRight: 2 }}>
                        {d > 0 ? t('qa.tt.umeRelCompress') : ''}
                      </Text>
                    )}
                    {comps.map((g, i) => (
                      <Tag key={`c${i}`} color="cyan" style={{ fontSize: 11, margin: 0 }}>{g.codename}{g.count > 1 ? ` ×${g.count}` : ''}</Tag>
                    ))}
                    {!!oris.length && (
                      <Text type="secondary" style={{ fontSize: 11, color: isDark ? '#aebbd4' : '#64748b', marginLeft: 6, marginRight: 2 }}>
                        {t('qa.tt.umeRelOrig')}
                      </Text>
                    )}
                    {oris.map((g, i) => (
                      <Tag key={`o${i}`} color="green" style={{ fontSize: 11, margin: 0 }}>{g.codename}{g.count > 1 ? ` ×${g.count}` : ''}</Tag>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )
      })()}
      {okItems.length === 0 ? (
        <Alert type="info" showIcon message={t('qa.tt.umeRelEmpty')} />
      ) : (
        <Tabs size="small" defaultActiveKey={items[0]?.key} items={items} />
      )}
    </div>
  )
}

function UmeAlarmView({ t, isDark, isMobile, border, umeKey, loading, error, data, onBack, onRetry }: {
  t: (k: string) => string
  isDark: boolean
  isMobile: boolean
  border: string
  umeKey: string
  loading: boolean
  error: string
  data: any
  onBack: () => void
  onRetry: () => void
}) {
  const header = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
      <ThunderboltOutlined style={{ color: '#13c2c2' }} />
      <Text strong style={{ fontSize: 15 }}>{t('qa.ume.label')}</Text>
      <Text type="secondary" style={{ fontSize: 12, wordBreak: 'break-all' }}>{umeKey}</Text>
      <Button size="small" style={{ marginLeft: 'auto' }} onClick={onBack}>{t('qa.ume.back')}</Button>
    </div>
  )

  if (loading) {
    return (
      <div>
        {header}
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
          <div style={{ marginTop: 12, color: isDark ? '#aebbd4' : '#64748b' }}>{t('qa.ume.analyzing')}</div>
        </div>
      </div>
    )
  }
  if (error) {
    return (
      <div>
        {header}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Text type="danger">{error}</Text>
          <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>{t('qa.tt.retry')}</Button>
        </div>
      </div>
    )
  }
  if (!data) return null
  if (!data.ok) {
    return (
      <div>
        {header}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Alert type="warning" showIcon message={data.error || t('qa.ume.failed')} />
          <Button size="small" icon={<ReloadOutlined />} onClick={onRetry}>{t('qa.tt.retry')}</Button>
        </div>
      </div>
    )
  }

  const cardStyle = { border, borderRadius: 8, padding: '10px 14px', marginBottom: 10, background: isDark ? 'rgba(0, 217, 255,0.04)' : '#fafcfe' }
  const a = data.alarm || {}
  const sc = data.site_cell || {}
  const local = sc.local
  const sug = data.suggestion

  const overviewRows: [string, any][] = [
    ['Alarm Title (EN)', a.title_en],
    ['Alarm Title (ZH)', a.title_zh],
    ['Alarm Code', a.alarmcode],
    ['Reason Code', a.reasoncode],
    ['Alarm Type', a.alarm_type],
    ['Severity', a.severity],
    ['Raised Time (GMT)', a.raised_time],
    ['Duration', a.duration],
    ['Clear State', a.clear_state],
    ['Ack State', a.ack_state],
    ['Resource Type', a.restype_name],
    ['Alarm ID', a.alarm_id],
    ['Source', a.source],
  ]

  const siteRows: [string, any][] = [
    ['Site Name', sc.site_name],
    ['Site ID', sc.site_id],
    ['Alarm Object', sc.object_name],
    ['Object Type', sc.object_type],
    ['Object ID', sc.object_id],
    ['Network Type', sc.network_type],
    ['NE Name', sc.ne_name],
    ['Related NE', sc.related_ne_name],
    ['NE IP', sc.ne_ip],
    ['MOC', sc.moc],
    ['DN', sc.dn],
    ['Position', sc.position],
    ['Location', sc.location],
  ]
  if (local) {
    siteRows.push(['Region / County', [local.region, local.county].filter(Boolean).join(' / ')])
    siteRows.push(['Tech', (local.techs || []).join(' / ')])
    siteRows.push(['Category', local.category])
  }

  return (
    <div>
      {header}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        {a.severity && <Tag color={severityColor(a.severity)}>{a.severity}</Tag>}
        {a.alarmcode && <Tag>{a.alarmcode}</Tag>}
        {sc.site_name && <Tag color="cyan">{sc.site_name}</Tag>}
        {sc.object_name && <Tag color="geekblue">{sc.object_name}</Tag>}
        {data.elapsed_sec != null && <Text type="secondary" style={{ fontSize: 12, alignSelf: 'center' }}>{data.elapsed_sec}s</Text>}
      </div>

      {/* 告警概览 */}
      <div style={cardStyle}>
        <Text strong>{t('qa.ume.overview')}</Text>
        <div style={{ marginTop: 6 }}>
          <KvRows rows={overviewRows} isDark={isDark} isMobile={isMobile} />
        </div>
      </div>

      {/* 站点 / 小区信息 */}
      <div style={cardStyle}>
        <Text strong>{t('qa.ume.siteCell')}</Text>
        <div style={{ marginTop: 6 }}>
          <KvRows rows={siteRows} isDark={isDark} isMobile={isMobile} />
        </div>
        {!!(local && (local.cells || []).length) && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('qa.ume.local')} · {t('qa.ume.cells')}（{(local.cells || []).length}）
            </Text>
            <div style={{ marginTop: 4 }}>
              {(local.cells || []).slice(0, 60).map((c: string) => (
                <Tag key={c} style={{ margin: '2px 4px 2px 0', fontSize: 11 }}>{c}</Tag>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 处理建议 */}
      <div style={{ ...cardStyle, background: isDark ? 'rgba(250,173,20,0.08)' : 'rgba(250,173,20,0.08)' }}>
        <Text strong>{t('qa.ume.suggestion')}</Text>
        {sug?.default || sug?.customer ? (
          <div style={{ marginTop: 6 }}>
            {!!sug.customer && (
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>customermaintenancename</Text>
                <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0',
                  fontFamily: 'inherit', fontSize: 13, lineHeight: 1.75 }}>{sug.customer}</pre>
              </div>
            )}
            {!!sug.default && (
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>defaultmaintenancename</Text>
                <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0',
                  fontFamily: 'inherit', fontSize: 13, lineHeight: 1.75 }}>{sug.default}</pre>
              </div>
            )}
          </div>
        ) : (
          <div style={{ marginTop: 6 }}>
            <Alert type="info" showIcon message={data.suggestion_error || t('qa.ume.noSuggestion')} />
          </div>
        )}
      </div>

      {/* 关系链全量下级告警建议（推荐） */}
      <RelAlarmTabs t={t} isDark={isDark} isMobile={isMobile} border={cardStyle.border} rel={data.related_ume} />

      {/* 历史告警 */}
      {data.history_cell && (
        <div style={cardStyle}>
          <Text strong>{t('qa.ume.historyCell')}</Text>
          <div style={{ marginTop: 6 }}>
            <HistoryTable h={data.history_cell} t={t} isDark={isDark} isMobile={isMobile} />
          </div>
        </div>
      )}
      {data.history && (
        <div style={cardStyle}>
          <Text strong>{t('qa.ume.history')}</Text>
          <div style={{ marginTop: 6 }}>
            <HistoryTable h={data.history} t={t} isDark={isDark} isMobile={isMobile} />
          </div>
        </div>
      )}
      {!data.history && !data.history_cell && data.history_error && (
        <div style={cardStyle}>
          <Text strong>{t('qa.ume.history')}</Text>
          <Alert type="info" showIcon style={{ marginTop: 6 }} message={data.history_error} />
        </div>
      )}
    </div>
  )
}

export default function EflowQa() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const isMobile = useIsMobile()

  const [rawItems, setRawItems] = useState<DocItem[] | null>(null)
  // 按当前语言解析：en 优先 .en.md（无则回退中文原文），zh 只留中文原文
  const items = useMemo(() => (rawItems ? resolveLang(rawItems, locale) : null), [rawItems, locale])
  const [rootDir, setRootDir] = useState('')
  const [treeError, setTreeError] = useState('')
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [doc, setDoc] = useState<{ title: string; content: string; front_matter: Record<string, string>; path: string } | null>(null)
  const [docLoading, setDocLoading] = useState(false)
  const [docError, setDocError] = useState('')

  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [searchTerms, setSearchTerms] = useState<string[]>([])
  const [searched, setSearched] = useState(false)

  // ===== TT 快速分析 =====
  const [ttNo, setTtNo] = useState('')
  const [ttView, setTtView] = useState(false)
  const [ttLoading, setTtLoading] = useState(false)
  const [ttReport, setTtReport] = useState<any>(null)
  const [ttError, setTtError] = useState('')
  // 当前分析的请求序号（见 runTt）：旧请求的迟到结果直接丢弃
  const ttSeqRef = useRef(0)
  const [ttAi, setTtAi] = useState<any>(null)
  const [ttAiLoading, setTtAiLoading] = useState(false)
  const [ttAlarm, setTtAlarm] = useState<any>(null)
  const [ttAlarmLoading, setTtAlarmLoading] = useState(false)
  const [ttAlarmLookup, setTtAlarmLookup] = useState<any>(null)

  // ===== TT → AID → RAN UME 处理建议 =====
  const [ttAid, setTtAid] = useState('')
  const [ttUme, setTtUme] = useState<any>(null)
  const [ttUmeLoading, setTtUmeLoading] = useState(false)
  const [ttUmeFailed, setTtUmeFailed] = useState(false)

  // ===== TT 批量级别核查 =====
  const [ttBatchView, setTtBatchView] = useState(false)
  const [batchText, setBatchText] = useState('')
  const [batchFile, setBatchFile] = useState('')
  const [batchLoading, setBatchLoading] = useState(false)
  const [batchData, setBatchData] = useState<any>(null)
  const [batchError, setBatchError] = useState('')
  const [batchOnlyAdjust, setBatchOnlyAdjust] = useState(false)

  // ===== RAN UME 告警分析 =====
  const [umeKey, setUmeKey] = useState('')
  const [umeView, setUmeView] = useState(false)
  const [umeLoading, setUmeLoading] = useState(false)
  const [umeData, setUmeData] = useState<any>(null)
  const [umeError, setUmeError] = useState('')

  // ===== TT 复盘报告（程序化版，新增于 2026-09-23）=====
  const [postmortemOpen, setPostmortemOpen] = useState(false)
  // 与 TT 快速分析同款：请求序号，旧请求的迟到结果不回写
  const umeSeqRef = useRef(0)

  const runUme = useCallback((key: string) => {
    const clean = key.trim()
    if (!clean) return
    const seq = ++umeSeqRef.current
    const alive = () => seq === umeSeqRef.current
    setUmeKey(clean)
    setUmeView(true)
    setTtView(false)
    setTtBatchView(false)
    setUmeLoading(true)
    setUmeError('')
    setUmeData(null)
    // 同 ttGet：瞬时 502/网络抖动自动重试，避免「首次查询失败、再点一次就好」
    ttGet('/eflow-qa/ume-alarm', { alarm_id: clean, days: 30, limit: 50 })
      .then(res => { if (alive()) setUmeData(res.data) })
      .catch((e) => { if (alive()) setUmeError(`${t('qa.ume.failed')}（${ttFailReason(e, t)}）`) })
      .finally(() => { if (alive()) setUmeLoading(false) })
  }, [t])

  // 移动端：目录树抽屉
  const [treeOpen, setTreeOpen] = useState(false)

  // ===== TT 批量级别核查：提交 / 上传 / 导出 =====
  // 粘贴文本里解析出的单号（与后端 normalize_tt_list 同规则，仅用于预览计数）
  const batchTokens = useMemo(() => dedupeTokens([batchText]), [batchText])

  const runTtBatch = useCallback((tokens?: string[]) => {
    const list = dedupeTokens(tokens && tokens.length ? tokens : [batchText])
    if (!list.length) {
      setBatchError(t('qa.ttBatch.emptyInput'))
      setTtBatchView(true)
      return
    }
    setTtBatchView(true)
    setTtView(false)
    setUmeView(false)
    setBatchLoading(true)
    setBatchError('')
    setBatchOnlyAdjust(false)
    api.post('/eflow-qa/tt-batch-check', { tts: list })
      .then(res => setBatchData(res.data))
      .catch((e: any) => {
        setBatchData(null)
        setBatchError(e?.response?.data?.detail || t('qa.ttBatch.failed'))
      })
      .finally(() => setBatchLoading(false))
  }, [batchText, t])

  const onBatchFile = useCallback(async (file: File) => {
    setTtBatchView(true)
    setTtView(false)
    setUmeView(false)
    try {
      const tokens = await parseTtListFile(file)
      setBatchFile(file.name || '')
      if (!tokens.length) {
        setBatchError(t('qa.ttBatch.noTtInFile'))
        return false
      }
      setBatchText(tokens.join('\n'))
      runTtBatch(tokens)
    } catch {
      setBatchError(t('qa.ttBatch.fileFailed'))
    }
    return false // 阻止 antd 自动上传（纯本地解析）
  }, [runTtBatch, t])

  const verdictText = useCallback((r: any) => {
    if (!r?.found) return t('qa.ttBatch.judge.miss')
    return t(`qa.ttBatch.judge.${r.level_status}`)
  }, [t])

  /**
   * 下载「填写模板」—— 用户填好单号后直接把同一个文件上传回来即可核查。
   *
   * 两个必须守住的点：
   * 1. 模板里的说明文字**不能出现真实样式的单号**（如 TT202609140082），否则用户原样上传时
   *    会被前端解析器当成待查单号，凭空多出一行；所以说明里只写「前缀 TT + 12 位数字」。
   * 2. 若页面上已有解析好的单号（粘贴/上次上传的），预填进模板，方便「导出 → 改 → 回传」。
   */
  const downloadTtBatchTemplate = useCallback(async () => {
    try {
      await exportAoaReport({
        filename: 'tt_batch_check_template.xlsx',
        sheetName: t('qa.ttBatch.templateSheet'),
        title: t('qa.ttBatch.templateTitle'),
        subtitle: t('qa.ttBatch.templateSubtitle'),
        header: [t('qa.ttBatch.templateColTt'), t('qa.ttBatch.templateColNote')],
        rows: batchTokens.map(tok => [tok, '']),
        columnWidths: [26, 46],
        tabColor: '#2E7D32',
      })
    } catch {
      message.error(t('qa.ttBatch.failed'))
    }
  }, [batchTokens, t])

  const exportTtBatch = useCallback(async () => {
    const rows: any[] = batchData?.rows || []
    if (!rows.length) {
      message.warning(t('qa.ttBatch.exportEmpty'))
      return
    }
    const header = [
      t('qa.ttBatch.col.tt'), t('qa.ttBatch.col.judge'),
      t('qa.ttBatch.col.current'), t('qa.ttBatch.col.expected'),
      t('qa.ttBatch.col.site'), t('qa.ttBatch.col.alarm'),
      t('qa.ttBatch.col.vip'), 'site_type', 'down_site_count',
      'domain', t('qa.ttBatch.col.status'), t('qa.ttBatch.col.project'),
      t('qa.ttBatch.col.rule'), t('qa.ttBatch.col.detail'),
      'alarm_occur_time', 'created_time', 'last_modified_time',
    ]
    const toRow = (r: any) => [
      r.tt_no, verdictText(r), r.ticket_severity, r.expected_severity,
      r.site_name, r.alarm_code, r.vip_site, r.site_type, r.down_site_count,
      r.domain, r.status, r.project_name,
      r.matched_rule_id ? `${r.matched_rule_id}${r.matched_rule_name ? ' ' + r.matched_rule_name : ''}` : '',
      r.match_details,
      r.alarm_occur_time, r.created_time, r.last_modified_time,
    ]
    const adjust = rows.filter(r => r.level_status === 'adjust')
    // 导出「当前表格看到的内容」：勾了「只看需调整」就只导该 sheet，
    // 否则导「全部结果」，并在有需调整行时额外附一个「需调整」sheet。
    const specs: any[] = batchOnlyAdjust
      ? [{
          name: t('qa.ttBatch.sheetAdjust'),
          title: `${t('qa.ttBatch.title')} — ${t('qa.ttBatch.stat.adjust')}`,
          header,
          rows: adjust.map(toRow),
          numericCols: [8],
          tabColor: '#BF8F00',
        }]
      : [{
          name: t('qa.ttBatch.sheetAll'),
          title: t('qa.ttBatch.title'),
          header,
          rows: rows.map(toRow),
          numericCols: [8],
          tabColor: '#2F5496',
        }]
    if (!batchOnlyAdjust && adjust.length) {
      specs.push({
        name: t('qa.ttBatch.sheetAdjust'),
        title: `${t('qa.ttBatch.title')} — ${t('qa.ttBatch.stat.adjust')}`,
        header,
        rows: adjust.map(toRow),
        numericCols: [8],
        tabColor: '#BF8F00',
      })
    }
    const d = new Date()
    const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}_${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}`
    try {
      await exportReport(specs, `tt_batch_severity_${stamp}.xlsx`)
    } catch {
      message.error(t('qa.ttBatch.failed'))
    }
  }, [batchData, batchOnlyAdjust, t, verdictText])

  const runTt = useCallback((no: string) => {
    const clean = no.trim().toUpperCase()
    if (!clean) return
    // 请求序号：连点两次 / 换单号时，旧请求的失败结果不再回写，避免「旧失败盖住新成功」
    const seq = ++ttSeqRef.current
    const alive = () => seq === ttSeqRef.current
    setTtNo(clean)
    setTtView(true)
    setTtBatchView(false)
    setTtLoading(true)
    setTtError('')
    setTtAi(null)
    setTtAiLoading(true)
    setTtAlarm(null)
    setTtAlarmLookup(null)
    setTtAlarmLoading(false)
    // RAN UME 处理建议（后端按 TT → 告警 AID → UME suggestions 链路），独立加载不阻塞
    setTtAid('')
    setTtUme(null)
    setTtUmeFailed(false)
    setTtUmeLoading(true)
    // 基础报告（本地 sqlite，快）先到先显；告警与 AI 各自独立加载
    // 三个请求都走 ttGet：瞬时故障自动重试，消除「首次点分析失败、再点一次就好」
    ttGet('/eflow-qa/inspect-tt', { tt: clean }).then(res => {
      if (!alive()) return
      const rep = res.data.report
      setTtReport(rep)
      if (rep?.found && rep.alarm?.found) {
        setTtAlarm(rep.alarm)
        setTtAlarmLookup({ mode: 'local', source: rep.alarm.source })
      } else if (rep?.found) {
        // 本地告警库未命中 → 单独查 eFlow 活接口（较慢，不阻塞其它块）
        setTtAlarmLoading(true)
        ttGet('/eflow-qa/tt-alarm', { tt: clean }).then(r2 => {
          if (!alive()) return
          setTtAlarm(r2.data.alarm)
          setTtAlarmLookup(r2.data.alarm_lookup)
        }).catch(() => { if (alive()) setTtAlarmLookup({ mode: 'error', error: t('qa.tt.alarmQueryFailed') }) })
          .finally(() => { if (alive()) setTtAlarmLoading(false) })
      }
    }).catch((e) => {
      if (!alive()) return
      setTtError(`${t('qa.tt.failed')}（${ttFailReason(e, t)}）`)
    }).finally(() => { if (alive()) setTtLoading(false) })
    // AI 结论并行请求（Open WebUI「TT单分析」技能，约 10s）
    ttGet('/eflow-qa/tt-ai', { tt: clean, lang: locale }).then(res => {
      if (!alive()) return
      setTtAi(res.data.ai)
      const rep = res.data.report
      // tt-ai 内部同样会回填 eFlow 兜底结果，告警块未到则顺带补上
      if (rep?.alarm?.found) setTtAlarm((prev: any) => prev || rep.alarm)
    }).catch(() => { /* AI 失败不阻塞工单信息展示 */ }).finally(() => { if (alive()) setTtAiLoading(false) })
    // RAN UME 处理建议并行请求（TT → 告警 AID → UME，不阻塞其它块）
    ttGet('/eflow-qa/tt-ume-suggestion', { tt: clean }).then(res => {
      if (!alive()) return
      setTtUme(res.data)
      if (res.data?.aid) setTtAid(res.data.aid)
    }).catch(() => { if (alive()) setTtUmeFailed(true) }).finally(() => { if (alive()) setTtUmeLoading(false) })
  }, [t, locale])

  // ===== 文档树 =====
  useEffect(() => {
    api.get('/eflow-qa/tree', { params: { lang: locale } }).then(res => {
      setRawItems(res.data.items || [])
      setRootDir(res.data.root || '')
    }).catch(() => setTreeError('load failed'))
  }, [locale])

  // 路径 → antd 树
  const treeData: TreeItem[] = useMemo(() => {
    const root: TreeItem = { key: '__root__', title: t('qa.openInFolder'), children: [] }
    // 文件夹显示名：英文环境下去掉目录名里的中文段（00_操作篇_Operations → 00_Operations）
    // key 仍用完整原始段，真实路径不受影响
    const dirLabel = (seg: string) => {
      if (locale !== 'en') return seg
      const stripped = seg
        .replace(/[\u4e00-\u9fff]+/g, '')
        .replace(/[_\-\s]{2,}/g, '_')
        .replace(/^[_\-\s]+|[_\-\s]+$/g, '')
      return stripped || seg
    }
    const findOrCreate = (node: TreeItem, seg: string, keyPath: string): TreeItem => {
      if (!node.children) node.children = []
      let child = node.children.find(c => c.key === keyPath)
      if (!child) {
        child = { key: keyPath, title: <span><FolderOutlined style={{ marginRight: 4, color: '#13c2c2' }} />{dirLabel(seg)}</span>, children: [] }
        node.children.push(child)
      }
      return child
    }
    for (const it of items || []) {
      const segs = it.path.split('/')
      let cur = root
      for (let i = 0; i < segs.length - 1; i++) {
        cur = findOrCreate(cur, segs[i], segs.slice(0, i + 1).join('/') + '/')
      }
      cur.children!.push({
        key: it.path,
        isLeaf: true,
        title: (
          <span>
            <FileTextOutlined style={{ marginRight: 4, opacity: 0.65 }} />
            {it.title}
            {it.status && (
              <Tag color={statusColor(it.status)} style={{ marginLeft: 6, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                {statusLabel(it.status, t)}
              </Tag>
            )}
          </span>
        ),
      })
    }
    // 目录内文档排前、目录排后
    const sortRec = (n: TreeItem) => {
      if (!n.children) return
      n.children.sort((a, b) => (!!a.isLeaf === !!b.isLeaf) ? a.key.localeCompare(b.key) : (a.isLeaf ? -1 : 1))
      n.children.forEach(sortRec)
    }
    sortRec(root)
    return root.children || []
  }, [items, t, locale])

  // ===== 读取文档 =====
  const loadDoc = useCallback((path: string) => {
    setTtView(false)
    setTtBatchView(false)
    setSelectedPath(path)
    setDocLoading(true)
    setDocError('')
    api.get('/eflow-qa/doc', { params: { path } }).then(res => {
      setDoc(res.data)
    }).catch(() => setDocError(t('qa.loadFailed'))).finally(() => setDocLoading(false))
  }, [t])

  // ===== 检索 =====
  const doSearch = useCallback((q: string) => {
    const terms = q.trim().split(/\s+/).filter(Boolean)
    if (!terms.length) return
    setTtView(false)
    setTtBatchView(false)
    setSearching(true)
    setSearched(true)
    api.get('/eflow-qa/search', { params: { q, lang: locale } }).then(res => {
      setHits(resolveLang(res.data.hits || [], locale))
      setSearchTerms(res.data.terms || terms)
    }).catch(() => setHits([])).finally(() => setSearching(false))
  }, [locale])

  const panelBg = isDark ? '#0f2744' : '#ffffff'
  const border = isDark ? '1px solid rgba(0, 217, 255,0.2)' : '1px solid #d9e6f2'

  const mdStyle = `
    .eflowqa-md { line-height: 1.75; font-size: 0.9375rem; }
    .eflowqa-md h1, .eflowqa-md h2, .eflowqa-md h3, .eflowqa-md h4 { margin: 1.2em 0 0.5em; color: ${isDark ? '#e2e8f0' : '#1e293b'}; }
    .eflowqa-md h1 { font-size: 1.35em; border-bottom: 1px solid ${isDark ? 'rgba(0, 217, 255,0.2)' : '#d9e6f2'}; padding-bottom: 0.3em; }
    .eflowqa-md h2 { font-size: 1.2em; }
    .eflowqa-md h3 { font-size: 1.05em; }
    .eflowqa-md p { margin: 0.6em 0; }
    .eflowqa-md table { border-collapse: collapse; margin: 0.8em 0; width: 100%; font-size: 0.875em; }
    .eflowqa-md th, .eflowqa-md td { border: 1px solid ${isDark ? 'rgba(148,163,184,0.35)' : '#cbd5e1'}; padding: 6px 10px; text-align: left; }
    .eflowqa-md th { background: ${isDark ? 'rgba(19,194,194,0.12)' : '#f0f5fa'}; }
    .eflowqa-md code { background: ${isDark ? 'rgba(0, 217, 255,0.1)' : 'rgba(13,148,136,0.08)'}; padding: 1px 5px; border-radius: 4px; font-size: 0.875em; }
    .eflowqa-md pre { background: ${isDark ? '#02050c' : '#0f172a'}; color: ${isDark ? '#dbeafe' : '#e2e8f0'}; padding: 12px 14px; border-radius: 8px; overflow-x: auto; }
    .eflowqa-md pre code { background: transparent; padding: 0; color: inherit; }
    .eflowqa-md blockquote { border-left: 3px solid #13c2c2; margin: 0.8em 0; padding: 0.2em 1em; background: ${isDark ? 'rgba(19,194,194,0.06)' : 'rgba(19,194,194,0.05)'}; }
    .eflowqa-md ul, .eflowqa-md ol { padding-left: 1.6em; margin: 0.5em 0; }
    .eflowqa-md hr { border: none; border-top: 1px solid ${isDark ? 'rgba(148,163,184,0.3)' : '#d9e6f2'}; margin: 1.2em 0; }
    .eflowqa-md a { color: #13c2c2; }
    @media (max-width: 767px) {
      .eflowqa-md { font-size: 0.9375rem; line-height: 1.8; }
      .eflowqa-md h1 { font-size: 1.2em; }
      .eflowqa-md h2 { font-size: 1.1em; }
      /* 宽表格在窄屏改为可横向滚动，避免撑破视口 */
      .eflowqa-md table { display: block; width: 100%; overflow-x: auto; white-space: nowrap; -webkit-overflow-scrolling: touch; }
      .eflowqa-md pre { font-size: 0.8rem; padding: 10px 12px; }
      .eflowqa-md ul, .eflowqa-md ol { padding-left: 1.3em; }
    }
  `

  // ===== 检索 + TT（桌面左栏顶部）=====
  const searchBlock = (
    <>
      <div id="knowledge-search" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <SearchOutlined style={{ color: '#1677ff' }} />
        <Text strong style={{ fontSize: 13 }}>{t('qa.search')}</Text>
      </div>
      <Input.Search
        placeholder={t('qa.searchPlaceholder')}
        enterButton={t('qa.search')}
        value={query}
        onChange={e => setQuery(e.target.value)}
        onSearch={doSearch}
        allowClear
      />
      <div style={{ borderTop: isDark ? '1px solid rgba(0, 217, 255,0.15)' : '1px solid #e5eef5', margin: '2px 0' }} />
      <div id="tt-quick-analysis" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ThunderboltOutlined style={{ color: '#faad14' }} />
        <Text strong style={{ fontSize: 13 }}>{t('qa.tt.label')}</Text>
      </div>
      <Input.Search
        placeholder={t('qa.tt.placeholder')}
        enterButton={t('qa.tt.button')}
        value={ttNo}
        onChange={e => setTtNo(e.target.value)}
        onSearch={runTt}
        allowClear
      />
      <div style={{ borderTop: isDark ? '1px solid rgba(0, 217, 255,0.15)' : '1px solid #e5eef5', margin: '2px 0' }} />
      <div id="tt-batch-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ThunderboltOutlined style={{ color: '#722ed1' }} />
        <Text strong style={{ fontSize: 13 }}>{t('qa.ttBatch.label')}</Text>
      </div>
      <Upload accept=".xlsx,.xls,.csv,.txt" showUploadList={false} beforeUpload={onBatchFile}>
        <Button block icon={<UploadOutlined />}>{t('qa.ttBatch.upload')}</Button>
      </Upload>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Button
          type="link"
          size="small"
          style={{ padding: 0, height: 'auto', textAlign: 'left' }}
          onClick={() => { setTtBatchView(true); setTtView(false); setUmeView(false) }}
        >
          {t('qa.ttBatch.pasteLink')}
        </Button>
        <Tooltip title={t('qa.ttBatch.templateTip')}>
          <Button
            type="link"
            size="small"
            style={{ padding: 0, height: 'auto', textAlign: 'left' }}
            onClick={downloadTtBatchTemplate}
          >
            {t('qa.ttBatch.templateLink')}
          </Button>
        </Tooltip>
      </div>

      <div style={{ borderTop: isDark ? '1px solid rgba(0, 217, 255,0.15)' : '1px solid #e5eef5', margin: '2px 0' }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <FileSearchOutlined style={{ color: '#eb2f96' }} />
        <Text strong style={{ fontSize: 13 }}>TT 复盘报告生成</Text>
      </div>
      <Button
        block
        icon={<FileSearchOutlined />}
        onClick={() => setPostmortemOpen(true)}
      >
        生成完整复盘报告（程序化版）
      </Button>
      <TtPostmortemPanel open={postmortemOpen} onClose={() => setPostmortemOpen(false)} />
      <div id="ran-ume-alarm-analysis" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ThunderboltOutlined style={{ color: '#13c2c2' }} />
        <Text strong style={{ fontSize: 13 }}>{t('qa.ume.label')}</Text>
      </div>
      <Input.Search
        placeholder={t('qa.ume.placeholder')}
        enterButton={t('qa.ume.button')}
        value={umeKey}
        onChange={e => setUmeKey(e.target.value)}
        onSearch={runUme}
        allowClear
      />
    </>
  )

  // ===== 文档树（桌面左栏 / 移动端抽屉共用）=====
  const treeBlock = (
    <>
      {treeError && <Text type="danger">{t('qa.loadFailed')}</Text>}
      {!items && !treeError && <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>}
      {items && (
        <>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {items.length}{t('qa.docCount')}{rootDir ? ` · ${rootDir}` : ''}
          </Text>
          <Tree
            treeData={treeData}
            defaultExpandAll
            showLine={false}
            selectedKeys={selectedPath ? [selectedPath] : []}
            onSelect={keys => {
              const k = keys[0] as string | undefined
              if (k && !k.endsWith('/')) {
                loadDoc(k)
                setTreeOpen(false)
              }
            }}
            blockNode
          />
        </>
      )}
    </>
  )

  return (
    // height:'100%' 而不是 calc(100vh - Header - margin*2 - padding*2)：
    // 外壳 embed/bare 模式（?page= 直链 / ?embed=1）会把 Header 不渲染、Content 留白置 0，
    // 再减一遍「外壳留白」底部就会多出 108px 空白（同 LegacyToolFrame 的坑）。
    <div style={isMobile
      ? { display: 'flex', flexDirection: 'column', gap: 10, flexShrink: 0 }
      : { display: 'flex', gap: 12, height: '100%', minHeight: 480 }
    }>
      <style>{mdStyle}</style>

      {/* ===== 目录树：桌面为左侧栏，移动端收进抽屉 ===== */}
      {!isMobile && (
        <div style={{
          width: 320,
          flexShrink: 0,
          background: panelBg,
          border,
          borderRadius: 10,
          padding: 12,
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}>
          {searchBlock}
          {treeBlock}
        </div>
      )}

      {/* ===== 移动端：顶部工具条（检索 / 目录 / TT）===== */}
      {isMobile && (
        <div style={{
          flexShrink: 0,
          background: panelBg,
          border,
          borderRadius: 10,
          padding: 10,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}>
          <Input.Search
            placeholder={t('qa.searchPlaceholder')}
            enterButton={<SearchOutlined />}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onSearch={v => { doSearch(v); setTreeOpen(false) }}
            allowClear
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Button icon={<MenuOutlined />} onClick={() => setTreeOpen(true)} style={{ flexShrink: 0 }}>
              {t('qa.catalog')}
            </Button>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Input.Search
                placeholder={t('qa.tt.placeholder')}
                enterButton={<ThunderboltOutlined />}
                value={ttNo}
                onChange={e => setTtNo(e.target.value)}
                onSearch={runTt}
                allowClear
              />
            </div>
          </div>
          <Input.Search
            placeholder={t('qa.ume.placeholder')}
            enterButton={<ThunderboltOutlined style={{ color: '#13c2c2' }} />}
            value={umeKey}
            onChange={e => setUmeKey(e.target.value)}
            onSearch={runUme}
            allowClear
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <Upload accept=".xlsx,.xls,.csv,.txt" showUploadList={false} beforeUpload={onBatchFile} style={{ flex: 1 }}>
              <Button icon={<UploadOutlined />} block>{t('qa.ttBatch.upload')}</Button>
            </Upload>
            <Button
              icon={<ThunderboltOutlined style={{ color: '#722ed1' }} />}
              onClick={() => { setTtBatchView(true); setTtView(false); setUmeView(false) }}
            >
              {t('qa.ttBatch.paste')}
            </Button>
          </div>
        </div>
      )}

      {/* ===== 右侧：内容 / 检索结果 ===== */}
      <div style={{
        flex: 1,
        minWidth: 0,
        background: panelBg,
        border,
        borderRadius: 10,
        padding: isMobile ? '12px 14px' : '16px 20px',
        // 移动端交给外层容器整体滚动，避免嵌套滚动条
        overflow: isMobile ? 'visible' : 'auto',
      }}>
        {/* ===== TT 快速分析视图 ===== */}
        {ttView && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              <ThunderboltOutlined style={{ color: '#faad14' }} />
              <Text strong style={{ fontSize: 16 }}>{ttNo}</Text>
              {ttReport?.found && <Tag color="cyan">{ttReport.site_name}</Tag>}
              {ttReport?.remote && <Tag color="green">{t('qa.tt.liveSource')}</Tag>}
              <Button size="small" style={{ marginLeft: 'auto' }} onClick={() => setTtView(false)}>{t('qa.tt.back')}</Button>
            </div>
            {ttLoading && (
              <div style={{ textAlign: 'center', padding: 60 }}>
                <Spin size="large" />
                <div style={{ marginTop: 12, color: isDark ? '#aebbd4' : '#64748b' }}>{t('qa.tt.analyzing')}</div>
              </div>
            )}
            {!ttLoading && ttError && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <Text type="danger">{ttError}</Text>
                <Button size="small" icon={<ReloadOutlined />} onClick={() => runTt(ttNo)}>
                  {t('qa.tt.retry')}
                </Button>
              </div>
            )}
            {!ttLoading && !ttError && ttReport && !ttReport.found && (
              <div>
                <Alert type="warning" showIcon message={`${t('qa.tt.notFound')}${ttReport.error ? `：${ttReport.error}` : ''}`} />
                {!!ttReport.suggestions?.length && (
                  <div style={{ marginTop: 12 }}>
                    <Text type="secondary">{t('qa.tt.suggestions')}</Text>
                    <div style={{ marginTop: 4 }}>
                      {ttReport.suggestions.map((s: string) => (
                        <Tag key={s} style={{ cursor: 'pointer', margin: '4px 6px 4px 0' }} onClick={() => runTt(s)}>{s}</Tag>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {!ttLoading && !ttError && ttReport?.found && (() => {
              const ruleDoc = items?.find(i => i.path.includes('掉站工单派单归属判定规则'))
              const cardStyle = { border, borderRadius: 8, padding: '10px 14px', marginBottom: 10, background: isDark ? 'rgba(0, 217, 255,0.04)' : '#fafcfe' }
              return (
                <div>
                  {/* AI 分析结论（TT单分析技能，页面顶部） */}
                  {ttAiLoading && (
                    <div style={{ ...cardStyle, background: isDark ? 'rgba(24,144,255,0.06)' : '#f0f7ff' }}>
                      <RobotOutlined style={{ color: '#1677ff', marginRight: 8 }} />
                      <Text strong>{t('qa.tt.aiConclusion')}</Text>
                      <div style={{ marginTop: 6, color: isDark ? '#aebbd4' : '#64748b', fontSize: 13 }}>{t('qa.tt.aiAnalyzing')}</div>
                    </div>
                  )}
                  {!ttAiLoading && ttAi && !ttAi.ok && (
                    <div style={cardStyle}>
                      <Alert type="error" showIcon message={`${t('qa.tt.aiFailed')}${ttAi.error}`} />
                      {/* 模型全档失败 → 后端用本地规则引擎程序化出的结论（无模型参与） */}
                      {ttAi.fallback_conclusion ? (
                        <>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', margin: '10px 0 6px' }}>
                            <Tag color="orange">{t('qa.tt.fallbackTag')}</Tag>
                            <Text type="secondary" style={{ fontSize: 12 }}>{t('qa.tt.fallbackHint')}</Text>
                          </div>
                          <div className="eflowqa-md" style={{ fontSize: 13, lineHeight: 1.7 }}>
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{ttAi.fallback_conclusion}</ReactMarkdown>
                          </div>
                        </>
                      ) : null}
                      {/* 规则命中证据（本地规则引擎，确定性；与 eFlow TT Rules Check 页签同源） */}
                      <TtRuleEvidence ev={ttAi.rules} t={t} isDark={isDark} isMobile={isMobile}
                        border={border} onOpenRule={ruleDoc ? () => loadDoc(ruleDoc.path) : undefined} />
                      {ttAi.elapsed_total_sec != null && (
                        <div style={{ marginTop: 8, fontSize: 12, color: isDark ? '#aebbd4' : '#64748b' }}>
                          {t('qa.tt.aiElapsed')}: {ttAi.elapsed_total_sec}s
                        </div>
                      )}
                    </div>
                  )}
                  {!ttAiLoading && ttAi?.ok && (
                    <div style={{ ...cardStyle, background: isDark ? 'rgba(24,144,255,0.06)' : '#f0f7ff' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                        <RobotOutlined style={{ color: '#1677ff' }} />
                        <Text strong>{t('qa.tt.aiConclusion')}</Text>
                      </div>
                      <div className="eflowqa-md" style={{ fontSize: 13, lineHeight: 1.7 }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{ttAi.conclusion}</ReactMarkdown>
                      </div>
                      {/* 规则命中证据（本地规则引擎，确定性；与 eFlow TT Rules Check 页签同源） */}
                      <TtRuleEvidence ev={ttAi.rules} t={t} isDark={isDark} isMobile={isMobile}
                        border={border} onOpenRule={ruleDoc ? () => loadDoc(ruleDoc.path) : undefined} />
                      <div style={{ marginTop: 8, fontSize: 12, color: isDark ? '#aebbd4' : '#64748b' }}>
                        {ttAi.skill_title && <Tag color="blue" style={{ marginRight: 6 }}>{ttAi.skill_title}</Tag>}
                        {ttAi.model && <Tag style={{ marginRight: 6 }}>{ttAi.model}</Tag>}
                        {ttAi.alarm_source && <Tag color="cyan" style={{ marginRight: 6 }}>{t('qa.tt.alarmSource')}: {ttAi.alarm_source}</Tag>}
                        {ttAi.elapsed_total_sec != null && <span>{t('qa.tt.aiElapsed')}: {ttAi.elapsed_total_sec}s</span>}
                      </div>
                    </div>
                  )}

                  {/* 告警信息（本地告警库命中即显；未命中则 eFlow 活查，期间只在本卡内 loading） */}
                  {ttAlarmLoading && (
                    <div style={{ ...cardStyle, background: isDark ? 'rgba(0, 217, 255,0.06)' : '#f4fbfa' }}>
                      <Spin size="small" style={{ marginRight: 8 }} />
                      <Text strong>{t('qa.tt.alarmCard')}</Text>
                      <div style={{ marginTop: 6, color: isDark ? '#aebbd4' : '#64748b', fontSize: 13 }}>
                        {t('qa.tt.alarmEflowLoading')}
                      </div>
                    </div>
                  )}
                  {!ttAlarmLoading && ttAlarm?.found && (
                    <div style={cardStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                        <Text strong>{t('qa.tt.alarmCard')}</Text>
                        <Tag color={ttAlarm.source?.startsWith('eflow') ? 'gold' : 'green'}>{t('qa.tt.alarmSource')}: {ttAlarm.source}</Tag>
                        {ttAlarmLookup?.elapsed_sec ? <Text type="secondary" style={{ fontSize: 12 }}>{ttAlarmLookup.elapsed_sec}s</Text> : null}
                      </div>
                      <div style={{ fontSize: 13, lineHeight: 1.9 }}>
                        {ttAlarm.items.map((it: any) => (
                          <div key={it.key} style={isMobile
                            ? { display: 'flex', flexDirection: 'column', padding: '2px 0' }
                            : { display: 'flex', gap: 10 }}>
                            <Text type="secondary" style={isMobile
                              ? { fontFamily: 'monospace', fontSize: 11 }
                              : { width: 180, flexShrink: 0, fontFamily: 'monospace', fontSize: 12 }}>{it.key}</Text>
                            <span style={{ wordBreak: 'break-all' }}>{it.value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {!ttAlarmLoading && !ttAlarm?.found && ttAlarmLookup && (
                    <div style={cardStyle}>
                      <Text strong>{t('qa.tt.alarmCard')}</Text>
                      <Alert type="info" showIcon style={{ marginTop: 6 }}
                        message={t('qa.tt.alarmNotFound')}
                        description={ttAlarmLookup.error || ttAlarmLookup.mode} />
                    </div>
                  )}

                  {/* RAN UME 处理建议：有链路时整块横向页签（含主建议）；无链路才直出长文本 */}
                  {(() => {
                    const ume = ttUme?.ume
                    const fullKey = ume?.ok ? (ume?.alarm?.alarm_id || ttAid) : ttAid
                    const hasRel = !ttUmeLoading && ttUme?.related_ume?.items?.length
                    return (
                      <div style={{ ...cardStyle, background: isDark ? 'rgba(19,194,194,0.08)' : '#f4fbfa' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                          <ThunderboltOutlined style={{ color: '#13c2c2' }} />
                          <Text strong>{t('qa.tt.umeCard')}</Text>
                          {!!ttAid && <Tag color="cyan" style={{ fontFamily: 'monospace' }}>AID: {ttAid}</Tag>}
                          {ume?.ok && ume?.strategy === 'site_time' && <Tag color="purple">{t('qa.tt.umeMatched')}</Tag>}
                          {ume?.ok && fullKey && !ttUmeLoading && (
                            <Button size="small" type="link" style={{ marginLeft: 'auto', padding: 0 }}
                              onClick={() => runUme(fullKey)}>{t('qa.tt.umeFull')}</Button>
                          )}
                        </div>
                        {ttUmeLoading && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: isDark ? '#aebbd4' : '#64748b', fontSize: 13 }}>
                            <Spin size="small" />{t('qa.tt.umeLoading')}
                          </div>
                        )}
                        {!ttUmeLoading && (ttUmeFailed || (ttUme && !ume?.ok)) && !hasRel && (
                          <Alert type="info" showIcon style={{ marginTop: 4 }}
                            message={ttUme?.error || ume?.error || t('qa.tt.umeFailed')} />
                        )}
                        {hasRel ? (
                          <RelAlarmTabs t={t} isDark={isDark} isMobile={isMobile} border={cardStyle.border} rel={ttUme?.related_ume} />
                        ) : (
                          <>
                            {!ttUmeLoading && ume?.ok && ume?.alarm && (
                              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6, alignItems: 'center' }}>
                                {ume.alarm.title_en && <Tag color="geekblue">{ume.alarm.title_en}</Tag>}
                                {ume.alarm.alarmcode != null && <Tag>{ume.alarm.alarmcode}</Tag>}
                                {ume.alarm.severity && <Tag color={severityColor(ume.alarm.severity)}>{ume.alarm.severity}</Tag>}
                                {ume.alarm.raised_time && <Text type="secondary" style={{ fontSize: 12 }}>{ume.alarm.raised_time}</Text>}
                                {ume.elapsed_sec != null && <Text type="secondary" style={{ fontSize: 12 }}>{ume.elapsed_sec}s</Text>}
                              </div>
                            )}
                            {!ttUmeLoading && ume?.ok && (
                              ume?.suggestion?.default || ume?.suggestion?.customer ? (
                                <div>
                                  {!!ume.suggestion.customer && (
                                    <div style={{ marginBottom: 8 }}>
                                      <Text type="secondary" style={{ fontSize: 12 }}>customermaintenancename</Text>
                                      <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0', fontFamily: 'inherit', fontSize: 13, lineHeight: 1.6 }}>{ume.suggestion.customer}</pre>
                                    </div>
                                  )}
                                  {!!ume.suggestion.default && (
                                    <div>
                                      <Text type="secondary" style={{ fontSize: 12 }}>defaultmaintenancename</Text>
                                      <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0', fontFamily: 'inherit', fontSize: 13, lineHeight: 1.6 }}>{ume.suggestion.default}</pre>
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <Alert type="info" showIcon message={ume?.suggestion_error || t('qa.ume.noSuggestion')} />
                              )
                            )}
                          </>
                        )}
                      </div>
                    )
                  })()}

                  {/* 结论要点 */}
                  <div style={{ ...cardStyle, background: isDark ? 'rgba(250,173,20,0.08)' : 'rgba(250,173,20,0.08)' }}>
                    <Text strong>{t('qa.tt.conclusion')}</Text>
                    <ol style={{ margin: '8px 0 0', paddingLeft: isMobile ? 18 : 20, lineHeight: 1.9, fontSize: isMobile ? 13 : undefined }}>
                      <li>{t('qa.tt.rootCause')} <b>{ttReport.root_cause}</b> / {ttReport.sub_root_cause} —— {t('qa.tt.conc1')}</li>
                      <li>{t('qa.tt.assigned')}：<b>{ttReport.assigned_group}</b></li>
                      <li>{t('qa.tt.timing')}：{ttReport.timing.lag_text}</li>
                    </ol>
                  </div>

                  {/* 时间差 */}
                  <div style={cardStyle}>
                    <Text strong>{t('qa.tt.timing')}</Text>
                    <div style={{ marginTop: 6, fontSize: 13, lineHeight: 1.8 }}>
                      <div>alarm_occur_time：{ttReport.timing.alarm_occur_time}</div>
                      <div>created_time：{ttReport.timing.created_time}</div>
                      <div>{ttReport.timing.lag_text}</div>
                    </div>
                    {ttReport.timing.delayed_over_1h && (
                      <Alert type="warning" showIcon style={{ marginTop: 8 }} message={t('qa.tt.delayWarn')} />
                    )}
                  </div>

                  {/* 工单字段（折叠） */}
                  <Collapse
                    ghost
                    items={ttReport.fields.map((sec: any) => ({
                      key: sec.section,
                      label: <Text strong>{ttSectionLabel(sec.section, locale)} <Text type="secondary" style={{ fontSize: 12 }}>({sec.items.length})</Text></Text>,
                      children: (
                        <div style={{ fontSize: 13, lineHeight: 2 }}>
                          {sec.items.map((it: any) => (
                            <div key={it.key} style={isMobile
                              ? { display: 'flex', flexDirection: 'column', gap: 0, padding: '4px 0', borderBottom: isDark ? '1px dashed rgba(148,163,184,0.2)' : '1px dashed #e5eef5' }
                              : { display: 'flex', gap: 10 }
                            }>
                              <Text type="secondary" style={isMobile
                                ? { fontFamily: 'monospace', fontSize: 11 }
                                : { width: 220, flexShrink: 0, fontFamily: 'monospace', fontSize: 12 }
                              }>{it.key}</Text>
                              <span style={{ wordBreak: 'break-all' }}>{it.value}</span>
                            </div>
                          ))}
                        </div>
                      ),
                    }))}
                    defaultActiveKey={[]}
                  />

                  {ruleDoc && (
                    <div style={{ marginTop: 8 }}>
                      <a onClick={() => loadDoc(ruleDoc.path)}>
                        <BookOutlined style={{ marginRight: 6 }} />{t('qa.tt.openRule')}
                      </a>
                    </div>
                  )}
                </div>
              )
            })()}
          </div>
        )}

        {/* ===== TT 批量级别核查视图 ===== */}
        {ttBatchView && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
              <ThunderboltOutlined style={{ color: '#722ed1' }} />
              <Text strong style={{ fontSize: 16 }}>{t('qa.ttBatch.title')}</Text>
              {!!batchData?.rules?.count && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('qa.ttBatch.rules', { n: batchData.rules.count, time: batchData.rules.updated_at || '—' })}
                </Text>
              )}
              <Space style={{ marginLeft: 'auto' }} wrap>
                <Button size="small" loading={batchLoading} disabled={!batchTokens.length} onClick={() => runTtBatch()}>
                  {t('qa.ttBatch.rerun')}
                </Button>
                <Button size="small" icon={<ClearOutlined />} onClick={() => {
                  setBatchText(''); setBatchFile(''); setBatchData(null); setBatchError(''); setBatchOnlyAdjust(false)
                }}>
                  {t('qa.ttBatch.clear')}
                </Button>
                <Button size="small" onClick={() => setTtBatchView(false)}>{t('qa.ttBatch.back')}</Button>
              </Space>
            </div>
            <div style={{ fontSize: 12, color: isDark ? '#aebbd4' : '#64748b', marginBottom: 10 }}>
              {t('qa.ttBatch.subtitle')}
            </div>

            {/* 输入区：上传清单文件 / 粘贴单号列表 */}
            <div style={{
              border, borderRadius: 8, padding: '10px 14px', marginBottom: 10,
              background: isDark ? 'rgba(114,46,209,0.10)' : '#faf8ff',
            }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
                <Upload accept=".xlsx,.xls,.csv,.txt" showUploadList={false} beforeUpload={onBatchFile}>
                  <Button icon={<UploadOutlined />}>{t('qa.ttBatch.upload')}</Button>
                </Upload>
                <Tooltip title={t('qa.ttBatch.templateTip')}>
                  <Button icon={<DownloadOutlined />} onClick={downloadTtBatchTemplate}>
                    {t('qa.ttBatch.template')}
                  </Button>
                </Tooltip>
                {batchFile && <Tag color="purple">{batchFile}</Tag>}
                <Text type="secondary" style={{ fontSize: 12 }}>{t('qa.ttBatch.uploadHint')}</Text>
              </div>
              <Input.TextArea
                rows={4}
                value={batchText}
                onChange={e => setBatchText(e.target.value)}
                placeholder={t('qa.ttBatch.placeholder')}
              />
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
                <Button type="primary" loading={batchLoading} onClick={() => runTtBatch()}>
                  {batchLoading ? t('qa.ttBatch.checking') : t('qa.ttBatch.run')}
                </Button>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('qa.ttBatch.parsed', { n: batchTokens.length })}
                </Text>
              </div>
            </div>

            {!!batchError && <Alert type="error" showIcon message={batchError} style={{ marginBottom: 10 }} />}
            {batchLoading && (
              <div style={{ textAlign: 'center', padding: 50 }}>
                <Spin size="large" />
                <div style={{ marginTop: 12, color: isDark ? '#aebbd4' : '#64748b' }}>{t('qa.ttBatch.checking')}</div>
              </div>
            )}

            {!batchLoading && batchData && (() => {
              const s = batchData.summary || {}
              const allRows: any[] = batchData.rows || []
              const shown = batchOnlyAdjust ? allRows.filter(r => r.level_status === 'adjust') : allRows
              const stat = (label: string, value: number, color?: string) => (
                <Tag color={color} style={{ margin: 0, padding: '2px 10px', fontSize: 13 }}>
                  {label} <b>{value}</b>
                </Tag>
              )
              const columns = [
                {
                  title: t('qa.ttBatch.col.tt'), dataIndex: 'tt_no', width: 150,
                  fixed: isMobile ? undefined : ('left' as const),
                  render: (v: string, r: any) => (
                    <a style={{ fontFamily: 'monospace' }} onClick={() => runTt(r.tt_no)}>{v}</a>
                  ),
                },
                {
                  title: t('qa.ttBatch.col.judge'), dataIndex: 'level_status', width: 110,
                  render: (_: any, r: any) => (
                    <Tag color={verdictColor(r.found ? r.level_status : 'miss')} style={{ margin: 0 }}>
                      {verdictText(r)}
                    </Tag>
                  ),
                },
                {
                  title: t('qa.ttBatch.col.current'), dataIndex: 'ticket_severity', width: 90,
                  render: (v: string) => (v ? <Tag color={levelColor(v)} style={{ margin: 0 }}>{v}</Tag> : '—'),
                },
                {
                  title: t('qa.ttBatch.col.expected'), dataIndex: 'expected_severity', width: 90,
                  render: (v: string, r: any) => (v
                    ? <Tag color={levelColor(v)} style={{ margin: 0, fontWeight: r.level_status === 'adjust' ? 700 : undefined }}>{v}</Tag>
                    : '—'),
                },
                { title: t('qa.ttBatch.col.site'), dataIndex: 'site_name', width: 140, ellipsis: true },
                { title: t('qa.ttBatch.col.alarm'), dataIndex: 'alarm_code', width: 100 },
                { title: t('qa.ttBatch.col.vip'), dataIndex: 'vip_site', width: 70 },
                { title: t('qa.ttBatch.col.status'), dataIndex: 'status', width: 110, ellipsis: true },
                {
                  title: t('qa.ttBatch.col.rule'), dataIndex: 'matched_rule_name', ellipsis: true, width: 220,
                  render: (v: string, r: any) => (v ? <span>{r.matched_rule_id} {v}</span> : '—'),
                },
                {
                  title: t('qa.ttBatch.col.detail'), dataIndex: 'match_details', ellipsis: true,
                  render: (v: string) => (v
                    ? <Tooltip title={<span style={{ wordBreak: 'break-all' }}>{v}</span>}>
                        <span style={{ fontSize: 12, color: isDark ? '#aebbd4' : '#64748b' }}>{v}</span>
                      </Tooltip>
                    : '—'),
                },
              ]
              return (
                <div>
                  {/* 汇总统计 */}
                  <div style={{ marginBottom: 6 }}>
                    <Text strong style={{ fontSize: 13 }}>{t('qa.ttBatch.summary')}</Text>
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
                    {stat(t('qa.ttBatch.stat.input'), batchData.input?.valid ?? 0)}
                    {stat(t('qa.ttBatch.stat.found'), s.found ?? 0, 'cyan')}
                    {stat(t('qa.ttBatch.stat.miss'), s.not_found ?? 0, 'default')}
                    {stat(t('qa.ttBatch.stat.ok'), s.level_ok ?? 0, 'green')}
                    {stat(t('qa.ttBatch.stat.adjust'), s.level_adjust ?? 0, 'red')}
                    {stat(t('qa.ttBatch.stat.unknown'), s.level_unknown ?? 0, 'orange')}
                  </div>
                  {/* 表格工具条：筛选 + 行数 + 导出（导出的是当前表格内容） */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
                    <Checkbox checked={batchOnlyAdjust} onChange={e => setBatchOnlyAdjust(e.target.checked)}>
                      <Tooltip title={t('qa.ttBatch.onlyAdjustTip')}>
                        <span style={{ fontSize: 13 }}>{t('qa.ttBatch.onlyAdjust')}</span>
                      </Tooltip>
                    </Checkbox>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t('qa.ttBatch.tableCount', { n: shown.length, total: allRows.length })}
                    </Text>
                    <Space style={{ marginLeft: 'auto' }} wrap>
                      <Tooltip title={t('qa.ttBatch.exportTip')}>
                        <Button
                          size="small"
                          type="primary"
                          ghost
                          icon={<DownloadOutlined />}
                          disabled={!shown.length}
                          onClick={exportTtBatch}
                        >
                          {t('qa.ttBatch.export')}
                        </Button>
                      </Tooltip>
                    </Space>
                  </div>
                  {!!batchData.error && (
                    <Alert type="warning" showIcon style={{ marginBottom: 8 }}
                      message={t('qa.ttBatch.rulesFailed', { err: batchData.error })} />
                  )}
                  {!!batchData.input?.invalid?.length && (
                    <Alert type="warning" showIcon style={{ marginBottom: 8 }}
                      message={t('qa.ttBatch.invalid', {
                        n: batchData.input.invalid.length,
                        list: batchData.input.invalid.slice(0, 10).join(', '),
                      })} />
                  )}
                  {batchData.input?.truncated && (
                    <Alert type="info" showIcon style={{ marginBottom: 8 }}
                      message={t('qa.ttBatch.truncated', { n: batchData.input.limit })} />
                  )}
                  <Table
                    size="small"
                    rowKey="tt_no"
                    dataSource={shown}
                    columns={columns}
                    scroll={isMobile ? { x: 1200 } : undefined}
                    pagination={{ pageSize: 20, showSizeChanger: true, size: 'small' }}
                  />
                </div>
              )
            })()}
          </div>
        )}

        {/* ===== RAN UME 告警分析视图 ===== */}
        {umeView && (
          <UmeAlarmView
            t={t}
            isDark={isDark}
            isMobile={isMobile}
            border={border}
            umeKey={umeKey}
            loading={umeLoading}
            error={umeError}
            data={umeData}
            onBack={() => setUmeView(false)}
            onRetry={() => runUme(umeKey)}
          />
        )}

        {!ttView && !umeView && !ttBatchView && searched && !docLoading && hits !== null && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Text strong>
                {searching ? t('qa.searching') : `${hits.length}${t('qa.results')}`}
              </Text>
              <Button size="small" onClick={() => { setHits(null); setSearched(false) }}>
                {t('qa.backToResults')}
              </Button>
            </div>
            {searching ? (
              <div style={{ textAlign: 'center', padding: 40 }}><SpinIcon /></div>
            ) : hits.length === 0 ? (
              <Empty description={t('qa.noResults')} />
            ) : (
              hits.map(h => (
                <div
                  key={h.path}
                  onClick={() => loadDoc(h.path)}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    border,
                    marginBottom: 10,
                    cursor: 'pointer',
                    background: isDark ? 'rgba(0, 217, 255,0.04)' : '#fafcfe',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <BookOutlined style={{ color: '#13c2c2' }} />
                    <Text strong>{h.title}</Text>
                    {h.status && <Tag color={statusColor(h.status)}>{statusLabel(h.status, t)}</Tag>}
                    <Text type="secondary" style={{ fontSize: 12, marginLeft: isMobile ? 0 : 'auto' }}>
                      {h.match_count} {t('qa.matchLines')}
                    </Text>
                  </div>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 2 }}>{displayPath(h.path, locale)}</Text>
                  {h.snippets.map(s => (
                    <div key={s.line} style={{ fontSize: 13, marginTop: 4, color: isDark ? '#aebbd4' : '#475569' }}>
                      <Text type="secondary" style={{ fontSize: 11, marginRight: 6 }}>{s.line}</Text>
                      <Highlight text={s.text} terms={searchTerms} />
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        )}

        {/* 文档视图 */}
        {!ttView && !umeView && !ttBatchView && docLoading && <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>}
        {!ttView && !umeView && !ttBatchView && !docLoading && docError && <Text type="danger">{docError}</Text>}
        {!ttView && !umeView && !ttBatchView && !docLoading && !doc && !searched && (
          <Empty description={isMobile ? t('qa.selectDocMobile') : t('qa.selectDoc')} style={{ marginTop: isMobile ? 32 : 80 }} />
        )}
        {!ttView && !umeView && !ttBatchView && !docLoading && doc && (
          <div>
            <Title level={4} style={{ marginTop: 0, marginBottom: 8, fontSize: isMobile ? 17 : undefined }}>{doc.title}</Title>
            <div style={{ marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {doc.front_matter['状态'] && <Tag color={statusColor(doc.front_matter['状态'])}>{t('qa.status')}: {statusLabel(doc.front_matter['状态'], t)}</Tag>}
              {doc.front_matter['来源'] && <Tag>{t('qa.source')}: {doc.front_matter['来源']}</Tag>}
              <Text type="secondary" style={{ fontSize: 12, alignSelf: 'center' }}>{displayPath(doc.path, locale)}</Text>
            </div>
            <div className="eflowqa-md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.content}</ReactMarkdown>
            </div>
          </div>
        )}
      </div>

      {/* ===== 移动端：目录抽屉 ===== */}
      {isMobile && (
        <Drawer
          title={t('qa.catalog')}
          placement="left"
          width="85%"
          open={treeOpen}
          onClose={() => setTreeOpen(false)}
          styles={{ body: { padding: 12, display: 'flex', flexDirection: 'column', gap: 10 } }}
        >
          {treeBlock}
        </Drawer>
      )}
    </div>
  )
}
