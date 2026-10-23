import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Card, Table, Button, Space, Select, Tag, Typography, message, Empty, Tabs, Row, Col, Statistic, Alert, Input, Spin } from 'antd'
import { ReloadOutlined, DownloadOutlined, FileExcelOutlined, FileTextOutlined, ThunderboltOutlined, SearchOutlined } from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { formatDateTime } from '../datetime'
import { cardStyle, pageWrap } from '../theme'
import { exportReport, type ReportSheetSpec } from '../utils/excelReport'
import DraggableClickModal from '../components/DraggableClickModal'

const { Text } = Typography

/**
 * 本页是否正被「无外壳」地嵌入（门户 iframe / 大屏深链）。
 *
 * 为什么要判这个：门户（/v2/olbrportal/、MsPortal）是用
 * `/myapp/?page=email_reports` 内嵌本页的，而它自己在同一块面板顶部已经渲染了
 * 一行橙色标题「Auto Report Files」。若本页再顶上自己的 Card 标题
 * 「Task Report Files / 任务报告文件」，两块标题就会**上下叠在一起**，
 * 用户看到的就是「同一个标题出现两次」（2026-09-28 用户反馈）。
 *
 * 判据与 App.tsx 的 shellHidden 保持一致，即 ?page= 直链 bare 或 ?embed=1：
 *   · ?page=xxx —— 门户 iframe 的 src 就是这种形态（本页实际的嵌入方式）；
 *   · ?embed=1 / ?embed=true / ?layout=bare —— 大屏与其它嵌入方走这条。
 * 独立打开 /myapp/ 再从侧栏进本页时两者都不成立，Card 标题照常显示 ——
 * 那种场景下没有外层标题，去掉就成了「这一页没有名字」。
 */
function isShellLessEmbed(): boolean {
  try {
    const sp = new URLSearchParams(window.location.search)
    return sp.get('page') != null || sp.get('embed') === '1' || sp.get('embed') === 'true' || sp.get('layout') === 'bare'
  } catch { return false }
}

/**
 * 门户 v2（/v2/olbrportal/）内嵌本页时专属的「精简显示」开关。
 *
 * 为什么单独一个参数：门户 v2 的 Auto Report Files 面板只想要「最新邮件附件」这一件事，
 * 于是它把 iframe 的 src 写成 `/myapp/?page=email_reports&lang=…&portalFiles=1`
 * （见 v2/olbrportal/assets/olbr.js 的 emailSrc()）。本页据此：
 *   · 只渲染 Latest Email 一个页签（隐藏 FINEBI report / eFlow TT Rules Check / TTs and MTTR）；
 *   · 前三列表头改用 emailReports.portalCol* 那三条文案。
 * ⚠️ 只有 v2 那块面板带此参数 —— MsPortal / 根 olbrportal / v1 的内嵌 src 都不带，
 *    用户直接打开 /myapp/?page=email_reports&lang=en 也不带，故它们一律保持原样
 *    （全部 4 个页签 + 旧表头）。这与 isShellLessEmbed() 的「是否被无外壳嵌入」是两回事：
 *    后者所有门户都命中，不能用来做 v2 专属开关。
 */
function isPortalFilesMode(): boolean {
  try {
    return new URLSearchParams(window.location.search).get('portalFiles') === '1'
  } catch { return false }
}

// 后端 /api/email-reports/latest 的返回结构（只含文档类报告，无图片）
interface ReportFile {
  name: string
  size: number
  mtime: number
}
interface ReportSource {
  source_id: string
  task_id: string
  task_name: string
  label: string
  dir: string
  files: ReportFile[]
}
// 展平成表格行：一个文件一行
interface Row {
  key: string
  task_name: string
  task_id: string
  label: string
  dir: string
  source_id: string
  name: string
  size: number
  mtime: number
}
// 后端 /api/finebi-reports/latest 的返回结构（每个 FineBI 文件夹最新一份 Excel）
interface FinebiRow {
  key: string
  folder: string
  name: string
  size: number
  mtime: number
}
// 后端 /api/email-reports/eflow-check 返回结构
interface EflowFile {
  name: string
  size: number
  mtime: number
  // kind=rule：从 eFlow 收集的规则表；kind=report：本次检查的产物（矫正表/报告）
  kind?: 'rule' | 'report'
  label?: string
}
interface EflowBreakdownRow {
  priority: number | null
  rule_id: number | null
  rule_name: string
  severity: string
  matched: number
  changed: number
}
// ===== eFlow TT Rules Check 页签的 TT 级下钻（2026-10-23 新增）=====
// 口径：/api/email-reports/eflow_tt_rules_check/drill 直接读匹配器导出的矫正表
// （All_TT_Records），所以「卡片上的数字」与「弹窗里的行数」是同一次运行的同一份数据。
interface EflowDrillRow {
  tt_no: string | null
  wo_no: string | null
  ticket_no: string | null
  title: string | null
  alarm_code: number | string | null
  site_name: string | null
  ne_name: string | null
  domain: string | null
  site_type: string | null
  vip_site: string | null
  down_site_count: number | null
  cur_severity: string | null
  rule_id: number | null
  rule_name: string | null
  new_severity: string | null
  changed: boolean
  evidence: string | null
  status: string | null
  // 2026-10-23 用户要求补充的字段
  site_id: string | null
  created_time: string | null
  alarm_occur_time: string | null
  alarm_clear_time: string | null
  trm_type: string | null
  // 规则里用到的全部字段（判定时实际比较的值，已归一化）
  f_alarm_code: string | null
  f_vip_site: string | null
  f_hub_site: string | null
  f_site_subtype: string | null
  f_asset_type: string | null
  f_network_type: string | null
  f_downstream_sites: string | null
  f_alarm_description: string | null
}
type EflowDrillMetric = 'total' | 'matched' | 'unmatched' | 'changed' | 'rule' | 'rule_changed' | 'shift'
  | 'cur_sev' | 'new_sev'

// 级别对照统计（Change direction 上方的卡片，2026-10-23）
interface EflowSeverityMatrix {
  levels: string[]
  actual: Record<string, number>
  proposed: Record<string, number>
  other: { actual: number; proposed: number }
  total: number
  moved: number
}
// 打开下钻弹窗所需的全部参数；title 是弹窗标题（已翻译文案 + 可选过滤说明）
interface EflowDrillTarget {
  metric: EflowDrillMetric
  ruleId?: number | null
  sevFrom?: string
  sevTo?: string
  alarmCode?: string | null
  title: string
}
interface EflowUnmatchedGroup {
  alarm_code: string | number | null
  vip_site: string | null
  site_type: string | null
  count: number
}

interface EflowSummary {
  success: boolean
  generated_at: string
  limit: number
  total: number
  matched: number
  unmatched?: number
  changed: number
  elapsed_seconds?: number
  rule_breakdown?: EflowBreakdownRow[]
  change_matrix?: { from: string; to: string; count: number }[]
  rules_count?: number | null
  // 摘要 JSON 与矫正表 xlsx 是否出自同一次运行（后端比对 mtime）。
  // 为 true 时统计卡数字与下钻明细会对不上，页面必须显式告警（2026-10-23）。
  correction_drift?: boolean
  // 规则引用了、但本地取不到的字段 → 这些规则**永远不会命中**。
  // 不展示的话，界面上只表现为「某条规则不在表里」，看起来像统计不全（2026-10-23 HUB 案例）。
  missing_fields?: Record<string, string[]>
  rules_collected?: { success?: boolean; rules_file_exists?: boolean; error?: string; returncode?: number }
  error?: string
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

/**
 * 可下钻的数字（2026-10-23）。页面上的「每个数字都要可点」是硬要求
 * （AGENTS.md 三.1b），这里统一成一种视觉：主色 + 虚线下划线 + 手型。
 * disabled 时退回纯文本 —— 例如某个规则匹配数为 0，点开只会是空弹窗。
 */
function DrillLink({ label, onClick, danger, disabled }: {
  label: string
  onClick: (e: React.MouseEvent) => void
  danger?: boolean
  disabled?: boolean
}) {
  if (disabled) return <Text type="secondary">{label}</Text>
  return (
    <a
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e as any) } }}
      style={{
        color: danger ? '#cf1322' : 'var(--wh-color-primary, #1677ff)',
        fontWeight: 600,
        textDecoration: 'underline dotted',
        textUnderlineOffset: '0.2em',
        cursor: 'pointer',
      }}
    >
      {label}
    </a>
  )
}

