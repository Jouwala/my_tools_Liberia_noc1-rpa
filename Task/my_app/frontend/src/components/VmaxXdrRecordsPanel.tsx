/* ============================================================================
 * VmaxXdrRecordsPanel —— XDR Records（分表信令详单）
 * ============================================================================
 *
 * 与「信令详单」页签（VmaxXdrPanel，合并表 exec_merge_query）的分工：
 *   - 合并表：一个号码在窗口内**所有接口**的流水，适合看「发生了什么」；
 *   - 本面板：按**单张 XDR 表**查（UEMR_XDR / UU_XDR / X2_XDR…），列由该表列头
 *     决定。UEMR_XDR 带 RSRP/SINR 等空口测量列，排障看无线质量必须用它。
 *
 * 2026-10-30 改版：**时间窗改为页面级共用**（见 pages/vmaxWindowContext.ts）。
 *   本面板不再渲染自己的 RangePicker，也不存 rtStart/rtEnd 两份 URL 参数；
 *   窗口从 useVmaxWindow() 取，顶部「查询」一点即与另外两个页签并行取数。
 *
 * 表清单来自后端 /vmax-xdr-records/tables（上游 get_tabinfo 缓存 10 分钟），
 * 不在前端写死 —— 现场新增表无需改码。
 *
 * 两条与其它 VMAX 面板不同的能力（对应后端的落库部分）：
 *   ① 存档：上游只保留 24~72 小时，关键记录点「存档」落本地库，之后可复核；
 *   ② 查询历史：每次查询都记审计（号码打码，按登录用户隔离）。
 * 存档/历史都只对当前登录用户可见，后端按 username 过滤。
 * ========================================================================== */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, Button, Descriptions, Input, Popconfirm, Segmented, Select, Space,
  Spin, Table, Tag, Typography, message,
} from 'antd'
import {
  BookOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, HistoryOutlined,
  ReloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import { useI18n } from '../i18n'
import { exportAoaReport } from '../utils/excelReport'
import DraggableClickModal from './DraggableClickModal'
import {
  vmaxXdrDeleteSaved, vmaxXdrQueryHistory, vmaxXdrRecords, vmaxXdrSaveRecord,
  vmaxXdrSavedRecord, vmaxXdrSavedRecords, vmaxXdrServices, vmaxXdrTables,
} from '../api'
import { readParam, writeParams } from '../urlState'
import { useVmaxWindow } from '../pages/vmaxWindowContext'
import { rangeToParams } from '../pages/vmaxWindow'

const { Text } = Typography

type ServiceItem = {
  id: string; name: string; name_zh?: string; retention_hours?: number
}
type TableItem = { table_name: string; xdr_name: string }
type XdrRow = Record<string, string>

type RecordResult = {
  msisdn: string
  service_type: string
  table: string
  table_label: string
  window: { starttime: string; endtime: string }
  page: number
  page_size: number
  total_pages: number
  records: number
  field: string[]
  header: string[]
  rows: XdrRow[]
}

type SavedItem = {
  id: number
  msisdn_mask: string
  service_type: string
  table_name: string
  table_label?: string
  record_time?: string
  note?: string
  created_at: string
}

type HistoryItem = {
  id: number
  msisdn_mask: string
  service_type: string
  table_name: string
  window_start: string
  window_end: string
  records: number
  page: number
  elapsed_ms: number
  status: string
  err_msg?: string
  created_at: string
}

/** 统一空值展示：— 而不是 null / 空串（AGENTS.md 三.6） */
const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

/** 单次导出行数上限：UEMR 一天可达数万条，全拉会拖死上游与浏览器 */
const MAX_EXPORT = 5000

export default function VmaxXdrRecordsPanel({ msisdn }: { msisdn: string }) {
  const { t, locale } = useI18n()
  const ctx = useVmaxWindow()

  const [serviceType, setServiceType] = useState(() => readParam('rtSvc') || '32')
  const [table, setTable] = useState(() => readParam('rtTable'))
  const [pageSize, setPageSize] = useState(20)

  const [services, setServices] = useState<ServiceItem[]>([])
  const [tables, setTables] = useState<TableItem[]>([])
  const [tablesLoading, setTablesLoading] = useState(false)

  const [result, setResult] = useState<RecordResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  const [detailRow, setDetailRow] = useState<XdrRow | null>(null)
  const [detailAnchor, setDetailAnchor] = useState<{ x: number; y: number } | null>(null)

  const [savedOpen, setSavedOpen] = useState(false)
  const [savedTab, setSavedTab] = useState<'saved' | 'history'>('saved')
  const [savedRows, setSavedRows] = useState<SavedItem[]>([])
  const [savedLoading, setSavedLoading] = useState(false)
  const [historyRows, setHistoryRows] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [savedDetail, setSavedDetail] = useState<{ meta: SavedItem; payload: XdrRow } | null>(null)
  const [note, setNote] = useState('')

  const seqRef = useRef(0)
  const lastMsisdn = useRef(msisdn)

  /* 查询类型清单（含各类型的保留时长）*/
  useEffect(() => {
    vmaxXdrServices()
      .then((r) => setServices((r.data?.services || []) as ServiceItem[]))
      .catch(() => setServices([]))
  }, [])

  /* URL 带来的类型若已下线：回落 32（LTE，最常用），并清掉表名 ——
     旧表在新类型下多半不存在，留着只会得到一句「无数据」 */
  useEffect(() => {
    if (!services.length || services.some((s) => s.id === serviceType)) return
    setTable('')
    setServiceType(services.find((s) => s.id === '32')?.id || services[0].id)
    // 只在清单到达时校验一次；用户主动改类型不该被这段拉回去
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [services])

  /* 表清单：跟着 serviceType 变，默认优先 UEMR_XDR（排障最常看的一张）*/
  const loadTables = useCallback(async (sid: string) => {
    setTablesLoading(true)
    try {
      const r = await vmaxXdrTables(sid)
      const list = (r.data?.tables || []) as TableItem[]
      setTables(list)
      // 保留当前已选表（含 URL 带来的那张）；只有它不在清单里才回落到 UEMR_XDR，
      // 否则刷新回来会被强行改成默认表，用户还得再找一遍
      setTable((cur) => {
        if (cur && list.some((x) => x.table_name === cur)) return cur
        const preferred = list.find((x) => x.xdr_name.toUpperCase() === 'UEMR_XDR') || list[0]
        return preferred?.table_name || ''
      })
    } catch {
      setTables([])
      setTable('')
    } finally {
      setTablesLoading(false)
    }
  }, [])

  useEffect(() => { void loadTables(serviceType) }, [serviceType, loadTables])

  /* 父页面换号码：清掉上一次结果，避免张冠李戴 */
  useEffect(() => {
    if (lastMsisdn.current !== msisdn) {
      lastMsisdn.current = msisdn
      setResult(null)
      setError('')
      setSearched(false)
    }
  }, [msisdn])

  const run = useCallback(async (raw: string, p: number, ps: number, tbl = table,
                               sid = serviceType,
                               winParams?: { start?: string; end?: string }) => {
    const q = raw.trim()
    if (!q || !tbl) return
    const seq = ++seqRef.current
    setLoading(true)
    setError('')
    setSearched(true)
    const w = winParams || rangeToParams(ctx?.range || null)
    try {
      const r = await vmaxXdrRecords({
        msisdn: q, service_type: sid, table: tbl,
        start: w.start,
        end: w.end,
        page: p, page_size: ps,
      })
      if (seq !== seqRef.current) return      // 旧请求迟到，丢弃
      const data = r.data as RecordResult
      setResult(data)
      // 类型与表名随结果入 URL（时间窗滚动、不再写进 URL，此处只记类型与表）
      writeParams({
        rtSvc: data.service_type,
        rtTable: data.table,
      })
    } catch (e: any) {
      if (seq !== seqRef.current) return
      setError(e?.response?.data?.detail || e?.message || String(e))
      setResult(null)
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [serviceType, table, ctx])

  /* 并行取数：页面级「查询」每执行一次，context.query.token 就 +1。
     这里盯着 token 变化自动发请求 —— 与 CCA 概览、信令详单两个页签
     同时跑，谁先回来谁先渲染，互不等待。
     依赖 services/table 是因为 URL 带来的表可能已下线：等清单到达、
     确认表有效再查，否则会白打一次上游并报「无数据」。 */
  const lastToken = useRef(0)
  useEffect(() => {
    const q = ctx?.query
    if (!q || q.token === lastToken.current) return
    if (!q.msisdn.trim()) return
    if (!services.length || !table) return
    if (!services.some((s) => s.id === serviceType)) return
    lastToken.current = q.token
    void run(q.msisdn, 1, pageSize, table, serviceType, rangeToParams(q.range))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx?.query?.token, services, serviceType, table])

  /* 翻页/改页长必须沿用**屏幕上这张表**的窗口，而不是控件当前值 ——
     用户可能改了顶部时间选择器却还没点「查询」，按控件值拉会把两次查询的
     数据混在一起。result.window 是服务端归一后的窗口（格式 "YYYY-MM-DD HH:MM:SS.000"，
     后端 parse 只认前 16 位）。 */
  const resultWindow = result
    ? { start: result.window.starttime.slice(0, 16), end: result.window.endtime.slice(0, 16) }
    : undefined

  /* ---- 动态列：上游 header[i] 对齐 field[i] ---- */
  const columns = (result?.header || []).map((title, idx) => {
    const key = result?.field?.[idx] || `col_${idx}`
    return {
      title,
      dataIndex: key,
      key,
      width: idx === 0 ? 170 : 150,
      fixed: idx === 0 ? ('left' as const) : undefined,
      ellipsis: true,
      render: (v: string) => (
        <Text style={{ fontSize: 12 }} title={v || undefined}>{fmt(v)}</Text>
      ),
    }
  })

  const openDetail = (row: XdrRow, ev?: React.MouseEvent) => {
    setDetailRow(row)
    setDetailAnchor(ev ? { x: ev.clientX, y: ev.clientY } : null)
  }

  const onSave = async (row: XdrRow) => {
    if (!result) return
    try {
      const r = await vmaxXdrSaveRecord({
        msisdn: result.msisdn,
        service_type: result.service_type,
        table: result.table,
        table_label: result.table_label,
        // 记录时间交给后端按域的 time_field（32 是 btime）从 payload 里取，
        // 不在这里猜「第一列是不是时间」—— 列顺序由上游列头决定。
        note: note.trim() || undefined,
        payload: row,
      })
      message.success(r.data?.message || t('vmaxxdr.savedOk'))
      setNote('')
      if (savedOpen) void loadSaved()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('vmaxxdr.saveFail'))
    }
  }

  const loadSaved = useCallback(async () => {
    setSavedLoading(true)
    try {
      const r = await vmaxXdrSavedRecords({ limit: 100 })
      setSavedRows((r.data?.rows || []) as SavedItem[])
    } catch {
      setSavedRows([])
    } finally {
      setSavedLoading(false)
    }
  }, [])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const r = await vmaxXdrQueryHistory(100)
      setHistoryRows((r.data?.rows || []) as HistoryItem[])
    } catch {
      setHistoryRows([])
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const onOpenSaved = () => {
    setSavedOpen(true)
    if (savedTab === 'saved') void loadSaved()
    else void loadHistory()
  }

  const onViewSaved = async (id: number) => {
    try {
      const r = await vmaxXdrSavedRecord(id)
      const d = r.data
      setSavedDetail({
        meta: {
          id: d.id, msisdn_mask: d.msisdn_mask, service_type: d.service_type,
          table_name: d.table_name, table_label: d.table_label,
          record_time: d.record_time, note: d.note, created_at: d.created_at,
        },
        payload: (d.payload || {}) as XdrRow,
      })
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('vmaxxdr.detailFail'))
    }
  }

  const onDeleteSaved = async (id: number) => {
    try {
      await vmaxXdrDeleteSaved(id)
      message.success(t('vmaxxdr.deleted'))
      void loadSaved()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('vmaxxdr.deleteFail'))
    }
  }

  /* ---- 导出：按 200/批 逐页拉全（服务端分页），截断时显式提示 ---- */
  const [exporting, setExporting] = useState(false)
  const onExport = async () => {
    if (!result) return
    setExporting(true)
    try {
      const batch = 200
      const collected: XdrRow[] = []
      let field = result.field
      let header = result.header
      const win = { start: result.window.starttime.slice(0, 16),
                    end: result.window.endtime.slice(0, 16) }
      const hardStop = Math.ceil(Math.min(result.records, MAX_EXPORT) / batch)
      for (let page = 1; page <= hardStop; page += 1) {
        const r = await vmaxXdrRecords({
          msisdn: result.msisdn, service_type: result.service_type, table: result.table,
          start: win.start, end: win.end, page, page_size: batch,
        })
        const d = r.data as RecordResult
        if (d.field?.length) { field = d.field; header = d.header }
        collected.push(...d.rows)
        if (collected.length >= result.records || !d.rows.length) break
      }
      const rows = collected.slice(0, MAX_EXPORT).map((row) => field.map((f) => row[f] ?? ''))
      const parts = [
        result.table_label || result.table,
        `${win.start} ~ ${win.end}`,
        t('vmaxxdr.exportCount', { n: rows.length, total: result.records }),
      ]
      if (result.records > MAX_EXPORT) parts.push(t('vmaxxdr.exportTruncated', { max: MAX_EXPORT }))
      await exportAoaReport({
        filename: `vmax_xdr_records_${result.table_label}_${result.msisdn}_${dayjs().format('YYYYMMDD_HHmm')}.xlsx`,
        sheetName: (result.table_label || 'XDR').slice(0, 30),
        title: t('vmaxxdr.recordsTitle'),
        subtitle: `${t('vmaxxdr.msisdn')}: ${result.msisdn}    |    ${parts.join('    |    ')}`,
        header,
        rows,
      })
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || String(e))
    } finally {
      setExporting(false)
    }
  }

  const serviceLabel = (s: ServiceItem) => (locale === 'zh' ? (s.name_zh || s.name) : s.name)
  /* 所选类型的上游保留时长（小时）：窗口跨度上限由后端按它校验，
   * 这里只做提示。页面级的时间选择器按最短保留期（24h）置灰，
   * 所以任何类型都不会因为窗口太长而查不到（见 vmaxWindow.ts）。 */
  const currentSvc = services.find((s) => s.id === serviceType)
  const retentionHours = currentSvc?.retention_hours ?? 72
  const noMsisdn = !msisdn.trim()
  const tableLabel = tables.find((x) => x.table_name === table)?.xdr_name || table

  /* 详情弹窗的字段列表：优先用列头（中文/英文显示名），拿不到时退回字段名 */
  const detailItems = (() => {
    const src = savedDetail ? null : result
    const row = savedDetail ? savedDetail.payload : detailRow
    if (!row) return []
    const fields = src?.field?.length ? src.field : Object.keys(row)
    const headers = src?.header?.length ? src.header : fields
    return fields
      .filter((f) => f in row)
      .map((f, i) => ({ key: f, label: headers[i] || f, value: row[f] }))
  })()

  const detailTitleText = savedDetail
    ? `${savedDetail.meta.table_label || savedDetail.meta.table_name} · ${savedDetail.meta.msisdn_mask}`
    : `${tableLabel} · ${result?.msisdn || ''}`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <Space wrap>
        <Select
          style={{ width: 170 }}
          value={serviceType}
          onChange={(v) => { setServiceType(v); setResult(null); setTable('') }}
          options={services.map((s) => ({ value: s.id, label: serviceLabel(s) }))}
          placeholder={t('vmaxxdr.servicePlaceholder')}
        />
        <Select
          style={{ width: 190 }}
          value={table || undefined}
          onChange={(v) => { setTable(v); setResult(null) }}
          options={tables.map((x) => ({
            value: x.table_name,
            label: `${x.xdr_name} · ${x.table_name}`,
          }))}
          loading={tablesLoading}
          placeholder={t('vmaxxdr.tablePlaceholder')}
          showSearch
          optionFilterProp="label"
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          loading={loading}
          disabled={noMsisdn || !table}
          onClick={() => void run(ctx?.query?.msisdn || msisdn, 1, pageSize)}
        >
          {t('vmaxxdr.search')}
        </Button>
        <Button
          icon={<DownloadOutlined />}
          loading={exporting}
          disabled={!result || !result.rows.length || loading}
          onClick={() => void onExport()}
        >
          {t('vmaxxdr.export')}
        </Button>
        <Button icon={<BookOutlined />} onClick={onOpenSaved}>
          {t('vmaxxdr.savedBtn')}
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('vmaxxdr.hintRetention', { h: retentionHours })}
        </Text>
      </Space>

      {noMsisdn && <Alert type="info" showIcon message={t('vmaxxdr.needMsisdn')} />}
      {!table && !noMsisdn && <Alert type="warning" showIcon message={t('vmaxxdr.needTable')} />}

      {error && (
        <Alert
          type="error"
          showIcon
          message={t('vmaxxdr.errorTitle')}
          description={error}
          action={
            <Button size="small" icon={<ReloadOutlined />}
                    onClick={() => void run(ctx?.query?.msisdn || msisdn, 1, pageSize)}>
              {t('vmaxxdr.retry')}
            </Button>
          }
        />
      )}

      <Spin spinning={loading}>
        {result && result.rows.length > 0 ? (
          <>
            <Space size="small" wrap>
              <Tag color="geekblue">{result.table_label}</Tag>
              <Tag color="blue">{t('vmaxxdr.records', { n: result.records })}</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {result.window.starttime} ~ {result.window.endtime}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxxdr.clickRowHint')}</Text>
            </Space>
            <Table
              rowKey={(_, i) => String((result.page - 1) * result.page_size + (i || 0))}
              size="small"
              bordered
              columns={columns as any}
              dataSource={result.rows}
              scroll={{ x: Math.max(900, (result.header.length || 1) * 150) }}
              onRow={(row) => ({
                onClick: (ev) => openDetail(row, ev),
                style: { cursor: 'pointer' },
              })}
              pagination={{
                current: result.page,
                pageSize: result.page_size,
                total: result.records,
                showSizeChanger: true,
                pageSizeOptions: ['20', '50', '100', '200'],
                showTotal: (n) => t('vmaxxdr.total', { n }),
                onChange: (p, ps) => { setPageSize(ps); void run(ctx?.query?.msisdn || msisdn, p, ps, table, serviceType, resultWindow) },
              }}
            />
          </>
        ) : (
          <Text type="secondary">
            {loading ? t('vmaxxdr.loading')
              : (searched && !error ? t('vmaxxdr.emptyTable') : t('vmaxxdr.idle'))}
          </Text>
        )}
      </Spin>

      {/* 记录详情（下钻弹窗，统一用 DraggableClickModal）*/}
      <DraggableClickModal
        open={!!detailRow || !!savedDetail}
        title={detailTitleText}
        anchor={detailAnchor}
        width="92%"
        maxWidth="72rem"
        onClose={() => { setDetailRow(null); setSavedDetail(null); setNote('') }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 480 }}>
          <Space wrap>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxxdr.detailHint')}</Text>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => {
                void navigator.clipboard.writeText(JSON.stringify(
                  savedDetail ? savedDetail.payload : detailRow, null, 2))
                message.success(t('vmaxxdr.copied'))
              }}
            >
              {t('vmaxxdr.copyJson')}
            </Button>
          </Space>
          <div style={{ maxHeight: '58vh', overflow: 'auto' }}>
            <Descriptions
              size="small"
              bordered
              column={1}
              labelStyle={{ width: 240 }}
              items={detailItems.map((it) => ({
                key: it.key,
                label: it.label,
                children: (
                  <Text style={{ fontSize: 12, fontFamily: 'Consolas, monospace' }}>
                    {fmt(it.value)}
                  </Text>
                ),
              }))}
            />
          </div>
          {!savedDetail && (
            <Space wrap>
              <Input
                style={{ width: 360 }}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t('vmaxxdr.notePlaceholder')}
                maxLength={200}
              />
              <Button type="primary" icon={<BookOutlined />}
                      onClick={() => detailRow && void onSave(detailRow)}>
                {t('vmaxxdr.saveBtn')}
              </Button>
            </Space>
          )}
        </div>
      </DraggableClickModal>

      {/* 存档 / 查询历史 */}
      <DraggableClickModal
        open={savedOpen}
        title={t('vmaxxdr.savedTitle')}
        width="92%"
        maxWidth="80rem"
        onClose={() => setSavedOpen(false)}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 560 }}>
          <Segmented
            className="wh-seg"
            options={[
              { label: t('vmaxxdr.savedBtn'), value: 'saved' },
              { label: t('vmaxxdr.historyTitle'), value: 'history' },
            ]}
            value={savedTab}
            onChange={(v) => {
              const tab = v as 'saved' | 'history'
              setSavedTab(tab)
              if (tab === 'saved') void loadSaved()
              else void loadHistory()
            }}
          />
          {savedTab === 'saved' ? (
            <Spin spinning={savedLoading}>
              {savedRows.length ? (
                <Table
                  rowKey="id"
                  size="small"
                  bordered
                  dataSource={savedRows}
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: t('vmaxxdr.savedAt'), dataIndex: 'created_at', width: 160 },
                    { title: t('vmaxxdr.msisdn'), dataIndex: 'msisdn_mask', width: 140 },
                    { title: t('vmaxxdr.tableLabel'), dataIndex: 'table_name', width: 180,
                      render: (v: string, r: SavedItem) => r.table_label || v },
                    { title: t('vmaxxdr.recordTime'), dataIndex: 'record_time', width: 180 },
                    { title: t('vmaxxdr.noteLabel'), dataIndex: 'note',
                      render: (v: string) => fmt(v) },
                    {
                      title: '', width: 130, fixed: 'right' as const,
                      render: (_: unknown, r: SavedItem) => (
                        <Space size="small">
                          <Button size="small" type="link" onClick={() => void onViewSaved(r.id)}>
                            {t('vmaxxdr.view')}
                          </Button>
                          <Popconfirm title={t('vmaxxdr.deleteConfirm')}
                                      onConfirm={() => void onDeleteSaved(r.id)}>
                            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              ) : (
                <Text type="secondary">{t('vmaxxdr.savedEmpty')}</Text>
              )}
            </Spin>
          ) : (
            <Spin spinning={historyLoading}>
              {historyRows.length ? (
                <Table
                  rowKey="id"
                  size="small"
                  bordered
                  dataSource={historyRows}
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: t('vmaxxdr.savedAt'), dataIndex: 'created_at', width: 160 },
                    { title: t('vmaxxdr.msisdn'), dataIndex: 'msisdn_mask', width: 140 },
                    { title: t('vmaxxdr.tableLabel'), dataIndex: 'table_name', width: 170 },
                    { title: t('vmaxxdr.recordsCol'), dataIndex: 'records', width: 90 },
                    { title: t('vmaxxdr.elapsed'), dataIndex: 'elapsed_ms', width: 90,
                      render: (v: number) => `${v} ms` },
                    {
                      title: t('vmaxxdr.status'), dataIndex: 'status', width: 90,
                      render: (v: string) => (
                        <Tag color={v === 'ok' ? 'green' : 'red'}>
                          {v === 'ok' ? t('vmaxxdr.statusOk') : t('vmaxxdr.statusFail')}
                        </Tag>
                      ),
                    },
                    { title: t('vmaxxdr.errorMsg'), dataIndex: 'err_msg',
                      render: (v: string) => <Text style={{ fontSize: 12 }}>{fmt(v)}</Text> },
                  ]}
                />
              ) : (
                <Text type="secondary">{t('vmaxxdr.historyEmpty')}</Text>
              )}
            </Spin>
          )}
          <Text type="secondary" style={{ fontSize: 12 }}>
            <HistoryOutlined /> {t('vmaxxdr.savedHint')}
          </Text>
        </div>
      </DraggableClickModal>
    </div>
  )
}
