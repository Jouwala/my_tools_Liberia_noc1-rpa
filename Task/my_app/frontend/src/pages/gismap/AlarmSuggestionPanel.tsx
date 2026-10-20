import { useEffect, useState, useMemo } from 'react'
import { Card, Spin, Alert, Tag, Tooltip, Button, Collapse, Empty } from 'antd'
import { ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons'
import api from '../../api'
import { useI18n } from '../../i18n'
import { WH, cardStyle, useTheme } from '../../theme'
import { fmtTs } from './helpers'
import { fmtWarnings } from '../../utils/warnCodes'

/**
 * 站点下钻抽屉底部「告警处理建议」面板（2026-10-16 新增）。
 *
 * 数据来源：与 eFlow QA 的 TT Quick Analysis 同源（复用后端 lookup_alarm 链路）
 *   GET /api/gis/site-alarm-suggestions?site_id=&days=&limit=
 *
 * 取数口径：先 realtime_alarm，再叠加 history_alarm（按 days 窗口过滤），
 *           取最近 N 条可解析 alarm_id 的告警，逐条去 UME 取处理建议。
 *
 * 设计取舍：
 *   · 抽屉打开 / site_id 变化 / rangeDays 变化 时自动重取；切到实时抽屉不取。
 *   · 单告警失败 / miss 都不会让整块面板红，**逐条降级**：该条显示错误，其余继续。
 *   · 建议文本走 `pre + white-space: pre-wrap`，与 eFlow QA 的 TT Quick Analysis
 *     视觉一致；default / customer 分两块，对应后端 suggestion.default / .customer。
 *   · 默认全部展开 —— 抽屉底部一次性展示，用户无需额外点击。
 */

export interface AlarmSuggestionItem {
  alarm_id?: string
  alarm_title?: string
  alarmcode?: number | string | null
  severity?: string
  raised_time?: string | number
  tt_id?: string
  source_table?: 'realtime_alarm' | 'history_alarm'
  ok?: boolean
  mode?: string
  suggestion?: { default?: string; customer?: string } | null
  suggestion_error?: string | null
  error?: string | null
  elapsed_sec?: number
}

interface SiteAlarmSuggestionsResp {
  site_id?: string
  items?: AlarmSuggestionItem[]
  elapsed_sec?: number
  warnings?: string[]
  cached?: boolean
}

interface AlarmSuggestionPanelProps {
  /** 站点 ID（必传） */
  siteId: string
  /** 时间窗口天数（与抽屉的 rangeDays 对齐，默认 60） */
  days?: number
  /** 最大条数（默认 20，避免抽屉打开一次打 UME 上百次） */
  limit?: number
  /** 实时模式下不取建议（站点表无历史可关联） */
  enabled?: boolean
}

export function AlarmSuggestionPanel({
  siteId, days = 60, limit = 20, enabled = true,
}: AlarmSuggestionPanelProps) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<SiteAlarmSuggestionsResp | null>(null)
  const [error, setError] = useState<string>('')

  useEffect(() => {
    if (!enabled || !siteId) return
    let alive = true
    setLoading(true)
    setError('')
    api.get('/gis/site-alarm-suggestions', { params: { site_id: siteId, days, limit } })
      .then(res => { if (alive) setData(res.data) })
      .catch(e => {
        if (alive) {
          setError(e?.response?.data?.detail || e?.message || t('gis.alarmSug.fetchFailed'))
          setData(null)
        }
      })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [siteId, days, limit, enabled, t])

  const onRetry = () => {
    setLoading(true)
    setError('')
    api.get('/gis/site-alarm-suggestions', { params: { site_id: siteId, days, limit } })
      .then(res => setData(res.data))
      .catch(e => {
        setError(e?.response?.data?.detail || e?.message || t('gis.alarmSug.fetchFailed'))
        setData(null)
      })
      .finally(() => setLoading(false))
  }

  const items = data?.items || []
  const okCount = useMemo(() => items.filter(i => i.ok).length, [items])
  const sourceLabel = (s?: string) =>
    s === 'realtime_alarm' ? t('gis.alarmSug.sourceRealtime')
      : s === 'history_alarm' ? t('gis.alarmSug.sourceHistory')
      : s || ''

  return (
    <Card
      size="small"
      style={{ ...cardStyle, marginTop: 'var(--wh-space-md)' }}
      title={
        <span style={{ color: WH.text, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <ThunderboltOutlined style={{ color: WH.teal }} />
          <span style={{ fontWeight: 600 }}>{t('gis.alarmSug.title')}</span>
          {data && (
            <span style={{ fontSize: 12, color: WH.textMuted, fontWeight: 400 }}>
              {t('gis.alarmSug.summary', { ok: okCount, total: items.length, sec: data.elapsed_sec ?? 0 })}
            </span>
          )}
          <Button
            size="small"
            type="text"
            icon={<ReloadOutlined />}
            onClick={onRetry}
            disabled={loading}
            style={{ marginLeft: 'auto' }}
          >
            {t('common.refresh')}
          </Button>
        </span>
      }
    >
      {/* 顶部提示：解释数据源与耗时；warnings 用一行小字标出截断/跳过 */}
      <div style={{ marginBottom: 'var(--wh-space-sm)', color: WH.textMuted, fontSize: 12 }}>
        {t('gis.alarmSug.note')}
      </div>
      {data?.warnings && data.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 'var(--wh-space-sm)' }}
          message={fmtWarnings(data.warnings, t, '；')}
        />
      )}

      {loading && !data && (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
          <div style={{ marginTop: 8, color: WH.textMuted, fontSize: 12 }}>
            {t('gis.alarmSug.loading')}
          </div>
        </div>
      )}

      {!loading && error && (
        <Alert
          type="error"
          showIcon
          message={<span style={{ fontSize: 12 }}>{error}</span>}
          action={<Button size="small" onClick={onRetry}>{t('qa.tt.retry')}</Button>}
        />
      )}

      {!loading && !error && items.length === 0 && data && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('gis.alarmSug.empty')}
        />
      )}

      {!loading && !error && items.length > 0 && (
        <Collapse
          ghost
          defaultActiveKey={items.map((_, i) => `sug-${i}`)}
          className="gis-alarm-sug-collapse"
          items={items.map((it, i) => ({
            key: `sug-${i}`,
            label: (
              <span style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                {it.severity && (
                  <Tag color={severityColorOf(it.severity, isDark)} style={{ margin: 0 }}>
                    {it.severity}
                  </Tag>
                )}
                <span style={{ color: WH.text, fontWeight: 600 }}>
                  {it.alarm_title || t('gis.alarmSug.unknownAlarm')}
                </span>
                {it.alarmcode != null && it.alarmcode !== '' && (
                  <Tag style={{ margin: 0 }}>{it.alarmcode}</Tag>
                )}
                <Tooltip title={sourceLabel(it.source_table)}>
                  <Tag color={it.source_table === 'realtime_alarm' ? 'red' : 'default'} style={{ margin: 0 }}>
                    {sourceLabel(it.source_table)}
                  </Tag>
                </Tooltip>
                <span style={{ color: WH.textMuted, fontSize: 12 }}>
                  {fmtTs(it.raised_time)}
                </span>
                {it.tt_id && (
                  <span style={{ color: WH.textMuted, fontSize: 12, fontFamily: 'monospace' }}>
                    TT: {it.tt_id}
                  </span>
                )}
                <Tag
                  color={it.ok ? 'green' : 'orange'}
                  style={{ marginLeft: 'auto', marginRight: 0 }}
                >
                  {it.ok ? t('gis.alarmSug.hasSug') : t('gis.alarmSug.noSug')}
                </Tag>
              </span>
            ),
            children: it.ok
              ? <SuggestionBody item={it} isDark={isDark} t={t} />
              : <Alert
                  type="info"
                  showIcon
                  message={
                    <span style={{ fontSize: 12 }}>
                      {it.suggestion_error || it.error || t('gis.alarmSug.noSugDetail')}
                    </span>
                  }
                />,
          }))}
        />
      )}
    </Card>
  )
}

