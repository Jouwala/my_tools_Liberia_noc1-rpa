import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Collapse,
  Drawer,
  Empty,
  Input,
  Spin,
  Tag,
  Tree,
  Typography,
  Button,
  Spin as SpinIcon,
} from 'antd'
import {
  BookOutlined,
  FileTextOutlined,
  FolderOutlined,
  MenuOutlined,
  RobotOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import api from '../api'
import { useI18n } from '../i18n'
import { useIsMobile, useTheme } from '../theme'

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
  const [ttAi, setTtAi] = useState<any>(null)
  const [ttAiLoading, setTtAiLoading] = useState(false)
  const [ttAlarm, setTtAlarm] = useState<any>(null)
  const [ttAlarmLoading, setTtAlarmLoading] = useState(false)
  const [ttAlarmLookup, setTtAlarmLookup] = useState<any>(null)

  // 移动端：目录树抽屉
  const [treeOpen, setTreeOpen] = useState(false)

  const runTt = useCallback((no: string) => {
    const clean = no.trim().toUpperCase()
    if (!clean) return
    setTtNo(clean)
    setTtView(true)
    setTtLoading(true)
    setTtError('')
    setTtAi(null)
    setTtAiLoading(true)
    setTtAlarm(null)
    setTtAlarmLookup(null)
    setTtAlarmLoading(false)
    // 基础报告（本地 sqlite，快）先到先显；告警与 AI 各自独立加载
    api.get('/eflow-qa/inspect-tt', { params: { tt: clean } }).then(res => {
      const rep = res.data.report
      setTtReport(rep)
      if (rep?.found && rep.alarm?.found) {
        setTtAlarm(rep.alarm)
        setTtAlarmLookup({ mode: 'local', source: rep.alarm.source })
      } else if (rep?.found) {
        // 本地告警库未命中 → 单独查 eFlow 活接口（较慢，不阻塞其它块）
        setTtAlarmLoading(true)
        api.get('/eflow-qa/tt-alarm', { params: { tt: clean } }).then(r2 => {
          setTtAlarm(r2.data.alarm)
          setTtAlarmLookup(r2.data.alarm_lookup)
        }).catch(() => setTtAlarmLookup({ mode: 'error', error: t('qa.tt.alarmQueryFailed') }))
          .finally(() => setTtAlarmLoading(false))
      }
    }).catch(() => setTtError(t('qa.tt.failed'))).finally(() => setTtLoading(false))
    // AI 结论并行请求（Open WebUI「TT单分析」技能，约 10s）
    api.get('/eflow-qa/tt-ai', { params: { tt: clean } }).then(res => {
      setTtAi(res.data.ai)
      const rep = res.data.report
      // tt-ai 内部同样会回填 eFlow 兜底结果，告警块未到则顺带补上
      if (rep?.alarm?.found) setTtAlarm((prev: any) => prev || rep.alarm)
    }).catch(() => { /* AI 失败不阻塞工单信息展示 */ }).finally(() => setTtAiLoading(false))
  }, [t])

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
    setSearching(true)
    setSearched(true)
    api.get('/eflow-qa/search', { params: { q, lang: locale } }).then(res => {
      setHits(resolveLang(res.data.hits || [], locale))
      setSearchTerms(res.data.terms || terms)
    }).catch(() => setHits([])).finally(() => setSearching(false))
  }, [locale])

  const panelBg = isDark ? '#0f2744' : '#ffffff'
  const border = isDark ? '1px solid rgba(100,255,218,0.2)' : '1px solid #d9e6f2'

  const mdStyle = `
    .eflowqa-md { line-height: 1.75; font-size: 0.9375rem; }
    .eflowqa-md h1, .eflowqa-md h2, .eflowqa-md h3, .eflowqa-md h4 { margin: 1.2em 0 0.5em; color: ${isDark ? '#e2e8f0' : '#1e293b'}; }
    .eflowqa-md h1 { font-size: 1.35em; border-bottom: 1px solid ${isDark ? 'rgba(100,255,218,0.2)' : '#d9e6f2'}; padding-bottom: 0.3em; }
    .eflowqa-md h2 { font-size: 1.2em; }
    .eflowqa-md h3 { font-size: 1.05em; }
    .eflowqa-md p { margin: 0.6em 0; }
    .eflowqa-md table { border-collapse: collapse; margin: 0.8em 0; width: 100%; font-size: 0.875em; }
    .eflowqa-md th, .eflowqa-md td { border: 1px solid ${isDark ? 'rgba(148,163,184,0.35)' : '#cbd5e1'}; padding: 6px 10px; text-align: left; }
    .eflowqa-md th { background: ${isDark ? 'rgba(19,194,194,0.12)' : '#f0f5fa'}; }
    .eflowqa-md code { background: ${isDark ? 'rgba(100,255,218,0.1)' : 'rgba(13,148,136,0.08)'}; padding: 1px 5px; border-radius: 4px; font-size: 0.875em; }
    .eflowqa-md pre { background: ${isDark ? '#0a1929' : '#0f172a'}; color: ${isDark ? '#dbeafe' : '#e2e8f0'}; padding: 12px 14px; border-radius: 8px; overflow-x: auto; }
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
      <Input.Search
        placeholder={t('qa.searchPlaceholder')}
        enterButton={t('qa.search')}
        value={query}
        onChange={e => setQuery(e.target.value)}
        onSearch={doSearch}
        allowClear
      />
      <div style={{ borderTop: isDark ? '1px solid rgba(100,255,218,0.15)' : '1px solid #e5eef5', margin: '2px 0' }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
    <div style={isMobile
      ? { display: 'flex', flexDirection: 'column', gap: 10, flexShrink: 0 }
      : { display: 'flex', gap: 12, height: 'calc(100vh - var(--wh-header-height) - var(--wh-content-margin) * 2 - var(--wh-content-padding) * 2)', minHeight: 480 }
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
              <Button size="small" style={{ marginLeft: 'auto' }} onClick={() => setTtView(false)}>{t('qa.tt.back')}</Button>
            </div>
            {ttLoading && (
              <div style={{ textAlign: 'center', padding: 60 }}>
                <Spin size="large" />
                <div style={{ marginTop: 12, color: isDark ? '#94a3b8' : '#64748b' }}>{t('qa.tt.analyzing')}</div>
              </div>
            )}
            {!ttLoading && ttError && <Text type="danger">{ttError}</Text>}
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
              const cardStyle = { border, borderRadius: 8, padding: '10px 14px', marginBottom: 10, background: isDark ? 'rgba(100,255,218,0.04)' : '#fafcfe' }
              return (
                <div>
                  {/* AI 分析结论（TT单分析技能，页面顶部） */}
                  {ttAiLoading && (
                    <div style={{ ...cardStyle, background: isDark ? 'rgba(24,144,255,0.06)' : '#f0f7ff' }}>
                      <RobotOutlined style={{ color: '#1677ff', marginRight: 8 }} />
                      <Text strong>{t('qa.tt.aiConclusion')}</Text>
                      <div style={{ marginTop: 6, color: isDark ? '#94a3b8' : '#64748b', fontSize: 13 }}>{t('qa.tt.aiAnalyzing')}</div>
                    </div>
                  )}
                  {!ttAiLoading && ttAi && !ttAi.ok && (
                    <div style={cardStyle}>
                      <Alert type="error" showIcon message={`${t('qa.tt.aiFailed')}${ttAi.error}`} />
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
                      <div style={{ marginTop: 8, fontSize: 12, color: isDark ? '#94a3b8' : '#64748b' }}>
                        {ttAi.skill_title && <Tag color="blue" style={{ marginRight: 6 }}>{ttAi.skill_title}</Tag>}
                        {ttAi.model && <Tag style={{ marginRight: 6 }}>{ttAi.model}</Tag>}
                        {ttAi.alarm_source && <Tag color="cyan" style={{ marginRight: 6 }}>{t('qa.tt.alarmSource')}: {ttAi.alarm_source}</Tag>}
                        {ttAi.elapsed_total_sec != null && <span>{t('qa.tt.aiElapsed')}: {ttAi.elapsed_total_sec}s</span>}
                      </div>
                    </div>
                  )}

                  {/* 告警信息（本地告警库命中即显；未命中则 eFlow 活查，期间只在本卡内 loading） */}
                  {ttAlarmLoading && (
                    <div style={{ ...cardStyle, background: isDark ? 'rgba(100,255,218,0.06)' : '#f4fbfa' }}>
                      <Spin size="small" style={{ marginRight: 8 }} />
                      <Text strong>{t('qa.tt.alarmCard')}</Text>
                      <div style={{ marginTop: 6, color: isDark ? '#94a3b8' : '#64748b', fontSize: 13 }}>
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
                      label: <Text strong>{sec.section} <Text type="secondary" style={{ fontSize: 12 }}>({sec.items.length})</Text></Text>,
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

        {!ttView && searched && !docLoading && hits !== null && (
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
                    background: isDark ? 'rgba(100,255,218,0.04)' : '#fafcfe',
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
                    <div key={s.line} style={{ fontSize: 13, marginTop: 4, color: isDark ? '#94a3b8' : '#475569' }}>
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
        {!ttView && docLoading && <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>}
        {!ttView && !docLoading && docError && <Text type="danger">{docError}</Text>}
        {!ttView && !docLoading && !doc && !searched && (
          <Empty description={isMobile ? t('qa.selectDocMobile') : t('qa.selectDoc')} style={{ marginTop: isMobile ? 32 : 80 }} />
        )}
        {!ttView && !docLoading && doc && (
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
