import { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { Card, Table, Select, Input, Tag, Spin, Tabs, Row, Col, Statistic, Progress, Descriptions, Badge, Button, Dropdown, message, Modal, Checkbox, Divider, Upload, Space, AutoComplete } from 'antd'
import { DownloadOutlined, SettingOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import * as XLSX from 'xlsx'
import api from '../api'
import { useI18n, numLocale } from '../i18n'
import { cardStyle, controlCardStyle } from '../theme'
// Data Agent 只读 NL2SQL 入口（探索性副驾，不参与定时报表/看板产出）。
// 定位、护栏与风险清单见 docs/DATA_AGENT_EVALUATION.md。
import DataAgentBar from '../components/DataAgentBar'
import ExcludeListUpload from '../components/ExcludeListUpload'

interface TableInfo {
  name: string
  row_count: number
  col_count: number
  columns: { name: string; type: string; notnull: number; pk: number }[]
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

export default function TableBrowser() {
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selectedTable, setSelectedTable] = useState<string>('')
  const [tableData, setTableData] = useState<any[]>([])
  const [tableColumns, setTableColumns] = useState<any[]>([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [profileData, setProfileData] = useState<ProfileResult | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [visibleCols, setVisibleCols] = useState<string[] | null>(null)
  const [colModalOpen, setColModalOpen] = useState(false)
  const [draftCols, setDraftCols] = useState<string[]>([])
  const [templates, setTemplates] = useState<ViewTemplate[]>([])
  const [tplName, setTplName] = useState('')
  const [colFilter, setColFilter] = useState('')
  const { t, locale } = useI18n()

  const searchTextRef = useRef('')
  const loadingRef = useRef(false)
  const requestIdRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSearchValueRef = useRef('')
  const hasLoadedOnceRef = useRef(false)

  useEffect(() => { searchTextRef.current = searchText }, [searchText])

  useEffect(() => {
    api.get('/tables').then(res => {
      const tbls = res.data.tables.filter((t: TableInfo) => !t.name.startsWith('_'))
      setTables(tbls)
      if (tbls.length > 0) {
        setSelectedTable(tbls[0].name)
      }
    })
  }, [])

  useEffect(() => {
    if (!selectedTable) return
    setVisibleCols(null)
    setTplName('')
    setSearchText('')
    searchTextRef.current = ''
    lastSearchValueRef.current = ''
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

  const loadTableData = useCallback((page: number, search?: string) => {
    if (!selectedTable) return
    const effectiveSearch = search ?? searchTextRef.current

    const isDuplicate = page === 1 && effectiveSearch === lastSearchValueRef.current && hasLoadedOnceRef.current
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

    const controller = new AbortController()
    abortRef.current = controller

    api.get(`/tables/${selectedTable}/data`, { params, signal: controller.signal })
      .then(res => {
        if (requestId !== requestIdRef.current) return
        const newData = res.data.data.map((r: any, i: number) => ({ ...r, __row_index: `${page}-${i}` }))
        setTableData(newData)
        lastSearchValueRef.current = effectiveSearch
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
    if (visibleCols && visibleCols.length) params.set('columns', visibleCols.join(','))
    message.info(t('table.exportStart'))
    window.open(`/api/tables/${encodeURIComponent(selectedTable)}/export?${params.toString()}`, '_blank')
  }

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

  const shownCols = useMemo(() => {
    if (visibleCols) {
      return visibleCols.filter(c => tableColumns.includes(c))
    }
    return tableColumns
  }, [visibleCols, tableColumns])

  const dataColumns = useMemo(() => shownCols.map((col: string) => ({
    title: col,
    dataIndex: col,
    key: col,
    minWidth: 120,
    ellipsis: true,
    render: (v: any) => v === null || v === undefined ? <Tag>NULL</Tag> : String(v),
  })), [shownCols])

  const stableRowKey = useMemo(() => (record: any) => {
    if (record.__row_index) return record.__row_index
    const parts: string[] = shownCols.map((c: string) => String(record[c] ?? ''))
    const joined = parts.join('|')
    return `rec-${joined.length}-${parts.slice(0, 3).join('-').replace(/[^a-zA-Z0-9-]/g, '_')}`
  }, [shownCols])

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
              enterButton
            />
          </Col>
          {tableInfo && (
            <Col xs={24} lg={6}>
              <Tag color="blue">{tableInfo.row_count.toLocaleString(numLocale(locale))} {t('common.rows')}</Tag>
              <Tag color="green">{tableInfo.col_count} {t('common.cols')}</Tag>
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
                <Tag color="orange">{t('table.visibleColsTag', { n: shownCols.length, m: tableColumns.length })}</Tag>
              )}
            </Space>
          </Col>
        </Row>
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
                <span style={{ color: '#888' }}>
                  {tbl.row_count.toLocaleString(numLocale(locale))} {t('common.rows')} / {tbl.col_count} {t('common.cols')}
                </span>
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
              <Tag color="blue">{t('table.mwSites', { n: mwStatus.sites })}</Tag>
              <Tag color="green">{t('table.mwLinks', { n: mwStatus.links })}</Tag>
              {mwStatus.import_time && <Tag>{mwStatus.import_time}</Tag>}
            </div>
            {mwStatus.source_file && (
              <div style={{ marginTop: 'var(--wh-space-xs)', color: '#999' }}>{mwStatus.source_file}</div>
            )}
          </div>
        )}

        {mwResult && (
          <div style={{ marginTop: 'var(--wh-space-md)' }}>
            <Tag color="green">{t('table.mwSites', { n: mwResult.sites })}</Tag>
            <Tag color="green">{t('table.mwLinks', { n: mwResult.links })}</Tag>
            {mwResult.skipped > 0 && <Tag color="orange">skip {mwResult.skipped}</Tag>}
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
                <div className="wh-table-responsive">
                  <Table
                    dataSource={tableData}
                    columns={dataColumns}
                    loading={loading}
                    scroll={{ x: 'max-content' }}
                    size="small"
                    rowKey={stableRowKey}
                    pagination={{
                      ...pagination,
                      showSizeChanger: false,
                      showTotal: (total) => t('table.totalRecords', { n: total }),
                      onChange: (p) => loadTableData(p),
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
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}><Statistic title={t('table.qualityScore')} value={p.quality_score} suffix={t('table.scoreUnit')} valueStyle={{ color: p.quality_score >= 80 ? '#52c41a' : '#faad14' }} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}><Statistic title={t('table.totalRowsLabel')} value={p.total_rows} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}><Statistic title={t('table.totalColsLabel')} value={p.total_cols} /></Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card style={cardStyle}><Statistic title={t('table.qualityIssues')} value={p.issues_summary.length} valueStyle={{ color: p.issues_summary.length > 0 ? '#ff4d4f' : '#52c41a' }} /></Card>
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
                  { title: t('table.nullRate'), dataIndex: 'null_rate', key: 'null_rate', minWidth: 120, render: (v: number) => <Progress percent={v} size="small" strokeColor={v > 50 ? '#ff4d4f' : v > 20 ? '#faad14' : '#52c41a'} /> },
                  { title: t('table.uniqueCount'), dataIndex: 'unique_count', key: 'unique_count', minWidth: 90 },
                  { title: t('table.issueCount'), dataIndex: 'issue_count', key: 'issue_count', minWidth: 90, render: (v: number) => v > 0 ? <Badge count={v} /> : '-' },
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
