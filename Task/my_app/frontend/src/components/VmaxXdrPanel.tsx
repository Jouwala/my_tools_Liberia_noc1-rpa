/* ============================================================================
 * VmaxXdrPanel —— VMAX 信令详单表格（Talon XDR 合并表）
 * ============================================================================
 *
 * 2026-10-26 从独立页 VmaxXdrQuery 抽成组件，供「VMAX 用户查询」页的
 * 「信令详单」页签复用 —— 两个视角查的是同一个号码，没必要分两个菜单。
 *
 * 2026-10-30 改版：**时间窗改为页面级共用**（见 pages/vmaxWindowContext.ts）。
 *   - 本组件不再渲染自己的 RangePicker，也不存 mxStart/mxEnd 两份 URL 参数；
 *   - 窗口从 useVmaxWindow() 取，与概览 / XDR 记录三个页签同一份；
 *   - 顶部「查询」一点，本面板**并行**发请求（监听 context.query.token），
 *     不再需要用户切到这个页签再点一次「查询」。
 *
 * 与父页面（CCA 概览）的分工：
 *   - 号码由父页面传入，本组件不自带输入框；
 *   - 查询类型（1100/1300/1301）仍在本视图内独立选（不同类型的字段集不同）。
 *
 * 列不写死：后端把 get_xdrheader_info 的 field/header 一并返回，
 * 前端按 header 建列、按 field 取值 —— 上游加字段不白屏、不改码。
 *
 * 请求序号守卫：防止旧请求迟到覆盖新结果（与父页面同一纪律）。
 * ========================================================================== */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Select, Space, Spin, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import { useI18n } from '../i18n'
import { exportAoaReport } from '../utils/excelReport'
import { vmaxXdrQuery, vmaxXdrServices } from '../api'
import { readParam, writeParams } from '../urlState'
import { useVmaxWindow } from '../pages/vmaxWindowContext'
import { rangeToParams } from '../pages/vmaxWindow'

const { Text } = Typography

type ServiceItem = {
  id: string; name: string; name_zh?: string
  /** 上游保留时长（小时）：窗口上限与「最早可选时间」都按它来 */
  retention_hours?: number
}

type XdrRow = Record<string, string>

type XdrResult = {
  msisdn: string
  service_type: string
  window: { starttime: string; endtime: string }
  page: number
  page_size: number
  total_pages: number
  records: number
  field: string[]
  header: string[]
  rows: XdrRow[]
}

/** 统一空值展示：— 而不是 null / 空串（AGENTS.md 三.6） */
const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

