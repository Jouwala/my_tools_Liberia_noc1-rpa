/* ============================================================================
 * VmaxFlowCategoryTabs —— 「流量信息」按分类拆两级页签
 * ============================================================================
 *
 * 2026-10-30 新增：参考面板是**两级页签**结构：
 *   第一级：数据 | 语音
 *   第二级：流量 | 视频 | 网页 | 游戏 | OTT语音 | OTT视频 | TCP指标 | 控制面
 *
 * 【数据源改为 XDR 用户面话单】（2026-10-30 用户反馈「应该使用 XDR 信令等
 * 获取的数据生成，而不是 Traffic Info」）
 *   原先数据来自 CCA 的 DPI 流量（query_flow），但**实测绝大多数用户为空**
 *   （total_flux="--"、app_flux="[]"，CCA 网页同样为空）——那是采集侧的问题。
 *   现在改由后端用 Talon XDR 用户面话单（fact_5gsa_psup_flow 等）自行聚合：
 *   后端已按上游 service 口径分好类，下发 {categories, apps, total_flux}，
 *   分类与指标口径都在后端（services/vmax_cca/vmax_flow_from_xdr.py），
 *   前端不自己猜分类。
 *
 * 【页签条恒在】
 *   页签结构本身是「这个面板长什么样」的信息，不该随数据有无消失 ——
 *   否则用户看到的就是一句空态文案，误以为功能没做。
 *
 * 【语音档】
 *   上游 Talon XDR 的用户面话单**没有语音口径**（只有数据面），
 *   所以「语音」这一档选中时给出明确说明，而不是静默隐藏。
 * ========================================================================== */

import { useMemo, useState } from 'react'
import { Descriptions, Segmented, Space, Table, Tag, Tooltip, Typography } from 'antd'

import { useI18n } from '../i18n'

const { Text } = Typography

/** 与后端 CATEGORY_KEYS 一一对应（顺序即面板顺序） */
export type CategoryKey =
  | 'all' | 'video' | 'web' | 'game' | 'ottvoice' | 'ottvideo'
  | 'tcp' | 'control'

const CATEGORY_ORDER: CategoryKey[] = [
  'all', 'video', 'web', 'game', 'ottvoice', 'ottvideo', 'tcp', 'control',
]

/** 应用分类页签对应的后端分类 key（tcp/control 是指标口径，不对应应用分类） */
const CATEGORY_TO_BACKEND_KEY: Partial<Record<CategoryKey, string>> = {
  video: 'video',
  web: 'web',
  game: 'game',
  ottvoice: 'ottvoice',
  ottvideo: 'ottvideo',
}

/** KPI 行（后端 _quality_kpis 的输出） */
export type FlowKpi = {
  /** i18n key 后缀，前端拼 `vmaxq.flow.kpi.<key>`；老版本后端没有此字段 */
  key?: string
  /** 中文原文，key 缺失时兜底 */
  name: string
  value: string
  unit: string
  /** 包数类指标的原始值；有它前端按语言缩进，没有则回退 value */
  raw?: number
}

/** 应用行（后端 vmax_flow_from_xdr._app_rows 的输出） */
export type FlowApp = {
  app_name: string
  category: string
  /** i18n key 后缀，前端拼 `vmaxq.flow.svc.<service_key>`；未登记时为空串 */
  service_key?: string
  /** 中文原文，service_key 缺失时兜底 */
  category_label: string
  service: string
  subservice: string
  records: number
  ul_traffic: string
  dl_traffic: string
  total_traffic: string
  total_traffic_kb: number
  ul_pkt: string
  dl_pkt: string
  ratio: string
}

/** 分类页签数据（后端 aggregate_categories 的输出） */
export type FlowCategory = {
  key: string
  apps: FlowApp[]
  kpis: FlowKpi[]
  total_flux: string
  total_flux_kb: number
}