/** 告警建议正文：default / customer 两块，与 eFlow QA 的 UmeAlarmView 视觉一致。 */
function SuggestionBody({
  item, isDark, t,
}: {
  item: AlarmSuggestionItem
  isDark: boolean
  t: (k: string, p?: Record<string, string | number>) => string
}) {
  const sug = item.suggestion || {}
  const cardBg = isDark ? 'rgba(250,173,20,0.08)' : 'rgba(250,173,20,0.08)'
  return (
    <div
      style={{
        background: cardBg,
        borderRadius: 8,
        padding: '10px 14px',
      }}
    >
      {!!sug.customer && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ color: WH.textMuted, fontSize: 12 }}>customermaintenancename</div>
          <pre style={{
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0',
            fontFamily: 'inherit', fontSize: 13, lineHeight: 1.75, color: WH.text,
          }}>{sug.customer}</pre>
        </div>
      )}
      {!!sug.default && (
        <div>
          <div style={{ color: WH.textMuted, fontSize: 12 }}>defaultmaintenancename</div>
          <pre style={{
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0 0',
            fontFamily: 'inherit', fontSize: 13, lineHeight: 1.75, color: WH.text,
          }}>{sug.default}</pre>
        </div>
      )}
      {!sug.customer && !sug.default && (
        <Alert type="info" showIcon message={t('gis.alarmSug.noSugDetail')} />
      )}
    </div>
  )
}

/** 严重度 → 颜色。复用 helpers.tsx 的 sev map，避免两处撞色。 */
function severityColorOf(sev: string | number, _isDark: boolean): string {
  const m: Record<string, string> = {
    critical: 'red', major: 'orange', warning: 'gold', info: 'blue',
  }
  if (typeof sev === 'number') {
    return m[String(sev)] || 'default'
  }
  return m[String(sev).toLowerCase()] || 'default'
}