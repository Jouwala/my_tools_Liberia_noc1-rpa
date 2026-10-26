/* ============================================================================
 * VmaxXdrQuery —— VMAX 信令详单（Talon XDR 合并表）
 * ============================================================================
 *
 * 输入号码 + 时间窗 + 查询类型 → 后端经 Talon XDR 合并查询接口
 * （services/vmax_cca/vmax_xdr_client.py）取该号码窗口内的逐条信令记录。
 *
 * 与 VmaxUserQuery（CCA 投诉摘要）的区别：CCA 给"用户画像 + 根因摘要"，
 * 本页给"逐条原始信令详单"——用于排障时下钻到单次会话/过程。
 *
 * 列不是写死的：后端把 get_xdrheader_info 的 field/header 一起返回，
 * 前端按 header 动态建列（上游加字段不会白屏）。列多（59~88 列）且横向长，
 * 表格可横向滚动，首列冻结。
 *
 * 三态渲染与请求序号守卫沿用 VmaxUserQuery（防旧请求迟到回写）。
 * ========================================================================== */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert, Button, DatePicker, Input, Select, Space, Spin, Table, Tag, Typography,
} from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import { vmaxXdrQuery, vmaxXdrServices } from '../api'

const { Text } = Typography
const { RangePicker } = DatePicker

type ServiceItem = { id: string; name: string; name_zh?: string }

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

/** 时间窗默认：最近 24 小时（信令详单一天可达万级记录，再大既慢又难读） */
const defaultRange = () => [dayjs().subtract(24, 'hour'), dayjs()] as [dayjs.Dayjs, dayjs.Dayjs]

export default function VmaxXdrQuery() {
  const { t, locale } = useI18n()

  const [msisdn, setMsisdn] = useState('')
  const [serviceType, setServiceType] = useState('1100')
  const [range, setRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(defaultRange)
  const [page, setPage] = useState(1)
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
      .then((r) => setServices((r.data?.services || []) as ServiceItem[]))
      .catch(() => setServices([]))     // 取不到就用空清单，不阻塞主流程
  }, [])

  const run = useCallback(async (raw: string, p: number, ps: number) => {
    const q = raw.trim()
    if (!q) return
    const seq = ++seqRef.current
    setLoading(true)
    setError('')
    setSearched(true)
    try {
      const r = await vmaxXdrQuery({
        msisdn: q,
        service_type: serviceType,
        start: range?.[0]?.format('YYYY-MM-DD HH:mm') || undefined,
        end: range?.[1]?.format('YYYY-MM-DD HH:mm') || undefined,
        page: p,
        page_size: ps,
      })
      if (seq !== seqRef.current) return      // 已有更新的查询，丢弃本次结果
      setResult(r.data as XdrResult)
    } catch (e: any) {
      if (seq !== seqRef.current) return
      // 后端 HTTPException 的中文说明在 detail（凭据未配置 / 上游不可用等）
      setError(e?.response?.data?.detail || e?.message || String(e))
      setResult(null)
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [serviceType, range])

  const onSearch = () => { setPage(1); run(msisdn, 1, pageSize) }

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

  const serviceLabel = (s: ServiceItem) => (
    locale === 'zh' ? (s.name_zh || s.name) : s.name
  )

  return (
    <div style={{ padding: 16 }}>
      <CardBase title={t('vmaxxdr.title')}>
        <Space wrap size="middle">
          <Input
            allowClear
            style={{ width: 240 }}
            placeholder={t('vmaxxdr.msisdnPlaceholder')}
            value={msisdn}
            onChange={(e) => setMsisdn(e.target.value)}
            onPressEnter={onSearch}
          />
          <Select
            style={{ width: 200 }}
            value={serviceType}
            onChange={(v) => { setServiceType(v); setPage(1) }}
            options={services.map((s) => ({ value: s.id, label: serviceLabel(s) }))}
            placeholder={t('vmaxxdr.servicePlaceholder')}
          />
          <RangePicker
            showTime={{ format: 'HH:mm' }}
            format="YYYY-MM-DD HH:mm"
            value={range}
            onChange={(v) => setRange(v as [dayjs.Dayjs, dayjs.Dayjs] | null)}
            allowClear={false}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={loading}
            onClick={onSearch}
          >
            {t('vmaxxdr.search')}
          </Button>
        </Space>
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxxdr.hint')}</Text>
        </div>
      </CardBase>

      {error && (
        <Alert
          style={{ marginTop: 12 }}
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

      {searched && !error && (
        <CardBase
          title={t('vmaxxdr.resultTitle')}
          style={{ marginTop: 12 }}
          extra={result ? (
            <Space size="small">
              <Tag color="blue">{t('vmaxxdr.records', { n: result.records })}</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {result.window.starttime} ~ {result.window.endtime}
              </Text>
            </Space>
          ) : undefined}
        >
          <Spin spinning={loading}>
            {result && result.rows.length > 0 ? (
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
                    setPage(p); setPageSize(ps)
                    run(msisdn, p, ps)
                  },
                }}
              />
            ) : (
              <Text type="secondary">
                {loading ? t('vmaxxdr.loading') : t('vmaxxdr.empty')}
              </Text>
            )}
          </Spin>
        </CardBase>
      )}
    </div>
  )
}