export type FlowData = {
  found?: boolean
  total_flux: string
  total_flux_kb?: number
  apps: FlowApp[]
  categories: FlowCategory[]
  /** 数据来源标记（xdr_user_plane）；用于卡片上标注来源 */
  source?: string
  records?: number
}

/** 统一空值展示：— 而不是 undefined / null（AGENTS.md 三.6） */
const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

/**
 * 包量的本地化格式（KPI 表的包数类指标用）。
 *
 * 后端 `_fmt_packets` 输出的是「1.42 万」——「万」是中文数字单位，
 * 英文界面会原样露出中文。单位词属于文案，且本接口没有 lang 参数，
 * 所以后端改成同时给原始数字（kpi.raw），由前端按当前语言缩进：
 * 中文按万（10^4）、英文按 K（10^3）。取不到原值时回退后端字符串。
 */
function usePacketFormatter() {
  const { t, locale } = useI18n()
  return (raw: number | undefined, fallback: string): string => {
    if (raw === undefined || raw === null || !raw) return fallback
    if (raw < 10000) return String(raw)
    // 除数跟着语言走（万=10^4、K=10^3），字典只出单位词。
    // 不能用一个「{{v}} 万 / {{v}}K」模板吃同一个数值：1.42 万 == 14200，
    // 而 1.42K == 1420，同一个 v 在两门语言下表示的量差 10 倍。
    const unit = t('vmaxq.flow.pktUnit')
    return locale === 'zh'
      ? `${(raw / 1e4).toFixed(2)} ${unit}`
      : `${(raw / 1e3).toFixed(1)}${unit}`
  }
}

