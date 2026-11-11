import { useEffect, useState, useRef, useCallback, useMemo, cloneElement, isValidElement } from 'react'
import type { ReactElement } from 'react'
import { Card, Table, Select, Input, Tag, Spin, Tabs, Row, Col, Statistic, Progress, Descriptions, Badge, Button, Dropdown, message, Modal, Checkbox, Divider, Upload, Space, AutoComplete, Alert, Popover, Tooltip, Segmented } from 'antd'
import { DownloadOutlined, SettingOutlined, SearchOutlined, UploadOutlined, FilterOutlined, FilterFilled, EyeInvisibleOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import * as XLSX from 'xlsx'
import api from '../api'
import { useI18n, numLocale } from '../i18n'
import { cardStyle, controlCardStyle } from '../theme'
import { ExplainIcon, ExplainPopover } from '../components/MetricExplain'
// Data Agent 只读 NL2SQL 入口（探索性副驾，不参与定时报表/看板产出）。
// 定位、护栏与风险清单见 docs/DATA_AGENT_EVALUATION.md。
import DataAgentBar from '../components/DataAgentBar'
import ExcludeListUpload from '../components/ExcludeListUpload'
import { readParam, writeParams } from '../urlState'

interface TableInfo {
  name: string
  row_count: number
  col_count: number
  columns: { name: string; type: string; notnull: number; pk: number }[]
}

/** 「本地权威表」—— 内容只写本地 SQLite（`db/app.db`），而本页读的是**当前主库**。
 *
 *  **为什么要有这份清单**（2026-10-23，用户报「数据库里有，tables 页面的 credentials 是空的」）：
 *   `backend/services/credential_store.py::_get_conn` 与
 *   `backend/services/email_recipient_store.py` 刻意用裸 `sqlite3.connect` 写本地库；
 *   `backend/scripts/sync_pg_to_sqlite.py` 的 `SKIP_TABLES` 又把这三张表排除在 PG→SQLite
 *   同步之外（2026-09-18 那次「每小时 :45 凭据被抹成空」的事故就是漏了这一步）。
 *   于是 PG 里只有 SQLAlchemy 建的空壳表（`0 行`），而本页在 `MY_APP_DB_MODE=pg` 下
 *   经 `get_raw_connection()` 读的正是 PG —— 用户看到 0 行，但设置页里 19 条都在。
 *
 *  **为什么在页面上说明而不是让本页改读 SQLite**：
 *   「表浏览器 = 看当前主库」是它一贯的语义，混进另一路数据源会让所有表的行数
 *   口径变含糊（而且 PG 里同名空壳还在，两路都显示会出现两个 credentials）。
 *   这里只做**如实告知**，并给出正确入口（AGENTS.md 三.6：取不到 ≠ 0）。
 *   清单必须与 `sync_pg_to_sqlite.py::SKIP_TABLES` 保持一致，别再分叉出第二份判断。 */
const LOCAL_AUTHORITATIVE_TABLES: Record<string, string> = {
  credentials: 'settings',
  email_recipients: 'settings',
  task_schedule_config: 'settings',
}

interface ProfileColumn {
  name: string
  dtype: string
  type_category: string
  total: number
  non_null: number
  null_count: number
  null_rate: number
  unique_count: number
  unique_rate: number
  duplicate_rate: number
  issues: any[]
  issue_count: number
  stats: any
  top_values: { value: string; count: number; rate: number }[]
  outlier_count?: number
  outlier_rate?: number
  is_candidate_key?: boolean
}

interface ProfileResult {
  table_name: string
  profile: {
    total_rows: number
    total_cols: number
    columns: ProfileColumn[]
    quality_score: number
    issues_summary: any[]
  }
  conclusions: string[]
}

interface ViewTemplate {
  table_name: string
  name: string
  columns: string[]
  created_at: string
  updated_at: string
}

/** 列头筛选条件（与 backend/routers/tables.py::_build_column_filter_clause 同契约）。
 *
 *  服务端分页，所以**不能**用 antd 的本地 onFilter —— 筛选必须随请求发给
 *  /data 与 /export，否则「第一页筛了、翻页又冒出不符合条件的行」。 */
type ColFilterOp = 'contains' | 'equals' | 'in' | 'empty'
interface ColFilter {
  op: ColFilterOp
  value?: string
  values?: string[]
}

export default function TableBrowser() {
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('')
  const [tableData, setTableData] = useState<any[]>([])
  const [tableColumns, setTableColumns] = useState<any[]>([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  /* 首屏是「先取表清单 → 再取表数据」两级请求，两者都算 loading。
     2026-11-08：统一门户 Knowledge Q&A 的 Master Site 页签把本页内嵌进 iframe 时，
     门户同屏还有地图/报告/工具等多路 my_app iframe，/api/tables 会被后端排队十几秒；
     旧版 loading 初值 false，这段等待期 antd 会把「该表暂无数据」当成事实显示出来
     （取不到 ≠ 0，见 AGENTS.md 三.6），容易误判成功能坏了。初值改为 true，
     由 loadTableData 首屏结束时复位；表清单失败 / 空清单时兜底复位，不会永远转圈。 */
  const [loading, setLoading] = useState(true)
  const [profileData, setProfileData] = useState<ProfileResult | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [visibleCols, setVisibleCols] = useState<string[] | null>(null)
  const [colModalOpen, setColModalOpen] = useState(false)
  const [draftCols, setDraftCols] = useState<string[]>([])
  const [templates, setTemplates] = useState<ViewTemplate[]>([])
  const [tplName, setTplName] = useState('')
  const [colFilter, setColFilter] = useState('')
  /* 列头筛选：colFilters 用于渲染，colFiltersRef 供 loadTableData 的闭包读最新值
     （loadTableData 只依赖 selectedTable，不能把筛选条件挂进依赖里，否则每次
     输入都会重建请求函数、把正在输入的面板状态冲掉）。 */
  const [colFilters, setColFilters] = useState<Record<string, ColFilter>>({})
  const { t, locale } = useI18n()

  const searchTextRef = useRef('')
  const loadingRef = useRef(false)
  const requestIdRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSearchValueRef = useRef('')
  const lastFiltersKeyRef = useRef('')
  const colFiltersRef = useRef<Record<string, ColFilter>>({})
  const hasLoadedOnceRef = useRef(false)

  useEffect(() => { searchTextRef.current = searchText }, [searchText])

  /* 2026-11-08：支持 ?table=<表名> 深链。
     统一门户 /v3/olbrportal/ 的 Knowledge Q&A「Master Site」页签用它把默认表
     定在 master_site_db（表清单里的第一张是 kml_mw_links，不能直接当默认值）。
     ⚠️ 只在首屏加载表清单时读一次，且指定表名必须在清单里，否则回落到第一张 ——
        防止拼错 / 无权访问的表名让页面停在一个空壳 Select 上。
     页内 Select 仍是「也可以选择其他表格」的入口，不受这个初值影响。 */
  useEffect(() => {
    api.get('/tables').then(res => {
      const tbls = res.data.tables.filter((t: TableInfo) => !t.name.startsWith('_'))
      setTables(tbls)
      if (tbls.length > 0) {
        const wanted = readParam('table')
        setSelectedTable(tbls.some((tb: TableInfo) => tb.name === wanted) ? wanted : tbls[0].name)
      } else {
        setLoading(false)                 // 一张表都没有：没有后续取数来复位 loading
      }
    })
    .catch(() => { setLoading(false) })  // 表清单拉不到：别让转圈无限期挂着
  }, [])

  /* 选中的表写回地址栏（urlState.ts：URL 是页面状态的唯一真相源，一律 replaceState）。
     这样 iframe 里点门户的「刷新」、或把链接发给同事，都还能回到用户刚选的那张表；
     也保证从无参数进入 /myapp/?page=tables 时，地址栏与所见一致。
     ⚠️ writeParams 每次重读 location 再合并写，不会覆盖 App.tsx 维护的 ?page= /
        ?embed= / ?lang= / ?theme= 等参数（见 urlState.ts 的两条纪律）。 */
  useEffect(() => {
    if (!selectedTable) return
    writeParams({ table: selectedTable })
  }, [selectedTable])

  useEffect(() => {
    if (!selectedTable) return
    setVisibleCols(null)
    setTplName('')
    setSearchText('')
    searchTextRef.current = ''
    lastSearchValueRef.current = ''
    // 换表必须清列筛选：上一张表的列名/候选值对这张表毫无意义，
    // 带着走会让新表直接查出 0 行还看不出原因。
    colFiltersRef.current = {}
    lastFiltersKeyRef.current = ''
    setColFilters({})
    hasLoadedOnceRef.current = false
    loadTableData(1, '')
    loadTemplates()
}, [selectedTable])

  // ---- NUR 排除名单上传（TT_Exclude → 固定表 tt_exclude） ----
  // 实现在 components/ExcludeListUpload.tsx：与「自定义导入」是两套语义
  // （那个由用户指定表名，这个是固定表名 + 全量替换 + dry-run 护栏）。
  const [exOpen, setExOpen] = useState(false)

  // ---- 自定义导入（Excel/CSV → 自定义表名） ----
  const [importOpen, setImportOpen] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importName, setImportName] = useState('')
  const [importOverwrite, setImportOverwrite] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<any>(null)
  const [importSheets, setImportSheets] = useState<string[]>([])
  const [importSheet, setImportSheet] = useState('__all__')
  const ALL_SHEETS = '__all__'

  // 目标表名：可选已有表（下拉）或输入新表名（自由文本）
  const importNameExists = useMemo(
    () => !!importName.trim() && tables.some(tb => tb.name === importName.trim()),
    [importName, tables],
  )
  const existingTableOptions = useMemo(() => tables.map(tb => ({
    value: tb.name,
    label: (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--wh-space-sm)' }}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{tb.name}</span>
        <span style={{ color: '#999', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
          {tb.row_count.toLocaleString(numLocale(locale))} {t('common.rows')}
        </span>
      </div>
    ),
  })), [tables, locale, t])

  const suggestTableName = (filename: string) => {
    const stem = filename.replace(/\.[^.]+$/, '')
    const cleaned = stem
      .replace(/[^\w]/g, '_')
      .replace(/_+/g, '_')
      .replace(/^_+|_+$/g, '')
      .toLowerCase()
    return cleaned && /^[0-9]/.test(cleaned) ? `t_${cleaned}` : cleaned || ''
  }

  const openImport = () => {
    setImportFile(null)
    setImportName('')
    setImportOverwrite(false)
    setImportResult(null)
    setImportSheets([])
    setImportSheet(ALL_SHEETS)
    setImportOpen(true)
  }

  // 读取工作表列表（仅表头信息，不解析全部数据），失败则退回“无 sheet 选择”行为
  const detectSheets = async (file: any) => {
    setImportSheets([])
    setImportSheet(ALL_SHEETS)
    const fname = String(file?.name || '').toLowerCase()
    if (!/\.(xlsx|xlsm|xls)$/.test(fname)) return
    try {
      const raw: any = file?.originFileObj || file
      const buf: ArrayBuffer = typeof raw.arrayBuffer === 'function'
        ? await raw.arrayBuffer()
        : await new Promise<ArrayBuffer>((resolve, reject) => {
            const fr = new FileReader()
            fr.onload = () => resolve(fr.result as ArrayBuffer)
            fr.onerror = () => reject(fr.error)
            fr.readAsArrayBuffer(raw)
          })
      const wb = XLSX.read(buf, { type: 'array', bookSheets: true })
      const names: string[] = wb.SheetNames || []
      setImportSheets(names)
      setImportSheet(names.length > 1 ? ALL_SHEETS : (names[0] || ALL_SHEETS))
    } catch {
      setImportSheets([])
      setImportSheet(ALL_SHEETS)
    }
  }

  const onImportFileChange = (info: any) => {
    const file: File | undefined = info?.file
    if (file) {
      setImportFile(file)
      setImportResult(null)
      if (!importName) setImportName(suggestTableName(file.name))
      void detectSheets(file)
    }
  }

  const submitImport = () => {
    if (!importFile) { message.warning(t('table.importFileRequired')); return }
    if (!importName.trim()) { message.warning(t('table.importNameRequired')); return }
    setImporting(true)
    setImportResult(null)
    const formData = new FormData()
    formData.append('file', importFile)
    formData.append('table_name', importName.trim())
    formData.append('overwrite', String(importOverwrite))
    if (importSheets.length > 1 && importSheet) formData.append('sheet', importSheet)
    api.post('/tables/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
      .then((res) => {
        setImportResult(res.data)
        message.success(t('table.importSuccess', {
          n: res.data.tables?.length ?? 0,
          t: res.data.elapsed_seconds ?? 0,
        }))
        api.get('/tables').then((r) => {
          const tbls = (r.data.tables || []).filter((x: TableInfo) => !x.name.startsWith('_'))
          setTables(tbls)
          const first = res.data.tables?.[0]?.table_name
          if (first && tbls.some((x: TableInfo) => x.name === first)) {
            setSelectedTable(first)
          } else if (tbls.length > 0) {
            setSelectedTable(tbls[0].name)
          }
        })
      })
      .catch((err: any) => {
        message.error(t('table.importFailed', { msg: err.response?.data?.detail || err.message }))
      })
      .finally(() => setImporting(false))
  }

  const loadTemplates = () => {
    api.get('/tables/view-templates', { params: { table_name: selectedTable } })
      .then(res => setTemplates(res.data.templates || []))
      .catch(() => setTemplates([]))
  }

  // ---- MW Links (KML) 专用导入：目标表锁死 kml_mw_links，只影响 MW 叠加图层 ----
  const [mwOpen, setMwOpen] = useState(false)
  const [mwFile, setMwFile] = useState<File | null>(null)
  const [mwImporting, setMwImporting] = useState(false)
  const [mwStatus, setMwStatus] = useState<any>(null)
  const [mwResult, setMwResult] = useState<any>(null)

  const loadMwStatus = () => {
    api.get('/mw-links/status').then(r => setMwStatus(r.data)).catch(() => setMwStatus(null))
  }

  const openMwImport = () => {
    setMwFile(null)
    setMwResult(null)
    setMwStatus(null)
    loadMwStatus()
    setMwOpen(true)
  }

  const submitMwImport = () => {
    if (!mwFile) { message.warning(t('table.mwFileRequired')); return }
    setMwImporting(true)
    setMwResult(null)
    const fd = new FormData()
    fd.append('file', mwFile)
    api.post('/mw-links/import', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    })
      .then((res) => {
        setMwResult(res.data)
        setMwStatus(res.data.status)
        message.success(t('table.mwImportSuccess', {
          s: res.data.sites, l: res.data.links, t: res.data.elapsed_seconds,
        }))
      })
      .catch((err: any) => {
        message.error(t('table.importFailed', { msg: err.response?.data?.detail || err.message }))
      })
      .finally(() => setMwImporting(false))
  }

  const loadTableData = useCallback((page: number, search?: string, filters?: Record<string, ColFilter>) => {
    if (!selectedTable) return
    const effectiveSearch = search ?? searchTextRef.current
    const effectiveFilters = filters ?? colFiltersRef.current
    // 列筛选参与请求去重：只改筛选不改搜索时也是一次全新的查询，不能被误判为重复请求。
    const filtersKey = JSON.stringify(effectiveFilters)

    const isDuplicate = page === 1
      && effectiveSearch === lastSearchValueRef.current
      && filtersKey === lastFiltersKeyRef.current
      && hasLoadedOnceRef.current
    if (isDuplicate) return

    if (loadingRef.current) {
      abortRef.current?.abort()
    }

    const requestId = ++requestIdRef.current
    loadingRef.current = true

    const isInitialLoad = !hasLoadedOnceRef.current
    if (isInitialLoad) {
      setLoading(true)
    }

    const params: any = { page, page_size: 20 }
    if (effectiveSearch) params.search = effectiveSearch
    if (Object.keys(effectiveFilters).length) params.col_filters = filtersKey

    const controller = new AbortController()
    abortRef.current = controller

    api.get(`/tables/${selectedTable}/data`, { params, signal: controller.signal })
      .then(res => {
        if (requestId !== requestIdRef.current) return
        const newData = res.data.data.map((r: any, i: number) => ({ ...r, __row_index: `${page}-${i}` }))
        setTableData(newData)
        lastSearchValueRef.current = effectiveSearch
        lastFiltersKeyRef.current = filtersKey
        hasLoadedOnceRef.current = true

        const newCols = res.data.columns
        setTableColumns(prev => {
          if (prev.length === newCols.length && prev.every((c: string, i: number) => c === newCols[i])) {
            return prev
          }
          return newCols
        })

        setPagination({
          current: res.data.page,
          pageSize: res.data.page_size,
          total: res.data.total,
        })
      })
      .catch((err: any) => {
        if (err.name === 'CanceledError' || err.name === 'AbortError') return
        if (requestId !== requestIdRef.current) return
        if (isInitialLoad) {
          loadingRef.current = false
          setLoading(false)
        }
      })
      .finally(() => {
        if (requestId === requestIdRef.current) {
          loadingRef.current = false
          if (isInitialLoad) {
            setLoading(false)
          }
        }
      })
  }, [selectedTable])

  const debouncedSearch = useCallback((value: string) => {
    if (searchDebounceRef.current) {
      clearTimeout(searchDebounceRef.current)
    }
    searchDebounceRef.current = setTimeout(() => {
      setSearchText(value)
      searchTextRef.current = value
      loadTableData(1, value)
    }, 300)
  }, [loadTableData])

  const handleSearch = useCallback((value: string) => {
    if (searchDebounceRef.current) {
      clearTimeout(searchDebounceRef.current)
      searchDebounceRef.current = null
    }
    if (value === lastSearchValueRef.current && hasLoadedOnceRef.current) {
      return
    }
    setSearchText(value)
    searchTextRef.current = value
    loadTableData(1, value)
  }, [loadTableData])

  const loadProfile = () => {
    setProfileLoading(true)
    api.get(`/tables/${selectedTable}/profile`)
      .then(res => setProfileData(res.data))
      .finally(() => setProfileLoading(false))
  }

  const exportTable = (format: 'xlsx' | 'csv') => {
    if (!selectedTable) return
    const params = new URLSearchParams({ format })
    if (searchText) params.set('search', searchText)
    // 导出必须与表格当前所见一致：列筛选也要带上去（与 data 端点同一套 WHERE）。
    const cf = colFiltersRef.current
    if (Object.keys(cf).length) params.set('col_filters', JSON.stringify(cf))
    if (visibleCols && visibleCols.length) params.set('columns', visibleCols.join(','))
    message.info(t('table.exportStart'))
    window.open(`/api/tables/${encodeURIComponent(selectedTable)}/export?${params.toString()}`, '_blank')
  }

  /** 应用 / 清除某一列的筛选。传 null = 清掉该列条件。 */
  const applyColFilter = useCallback((col: string, f: ColFilter | null) => {
    const next = { ...colFiltersRef.current }
    if (f) next[col] = f
    else delete next[col]
    colFiltersRef.current = next
    setColFilters(next)
    loadTableData(1, searchTextRef.current, next)
  }, [loadTableData])

  const clearAllColFilters = useCallback(() => {
    const empty: Record<string, ColFilter> = {}
    colFiltersRef.current = empty
    setColFilters(empty)
    loadTableData(1, searchTextRef.current, empty)
  }, [loadTableData])

  /** 列头面板里的「隐藏此列」：把该列从显示列里摘掉（可随时在「自定义列」恢复）。 */
  const hideColumn = useCallback((col: string) => {
    setVisibleCols((visibleCols ?? [...tableColumns]).filter(c => c !== col))
  }, [visibleCols, tableColumns])

  const openColModal = () => {
    setDraftCols(visibleCols ?? [...tableColumns])
    setColFilter('')
    setColModalOpen(true)
  }

  const applyCols = () => {
    setVisibleCols(draftCols.length >= tableColumns.length ? null : [...draftCols])
    setColModalOpen(false)
  }

  const resetCols = () => {
    setVisibleCols(null)
    setDraftCols([...tableColumns])
    setColModalOpen(false)
  }

  const applyTemplate = (tp: ViewTemplate) => {
    setDraftCols(tp.columns.filter(c => tableColumns.includes(c)))
  }

  const saveTemplate = () => {
    const name = tplName.trim()
    if (!name) { message.warning(t('table.tplNameRequired')); return }
    if (!draftCols.length) { message.warning(t('table.noColSelected')); return }
    api.post('/tables/view-templates', {
      table_name: selectedTable, name, columns: draftCols,
    })
      .then(() => {
        message.success(t('table.templateSaved'))
        setTplName('')
        loadTemplates()
      })
      .catch(() => message.error(t('table.templateSaveFailed')))
  }

  const deleteTemplate = (name: string) => {
    api.delete('/tables/view-templates', { params: { table_name: selectedTable, name } })
      .then(() => {
        message.success(t('table.templateDeleted'))
        loadTemplates()
      })
  }

  const filterKw = colFilter.trim().toLowerCase()
  const filteredCols = filterKw
    ? tableColumns.filter((c: string) => c.toLowerCase().includes(filterKw))
    : tableColumns

  const tableInfo = tables.find(t => t.name === selectedTable)
  /** 选中的是不是「内容只在本地 SQLite」的表（见 LOCAL_AUTHORITATIVE_TABLES 注释）。 */
  const isLocalAuthoritative = !!selectedTable && selectedTable in LOCAL_AUTHORITATIVE_TABLES

  const shownCols = useMemo(() => {
    if (visibleCols) {
      return visibleCols.filter(c => tableColumns.includes(c))
    }
    return tableColumns
  }, [visibleCols, tableColumns])

  const dataColumns = useMemo(() => shownCols.map((col: string) => ({
    /* 每个列名右侧挂一个漏斗：按该列的值过滤行（服务端执行，翻页/导出都跟随）。
       这是数据过滤，与「自定义列」里的列名搜索（挑哪些列显示）是两回事。 */
    title: (
      <ColumnFilterHeader
        col={col}
        table={selectedTable}
        active={colFilters[col] || null}
        onApply={(f: ColFilter | null) => applyColFilter(col, f)}
        onClear={() => applyColFilter(col, null)}
        onHide={() => hideColumn(col)}
      />
    ),
    dataIndex: col,
    key: col,
    minWidth: 120,
    ellipsis: true,
    render: (v: any) => v === null || v === undefined ? <Tag>NULL</Tag> : String(v),
  })), [shownCols, colFilters, selectedTable, applyColFilter, hideColumn])

  const stableRowKey = useMemo(() => (record: any) => {
    if (record.__row_index) return record.__row_index
    const parts: string[] = shownCols.map((c: string) => String(record[c] ?? ''))
    const joined = parts.join('|')
    return `rec-${joined.length}-${parts.slice(0, 3).join('-').replace(/[^a-zA-Z0-9-]/g, '_')}`
  }, [shownCols])

  const filterEntries = Object.entries(colFilters)

  return (
    <div>
      <Card style={controlCardStyle}>
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} sm={12} lg={6}>
            <Select
              value={selectedTable}
              onChange={setSelectedTable}
              style={{ width: '100%' }}
              showSearch
              placeholder={t('table.selectTable')}
              options={tables.map(tbl => ({ value: tbl.name, label: `${tbl.name} (${tbl.row_count} ${t('common.rows')})` }))}
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Input.Search
              placeholder={t('table.searchPlaceholder')}
              value={searchText}
              onSearch={handleSearch}
              onChange={(e) => {
                const v = e.target.value
                setSearchText(v)
                searchTextRef.current = v
                debouncedSearch(v)
              }}
              style={{ width: '100%' }}
              allowClear
              // antd 默认 enterButton 是纯图标按钮、没有可访问名称（读屏只报「button」）。
              // 传自定义 Button 节点，cloneElement 分支会保留 aria-label 与 onClick。
              enterButton={
                <Button
                  aria-label={t('table.searchBtnAria')}
                  color="primary"
                  variant="solid"
                  icon={<SearchOutlined />}
                />
              }
            />
          </Col>
          {tableInfo && (
            <Col xs={24} lg={6}>
              <ExplainPopover text={t('table.explain.rowCount')}>
                <Tag color="blue">{tableInfo.row_count.toLocaleString(numLocale(locale))} {t('common.rows')}</Tag>
              </ExplainPopover>
              <ExplainPopover text={t('table.explain.colCount')}>
                <Tag color="green">{tableInfo.col_count} {t('common.cols')}</Tag>
              </ExplainPopover>
            </Col>
          )}
          <Col xs={24} lg={tableInfo ? 6 : 12}>
            <Space wrap style={{ width: '100%' }}>
              <Dropdown
                menu={{
                  items: [
                    { key: 'xlsx', label: 'Excel (.xlsx)' },
                    { key: 'csv', label: 'CSV (.csv)' },
                  ],
                  onClick: ({ key }) => exportTable(key as 'xlsx' | 'csv'),
                }}
              >
                <Button icon={<DownloadOutlined />} disabled={!selectedTable}>
                  {t('table.export')}
                </Button>
              </Dropdown>
              <Button icon={<UploadOutlined />} onClick={openImport}>
                {t('table.import')}
              </Button>
              <Button icon={<UploadOutlined />} onClick={() => setExOpen(true)}>
                {t('table.exBtn')}
              </Button>
              <Button icon={<UploadOutlined />} onClick={openMwImport}>
                {t('table.mwImport')}
              </Button>
              <Button icon={<SettingOutlined />} disabled={!selectedTable} onClick={openColModal}>
                {t('table.customizeCols')}
              </Button>
              {visibleCols && (
                <ExplainPopover text={t('table.explain.visibleCols', { n: shownCols.length, m: tableColumns.length })}>
                  <Tag color="orange">{t('table.visibleColsTag', { n: shownCols.length, m: tableColumns.length })}</Tag>
                </ExplainPopover>
              )}
            </Space>
          </Col>
        </Row>
        {/* 本地权威表说明（2026-10-23）：
            这三张表的真实数据只写本地 SQLite，而本页读当前主库（pg 模式下是 PG）。
            PG 里的同名表是 SQLAlchemy 建的空壳，恒 0 行 —— 不解释的话，
            用户在设置页存了 19 条凭据、来这里看到 0 行，只会当成「没存上」。
            只有表确实是空的才提示：将来若某次迁移把数据真灌进了 PG，这里自然不再出现。 */}
        {isLocalAuthoritative && tableInfo?.row_count === 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 'var(--wh-space-sm)' }}
            message={<span style={{ fontSize: 12 }}>{t('table.localAuthoritative')}</span>}
            action={
              <Button size="small" onClick={() => window.open(`${window.location.pathname}?page=${LOCAL_AUTHORITATIVE_TABLES[selectedTable]}`, '_self')}>
                {t('table.localAuthoritativeEdit')}
              </Button>
            }
          />
        )}
      </Card>

      {/* NUR 排除名单上传：固定表名 + 全量替换 + dry-run 预览 */}
      <ExcludeListUpload open={exOpen} onClose={() => setExOpen(false)} />

      <Modal
        title={t('table.colModalTitle')}
        open={colModalOpen}
        onCancel={() => setColModalOpen(false)}
        width={'min(90vw, 40rem)' as any}
        footer={[
          <Button key="reset" onClick={resetCols}>{t('table.resetCols')}</Button>,
          <Button key="cancel" onClick={() => setColModalOpen(false)}>{t('table.cancel')}</Button>,
          <Button key="ok" type="primary" onClick={applyCols}>{t('table.apply')}</Button>,
        ]}
      >
        <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <Button size="small" onClick={() => setDraftCols([...tableColumns])}>{t('table.selectAll')}</Button>
          <Button size="small" style={{ marginLeft: 'var(--wh-space-sm)' }} onClick={() => setDraftCols([])}>{t('table.clearAll')}</Button>
          <span style={{ marginLeft: 'var(--wh-space-md)', color: '#888' }}>{draftCols.length} / {tableColumns.length}</span>
        </div>
        <Input
          prefix={<SearchOutlined style={{ color: '#bbb' }} />}
          value={colFilter}
          onChange={e => setColFilter(e.target.value)}
          placeholder={t('table.filterColsPh')}
          allowClear
          style={{ marginBottom: 'var(--wh-space-sm)' }}
        />
        <div style={{ maxHeight: '17.5rem', overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 'var(--wh-radius-sm)', padding: 'var(--wh-space-sm)' }}>
          {filteredCols.length === 0 ? (
            <div style={{ color: '#999', textAlign: 'center', padding: 'var(--wh-space-sm)' }}>{t('table.noMatchCols')}</div>
          ) : (
            <Checkbox.Group value={draftCols} onChange={v => setDraftCols(v as string[])} style={{ width: '100%' }}>
              <Row>
                {filteredCols.map((c: string) => (
                  <Col xs={24} sm={12} lg={8} key={c} style={{ marginBottom: 'var(--wh-space-xs)' }}>
                    <Checkbox value={c}>{c}</Checkbox>
                  </Col>
                ))}
              </Row>
            </Checkbox.Group>
          )}
        </div>
        <Divider style={{ margin: 'var(--wh-space-sm) 0' }}>{t('table.templates')}</Divider>
        {templates.length === 0 ? (
          <div style={{ color: '#999', marginBottom: 'var(--wh-space-sm)' }}>{t('table.noTemplates')}</div>
        ) : (
          <div style={{ maxHeight: '8.75rem', overflow: 'auto', marginBottom: 'var(--wh-space-sm)' }}>
            {templates.map(tp => (
              <div key={tp.name} style={{ display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)', marginBottom: 'var(--wh-space-xs)' }}>
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{tp.name} <span style={{ color: '#999' }}>({tp.columns.length} {t('common.cols')})</span></span>
                <Button size="small" onClick={() => applyTemplate(tp)}>{t('table.loadTemplate')}</Button>
                <Button size="small" danger onClick={() => deleteTemplate(tp.name)}>{t('common.delete')}</Button>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: 'var(--wh-space-sm)' }}>
          <Input
            value={tplName}
            onChange={e => setTplName(e.target.value)}
            placeholder={t('table.templateNamePh')}
            onPressEnter={saveTemplate}
            maxLength={50}
          />
          <Button type="primary" onClick={saveTemplate}>{t('table.saveTemplate')}</Button>
        </div>
      </Modal>

      <Modal
        title={t('table.importModalTitle')}
        open={importOpen}
        onCancel={() => !importing && setImportOpen(false)}
        width={'min(90vw, 35rem)' as any}
        footer={[
          <Button key="cancel" disabled={importing} onClick={() => setImportOpen(false)}>{t('table.cancel')}</Button>,
          <Button key="ok" type="primary" loading={importing} onClick={submitImport}>
            {t('table.import')}
          </Button>,
        ]}
      >
        <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <div style={{ marginBottom: 'var(--wh-space-xs)', color: '#555' }}>{t('table.importFilePh')}</div>
          <Upload
            beforeUpload={() => false}
            maxCount={1}
            accept=".xlsx,.xls,.csv"
            fileList={importFile ? [{ uid: '-1', name: importFile.name, status: 'done' } as any] : []}
            onChange={onImportFileChange}
            onRemove={() => { setImportFile(null); setImportName(''); setImportSheets([]); setImportSheet(ALL_SHEETS) }}
          >
            <Button icon={<UploadOutlined />}>{t('table.importFilePh')}</Button>
          </Upload>
        </div>
        {importSheets.length > 1 && (
          <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
            <div style={{ marginBottom: 'var(--wh-space-xs)', color: '#555' }}>{t('table.importSheetPh')}</div>
            <Select
              value={importSheet}
              onChange={(v: string) => setImportSheet(v)}
              disabled={importing}
              style={{ width: '100%' }}
              options={[
                { value: ALL_SHEETS, label: t('table.importSheetAll', { n: importSheets.length }) },
                ...importSheets.map((s: string) => ({ value: s, label: s })),
              ]}
            />
            <div style={{ marginTop: 'var(--wh-space-xs)', color: '#999', fontSize: '0.75rem' }}>
              {importSheet === ALL_SHEETS
                ? t('table.importMultiSheetNote', { names: importSheets.join(', ') })
                : t('table.importSheetHint')}
            </div>
          </div>
        )}
        <div style={{ marginBottom: 'var(--wh-space-xs)', color: '#555' }}>{t('table.importNameLabel')}</div>
        <AutoComplete
          value={importName}
          options={existingTableOptions}
          onChange={(v: string) => setImportName(v || '')}
          filterOption={(input, option) =>
            String(option?.value ?? '').toLowerCase().includes(String(input ?? '').toLowerCase())}
          placeholder={t('table.importNamePh')}
          maxLength={63}
          allowClear
          disabled={importing}
          style={{ width: '100%' }}
        />
        <div style={{ marginTop: 'var(--wh-space-xs)', color: importNameExists ? '#fa8c16' : '#999', fontSize: '0.75rem' }}>
          {importNameExists ? t('table.importNameExists') : t('table.importNameHint')}
        </div>
        <div style={{ marginTop: 'var(--wh-space-md)' }}>
          <Checkbox checked={importOverwrite} onChange={e => setImportOverwrite(e.target.checked)} disabled={importing}>
            {t('table.importOverwrite')}
          </Checkbox>
          <span style={{ marginLeft: 'var(--wh-space-sm)', color: '#999', fontSize: '0.75rem' }}>{t('table.importOverwriteHint')}</span>
        </div>
        {importResult && (
          <div style={{ marginTop: 'var(--wh-space-md)' }}>
            {importResult.tables?.map((tbl: any, i: number) => (
              <div key={i} style={{ marginBottom: 'var(--wh-space-xs)' }}>
                <Tag color="blue">{tbl.table_name}</Tag>
                <ExplainPopover text={t('table.explain.importRows', { n: tbl.row_count, m: tbl.col_count })}>
                  <span style={{ color: '#888' }}>
                    {tbl.row_count.toLocaleString(numLocale(locale))} {t('common.rows')} / {tbl.col_count} {t('common.cols')}
                  </span>
                </ExplainPopover>
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal
        title={t('table.mwImportTitle')}
        open={mwOpen}
        onCancel={() => !mwImporting && setMwOpen(false)}
        width={'min(90vw, 38rem)' as any}
        footer={[
          <Button key="cancel" disabled={mwImporting} onClick={() => setMwOpen(false)}>{t('table.cancel')}</Button>,
          <Button key="ok" type="primary" loading={mwImporting} onClick={submitMwImport}>
            {t('table.import')}
          </Button>,
        ]}
      >
        <div style={{ marginBottom: 'var(--wh-space-sm)', padding: 'var(--wh-space-sm)', background: 'rgba(22,138,255,0.08)', borderRadius: 'var(--wh-radius-sm)' }}>
          {t('table.mwImportNote')}
        </div>

        <div style={{ marginBottom: 'var(--wh-space-xs)', color: '#555' }}>{t('table.mwFilePh')}</div>
        <Upload
          beforeUpload={() => false}
          maxCount={1}
          accept=".kml"
          fileList={mwFile ? [{ uid: '-1', name: mwFile.name, status: 'done' } as any] : []}
          onChange={(info: any) => { const f = info?.file; if (f) { setMwFile(f); setMwResult(null) } }}
          onRemove={() => { setMwFile(null); setMwResult(null) }}
        >
          <Button icon={<UploadOutlined />}>{t('table.mwFilePh')}</Button>
        </Upload>

        {mwStatus && mwStatus.exists && (
          <div style={{ marginTop: 'var(--wh-space-md)', color: '#666', fontSize: '0.8125rem' }}>
            <div>{t('table.mwCurrent')}</div>
            <div style={{ marginTop: 'var(--wh-space-xs)' }}>
              <ExplainPopover text={t('table.explain.mwSites', { n: mwStatus.sites })}>
                <Tag color="blue">{t('table.mwSites', { n: mwStatus.sites })}</Tag>
              </ExplainPopover>
              <ExplainPopover text={t('table.explain.mwLinks', { n: mwStatus.links })}>
                <Tag color="green">{t('table.mwLinks', { n: mwStatus.links })}</Tag>
              </ExplainPopover>
              {mwStatus.import_time && <Tag>{mwStatus.import_time}</Tag>}
            </div>
            {mwStatus.source_file && (
              <div style={{ marginTop: 'var(--wh-space-xs)', color: '#999' }}>{mwStatus.source_file}</div>
            )}
          </div>
        )}

        {mwResult && (
          <div style={{ marginTop: 'var(--wh-space-md)' }}>
            <ExplainPopover text={t('table.explain.mwWrittenSites', { n: mwResult.sites })}>
              <Tag color="green">{t('table.mwSites', { n: mwResult.sites })}</Tag>
            </ExplainPopover>
            <ExplainPopover text={t('table.explain.mwWrittenLinks', { n: mwResult.links })}>
              <Tag color="green">{t('table.mwLinks', { n: mwResult.links })}</Tag>
            </ExplainPopover>
            {mwResult.skipped > 0 && (
              <ExplainPopover text={t('table.explain.mwSkipped', { n: mwResult.skipped })}>
                <Tag color="orange">skip {mwResult.skipped}</Tag>
              </ExplainPopover>
            )}
            <div style={{ marginTop: 'var(--wh-space-xs)', color: '#888', fontSize: '0.8125rem' }}>
              {t('table.mwImportedHint')}
            </div>
          </div>
        )}
      </Modal>

      <Tabs
        items={[
          {
            key: 'data',
            label: t('table.browseTab'),
            children: (
              <Card style={cardStyle}>
                {/* 已启用的列筛选常驻可见：漏斗图标藏在表头里，光看数字会以为
                    全表就这么几行。每个标签可单独关掉，也可一键清空。 */}
                {filterEntries.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--wh-space-xs)', marginBottom: 'var(--wh-space-sm)' }}>
                    <span style={{ color: 'var(--wh-text-dim)', fontSize: '0.8125rem' }}>{t('table.colFilterActive')}:</span>
                    {filterEntries.map(([col, f]) => (
                      <Tag key={col} color="blue" closable onClose={() => applyColFilter(col, null)}>
                        {col} · {modeLabel(t, f.op)}
                        {(f.op === 'contains' || f.op === 'equals') ? ` ${f.value ?? ''}` : ''}
                        {f.op === 'in' ? ` ${(f.values ?? []).length}` : ''}
                      </Tag>
                    ))}
                    <Button type="link" size="small" onClick={clearAllColFilters}>{t('table.colFilterClearAll')}</Button>
                  </div>
                )}
                <div className="wh-table-responsive">
                  <Table
                    dataSource={tableData}
                    columns={dataColumns}
                    loading={loading}
                    scroll={{ x: 'max-content' }}
                    size="small"
                    rowKey={stableRowKey}
                    /* 空表必须说清楚「是空的」而不是留一片白（2026-10-23 用户报
                       「credentials 是空的」，实际是表体空白 + 分页条「共 0 条」，
                       分不清加载失败与确实无数据）。locale.emptyText 会按当前语言取文案。
                       ⚠️ 但「还在取数」不是「确实无数据」：首屏两级请求期间显示加载中，
                       别在 iframe 被后端排队时抢先宣布表是空的（2026-11-08 门户实测）。 */
                    locale={{
                      emptyText: loading
                        ? t('common.loading')
                        : searchText
                          ? t('table.emptyTableFiltered', { kw: searchText })
                          : filterEntries.length
                            ? t('table.emptyTableColFiltered')
                            : t('table.emptyTable'),
                    }}
                    pagination={{
                      ...pagination,
                      showSizeChanger: false,
                      showTotal: (total) => (
                        <ExplainPopover text={t('table.explain.pageTotal', { n: total })}>
                          <span>{t('table.totalRecords', { n: total })}</span>
                        </ExplainPopover>
                      ),
                      onChange: (p) => loadTableData(p),
                      // antd 的 prevIcon/nextIcon 是无名 button（title 只挂在 li 上），
                      // 读屏聚焦到按钮时读不出用途。只给上一页/下一页补名称，其余原样。
                      itemRender: (_page, type, originalElement) => {
                        if ((type === 'prev' || type === 'next') && isValidElement(originalElement)) {
                          return cloneElement(originalElement as ReactElement<{ 'aria-label'?: string }>, {
                            'aria-label': t(type === 'prev' ? 'table.prevPageAria' : 'table.nextPageAria'),
                          })
                        }
                        return originalElement
                      },
                    }}
                  />
                </div>
              </Card>
            ),
          },
          {
            key: 'profile',
            label: t('table.profileTab'),
            children: profileLoading ? (
              <Spin style={{ display: 'block', margin: '50px auto' }} />
            ) : profileData ? (
              <ProfilePanel profile={profileData} onLoad={loadProfile} />
            ) : (
              <Card>
                <div style={{ textAlign: 'center', padding: 50 }}>
                  <p>{t('table.profilePrompt')}</p>
                  <a onClick={loadProfile} style={{ fontSize: 16 }}>{t('table.startAnalysis')}</a>
                </div>
              </Card>
            ),
          },
          {
            key: 'data-agent',
            label: t('dataAgent.tab'),
            children: <DataAgentBar />,
          },
        ]}
      />
    </div>
  )
}

/** 列筛选标签上的模式名。
 *  ⚠️ 必须用 switch 返回字面量键：动态拼 t('table.colFilterMode.' + op) 会被
 *     check:i18n 当成键名 `table.colFilterMode.` 而误报字典缺失。 */
function modeLabel(t: (key: string) => string, op: ColFilterOp): string {
  switch (op) {
    case 'contains': return t('table.colFilterMode.contains')
    case 'equals': return t('table.colFilterMode.equals')
    case 'in': return t('table.colFilterMode.in')
    case 'empty': return t('table.colFilterMode.empty')
    default: return String(op)
  }
}

/** 列名右侧的漏斗 + 筛选面板。
 *
 *  服务端分页，筛选条件必须提交给 /data（翻页、导出都带上），因此这里**不用**
 *  antd Table 的 `filters/onFilter`（那只过滤当前页 20 行，翻页就漏）。
 *  面板里全部用内联组件（Segmented / Input / Checkbox）：antd Select 的下拉
 *  会 portal 到 body，点它会触发 Popover 的 click-outside 把整个面板关掉。 */
function ColumnFilterHeader({ col, table, active, onApply, onClear, onHide }: {
  col: string
  table: string
  active: ColFilter | null
  onApply: (f: ColFilter | null) => void
  onClear: () => void
  onHide: () => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<ColFilterOp>(active?.op ?? 'contains')
  const [text, setText] = useState(active?.value ?? '')
  const [values, setValues] = useState<string[]>(active?.values ?? [])
  const [optKw, setOptKw] = useState('')
  const [options, setOptions] = useState<{ value: string; count: number }[]>([])
  const [optLoading, setOptLoading] = useState(false)
  const [optLoaded, setOptLoaded] = useState(false)
  /* 候选值加载失败要显式报错 + 给重试入口（2026-11-11 QA）：
     SPA 兜底曾把「接口没部署」返回成 200 + index.html，旧实现 .catch 静默成
     「没有可选值」，用户无法区分「真的没数据」和「接口挂了」。 */
  const [optError, setOptError] = useState(false)
  const [optRetry, setOptRetry] = useState(0)
  const activeKey = active ? JSON.stringify(active) : ''

  // 外部（标签 × / 一键清空）改了筛选时同步面板草稿；面板正开着不打断输入。
  useEffect(() => {
    if (open) return
    const a: ColFilter | null = activeKey ? JSON.parse(activeKey) : null
    setMode(a?.op ?? 'contains')
    setText(a?.value ?? '')
    setValues(a?.values ?? [])
  }, [activeKey, open])

  // 候选值按需加载一次（全表去重、按出现次数取前 200，口径在面板里注明）。
  // ⚠️ 必须校验响应结构：后端 SPA 兜底会把「接口不存在」返回成 200 + index.html，
  //    只写 .catch 是抓不到的（它根本不是失败请求）。非预期响应一律判为加载失败。
  // ⚠️ 成败都要置 optLoaded：effect 依赖里有 optLoading，若失败时不置位，
  //    finally 把 optLoading 复位后会立即重跑，形成无限请求风暴。
  useEffect(() => {
    if (!open || mode !== 'in' || optLoaded || optLoading || !table) return
    setOptLoading(true)
    setOptError(false)
    api.get(`/tables/${encodeURIComponent(table)}/column-values`, { params: { column: col, limit: 200 } })
      .then(res => {
        const vals = res?.data?.values
        if (!Array.isArray(vals)) {
          setOptions([])
          setOptError(true)
        } else {
          setOptions(vals)
        }
        setOptLoaded(true)
      })
      .catch(() => {
        setOptions([])
        setOptError(true)
        setOptLoaded(true)
      })
      .finally(() => setOptLoading(false))
  }, [open, mode, optLoaded, optLoading, table, col, optRetry])

  const retryOptions = () => {
    setOptLoaded(false)
    setOptError(false)
    setOptRetry(n => n + 1)
  }

  const kw = optKw.trim().toLowerCase()
  const optionList = kw ? options.filter(o => o.value.toLowerCase().includes(kw)) : options

  const apply = () => {
    if (mode === 'empty') { onApply({ op: 'empty' }); setOpen(false); return }
    if (mode === 'in') {
      if (!values.length) { message.warning(t('table.colFilterNeedValue')); return }
      onApply({ op: 'in', values })
      setOpen(false)
      return
    }
    const v = text.trim()
    if (!v) { message.warning(t('table.colFilterNeedValue')); return }
    onApply({ op: mode, value: v })
    setOpen(false)
  }

  const panel = (
    <div style={{ width: 'min(19rem, 80vw)' }}>
      <div style={{ fontWeight: 600, marginBottom: 8, wordBreak: 'break-all' }}>
        {t('table.colFilterPanelTitle', { col })}
      </div>
      <Segmented
        size="small"
        block
        value={mode}
        onChange={(v) => setMode(v as ColFilterOp)}
        style={{ width: '100%', marginBottom: 8 }}
        options={[
          { value: 'contains', label: t('table.colFilterMode.contains') },
          { value: 'equals', label: t('table.colFilterMode.equals') },
          { value: 'in', label: t('table.colFilterMode.in') },
          { value: 'empty', label: t('table.colFilterMode.empty') },
        ]}
      />
      {(mode === 'contains' || mode === 'equals') && (
        <Input
          size="small"
          value={text}
          onChange={e => setText(e.target.value)}
          onPressEnter={apply}
          placeholder={t('table.colFilterValuePh')}
          allowClear
        />
      )}
      {mode === 'in' && (
        <>
          <Input
            size="small"
            prefix={<SearchOutlined style={{ color: '#bbb' }} />}
            value={optKw}
            onChange={e => setOptKw(e.target.value)}
            placeholder={t('table.colFilterSearchValues')}
            allowClear
          />
          <div style={{ maxHeight: '11rem', overflow: 'auto', marginTop: 6, border: '1px solid var(--wh-subtle-border)', borderRadius: 'var(--wh-radius-sm)', padding: 'var(--wh-space-xs)' }}>
            {optError ? (
              <div role="alert" style={{ color: 'var(--wh-text-dim)', textAlign: 'center', padding: 'var(--wh-space-xs)', fontSize: '0.8125rem' }}>
                <div style={{ marginBottom: 6 }}>{t('table.colFilterLoadFailed')}</div>
                <Button size="small" onClick={retryOptions}>{t('table.colFilterRetry')}</Button>
              </div>
            ) : optLoading ? (
              <Spin size="small" style={{ display: 'block', margin: '0.75rem auto' }} />
            ) : optionList.length === 0 ? (
              <div style={{ color: 'var(--wh-text-dim)', textAlign: 'center', padding: 'var(--wh-space-xs)', fontSize: '0.8125rem' }}>
                {t('table.colFilterNoValues')}
              </div>
            ) : (
              <Checkbox.Group value={values} onChange={v => setValues(v as string[])} style={{ width: '100%' }}>
                {optionList.map(o => (
                  <div key={o.value} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Checkbox value={o.value} style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'inline-block', maxWidth: '13rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }}>
                        {o.value}
                      </span>
                    </Checkbox>
                    <span style={{ color: 'var(--wh-text-dim)', fontSize: '0.75rem' }}>{o.count}</span>
                  </div>
                ))}
              </Checkbox.Group>
            )}
          </div>
          <div style={{ color: 'var(--wh-text-dim)', fontSize: '0.75rem', marginTop: 4 }}>
            {t('table.colFilterValuesHint')}
          </div>
        </>
      )}
      {mode === 'empty' && (
        <div style={{ color: 'var(--wh-text-dim)', fontSize: '0.8125rem' }}>
          {t('table.colFilterEmptyHint')}
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
        <Button size="small" type="primary" onClick={apply}>{t('table.apply')}</Button>
        <Button size="small" disabled={!active} onClick={() => { onClear(); setOpen(false) }}>
          {t('table.colFilterClear')}
        </Button>
        <Button size="small" type="text" icon={<EyeInvisibleOutlined />} onClick={() => { onHide(); setOpen(false) }}>
          {t('table.colFilterHideCol')}
        </Button>
      </div>
    </div>
  )

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{col}</span>
      <Popover content={panel} trigger="click" open={open} onOpenChange={setOpen} placement="bottomLeft">
        <Tooltip title={t('table.colFilterTitle')}>
          <Button
            type="text"
            size="small"
            aria-label={t('table.colFilterTitle')}
            icon={active ? <FilterFilled style={{ color: 'var(--wh-blue)' }} /> : <FilterOutlined />}
            onClick={(e) => e.stopPropagation()}
          />
        </Tooltip>
      </Popover>
    </span>
  )
}

function ProfilePanel({ profile, onLoad }: { profile: ProfileResult; onLoad: () => void }) {
  const { profile: p, conclusions } = profile
  const { t } = useI18n()

  const nullRateOption = {
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: p.columns.map((c: ProfileColumn) => c.name),
      axisLabel: { rotate: 60, fontSize: 9 },
    },
    yAxis: { type: 'value' as const, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'bar',
      data: p.columns.map((c: ProfileColumn) => ({
        value: c.null_rate,
        itemStyle: { color: c.null_rate > 50 ? '#ff4d4f' : c.null_rate > 20 ? '#faad14' : '#52c41a' },
      })),
    }],
    grid: { left: '3.125rem', right: '1.25rem', bottom: '6.25rem', top: '1.25rem' },
    dataZoom: [{ type: 'slider' }],
  }

  const typeGroups: Record<string, number> = {}
  p.columns.forEach((c: ProfileColumn) => {
    typeGroups[c.type_category] = (typeGroups[c.type_category] || 0) + 1
  })
  const typePieOption = {
    tooltip: { trigger: 'item' as const },
    series: [{
      type: 'pie',
      radius: '65%',
      data: Object.entries(typeGroups).map(([name, value]) => ({ name, value })),
    }],
  }

  return (
    <div>
      {/* 画像是**采样**结果：后端 SQL 写死 `SELECT * LIMIT 10000` 且无 ORDER BY。
          取满 1 万行时必须常驻说清，否则用户会把样本行数当成全表行数（AGENTS.md 四.10 的「异常常驻」）。 */}
      {p.total_rows >= 10000 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 'var(--wh-space-md)' }}
          message={t('table.profileSampled', { n: p.total_rows })}
        />
      )}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}>
            <ExplainPopover text={t('table.explain.quality')}>
              <Statistic title={<span>{t('table.qualityScore')} <ExplainIcon text={t('table.explain.quality')} /></span>} value={p.quality_score} suffix={t('table.scoreUnit')} valueStyle={{ color: p.quality_score >= 80 ? '#52c41a' : '#faad14' }} />
            </ExplainPopover>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}>
            <ExplainPopover text={t('table.explain.sampleRows', { n: p.total_rows })}>
              <Statistic title={<span>{t('table.totalRowsLabel')} <ExplainIcon text={t('table.explain.sampleRows', { n: p.total_rows })} /></span>} value={p.total_rows} />
            </ExplainPopover>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}>
            <ExplainPopover text={t('table.explain.sampleCols', { n: p.total_cols })}>
              <Statistic title={<span>{t('table.totalColsLabel')} <ExplainIcon text={t('table.explain.sampleCols', { n: p.total_cols })} /></span>} value={p.total_cols} />
            </ExplainPopover>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}>
            <ExplainPopover text={t('table.explain.issueListLen', { n: p.issues_summary.length })}>
              <Statistic title={<span>{t('table.qualityIssues')} <ExplainIcon text={t('table.explain.issueListLen', { n: p.issues_summary.length })} /></span>} value={p.issues_summary.length} valueStyle={{ color: p.issues_summary.length > 0 ? '#ff4d4f' : '#52c41a' }} />
            </ExplainPopover>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 'var(--wh-space-md)' }}>
        <Col xs={24} lg={16}>
          <Card title={t('table.nullRateDist')} style={cardStyle}>
            <ReactECharts option={nullRateOption} style={{ height: 'clamp(14rem, 28vw, 19rem)' }} />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={t('table.typeDist')} style={cardStyle}>
            <ReactECharts option={typePieOption} style={{ height: 'clamp(14rem, 28vw, 19rem)' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 'var(--wh-space-md)' }}>
        <Col span={24}>
          <Card title={t('table.conclusions')} style={cardStyle}>
            {conclusions.map((c, i) => (
              <div key={i} style={{ marginBottom: 'var(--wh-space-sm)', padding: 'var(--wh-space-sm) var(--wh-space-md)', background: 'var(--wh-subtle-bg)', borderRadius: 'var(--wh-radius-sm)' }}>
                {c}
              </div>
            ))}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 'var(--wh-space-md)' }}>
        <Col span={24}>
          <Card title={t('table.fieldDetails')} style={cardStyle}>
            <div className="wh-table-responsive">
              <Table
                dataSource={p.columns}
                columns={[
                  { title: t('table.fieldName'), dataIndex: 'name', key: 'name', minWidth: 120 },
                  { title: t('table.fieldType'), dataIndex: 'type_category', key: 'type_category', minWidth: 100, render: (v: string) => <Tag>{v}</Tag> },
                  { title: <span>{t('table.nullRate')} <ExplainIcon text={t('table.explain.colNullRate')} /></span>, dataIndex: 'null_rate', key: 'null_rate', minWidth: 120, render: (v: number, r: ProfileColumn) => (
                    <ExplainPopover text={t('table.explain.cellNullRate', { name: r.name, pct: v, nulls: r.null_count, total: r.total })}>
                      <span style={{ display: 'block' }}><Progress percent={v} size="small" strokeColor={v > 50 ? '#ff4d4f' : v > 20 ? '#faad14' : '#52c41a'} /></span>
                    </ExplainPopover>
                  ) },
                  { title: <span>{t('table.uniqueCount')} <ExplainIcon text={t('table.explain.colUnique')} /></span>, dataIndex: 'unique_count', key: 'unique_count', minWidth: 90, render: (v: number, r: ProfileColumn) => (
                    <ExplainPopover text={t('table.explain.cellUnique', { name: r.name, uniq: v, total: r.total })}><span>{v}</span></ExplainPopover>
                  ) },
                  { title: <span>{t('table.issueCount')} <ExplainIcon text={t('table.explain.colIssue')} /></span>, dataIndex: 'issue_count', key: 'issue_count', minWidth: 90, render: (v: number, r: ProfileColumn) => v > 0
                    ? <ExplainPopover text={t('table.explain.cellIssue', { name: r.name, n: v })}><Badge count={v} /></ExplainPopover>
                    : <ExplainPopover text={t('table.explain.cellIssueZero', { name: r.name })}><span>-</span></ExplainPopover> },
                  { title: t('table.candidateKey'), key: 'pk', minWidth: 90, render: (_: any, r: ProfileColumn) => r.is_candidate_key ? <Tag color="gold">{t('table.isKey')}</Tag> : '-' },
                ]}
                size="small"
                rowKey="name"
                pagination={{ pageSize: 20 }}
                scroll={{ x: 'max-content', y: 'clamp(18rem, 40vh, 25rem)' }}
              />
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