/** 下钻弹窗里的明细表列（语言在渲染时由 i18n 决定，故做成参数化函数） */
function eflowDrillColumns(t: (k: string, p?: Record<string, string | number>) => string) {
  return [
    {
      title: t('emailReports.drillColTt'),
      dataIndex: 'tt_no',
      key: 'tt_no',
      width: 170,
      fixed: 'left' as const,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColWo'),
      dataIndex: 'wo_no',
      key: 'wo_no',
      width: 130,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColTitle'),
      dataIndex: 'title',
      key: 'title',
      width: 320,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColAlarm'),
      dataIndex: 'alarm_code',
      key: 'alarm_code',
      width: 100,
      render: (v: number | string | null) => (v == null ? '—' : String(v)),
    },
    {
      title: t('emailReports.drillColSiteId'),
      dataIndex: 'site_id',
      key: 'site_id',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColSite'),
      dataIndex: 'site_name',
      key: 'site_name',
      width: 160,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColTrmType'),
      dataIndex: 'trm_type',
      key: 'trm_type',
      width: 130,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColSiteType'),
      dataIndex: 'site_type',
      key: 'site_type',
      width: 110,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColVip'),
      dataIndex: 'vip_site',
      key: 'vip_site',
      width: 80,
      render: (v: string | null) => v || '—',
    },
    {
      // 拆成「当前级别」+「变更结果」两列：合在一列时，不需要变更的行也很容易
      // 被读成「都在变」，用户看到 43 条 P2→P1 会误以为 45 条全是 P2（2026-10-23）。
      title: t('emailReports.drillColCurSev'),
      dataIndex: 'cur_severity',
      key: 'cur_severity',
      width: 110,
      render: (v: string | null) => <Tag>{v || '—'}</Tag>,
    },
    {
      title: t('emailReports.drillColChanged'),
      key: 'changed_flag',
      width: 150,
      render: (_: unknown, r: EflowDrillRow) => (
        r.changed
          ? <Tag color="red">→ {r.new_severity || '—'}</Tag>
          : <Text type="secondary">{t('emailReports.drillNoChange')}</Text>
      ),
    },
    {
      // 「规则变化」列：直接写出这条 TT 被判到了哪条规则、级别怎么变，
      // 不需要再去对照 status/evidence 自己推（2026-10-23 用户要求下钻体现规则变化）。
      title: t('emailReports.drillColRule'),
      key: 'rule',
      width: 260,
      render: (_: unknown, r: EflowDrillRow) => (
        <Space direction="vertical" size={2}>
          {r.rule_id == null
            ? <Text type="secondary">{t('emailReports.drillNoMatch')}</Text>
            : (
              <span>
                <Text strong>{r.rule_name || '—'}</Text>
                <Text type="secondary" style={{ fontSize: '0.75rem' }}> ID {r.rule_id}</Text>
              </span>
            )}
          {r.rule_id != null && (
            <Text style={{ fontSize: '0.75rem' }}>
              {r.changed
                ? <span style={{ color: '#cf1322' }}>
                    {t('emailReports.drillRuleShift', { from: r.cur_severity || '—', to: r.new_severity || '—' })}
                  </span>
                : <Text type="secondary">
                    {t('emailReports.drillRuleKeep', { sev: r.cur_severity || '—' })}
                  </Text>}
            </Text>
          )}
        </Space>
      ),
    },
    // ---- 时间字段（2026-10-23 用户要求）----
    {
      title: t('emailReports.drillColCreated'),
      dataIndex: 'created_time',
      key: 'created_time',
      width: 170,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColAlarmOccur'),
      dataIndex: 'alarm_occur_time',
      key: 'alarm_occur_time',
      width: 170,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColAlarmClear'),
      dataIndex: 'alarm_clear_time',
      key: 'alarm_clear_time',
      width: 170,
      // 未清除是业务上的正常状态（单子还开着），不能用「—」表示缺失，要区分开
      render: (v: string | null) => v || <Text type="secondary">{t('emailReports.drillNotCleared')}</Text>,
    },
    // ---- 规则里用到的全部字段（判定时实际比较的值）----
    {
      title: t('emailReports.drillColFieldAlarmCode'),
      dataIndex: 'f_alarm_code',
      key: 'f_alarm_code',
      width: 120,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColFieldVip'),
      dataIndex: 'f_vip_site',
      key: 'f_vip_site',
      width: 80,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColFieldHub'),
      dataIndex: 'f_hub_site',
      key: 'f_hub_site',
      width: 80,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColFieldSubtype'),
      dataIndex: 'f_site_subtype',
      key: 'f_site_subtype',
      width: 110,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColFieldAsset'),
      dataIndex: 'f_asset_type',
      key: 'f_asset_type',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColFieldNetwork'),
      dataIndex: 'f_network_type',
      key: 'f_network_type',
      width: 100,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColFieldDownstream'),
      dataIndex: 'f_downstream_sites',
      key: 'f_downstream_sites',
      width: 130,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColFieldAlarmDesc'),
      dataIndex: 'f_alarm_description',
      key: 'f_alarm_description',
      width: 280,
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: t('emailReports.drillColEvidence'),
      dataIndex: 'evidence',
      key: 'evidence',
      width: 420,
      render: (v: string | null) => (v ? <Text style={{ fontSize: '0.75rem' }}>{v}</Text> : '—'),
    },
  ]
}

/** 导出文件名时间戳（去掉日期里的分隔符，避免文件名出现空格/冒号） */
function stamp(): string {
  return new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
}

// ===== TTs and MTTR 页签 =====
// 生成任务（tt_mttr_report_generate）实测约 10 秒，但要排 m 组 worker 的串行队列，
// 完成时刻并不确定。后端没有可靠的「本次触发是否已结束」信号（任务由 worker 子进程执行），
// 因此判据取产物本身：目录里出现 mtime 更新的文件即视为生成完成 —— 这既当进度提示，
// 也是「文件真的写出来了」的证据，比按固定秒数盲刷（见 runTaskNow 的 setTimeout(3000)）可靠。
const TT_MTTR_TASK = 'tt_mttr_report_generate'
const MTTR_POLL_MS = 3000
const MTTR_POLL_TRIES = 30   // 最长约 90 秒，之后提示用户改用刷新

