/* ==================== NUR 计算链路说明（默认收起） ====================
 * NUR 口径的**唯一说明出处**：NurDashboard（page=nur / ms_nur_only）与
 * MsSlaDashboard（page=ms_sla）都渲染 KPI List NUR，两页共用本组件。
 *
 * 为什么抽出来而不是各页写一份：
 *   NUR 的口径细节多（告警归属规则表、站点小区数按站名取、分子分母筛选范围不一致），
 *   两处各维护一份必然分叉 —— 而"同一个数字在两页有不同解释"是比数字本身更糟的问题。
 *
 * 载体是 CalcChainNote（默认收起，点击标题展开），与全站既有约定一致
 * （BmMeta 的 scopeOpen / BpReport 的 caliberOpen）。
 * ================================================================ */
import { useState } from 'react'
import { Alert, Input, Space, Table, Tag, Tooltip } from 'antd'
import { DownOutlined, SearchOutlined } from '@ant-design/icons'
import { WH } from '../theme'
import { useI18n } from '../i18n'
import CalcChainNote from './CalcChainNote'
import DraggableClickModal from './DraggableClickModal'

/** 后端 nur_calc 下发的结构化告警明细（与 warnings 文案并列）。 */
export interface WarningDetailSite {
  name: string
  rows: number
}
export interface WarningDetail {
  kind: string
  title: string
  note?: string
  rows?: number
  sites?: WarningDetailSite[]
}

interface Props {
  /** 后端 warnings（如"站点在 cm_site_summary 找不到小区信息"）。
   *  传入后作为**常驻告警**渲染，不随收起隐藏 —— 口径有异常时必须始终可见。 */
  warnings?: string[]
  /** 与 warnings 对应的结构化明细；有 unmatched_sites 时告警条可点击展开完整站点清单。 */
  warningDetails?: WarningDetail[]
  /** 是否包含 SLA 小节（page=nur / ms_sla 全量时给出；ms_nur_only 只有 NUR 则省略） */
  withSla?: boolean
  style?: React.CSSProperties
}

export default function NurCalcChainNote({
  warnings, warningDetails, withSla = false, style,
}: Props) {
  const { t } = useI18n()
  return (
    <CalcChainNote
      style={style}
      title={t('nur.calcNote.title')}
      warning={warnings && warnings.length > 0
        ? <UnmatchedSitesAlert warnings={warnings} details={warningDetails} />
        : undefined}
      sections={[
        {
          title: t('nur.calcNote.sec.source'),
          lines: [
            t('nur.calcNote.src.tt'),
            t('nur.calcNote.src.cm'),
            t('nur.calcNote.src.site'),
            t('nur.calcNote.src.exclude'),
          ],
        },
        {
          title: t('nur.calcNote.sec.filter'),
          lines: [
            t('nur.calcNote.filter.narrow'),
            t('nur.calcNote.filter.both'),
          ],
        },
        {
          title: t('nur.calcNote.sec.match'),
          lines: [
            t('nur.calcNote.match.rule'),
            t('nur.calcNote.match.single'),
            t('nur.calcNote.match.sw'),
          ],
        },
        {
          title: t('nur.calcNote.sec.cells'),
          lines: [
            t('nur.calcNote.cells.why'),
            t('nur.calcNote.cells.demo'),
            t('nur.calcNote.cells.order'),
            t('nur.calcNote.cells.warn'),
          ],
        },
        {
          title: t('nur.calcNote.sec.formula'),
          lines: [
            t('nur.calcNote.formula.main'),
            t('nur.calcNote.formula.gr'),
            t('nur.calcNote.formula.unit'),
            t('nur.calcNote.formula.global'),
            ...(withSla ? [t('nur.calcNote.formula.sla')] : []),
          ],
        },
        {
          title: t('nur.calcNote.sec.drill'),
          lines: [
            t('nur.calcNote.drill'),
            t('nur.calcNote.persite'),
            t('nur.calcNote.cache'),
          ],
        },
      ]}
    />
  )
}

/* ==================== 未匹配站点告警条（可点击看全部站点） ====================
 * 后端 warnings 文案里只放前 8 个站点名 + 省略号（实测最多 26 个），
 * 用户需要能查全部 —— 故告警条本身可点击，弹层里给出完整清单 + 每站影响行数。
 *
 * 为什么用弹层而不是把全部名字塞进告警条：
 *   - 26 个站点名会把告警条撑成一大段，挤占首屏；
 *   - 弹层内可搜索、可排序（按影响行数），便于定位"哪个站点最值得修"。
 * ================================================================ */
function UnmatchedSitesAlert({ warnings, details }: {
  warnings: string[]
  details?: WarningDetail[]
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')

  const um = details?.find(d => d.kind === 'unmatched_sites')
  const sites = um?.sites || []
  // 无结构化明细时退回纯文案（老后端 / 其他告警类型），不做成可点击的死入口
  const clickable = sites.length > 0

  const rows = sites
    .filter(s => !q || s.name.toLowerCase().includes(q.toLowerCase()))
    .map((s, i) => ({ key: i, ...s }))

  return (
    <>
      <Alert
        type="warning" showIcon
        style={{ marginBottom: 'var(--wh-space-md)' }}
        message={
          <span
            onClick={() => clickable && setOpen(true)}
            style={{ cursor: clickable ? 'pointer' : 'default', userSelect: 'none' }}
          >
            {warnings.join('; ')}
            {clickable && (
              <a style={{ marginLeft: 8, fontSize: 12 }}>
                {t('nur.warn.viewAllSites', { n: sites.length })}
                <DownOutlined style={{ fontSize: 10, marginLeft: 4 }} />
              </a>
            )}
          </span>
        }
      />

      <DraggableClickModal
        open={open}
        onClose={() => { setOpen(false); setQ('') }}
        title={
          <span style={{ color: WH.text }}>
            {um?.title || t('nur.warn.unmatchedTitle')}
            <Tag color="orange" style={{ marginLeft: 8 }}>{t('common.records', { n: sites.length })}</Tag>
          </span>
        }
      >
        {/* 口径说明：这些行为什么被排除，避免用户以为"数据丢了" */}
        {um?.note && (
          <Alert type="info" showIcon message={um.note}
            style={{ marginBottom: 'var(--wh-space-md)' }} />
        )}
        <Space style={{ marginBottom: 'var(--wh-space-sm)' }} wrap>
          <Input
            prefix={<SearchOutlined />}
            placeholder={t('common.searchAllFields')}
            allowClear
            value={q}
            onChange={e => setQ(e.target.value)}
            style={{ width: 'min(100%, 18rem)' }}
          />
          {/* 站点数不多（实测 ≤26），但行数分布偏斜，排序后便于定位主要影响站点 */}
        </Space>
        <Table
          dataSource={rows}
          size="small"
          pagination={rows.length > 15 ? { pageSize: 15, size: 'small' } : false}
          columns={[
            {
              title: t('nur.warn.colSite'), dataIndex: 'name', key: 'name',
              render: (v: string) => <span style={{ color: WH.text }}>{v}</span>,
            },
            {
              title: t('nur.warn.colRows'), dataIndex: 'rows', key: 'rows',
              defaultSortOrder: 'descend' as const,
              sorter: (a: any, b: any) => a.rows - b.rows,
              render: (v: number) => (
                <Tooltip title={t('nur.warn.rowsTip')}><span>{v}</span></Tooltip>
              ),
            },
          ]}
        />
      </DraggableClickModal>
    </>
  )
}