export default function VmaxXdrPanel({ msisdn }: { msisdn: string }) {
  const { t, locale } = useI18n()
  const ctx = useVmaxWindow()

  // 号码由父页面给；父页面改了号码要重置本面板的结果，避免张冠李戴
  const lastMsisdn = useRef(msisdn)

  const [serviceType, setServiceType] = useState(() => readParam('mxSvc') || '1100')
  const [pageSize, setPageSize] = useState(20)

  const [services, setServices] = useState<ServiceItem[]>([])
  const [result, setResult] = useState<XdrResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  const seqRef = useRef(0)

  // 查询类型清单由后端给（单一真相源，避免前后端各写一份）
  useEffect(() => {
    vmaxXdrServices()
      .then((r) => {
        const list = (r.data?.services || []) as ServiceItem[]
        setServices(list)
        // URL 里带来的类型可能已下线：回落到 1100（或清单首个），
        // 否则下拉会显示一个查不动、用户也没法解释的值
        if (list.length) {
          setServiceType((cur) => (list.some((s) => s.id === cur)
            ? cur
            : (list.find((s) => s.id === '1100')?.id || list[0].id)))
        }
      })
      .catch(() => setServices([]))     // 取不到就用空清单，不阻塞主流程
  }, [])

  // 父页面换号码：清掉上一次的结果，避免旧号码的详单留在屏幕上
  useEffect(() => {
    if (lastMsisdn.current !== msisdn) {
      lastMsisdn.current = msisdn
      setResult(null)
      setError('')
      setSearched(false)
    }
  }, [msisdn])

  const run = useCallback(async (raw: string, p: number, ps: number,
                               winParams?: { start?: string; end?: string }) => {
    const q = raw.trim()
    if (!q) return
    const seq = ++seqRef.current
    setLoading(true)
    setError('')
    setSearched(true)
    const w = winParams || rangeToParams(ctx?.range || null)
    try {
      const r = await vmaxXdrQuery({
        msisdn: q,
        service_type: serviceType,
        start: w.start,
        end: w.end,
        page: p,
        page_size: ps,
      })
      if (seq !== seqRef.current) return      // 已有更新的查询，丢弃本次结果
      const data = r.data as XdrResult
      setResult(data)
      // 查询类型随结果入 URL（时间窗滚动、不再写进 URL，此处只记类型）
      writeParams({ mxSvc: data.service_type })
    } catch (e: any) {
      if (seq !== seqRef.current) return
      // 后端 HTTPException 的中文说明在 detail（凭据未配置 / 上游不可用等）
      setError(e?.response?.data?.detail || e?.message || String(e))
      setResult(null)
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [serviceType, ctx])

  /* 并行取数：页面级「查询」每执行一次，context.query.token 就 +1。
     这里盯着 token 变化自动发请求 —— 与 CCA 概览、XDR 记录两个页签
     同时跑，谁先回来谁先渲染，互不等待。
     依赖 services 是因为 URL 带来的类型可能已下线：等清单到达、
     确认类型有效再查，否则会白打一次上游并报错。 */
  const lastToken = useRef(0)
  useEffect(() => {
    const q = ctx?.query
    if (!q || q.token === lastToken.current) return
    if (!q.msisdn.trim()) return
    if (!services.length || !services.some((s) => s.id === serviceType)) return
    lastToken.current = q.token
    void run(q.msisdn, 1, pageSize, rangeToParams(q.range))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx?.query?.token, services, serviceType])

  const onSearch = () => run(ctx?.query?.msisdn || msisdn, 1, pageSize)

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
      width: idx === 0 ? 180 : 160,
      fixed: idx === 0 ? ('left' as const) : undefined,
      ellipsis: true,
      render: (v: string) => (
        <Text style={{ fontSize: 12 }} title={v || undefined}>{fmt(v)}</Text>
      ),
    }
  })

  const serviceLabel = (s: ServiceItem) => (locale === 'zh' ? (s.name_zh || s.name) : s.name)
  const noMsisdn = !msisdn.trim()

  /* 所选类型的上游保留时长（小时）：窗口跨度上限由后端按它校验，
   * 这里只做提示。页面级的时间选择器按**最短**保留期（24h）置灰，
   * 所以任何类型都不会因为窗口太长而查不到（见 vmaxWindow.ts）。 */
  const currentSvc = services.find((s) => s.id === serviceType)
  const retentionHours = currentSvc?.retention_hours ?? 72

  /* ---- 导出整个查询结果 ----
   * 表格是服务端分页的，当前页只有 pageSize 条。导「当前页」会让人误以为
   * 拿全了数据，所以这里按 200/批 逐页拉全，再一次性写 Excel（UNIFIED_EXCEL_V1）。
   * 上限 MAX_EXPORT：一天的信令可达数万条，全拉会把上游拖死、浏览器也会卡，
   * 截断时在副标题里显式写明「已截断」，不静默丢数据（AGENTS.md 三.1b）。 */
  const MAX_EXPORT = 5000
  const [exporting, setExporting] = useState(false)

  const onExport = async () => {
    const q = msisdn.trim()
    if (!q || !result) return
    setExporting(true)
    try {
      const batch = 200
      const collected: XdrRow[] = []
      let page = 1
      // 列定义用本轮拿到的最后一份（上游若中途加列，header 与 field 必须成对更新，
      // 否则表头与数据错位）；拿不到时回落到首次查询的结果
      let field = result.field
      let header = result.header
      let truncated = false
      // 一律用 result 里那次查询的窗口与类型导出，而不是界面当前控件的值：
      // 用户可能改了控件却没重新点「查询」，按控件值拉会把两次查询的数据混在一起。
      // result.window 的格式是 "YYYY-MM-DD HH:MM:SS.000"，后端 parse 只认前 16 位。
      const win = { start: result.window.starttime.slice(0, 16),
                    end: result.window.endtime.slice(0, 16) }
      // 已知总页数就按它循环，避免多打一次空请求
      const hardStop = Math.ceil(Math.min(result.records, MAX_EXPORT) / batch)
      while (page <= hardStop) {
        const r = await vmaxXdrQuery({
          msisdn: result.msisdn, service_type: result.service_type,
          start: win.start, end: win.end,
          page, page_size: batch,
        })
        const d = r.data as XdrResult
        if (d.field?.length) { field = d.field; header = d.header }
        collected.push(...d.rows)
        if (collected.length >= result.records) break
        if (!d.rows.length) break          // 上游提前返回空页，防死循环
        page += 1
      }
      if (result.records > MAX_EXPORT) truncated = true

      const rows = collected
        .slice(0, MAX_EXPORT)
        .map((row) => field.map((f) => row[f] ?? ''))

      const svcName = serviceLabel(
        services.find((s) => s.id === result.service_type)
          || { id: result.service_type, name: result.service_type })
      const parts = [
        svcName,
        `${win.start} ~ ${win.end}`,
        t('vmaxxdr.exportCount', { n: rows.length, total: result.records }),
      ]
      if (truncated) parts.push(t('vmaxxdr.exportTruncated', { max: MAX_EXPORT }))

      await exportAoaReport({
        filename: `vmax_xdr_${result.msisdn}_${dayjs().format('YYYYMMDD_HHmm')}.xlsx`,
        sheetName: `XDR ${result.service_type}`,
        title: t('vmaxxdr.title'),
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <Space wrap>
        <Select
          style={{ width: 200 }}
          value={serviceType}
          onChange={(v) => {
            setServiceType(v)
            setResult(null)
            // 窗口是页面级的（三个页签共用），这里不再自己收窄起点。
            // 页面上限已按最短保留期（24h）置灰，选不到超出范围的时间。
          }}
          options={services.map((s) => ({ value: s.id, label: serviceLabel(s) }))}
          placeholder={t('vmaxxdr.servicePlaceholder')}
        />
        <Button
          type="primary"
          icon={<SearchOutlined />}
          loading={loading}
          disabled={noMsisdn}
          onClick={onSearch}
        >
          {t('vmaxxdr.search')}
        </Button>
        <Button
          icon={<DownloadOutlined />}
          loading={exporting}
          // 必须先查过一次再导：导出用的是结果里的列头与窗口，空结果没法拼表头
          disabled={!result || !result.rows.length || loading}
          onClick={() => void onExport()}
        >
          {t('vmaxxdr.export')}
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('vmaxxdr.hintRetention', { h: retentionHours })}
        </Text>
      </Space>

      {noMsisdn && (
        <Alert type="info" showIcon message={t('vmaxxdr.needMsisdn')} />
      )}

      {error && (
        <Alert
          type="error"
          showIcon
          message={t('vmaxxdr.errorTitle')}
          description={error}
          action={
            <Button size="small" icon={<ReloadOutlined />} onClick={onSearch}>
              {t('vmaxxdr.retry')}
            </Button>
          }
        />
      )}

      <Spin spinning={loading}>
        {result && result.rows.length > 0 ? (
          <>
            <Space size="small">
              <Tag color="blue">{t('vmaxxdr.records', { n: result.records })}</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {result.window.starttime} ~ {result.window.endtime}
              </Text>
            </Space>
            <Table
              rowKey={(_, i) => String((result.page - 1) * result.page_size + (i || 0))}
              size="small"
              bordered
              columns={columns as any}
              dataSource={result.rows}
              scroll={{ x: Math.max(900, (result.header.length || 1) * 160) }}
              pagination={{
                current: result.page,
                pageSize: result.page_size,
                total: result.records,
                showSizeChanger: true,
                pageSizeOptions: ['20', '50', '100', '200'],
                showTotal: (n) => t('vmaxxdr.total', { n }),
                onChange: (p, ps) => {
                  // 翻页 / 改页长都重新向后端要数据（上游是服务端分页）
                  setPageSize(ps)
                  run(ctx?.query?.msisdn || msisdn, p, ps, resultWindow)
                },
              }}
            />
          </>
        ) : (
          <Text type="secondary">
            {loading ? t('vmaxxdr.loading') : (searched && !error ? t('vmaxxdr.empty') : t('vmaxxdr.idle'))}
          </Text>
        )}
      </Spin>
    </div>
  )
}