export default function EmailReports() {
  const { t } = useI18n()
  // 每次挂载求值一次即可：嵌入方式由 URL 决定，本页挂载后不会再变。
  // 用 state 而不是每次渲染现算，是为了让「是否渲染标题」在这次挂载内稳定。
  const [embed] = useState(isShellLessEmbed)
  // 门户 v2 内嵌的精简模式（?portalFiles=1）：同样由 URL 一次性决定，见 isPortalFilesMode()。
  const [portalFiles] = useState(isPortalFilesMode)
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(false)
  // 每个报告类型保留最近几份（默认 1 = 只要最新一份）
  const [limit, setLimit] = useState(1)
  const [finebiRows, setFinebiRows] = useState<FinebiRow[]>([])
  const [finebiLoading, setFinebiLoading] = useState(false)
  // eflow_check 页签：最新一次规则匹配检查摘要 + 可下载文件
  const [eflowSummary, setEflowSummary] = useState<EflowSummary | null>(null)
  const [eflowFiles, setEflowFiles] = useState<EflowFile[]>([])
  const [eflowLoading, setEflowLoading] = useState(false)
  // 正在触发的任务 id（tt 检查 / 告警规则收集 / 推单规则收集），用于各自按钮的 loading
  const [eflowRunningTask, setEflowRunningTask] = useState<string | null>(null)
  // TT 级下钻弹窗（2026-10-23）：点哪个数字就取哪个口径的明细
  const [drillTarget, setDrillTarget] = useState<EflowDrillTarget | null>(null)
  const [drillRows, setDrillRows] = useState<EflowDrillRow[]>([])
  const [drillMeta, setDrillMeta] = useState<{ total: number; truncated: boolean; limit: number } | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [drillError, setDrillError] = useState<string | null>(null)
  // 未匹配分布（点「未匹配」卡片时展示，可再按 alarm_code 下钻）
  const [unmatchedGroups, setUnmatchedGroups] = useState<EflowUnmatchedGroup[] | null>(null)
  // 弹窗内的搜索与锚点 —— 与项目其它下钻弹窗（AlarmDashboard / NocAnalyst）保持一致：
  // 以点击位置为中心弹出、可拖动、带搜索框与导出按钮（2026-10-23）
  const [drillSearch, setDrillSearch] = useState('')
  const [drillAnchor, setDrillAnchor] = useState<{ x: number; y: number } | null>(null)
  // 级别对照统计：单子实际级别 vs 新规则建议级别（Change direction 上方的卡片）
  const [sevMatrix, setSevMatrix] = useState<EflowSeverityMatrix | null>(null)
  // TTs and MTTR 页签：生成中标志 + 轮询定时器（卸载时要能取消，否则页面切走后仍在打接口）
  const [mttrGenerating, setMttrGenerating] = useState(false)
  const mttrTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/email-reports/latest', { params: { limit } })
      const reports: ReportSource[] = res.data?.reports || []
      const flat: Row[] = []
      reports.forEach(r => {
        r.files.forEach(f => {
          flat.push({
            key: `${r.source_id}/${f.name}`,
            task_name: r.task_name,
            task_id: r.task_id,
            label: r.label,
            dir: r.dir,
            source_id: r.source_id,
            name: f.name,
            size: f.size,
            mtime: f.mtime,
          })
        })
      })
      // 最新的排最前
      flat.sort((a, b) => b.mtime - a.mtime)
      setRows(flat)
    } catch (e) {
      message.error(t('emailReports.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [limit, t])

  const loadFinebi = useCallback(async () => {
    setFinebiLoading(true)
    try {
      const res = await api.get('/finebi-reports/latest')
      const reports = (res.data?.reports || []) as Omit<FinebiRow, 'key'>[]
      setFinebiRows(reports.map(r => ({ ...r, key: r.folder })))
    } catch (e) {
      message.error(t('emailReports.finebiLoadFailed'))
    } finally {
      setFinebiLoading(false)
    }
  }, [t])

  const loadEflowCheck = useCallback(async () => {
    setEflowLoading(true)
    try {
      const res = await api.get('/email-reports/eflow_tt_rules_check')
      setEflowSummary(res.data?.summary || null)
      setEflowFiles(res.data?.files || [])
      // 级别对照数据与摘要同源（都读同一份矫正表），这里失败不应影响主摘要展示
      try {
        const m = await api.get('/email-reports/eflow_tt_rules_check/severity_matrix')
        setSevMatrix(m.data || null)
      } catch (e2) {
        setSevMatrix(null)
      }
    } catch (e) {
      message.error(t('emailReports.eflowLoadFailed'))
    } finally {
      setEflowLoading(false)
    }
  }, [t])

  /**
   * 打开 TT 级下钻弹窗。target 里的 metric 决定后端取哪一档口径，
   * 与页面上的数字一一对应（见后端 eflow_tt_rules_check_drill 的文档）。
   */
  const openEflowDrill = useCallback(async (target: EflowDrillTarget, anchor?: { x: number; y: number } | null) => {
    setDrillAnchor(anchor ?? null)
    setDrillSearch('')
    setDrillTarget(target)
    setDrillRows([])
    setDrillMeta(null)
    setDrillError(null)
    setDrillLoading(true)
    // 「未匹配」分组只在点未匹配卡片时拉一次，其余口径清空
    if (target.metric === 'unmatched') {
      try {
        const g = await api.get('/email-reports/eflow_tt_rules_check/unmatched_dist')
        setUnmatchedGroups(g.data?.groups || [])
      } catch (e) {
        setUnmatchedGroups([])
      }
    } else {
      setUnmatchedGroups(null)
    }
    try {
      // ⚠ 不要按 metric 逐个 if 拼参数：新增口径（cur_sev / new_sev）时漏传 sev_from
      // 就会直接 400（2026-10-23 实际发生）。这里统一透传 target 里所有非空筛选字段，
      // 后端按 metric 自行取用需要的那个；多传的字段后端不会理会。
      const params: Record<string, unknown> = { metric: target.metric, limit: 2000 }
      if (target.ruleId != null) params.rule_id = target.ruleId
      if (target.sevFrom) params.sev_from = target.sevFrom
      if (target.sevTo) params.sev_to = target.sevTo
      if (target.alarmCode != null) params.alarm_code = target.alarmCode
      const res = await api.get('/email-reports/eflow_tt_rules_check/drill', { params })
      setDrillRows(res.data?.rows || [])
      setDrillMeta({
        total: res.data?.total ?? 0,
        truncated: Boolean(res.data?.meta?.truncated),
        limit: res.data?.meta?.limit ?? 2000,
      })
    } catch (e: any) {
      setDrillError(e?.response?.data?.detail || t('emailReports.drillFailed'))
    } finally {
      setDrillLoading(false)
    }
  }, [t])

  const closeEflowDrill = useCallback(() => {
    setDrillTarget(null)
    setDrillRows([])
    setDrillMeta(null)
    setDrillError(null)
    setUnmatchedGroups(null)
    setDrillSearch('')
  }, [])

  // 弹窗内搜索：跨所有展示字段做子串匹配（与 AlarmDashboard 的 common.searchAllFields 同口径）
  const filteredDrillRows = useMemo(() => {
    const q = drillSearch.trim().toLowerCase()
    if (!q) return drillRows
    return drillRows.filter(r =>
      [r.tt_no, r.wo_no, r.ticket_no, r.title, r.alarm_code, r.site_id, r.site_name, r.ne_name,
        r.domain, r.site_type, r.vip_site, r.cur_severity, r.new_severity, r.rule_name,
        r.rule_id, r.evidence, r.status, r.trm_type,
        r.created_time, r.alarm_occur_time, r.alarm_clear_time,
        r.f_alarm_code, r.f_vip_site, r.f_hub_site, r.f_site_subtype, r.f_asset_type,
        r.f_network_type, r.f_downstream_sites, r.f_alarm_description]
        .some(v => v != null && String(v).toLowerCase().includes(q)),
    )
  }, [drillRows, drillSearch])

  // 弹窗内的导出：导「当前搜索结果」全部行，列与表格一致（不含操作列）
  const exportEflowDrill = useCallback(async () => {
    if (!filteredDrillRows.length) return
    await exportReport([{
      name: 'TT Detail',
      title: drillTarget?.title || t('emailReports.drillTotalTitle'),
      header: [
        t('emailReports.drillColTt'), t('emailReports.drillColWo'), t('emailReports.drillColTitle'),
        t('emailReports.drillColAlarm'), t('emailReports.drillColSite'), t('emailReports.drillColSiteType'),
        t('emailReports.drillColVip'), t('emailReports.drillColCurSev'), t('emailReports.drillColChanged'),
        t('emailReports.drillColRule'), t('emailReports.drillColEvidence'),
        // 2026-10-23 补充：站点/时间 + 规则里用到的全部字段
        t('emailReports.drillColSiteId'), t('emailReports.drillColTrmType'),
        t('emailReports.drillColCreated'), t('emailReports.drillColAlarmOccur'), t('emailReports.drillColAlarmClear'),
        t('emailReports.drillColFieldAlarmCode'), t('emailReports.drillColFieldVip'),
        t('emailReports.drillColFieldHub'), t('emailReports.drillColFieldSubtype'),
        t('emailReports.drillColFieldAsset'), t('emailReports.drillColFieldNetwork'),
        t('emailReports.drillColFieldDownstream'), t('emailReports.drillColFieldAlarmDesc'),
      ],
      rows: filteredDrillRows.map(r => [
        r.tt_no ?? '', r.wo_no ?? '', r.title ?? '', r.alarm_code == null ? '' : String(r.alarm_code),
        r.site_name ?? '', r.site_type ?? '', r.vip_site ?? '',
        r.cur_severity ?? '',
        // 与界面一致：需变更的写目标级别，不需要的明确写「不变」而不是留空
        r.changed ? (r.new_severity ?? '') : '-',
        r.rule_id == null
          ? t('emailReports.drillNoMatch')
          : `${r.rule_name || '—'} (ID ${r.rule_id})`,
        r.evidence ?? '',
        r.site_id ?? '', r.trm_type ?? '',
        r.created_time ?? '', r.alarm_occur_time ?? '', r.alarm_clear_time ?? '',
        r.f_alarm_code ?? '', r.f_vip_site ?? '', r.f_hub_site ?? '', r.f_site_subtype ?? '',
        r.f_asset_type ?? '', r.f_network_type ?? '', r.f_downstream_sites ?? '',
        r.f_alarm_description ?? '',
      ]),
      columnWidths: [20, 16, 40, 12, 22, 14, 8, 16, 30, 50,
        10, 14, 20, 20, 20, 14, 8, 8, 12, 10, 10, 14, 40],
      tabColor: '#2F5496',
    }], `eflow_tt_drill_${stamp()}.xlsx`)
  }, [filteredDrillRows, drillTarget, t])

  const runTaskNow = useCallback(async (taskId: string, okMsg: string, failMsg: string) => {
    setEflowRunningTask(taskId)
    try {
      // 同 generateMttr：/run 失败时也是 200，必须看响应体的 accepted
      const res = await api.post(`/tasks/${taskId}/run`)
      if (!res.data?.accepted) {
        message.error(res.data?.error ? `${failMsg}：${res.data.error}` : failMsg)
        return
      }
      message.success(okMsg)
      // 任务在后台线程/队列执行，3 秒后刷新一次（再由用户手动刷新补全）
      setTimeout(loadEflowCheck, 3000)
    } catch (e) {
      message.error(failMsg)
    } finally {
      setEflowRunningTask(null)
    }
  }, [loadEflowCheck])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadFinebi() }, [loadFinebi])
  useEffect(() => { loadEflowCheck() }, [loadEflowCheck])
  useEffect(() => () => {
    if (mttrTimer.current) clearTimeout(mttrTimer.current)
  }, [])

  // 只取 tt_mttr 一个源的当前文件列表（轮询用，绕开 load() 的 setState，避免读到旧 state）
  const fetchMttrFiles = useCallback(async (): Promise<ReportFile[]> => {
    const res = await api.get('/email-reports/latest', { params: { limit: 10 } })
    const src = ((res.data?.reports || []) as ReportSource[]).find(s => s.source_id === 'tt_mttr')
    return src?.files || []
  }, [])

  const downloadUrl = (row: Row) =>
    `/api/email-reports/download/${row.source_id}/${encodeURIComponent(row.name)}`

  const finebiDownloadUrl = (row: FinebiRow) =>
    `/api/finebi-reports/download/${encodeURIComponent(row.folder)}/${encodeURIComponent(row.name)}`

  const eflowDownloadUrl = (f: EflowFile) =>
    `/api/email-reports/download/eflow_tt_rules_check/${encodeURIComponent(f.name)}`

  // 该页签的行取自 /email-reports/latest 已展平的结果，只留 tt_mttr 源
  // （与「Email Reports」页签共用一次请求，且受同一个「保留最近 N 份」选择控制）
  const mttrRows = useMemo(() => rows.filter(r => r.source_id === 'tt_mttr'), [rows])

  const generateMttr = useCallback(async () => {
    setMttrGenerating(true)
    const prevMax = mttrRows.reduce((m, r) => Math.max(m, r.mtime), 0)
    try {
      // ⚠ 只判 HTTP 状态码会误报成功：/tasks/{id}/run 在「任务未找到 / 已禁用 /
      // 队列不可用」时同样返回 200，失败信号只在响应体的 accepted=false 里
      // （见 backend/services/task_runner.py:632-648 的 run_task_async）。
      // 2026-10-05 事故：后端进程启动早于任务注册，注册表里没有本任务，
      // 页面弹「已提交生成任务」后干等 90 秒超时，目录里始终没有文件。
      const res = await api.post(`/tasks/${TT_MTTR_TASK}/run`)
      if (!res.data?.accepted) {
        const running = Boolean(res.data?.running)
        message.error(
          running
            ? t('emailReports.mttrRunBusy')
            : t('emailReports.mttrRunFail') + (res.data?.error ? `：${res.data.error}` : ''),
        )
        setMttrGenerating(false)
        return
      }
      message.success(t('emailReports.mttrRunOk'))
    } catch (e) {
      message.error(t('emailReports.mttrRunFail'))
      setMttrGenerating(false)
      return
    }
    let tries = 0
    const poll = async () => {
      tries += 1
      let fresh: ReportFile[] = []
      try {
        fresh = await fetchMttrFiles()
      } catch (e) {
        // 拉取失败按「尚未就绪」处理，下一轮再试（接口抖动不该直接判生成失败）
      }
      if (fresh.some(f => f.mtime > prevMax)) {
        setMttrGenerating(false)
        void load()
        message.success(t('emailReports.mttrDone'))
        return
      }
      if (tries >= MTTR_POLL_TRIES) {
        setMttrGenerating(false)
        message.warning(t('emailReports.mttrTimeout'))
        return
      }
      mttrTimer.current = setTimeout(poll, MTTR_POLL_MS)
    }
    mttrTimer.current = setTimeout(poll, MTTR_POLL_MS)
  }, [mttrRows, fetchMttrFiles, load, t])

  // 前三列表头在门户 v2 精简模式下换文案（其余列不变）；独立打开时 portalFiles 为 false，
  // 仍走 colTask/colType/colFile。详见 isPortalFilesMode() 的注释。
  const columns = [
    {
      title: t(portalFiles ? 'emailReports.portalColTask' : 'emailReports.colTask'),
      dataIndex: 'task_name',
      key: 'task_name',
      minWidth: 220,
      render: (v: string, row: Row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          <Text type="secondary" style={{ fontSize: '0.75rem' }}>{row.task_id}</Text>
        </Space>
      ),
    },
    {
      title: t(portalFiles ? 'emailReports.portalColType' : 'emailReports.colType'),
      dataIndex: 'label',
      key: 'label',
      minWidth: 200,
      render: (v: string) => <Tag color="cyan">{v}</Tag>,
    },
    {
      title: t(portalFiles ? 'emailReports.portalColFile' : 'emailReports.colFile'),
      dataIndex: 'name',
      key: 'name',
      render: (v: string, row: Row) => (
        <a href={downloadUrl(row)} download={row.name} title={row.dir}>
          {v.toLowerCase().endsWith('.html')
            ? <FileTextOutlined style={{ marginRight: '0.375rem' }} />
            : <FileExcelOutlined style={{ marginRight: '0.375rem', color: '#1d6f42' }} />}
          {v}
        </a>
      ),
    },
    {
      title: t('emailReports.colSize'),
      dataIndex: 'size',
      key: 'size',
      minWidth: 110,
      align: 'right' as const,
      render: (v: number) => formatSize(v),
    },
    {
      title: t('emailReports.colTime'),
      dataIndex: 'mtime',
      key: 'mtime',
      minWidth: 180,
      render: (v: number) => formatDateTime(v),
    },
    {
      title: t('emailReports.colAction'),
      key: 'action',
      minWidth: 110,
      render: (_: unknown, row: Row) => (
        <Button size="small" icon={<DownloadOutlined />} href={downloadUrl(row)} download={row.name}>
          {t('emailReports.download')}
        </Button>
      ),
    },
  ]

  const finebiColumns = [
    {
      title: t('emailReports.finebiColFolder'),
      dataIndex: 'folder',
      key: 'folder',
      minWidth: 280,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: t('emailReports.colFile'),
      dataIndex: 'name',
      key: 'name',
      render: (v: string, row: FinebiRow) => (
        <a href={finebiDownloadUrl(row)} download={row.name}>
          <FileExcelOutlined style={{ marginRight: '0.375rem', color: '#1d6f42' }} />
          {v}
        </a>
      ),
    },
    {
      title: t('emailReports.colSize'),
      dataIndex: 'size',
      key: 'size',
      minWidth: 110,
      align: 'right' as const,
      render: (v: number) => formatSize(v),
    },
    {
      title: t('emailReports.colTime'),
      dataIndex: 'mtime',
      key: 'mtime',
      minWidth: 180,
      render: (v: number) => formatDateTime(v),
    },
    {
      title: t('emailReports.colAction'),
      key: 'action',
      minWidth: 110,
      render: (_: unknown, row: FinebiRow) => (
        <Button size="small" icon={<DownloadOutlined />} href={finebiDownloadUrl(row)} download={row.name}>
          {t('emailReports.download')}
        </Button>
      ),
    },
  ]

  const eflowColumns = [
    {
      title: t('emailReports.eflowColPri'),
      dataIndex: 'priority',
      key: 'priority',
      width: 90,
      render: (v: number | null) => (v == null ? '-' : v),
    },
    {
      title: t('emailReports.eflowColRule'),
      dataIndex: 'rule_name',
      key: 'rule_name',
      render: (v: string, row: EflowBreakdownRow) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          <Text type="secondary" style={{ fontSize: '0.75rem' }}>ID {row.rule_id ?? '-'}</Text>
        </Space>
      ),
    },
    {
      title: t('emailReports.eflowColSeverity'),
      dataIndex: 'severity',
      key: 'severity',
      width: 110,
      render: (v: string) => <Tag color="cyan">{v}</Tag>,
    },
    {
      title: t('emailReports.eflowColMatched'),
      dataIndex: 'matched',
      key: 'matched',
      width: 100,
      align: 'right' as const,
      // 0 命中的规则也会列出（规则全集），此时不可下钻 —— 列表本身已说明「本批没有符合的单」
      render: (v: number, row: EflowBreakdownRow) => (
        <DrillLink
          label={String(v)}
          disabled={!v || row.rule_id == null}
          onClick={e => { e.stopPropagation(); void openEflowDrill({
            metric: 'rule',
            ruleId: row.rule_id,
            title: `${t('emailReports.drillRuleTitle')} · ${row.rule_name} (ID ${row.rule_id})`,
          }, { x: e.clientX, y: e.clientY }) }}
        />
      ),
    },
    {
      title: t('emailReports.eflowColChanged'),
      dataIndex: 'changed',
      key: 'changed',
      width: 110,
      align: 'right' as const,
      render: (v: number, row: EflowBreakdownRow) => (v
        ? (
          <DrillLink
            danger
            label={String(v)}
            onClick={e => { e.stopPropagation(); void openEflowDrill({
              metric: 'rule_changed',
              ruleId: row.rule_id,
              title: `${t('emailReports.drillRuleChangedTitle')} · ${row.rule_name} (ID ${row.rule_id})`,
            }, { x: e.clientX, y: e.clientY }) }}
          />
        )
        : <Text type="secondary">0</Text>),
    },
  ]

  const eflowFileColumns = [
    {
      title: t('emailReports.colType'),
      dataIndex: 'label',
      key: 'label',
      minWidth: 200,
      render: (v: string, row: EflowFile) => (
        <Tag color={row.kind === 'rule' ? 'blue' : 'default'}>{v || row.name}</Tag>
      ),
    },
    {
      title: t('emailReports.colFile'),
      dataIndex: 'name',
      key: 'name',
      render: (v: string, row: EflowFile) => (
        <a href={eflowDownloadUrl(row)} download={row.name}>
          {v.toLowerCase().endsWith('.xlsx')
            ? <FileExcelOutlined style={{ marginRight: '0.375rem', color: '#1d6f42' }} />
            : <FileTextOutlined style={{ marginRight: '0.375rem' }} />}
          {v}
        </a>
      ),
    },
    {
      title: t('emailReports.colSize'),
      dataIndex: 'size',
      key: 'size',
      minWidth: 110,
      align: 'right' as const,
      render: (v: number) => formatSize(v),
    },
    {
      title: t('emailReports.colTime'),
      dataIndex: 'mtime',
      key: 'mtime',
      minWidth: 180,
      render: (v: number) => formatDateTime(v),
    },
    {
      title: t('emailReports.colAction'),
      key: 'action',
      minWidth: 110,
      render: (_: unknown, row: EflowFile) => (
        <Button size="small" icon={<DownloadOutlined />} href={eflowDownloadUrl(row)} download={row.name}>
          {t('emailReports.download')}
        </Button>
      ),
    },
  ]

  // TTs and MTTR 页签的文件表：同一目录里只有本产物，任务名/类型列没有信息量，
  // 只留 文件 / 大小 / 生成时间 / 下载（下载走通用的 downloadUrl，按 row.source_id 拼）
  const mttrColumns = [
    {
      title: t('emailReports.colFile'),
      dataIndex: 'name',
      key: 'name',
      minWidth: 320,
      render: (v: string, row: Row) => (
        <a href={downloadUrl(row)} download={row.name} title={row.dir}>
          <FileExcelOutlined style={{ marginRight: '0.375rem', color: '#1d6f42' }} />
          {v}
        </a>
      ),
    },
    {
      title: t('emailReports.colSize'),
      dataIndex: 'size',
      key: 'size',
      minWidth: 110,
      align: 'right' as const,
      render: (v: number) => formatSize(v),
    },
    {
      title: t('emailReports.colTime'),
      dataIndex: 'mtime',
      key: 'mtime',
      minWidth: 180,
      render: (v: number) => formatDateTime(v),
    },
    {
      title: t('emailReports.colAction'),
      key: 'action',
      minWidth: 110,
      render: (_: unknown, row: Row) => (
        <Button size="small" icon={<DownloadOutlined />} href={downloadUrl(row)} download={row.name}>
          {t('emailReports.download')}
        </Button>
      ),
    },
  ]

  // ========== 导出 ==========
  /* 三个页签各导一份「当前页签表格的全量行」——与界面显示的列一一对应，
     不含操作列（下载按钮在 Excel 里没有意义）。
     行的范围与 dataSource 一致（这些表 pagination={false}，无分页截断）。 */
  const exportEmail = useCallback(async () => {
    if (!rows.length) return
    await exportReport([{
      name: 'Email Reports',
      title: t('emailReports.title'),
      header: [
        t('emailReports.colTask'), t('emailReports.colType'), t('emailReports.colFile'),
        t('emailReports.colSize'), t('emailReports.colTime'),
      ],
      rows: rows.map(r => [
        r.task_name, r.label, r.name, formatSize(r.size), formatDateTime(r.mtime),
      ]),
      numericCols: [],
      columnWidths: [26, 24, 40, 12, 20],
      tabColor: '#2F5496',
    }], `email_reports_${stamp()}.xlsx`)
  }, [rows, t])

  const exportFinebi = useCallback(async () => {
    if (!finebiRows.length) return
    await exportReport([{
      name: 'FineBI Reports',
      title: t('emailReports.tabFinebi'),
      header: [
        t('emailReports.finebiColFolder'), t('emailReports.colFile'),
        t('emailReports.colSize'), t('emailReports.colTime'),
      ],
      rows: finebiRows.map(r => [r.folder, r.name, formatSize(r.size), formatDateTime(r.mtime)]),
      columnWidths: [34, 44, 12, 20],
      tabColor: '#548235',
    }], `finebi_reports_${stamp()}.xlsx`)
  }, [finebiRows, t])

  const exportEflowCheck = useCallback(async () => {
    const breakdown = eflowSummary?.rule_breakdown || []
    if (!breakdown.length && !eflowFiles.length) return
    const sheets: ReportSheetSpec[] = []
    // ① 摘要（统计卡 + 变更方向）：与页面顶部 Statistic/变更标签同一口径
    if (eflowSummary) {
      const rowsSummary: (string | number)[][] = [
        [t('emailReports.eflowStatTotal'), eflowSummary.total],
        [t('emailReports.eflowStatMatched'), eflowSummary.matched],
        [t('emailReports.eflowStatChanged'), eflowSummary.changed],
        [t('emailReports.eflowStatRunAt'), eflowSummary.generated_at],
      ]
      if (eflowSummary.rules_count != null) {
        rowsSummary.push([t('emailReports.rulesCollected'), eflowSummary.rules_count])
      }
      ;(eflowSummary.change_matrix || []).forEach(c => {
        rowsSummary.push([`${c.from} → ${c.to}`, c.count])
      })
      sheets.push({
        name: 'Summary',
        title: `${t('emailReports.tabEflowCheck')} · ${t('emailReports.eflowColRule')}`,
        header: [t('emailReports.eflowColRule'), t('emailReports.eflowColMatched')],
        rows: rowsSummary,
        numericCols: [1],
        columnWidths: [34, 18],
        tabColor: '#2F5496',
      })
    }
    // ② 规则明细（界面主表）
    if (breakdown.length) {
      sheets.push({
        name: 'Rules',
        title: t('emailReports.eflowColRule'),
        header: [
          t('emailReports.eflowColPri'), t('emailReports.eflowColRule'),
          t('emailReports.eflowColSeverity'), t('emailReports.eflowColMatched'),
          t('emailReports.eflowColChanged'),
        ],
        rows: breakdown.map(r => [
          r.priority ?? '', r.rule_name, r.severity, r.matched, r.changed,
        ]),
        numericCols: [0, 3, 4],
        valueColors: [4],
        columnWidths: [10, 40, 14, 12, 12],
        tabColor: '#BF8F00',
      })
    }
    // ③ 可下载产物清单
    if (eflowFiles.length) {
      sheets.push({
        name: 'Files',
        title: t('emailReports.eflowFilesLabel'),
        header: [t('emailReports.colType'), t('emailReports.colFile'), t('emailReports.colSize'), t('emailReports.colTime')],
        rows: eflowFiles.map(f => [f.label || f.name, f.name, formatSize(f.size), formatDateTime(f.mtime)]),
        columnWidths: [30, 44, 12, 20],
        tabColor: '#843C0C',
      })
    }
    await exportReport(sheets, `eflow_tt_rules_check_${stamp()}.xlsx`)
  }, [eflowSummary, eflowFiles, t])

  const exportMttr = useCallback(async () => {
    if (!mttrRows.length) return
    await exportReport([{
      name: 'TTs and MTTR Files',
      title: t('emailReports.tabTtMttr'),
      header: [t('emailReports.colFile'), t('emailReports.colSize'), t('emailReports.colTime')],
      rows: mttrRows.map(r => [r.name, formatSize(r.size), formatDateTime(r.mtime)]),
      columnWidths: [46, 12, 20],
      tabColor: '#C55A11',
    }], `tt_mttr_reports_${stamp()}.xlsx`)
  }, [mttrRows, t])

  return (
    <div style={pageWrap}>
      {/* 标题在「被门户无外壳嵌入」时不渲染：外层（门户那行 Auto Report Files）已经
          写了同一块功能的名字，这里再写一遍就是叠罗汉。独立打开时照常带标题。
          ⚠️ 只是不渲染标题，i18n 键 emailReports.title 必须保留 ——
          下面 exportEmail() 的 exportReport 还用它当 Excel 工作表名（搜 emailReports.title）。 */}
      <Card style={cardStyle} title={embed ? undefined : t('emailReports.title')}>
        <Tabs
          defaultActiveKey="email"
          /* 门户 v2 精简模式（?portalFiles=1）只有一个页签：页签条本身用 renderTabBar
             整体隐藏 —— 单个页签「Latest Email」单独占一行，与面板外层标题
             「Auto Report Files」语义重复、视觉上也是白占一行。其余场景（独立打开、
             MsPortal / olbrportal / v1 内嵌）portalFiles 为 false，页签条照常渲染。 */
          renderTabBar={portalFiles ? () => <></> : undefined}
          /* finebi / eflow_tt_rules_check / tt_mttr 三项在精简模式下滤掉，只留 email。 */
          items={[
            {
              key: 'email',
              label: t('emailReports.tabEmail'),
              children: (
                <>
                  <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
                    {/* 提示语在门户 v2 精简模式下不渲染：外层面板已有标题，这句「列出各邮件发送
                        任务生成的最新报告文件…」对只看附件的人没有信息量。独立打开 / 其它门户照常。 */}
                    {!portalFiles && <Text type="secondary">{t('emailReports.hint')}</Text>}
                    <Space>
                      <Select
                        size="small"
                        value={limit}
                        onChange={v => setLimit(v)}
                        style={{ width: 'min(100%, 9.375rem)' }}
                        options={[1, 3, 5].map(n => ({ value: n, label: t('emailReports.keepN').replace('{n}', String(n)) }))}
                      />
                      <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>
                        {t('emailReports.refresh')}
                      </Button>
                      <Button size="small" icon={<DownloadOutlined />} onClick={() => void exportEmail()} disabled={!rows.length}>
                        {t('common.exportExcel')}
                      </Button>
                    </Space>
                  </div>
                  <div className="wh-table-responsive">
                    <Table
                      size="small"
                      rowKey="key"
                      loading={loading}
                      columns={columns as any}
                      dataSource={rows}
                      pagination={false}
                      scroll={{ x: 'max-content' }}
                      locale={{ emptyText: <Empty description={t('emailReports.empty')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                    />
                  </div>
                </>
              ),
            },
            {
              key: 'finebi',
              label: t('emailReports.tabFinebi'),
              children: (
                <>
                  <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
                    <Text type="secondary">{t('emailReports.finebiHint')}</Text>
                    <Button size="small" icon={<ReloadOutlined />} onClick={loadFinebi} loading={finebiLoading}>
                      {t('emailReports.refresh')}
                    </Button>
                    <Button size="small" icon={<DownloadOutlined />} onClick={() => void exportFinebi()} disabled={!finebiRows.length}>
                      {t('common.exportExcel')}
                    </Button>
                  </div>
                  <div className="wh-table-responsive">
                    <Table
                      size="small"
                      rowKey="key"
                      loading={finebiLoading}
                      columns={finebiColumns as any}
                      dataSource={finebiRows}
                      pagination={false}
                      scroll={{ x: 'max-content' }}
                      locale={{ emptyText: <Empty description={t('emailReports.finebiEmpty')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                    />
                  </div>
                </>
              ),
            },
            {
              key: 'eflow_tt_rules_check',
              label: t('emailReports.tabEflowCheck'),
              children: (
                <>
                  <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
                    <Text type="secondary" style={{ maxWidth: '60rem' }}>{t('emailReports.eflowHint')}</Text>
                    <Space wrap>
                      <Button
                        size="small"
                        icon={<ThunderboltOutlined />}
                        onClick={() => runTaskNow('eflow_tt_rules_check', t('emailReports.eflowRunOk'), t('emailReports.eflowRunFail'))}
                        loading={eflowRunningTask === 'eflow_tt_rules_check'}
                      >
                        {t('emailReports.eflowRunNow')}
                      </Button>
                      <Button
                        size="small"
                        icon={<ThunderboltOutlined />}
                        onClick={() => runTaskNow('eflow_alarm_rules_collect', t('emailReports.eflowRunOk'), t('emailReports.eflowRunFail'))}
                        loading={eflowRunningTask === 'eflow_alarm_rules_collect'}
                      >
                        {t('emailReports.eflowRunAlarm')}
                      </Button>
                      <Button
                        size="small"
                        icon={<ThunderboltOutlined />}
                        onClick={() => runTaskNow('eflow_push_rules_collect', t('emailReports.eflowRunOk'), t('emailReports.eflowRunFail'))}
                        loading={eflowRunningTask === 'eflow_push_rules_collect'}
                      >
                        {t('emailReports.eflowRunPush')}
                      </Button>
                      <Button size="small" icon={<ReloadOutlined />} onClick={loadEflowCheck} loading={eflowLoading}>
                        {t('emailReports.refresh')}
                      </Button>
                      <Button
                        size="small"
                        icon={<DownloadOutlined />}
                        onClick={() => void exportEflowCheck()}
                        disabled={!(eflowSummary?.rule_breakdown?.length || eflowFiles.length)}
                      >
                        {t('common.exportExcel')}
                      </Button>
                    </Space>
                  </div>
                  {eflowSummary ? (
                    <>
                      {/* 有字段取不到 → 对应规则永远不会命中。必须显式展示，
                          否则用户只看到「规则表里少了一条」，会当成统计不全。 */}
                      {eflowSummary.success
                        && eflowSummary.missing_fields
                        && Object.keys(eflowSummary.missing_fields).length > 0 && (
                        <Alert
                          type="warning"
                          showIcon
                          style={{ marginBottom: '0.75rem' }}
                          message={t('emailReports.eflowMissingFields', {
                            detail: Object.entries(eflowSummary.missing_fields)
                              .map(([f, ids]) => `${f}（${t('emailReports.eflowMissingRules')} ${ids.join(', ')}）`)
                              .join('；'),
                          })}
                        />
                      )}
                      {/* 摘要与矫正表不同源：卡片数字（来自 JSON）和下钻明细（来自 xlsx）
                          会是两次不同运行的结果。沉默会让人以为是下钻的 bug。 */}
                      {eflowSummary.success && eflowSummary.correction_drift && (
                        <Alert
                          type="warning"
                          showIcon
                          style={{ marginBottom: '0.75rem' }}
                          message={t('emailReports.eflowDrift')}
                        />
                      )}
                      {!eflowSummary.success ? (
                        <div style={{ marginBottom: '0.75rem' }}>
                          <Tag color="red">FAIL</Tag>
                          <Text type="danger">{eflowSummary.error || 'unknown error'}</Text>
                        </div>
                      ) : (
                        <Row gutter={[16, 16]} style={{ marginBottom: '0.75rem' }}>
                          {/* 四个统计卡里前三个是「可下钻的数字」（AGENTS.md 三.1b），
                              第四个是时间戳，没有明细可跳，保持纯文本。 */}
                          {/* Statistic 本身不收 onClick（antd 类型里没有这个属性），
                              点击挂在外层 div 上。 */}
                          <Col xs={12} sm={6}>
                            <div
                              role="button"
                              tabIndex={0}
                              style={{ cursor: 'pointer' }}
                              onClick={e => void openEflowDrill({
                                metric: 'total',
                                title: t('emailReports.drillTotalTitle'),
                              }, { x: e.clientX, y: e.clientY })}
                              onKeyDown={e => { if (e.key === 'Enter') void openEflowDrill({ metric: 'total', title: t('emailReports.drillTotalTitle') }, (() => { const r = e.currentTarget.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } })()) }}
                            >
                              <Statistic title={t('emailReports.eflowStatTotal')} value={eflowSummary.total} />
                            </div>
                          </Col>
                          <Col xs={12} sm={6}>
                            <div
                              role="button"
                              tabIndex={0}
                              style={{ cursor: 'pointer' }}
                              onClick={e => void openEflowDrill({
                                metric: 'matched',
                                title: t('emailReports.drillMatchedTitle'),
                              }, { x: e.clientX, y: e.clientY })}
                              onKeyDown={e => { if (e.key === 'Enter') void openEflowDrill({ metric: 'matched', title: t('emailReports.drillMatchedTitle') }, (() => { const r = e.currentTarget.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } })()) }}
                            >
                              <Statistic
                                title={t('emailReports.eflowStatMatched')}
                                value={eflowSummary.matched}
                                suffix={`/ ${eflowSummary.total}`}
                              />
                            </div>
                          </Col>
                          <Col xs={12} sm={6}>
                            <div
                              role="button"
                              tabIndex={0}
                              style={{ cursor: 'pointer' }}
                              onClick={e => void openEflowDrill({
                                metric: 'unmatched',
                                title: t('emailReports.drillUnmatchedTitle'),
                              }, { x: e.clientX, y: e.clientY })}
                              onKeyDown={e => { if (e.key === 'Enter') void openEflowDrill({ metric: 'unmatched', title: t('emailReports.drillUnmatchedTitle') }, (() => { const r = e.currentTarget.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } })()) }}
                            >
                              <Statistic
                                title={t('emailReports.eflowStatUnmatched')}
                                value={eflowSummary.unmatched ?? (eflowSummary.total - eflowSummary.matched)}
                                valueStyle={{ color: '#cf1322' }}
                              />
                            </div>
                          </Col>
                          <Col xs={12} sm={6}>
                            <div
                              role="button"
                              tabIndex={0}
                              style={{ cursor: 'pointer' }}
                              onClick={e => void openEflowDrill({
                                metric: 'changed',
                                title: t('emailReports.drillChangedTitle'),
                              }, { x: e.clientX, y: e.clientY })}
                              onKeyDown={e => { if (e.key === 'Enter') void openEflowDrill({ metric: 'changed', title: t('emailReports.drillChangedTitle') }, (() => { const r = e.currentTarget.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } })()) }}
                            >
                              <Statistic
                                title={t('emailReports.eflowStatChanged')}
                                value={eflowSummary.changed}
                                valueStyle={eflowSummary.changed ? { color: '#cf1322' } : undefined}
                              />
                            </div>
                          </Col>
                          <Col xs={12} sm={6}><Statistic title={t('emailReports.eflowStatRunAt')} value={eflowSummary.generated_at} /></Col>
                        </Row>
                      )}
                      {eflowSummary.rules_collected && (
                        <div style={{ marginBottom: '0.75rem' }}>
                          <Space wrap>
                            <Text type="secondary">{t('emailReports.rulesCollected')}</Text>
                            {eflowSummary.rules_collected.success
                              ? <Tag color="green">{t('emailReports.rulesOk')}</Tag>
                              : <Tag color="red">{t('emailReports.rulesFail')}</Tag>}
                            <Text type="secondary">
                              {eflowSummary.rules_count != null ? t('emailReports.rulesCount', { n: eflowSummary.rules_count }) : ''}
                              {eflowSummary.rules_collected.rules_file_exists ? t('emailReports.rulesFileReady') : t('emailReports.rulesFileMissing')}
                            </Text>
                          </Space>
                        </div>
                      )}
                      {/* ===== 级别对照卡（2026-10-23）=====
                          单子实际级别 vs 新规则建议级别，各 P1~P4 单数对照。
                          每一格都可下钻；「建议」一侧点开能看到规则变化（当前→目标+命中依据）。 */}
                      {sevMatrix && (
                        <Card
                          size="small"
                          style={{ marginBottom: '0.75rem' }}
                          title={t('emailReports.sevMatrixTitle')}
                        >
                          <div className="wh-table-responsive">
                            <Table
                              size="small"
                              rowKey="level"
                              pagination={false}
                              dataSource={sevMatrix.levels.map(lv => ({ level: lv }))}
                              columns={[
                                {
                                  title: t('emailReports.sevMatrixLevel'),
                                  dataIndex: 'level',
                                  width: 90,
                                  render: (v: string) => <Tag color="blue">{v}</Tag>,
                                },
                                {
                                  title: t('emailReports.sevMatrixActual'),
                                  dataIndex: 'level',
                                  width: 150,
                                  align: 'center' as const,
                                  render: (lv: string) => {
                                    const n = sevMatrix.actual[lv] ?? 0
                                    return (
                                      <DrillLink
                                        label={String(n)}
                                        disabled={!n}
                                        onClick={e => void openEflowDrill({
                                          metric: 'cur_sev',
                                          sevFrom: lv,
                                          title: `${t('emailReports.drillActualSevTitle')} · ${lv}`,
                                        }, { x: e.clientX, y: e.clientY })}
                                      />
                                    )
                                  },
                                },
                                {
                                  title: t('emailReports.sevMatrixProposed'),
                                  dataIndex: 'level',
                                  width: 150,
                                  align: 'center' as const,
                                  render: (lv: string) => {
                                    const n = sevMatrix.proposed[lv] ?? 0
                                    return (
                                      <DrillLink
                                        label={String(n)}
                                        disabled={!n}
                                        onClick={e => void openEflowDrill({
                                          metric: 'new_sev',
                                          sevFrom: lv,
                                          title: `${t('emailReports.drillNewSevTitle')} · ${lv}`,
                                        }, { x: e.clientX, y: e.clientY })}
                                      />
                                    )
                                  },
                                },
                                {
                                  title: t('emailReports.sevMatrixDelta'),
                                  dataIndex: 'level',
                                  width: 140,
                                  align: 'center' as const,
                                  render: (lv: string) => {
                                    const d = (sevMatrix.proposed[lv] ?? 0) - (sevMatrix.actual[lv] ?? 0)
                                    if (!d) return <Text type="secondary">0</Text>
                                    return (
                                      <Text strong style={{ color: d > 0 ? '#389e0d' : '#cf1322' }}>
                                        {d > 0 ? `+${d}` : d}
                                      </Text>
                                    )
                                  },
                                },
                              ] as any}
                            />
                          </div>
                          <div style={{ marginTop: '0.375rem' }}>
                            <Text type="secondary">
                              {t('emailReports.sevMatrixHint', {
                                total: sevMatrix.total,
                                moved: sevMatrix.moved,
                              })}
                            </Text>
                          </div>
                        </Card>
                      )}
                      {eflowSummary.change_matrix && eflowSummary.change_matrix.length > 0 && (
                        <div style={{ marginBottom: '0.75rem' }}>
                          <Space wrap>
                            <Text type="secondary">{t('emailReports.changeDir')}</Text>
                            {eflowSummary.change_matrix.map((c, i) => (
                              // count 也要可点（AGENTS.md 三.1b）：点开就是该方向下的全部 TT
                              <Tag
                                key={i}
                                color="orange"
                                style={{ cursor: 'pointer' }}
                                onClick={e => void openEflowDrill({
                                  metric: 'shift',
                                  sevFrom: c.from,
                                  sevTo: c.to,
                                  title: `${t('emailReports.drillShiftTitle')} · ${c.from} → ${c.to}`,
                                }, { x: e.clientX, y: e.clientY })}
                              >
                                {c.from} → {c.to}: {c.count}
                              </Tag>
                            ))}
                          </Space>
                        </div>
                      )}
                      <div className="wh-table-responsive">
                        <Table
                          size="small"
                          rowKey="rule_id"
                          loading={eflowLoading}
                          columns={eflowColumns as any}
                          dataSource={eflowSummary.rule_breakdown || []}
                          pagination={false}
                          scroll={{ x: 'max-content' }}
                          locale={{ emptyText: <Empty description={t('emailReports.eflowEmpty')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                        />
                      </div>
                    </>
                  ) : (
                    <Empty description={t('emailReports.eflowNotRun')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  )}
                  {eflowFiles.length > 0 && (
                    <div style={{ marginTop: '0.75rem' }}>
                      <Text type="secondary">{t('emailReports.eflowFilesLabel')}</Text>
                      <div className="wh-table-responsive" style={{ marginTop: '0.375rem' }}>
                        <Table
                          size="small"
                          rowKey="name"
                          columns={eflowFileColumns as any}
                          dataSource={eflowFiles}
                          pagination={false}
                          scroll={{ x: 'max-content' }}
                        />
                      </div>
                    </div>
                  )}
                </>
              ),
            },
            {
              key: 'tt_mttr',
              label: t('emailReports.tabTtMttr'),
              children: (
                <>
                  <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
                    <Text type="secondary" style={{ maxWidth: '60rem' }}>{t('emailReports.mttrHint')}</Text>
                    <Space wrap>
                      <Button
                        size="small"
                        type="primary"
                        icon={<ThunderboltOutlined />}
                        onClick={() => void generateMttr()}
                        loading={mttrGenerating}
                      >
                        {mttrGenerating ? t('emailReports.mttrGenerating') : t('emailReports.mttrRunNow')}
                      </Button>
                      <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>
                        {t('emailReports.refresh')}
                      </Button>
                      <Button size="small" icon={<DownloadOutlined />} onClick={() => void exportMttr()} disabled={!mttrRows.length}>
                        {t('common.exportExcel')}
                      </Button>
                    </Space>
                  </div>
                  {mttrGenerating && (
                    <div style={{ marginBottom: '0.75rem' }}>
                      <Text type="secondary">{t('emailReports.mttrWaiting')}</Text>
                    </div>
                  )}
                  <div className="wh-table-responsive">
                    <Table
                      size="small"
                      rowKey="key"
                      loading={loading}
                      columns={mttrColumns as any}
                      dataSource={mttrRows}
                      pagination={false}
                      scroll={{ x: 'max-content' }}
                      locale={{ emptyText: <Empty description={t('emailReports.mttrEmpty')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                    />
                  </div>
                </>
              ),
            },
          ].filter(tab => !portalFiles || tab.key === 'email')}
        />
      </Card>

      {/* ===== eFlow TT Rules Check 的 TT 级下钻弹窗（2026-10-23）=====
          统计卡的每个数字、变更方向标签、规则表每一行都能点到这里；
          行数口径与卡片数字同源（都来自 eflow_tt_severity_correction.xlsx）。
          详情行的下钻按钮会把 alarm_code / 规则 作为附加过滤再查一次，
          这样从「未匹配 → 某告警码」一路都能落到具体 TT。 */}
      <DraggableClickModal
        open={drillTarget != null}
        anchor={drillAnchor}
        title={(
          <span>
            {drillTarget?.title || ''}
            {drillMeta && (
              <Tag color="cyan" style={{ borderRadius: 10, marginLeft: '0.5rem' }}>
                {t('common.records', { n: filteredDrillRows.length })}
              </Tag>
            )}
          </span>
        )}
        onClose={closeEflowDrill}
        width="92%"
        maxWidth="87.5rem"
      >
        {drillError && (
          <Alert type="error" showIcon message={drillError} style={{ marginBottom: '0.75rem' }} />
        )}
        {/* 截断必须显式暴露（AGENTS.md 三.1b）：否则用户看到行数少于卡片数字会当成 bug */}
        {drillMeta?.truncated && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: '0.75rem' }}
            message={t('emailReports.drillTruncated', { n: drillMeta.limit, total: drillMeta.total })}
          />
        )}

        {/* 未匹配分布：点「未匹配」卡片时出现，点某行再下钻到该告警码的全部未匹配 TT */}
        {drillTarget?.metric === 'unmatched' && (
          <div style={{ marginBottom: '0.75rem' }}>
            <Text type="secondary">{t('emailReports.drillUnmatchedDistHint')}</Text>
            {unmatchedGroups && unmatchedGroups.length > 0 ? (
              <div className="wh-table-responsive" style={{ marginTop: '0.375rem' }}>
                <Table
                  size="small"
                  rowKey={r => `${r.alarm_code}|${r.vip_site}|${r.site_type}`}
                  pagination={false}
                  dataSource={unmatchedGroups}
                  columns={[
                    {
                      title: t('emailReports.drillColAlarm'),
                      dataIndex: 'alarm_code',
                      render: (v: string | number | null) => (v == null ? '—' : String(v)),
                    },
                    { title: t('emailReports.drillColVip'), dataIndex: 'vip_site', render: (v: string | null) => v || '—' },
                    { title: t('emailReports.drillColSiteType'), dataIndex: 'site_type', render: (v: string | null) => v || '—' },
                    {
                      title: t('emailReports.drillColCount'),
                      dataIndex: 'count',
                      align: 'right' as const,
                      render: (v: number, r: EflowUnmatchedGroup) => (
                        <DrillLink
                          label={String(v)}
                          onClick={e => void openEflowDrill({
                            metric: 'unmatched',
                            alarmCode: r.alarm_code == null ? '' : String(r.alarm_code),
                            title: `${t('emailReports.drillUnmatchedTitle')} · ${t('emailReports.drillColAlarm')} ${r.alarm_code ?? '—'}`,
                          }, { x: e.clientX, y: e.clientY })}
                        />
                      ),
                    },
                  ]}
                />
              </div>
            ) : (
              !drillLoading && <Empty description={t('common.noData')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </div>
        )}

        {/* 工具栏：搜索 + 导出 —— 与项目其它下钻弹窗（AlarmDashboard / NocAnalyst）结构一致 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
          <Input
            prefix={<SearchOutlined />}
            placeholder={t('common.searchAllFields')}
            allowClear
            size="middle"
            style={{ width: 'min(100%, 21.875rem)' }}
            value={drillSearch}
            onChange={e => setDrillSearch(e.target.value)}
          />
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={() => void exportEflowDrill()}
            disabled={!filteredDrillRows.length}
          >
            {t('common.exportExcel')}
          </Button>
        </div>
        {drillLoading ? (
          <Spin style={{ display: 'block', margin: '3.75rem auto' }} />
        ) : (
          <div className="wh-table-responsive">
            <Table
              size="small"
              rowKey="tt_no"
              columns={eflowDrillColumns(t) as any}
              dataSource={filteredDrillRows}
              pagination={{
                pageSize: 15,
                size: 'small',
                showTotal: (total: number) => t('common.itemsTotal', { n: total }),
              }}
              scroll={{ x: 'max-content' }}
              locale={{ emptyText: <Empty description={t('common.noData')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
            />
          </div>
        )}
        {drillMeta && (
          <div style={{ marginTop: '0.375rem' }}>
            <Text type="secondary">
              {t('common.total')} {drillMeta.total} {t('common.items')}
            </Text>
          </div>
        )}
      </DraggableClickModal>
    </div>
  )
}