export default function VmaxFlowCategoryTabs({
  flow,
}: {
  flow: FlowData | null | undefined
}) {
  const { t } = useI18n()
  const fmtPkt = usePacketFormatter()
  const [active, setActive] = useState<CategoryKey>('all')
  /* 第一级：数据 | 语音。默认「数据」——用户面话单只有数据面（见文件头）。 */
  const [serviceType, setServiceType] = useState<'data' | 'voice'>('data')

  const categories = useMemo(() => flow?.categories || [], [flow])

  const catByKey = useMemo(() => {
    const m = new Map<string, FlowCategory>()
    categories.forEach((c) => m.set(c.key, c))
    return m
  }, [categories])

  /* 每个页签展示的应用 + 指标：
     - 应用分类页签（视频/网页/…）：后端该分类的应用列表
     - 流量（all）：全部应用 + 全量指标
     - TCP指标 / 控制面：后端已按指标口径算好的 kpis */
  const tabData = useMemo(() => {
    const out = new Map<CategoryKey, { apps: FlowApp[]; kpis: FlowKpi[] }>()
    for (const key of CATEGORY_ORDER) {
      if (key === 'all') {
        out.set(key, { apps: flow?.apps || [], kpis: catByKey.get('all')?.kpis || [] })
        continue
      }
      const backendKey = CATEGORY_TO_BACKEND_KEY[key]
      const src = backendKey ? catByKey.get(backendKey) : catByKey.get(key)
      out.set(key, { apps: src?.apps || [], kpis: src?.kpis || [] })
    }
    return out
  }, [catByKey, flow])

  const current = tabData.get(active) || { apps: [], kpis: [] }
  const hasAnyData = !!flow?.found && (!!flow?.apps?.length || categories.length > 0)

  const appColumns = [
    { title: t('vmaxq.flow.appName'), dataIndex: 'app_name', width: 200, ellipsis: true },
    { title: t('vmaxq.flow.category'), dataIndex: 'category_label', width: 110,
      /* 优先用 service_key 查当前语言；未登记的 service 只有中文原文，原样显示。
         service_key 由后端给（见 vmax_flow_from_xdr.SERVICE_KEYS），
         不靠中文名反查 —— 文案会改名，key 不会。 */
      render: (v: string, r: FlowApp) => {
        const label = r.service_key ? t(`vmaxq.flow.svc.${r.service_key}`) : v
        return label ? <Tag color="blue">{label}</Tag> : '—'
      } },
    { title: t('vmaxq.flow.ulTraffic'), dataIndex: 'ul_traffic', width: 100,
      align: 'right' as const, render: (v: string) => fmt(v) },
    { title: t('vmaxq.flow.dlTraffic'), dataIndex: 'dl_traffic', width: 100,
      align: 'right' as const, render: (v: string) => fmt(v) },
    { title: t('vmaxq.flow.totalTraffic'), dataIndex: 'total_traffic', width: 110,
      align: 'right' as const, render: (v: string) => fmt(v) },
    { title: t('vmaxq.flow.ratio'), dataIndex: 'ratio', width: 80, align: 'right' as const,
      render: (v: string) => fmt(v) },
  ]

  const kpiColumns = [
    /* KPI 名同样是后端文案：优先 key（字典），缺键时回退中文 name。
       rowKey 仍用 name —— key 可能缺失（老版本后端），name 一定在。 */
    { title: t('vmaxq.flow.kpiName'), dataIndex: 'name', ellipsis: true,
      render: (v: string, r: FlowKpi) => (r.key ? t(`vmaxq.flow.kpi.${r.key}`) : v) },
    { title: t('vmaxq.flow.kpiValue'), dataIndex: 'value', width: 110, align: 'right' as const,
      render: (v: string, r: FlowKpi) => fmtPkt(r.raw, v) },
    { title: t('vmaxq.flow.kpiUnit'), dataIndex: 'unit', width: 80,
      render: (v: string) => fmt(v) },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
      {/* 第一级页签：数据 | 语音（对齐参考面板）*/}
      <Space size="small" wrap>
        <Segmented
          className="wh-seg"
          options={[
            { label: t('vmaxq.flow.svc.data'), value: 'data' },
            { label: t('vmaxq.flow.svc.voice'), value: 'voice' },
          ]}
          value={serviceType}
          onChange={(v) => setServiceType(v as 'data' | 'voice')}
          style={{ background: 'var(--wh-seg-bg)' }}
        />
        {serviceType === 'voice' && (
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.flow.voiceUnsupported')}</Text>
        )}
      </Space>

      {/* 第二级页签：八个分类。恒在渲染（无数据时也在），否则用户看不到结构。*/}
      <Segmented
        className="wh-seg"
        options={CATEGORY_ORDER.map((k) => ({
          label: t(`vmaxq.flow.cat.${k}`),
          value: k,
        }))}
        value={active}
        onChange={(v) => setActive(v as CategoryKey)}
        style={{ background: 'var(--wh-seg-bg)', maxWidth: '100%', overflowX: 'auto' }}
      />

      {serviceType === 'voice' ? (
        /* 语音档：XDR 用户面话单没有语音口径，说明写清楚。 */
        <Text type="secondary">{t('vmaxq.flow.voiceUnsupported')}</Text>
      ) : (
        <>
          <Descriptions size="small" bordered column={1} items={[{
            key: 'total', label: t('vmaxq.flowTotal'),
            children: <Text strong>{fmt(flow?.total_flux)}</Text>,
          }]} />

          {current.kpis.length > 0 && (
            <Table
              rowKey={(r) => r.name}
              size="small"
              bordered
              columns={kpiColumns}
              dataSource={current.kpis}
              pagination={false}
              scroll={{ x: 420 }}
            />
          )}

          {current.apps.length > 0 ? (
            <Table
              rowKey={(r) => r.app_name + String(r.total_traffic)}
              size="small"
              bordered
              columns={appColumns}
              dataSource={current.apps}
              pagination={{ pageSize: 10, showSizeChanger: true }}
              scroll={{ x: 700 }}
            />
          ) : (
            <Tooltip title={hasAnyData ? '' : t('vmaxq.noFlow')}>
              <Text type="secondary">{t('vmaxq.flow.noApps')}</Text>
            </Tooltip>
          )}
        </>
      )}
    </div>
  )
}
