/* ============================================================================
 * VmaxUserCca —— VMAX 智能诊断工作台（Intelligent Diagnosis Workspace）
 * ============================================================================
 *
 * 2026-11-07 新建，与旧页 VmaxUserQuery（?page=vmax_user_query）**并存**：
 * 旧页保持「按数据源分视图」的查询工具形态，本页是投诉驱动的单页叙事：
 *
 *   区域 1 故障概览   —— VmaxDiagnosisCard 整卡入位（2026-11-07 P1-5 收编：
 *                        此前页面自渲染一份简化结论 + 下方再放整卡，同一
 *                        结论/四维分出现两遍；现在只留整卡一份，四维分带
 *                        MetricExplain 悬浮、数据源行带截断说明、覆写与
 *                        导出都在卡头 —— 导出此前是 () => undefined 死按钮）
 *   区域 2 故障分析   —— 链路 + 五段可解释指标 + 专卡 + 流量 + 时间线
 *   区域 3 根因与建议  —— 根因候选（CCA 关联证据，失败常驻红条）+ 建议
 *                        + 证据库（抽屉）
 *
 * 设计原则（用户 2026-11-07）：
 *   - 系统先给答案，用户沿证据深入（原始 XDR / 无线原始 / TCP 只在点证据时加载）
 *   - 无数据 ≠ 正常（unknown 优先于 ok）
 *   - 跨模块关联：单 TCP 重传不直接定无线问题
 *
 * 取数与计算复用 pages/useVmaxDiagnosis.ts（与旧页同源：抽取时只搬逻辑不改
 * 行为）；URL 命名空间 cca*，与旧页 msisdn/vmaxView/complaint/vq* 零冲突；
 * 结论由 vmaxDiagnosisRules.buildVerdict 原样产出，本页不篡改。
 * ========================================================================== */

import { useMemo, useState } from 'react'
import { Alert, Button, DatePicker, Input, Space, Typography } from 'antd'
import { MobileOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'

import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import VmaxComplaintTabs from '../components/VmaxComplaintTabs'
import {
  disabledRangeProps, PAGE_RETENTION_HOURS, clampRange,
} from './vmaxWindow'
import { VmaxWindowContext } from './vmaxWindowContext'
import { CCA_NS, useVmaxDiagnosis } from './useVmaxDiagnosis'
import { analyzeRateCeiling, analyzeTerminal } from './vmaxDiagnosisRules'
import { buildWorkspaceCorrelation } from '../lib/vmaxWorkspaceRules'
import { buildCellCrossCheck } from '../lib/vmaxCellCrossCheck'
import {
  exportVmaxDiagnosisExcel, exportVmaxPrintPdf,
} from '../lib/vmaxWorkspaceExport'
import VmaxWorkspaceAnalysis from '../components/vmax/VmaxWorkspaceAnalysis'
import VmaxWorkspaceVerdict from '../components/vmax/VmaxWorkspaceVerdict'
import { VmaxRateCard, VmaxTerminalCard } from '../components/vmax/VmaxTerminalRateCards'
import VmaxEvidenceDrawer from '../components/vmax/VmaxEvidenceDrawer'
import type { EvidenceKind } from '../lib/vmaxWorkspaceRules'
import VmaxDiagnosisCard from '../components/VmaxDiagnosisCard'
import VmaxOverrideModal from '../components/VmaxOverrideModal'
import { renderI18n } from '../renderI18n'

const { Text } = Typography
const { RangePicker } = DatePicker

export default function VmaxUserCca() {
  const { t } = useI18n()
  const d = useVmaxDiagnosis(CCA_NS)

  const [drawer, setDrawer] = useState<{ kind: EvidenceKind | null; open: boolean }>({
    kind: null, open: false,
  })
  const openDrawer = (kind: EvidenceKind) => setDrawer({ kind, open: true })

  const ws = useMemo(() => buildWorkspaceCorrelation({
    payload: d.diag,
    sources: d.sources,
    scores: d.scores,
    voice: d.voice,
    ott: d.ott,
    game: d.game,
    radio: d.radio,
    timeline: d.timeline,
    cca: d.result,
    complaint: d.complaint,
  }), [d.diag, d.sources, d.scores, d.voice, d.ott, d.game, d.radio, d.timeline, d.result, d.complaint])

  /* 终端画像 + 限速推断（2026-11-08）：同一批 sources 纯前端算，不重取 */
  const terminal = useMemo(
    () => (d.sources.length ? analyzeTerminal(d.sources) : null), [d.sources])
  const rate = useMemo(
    () => (d.sources.length ? analyzeRateCeiling(d.sources) : null), [d.sources])

  const rangePickerProps = disabledRangeProps(PAGE_RETENTION_HOURS)
  const ctxValue = {
    range: d.range, setRange: d.setRange,
    retentionHours: PAGE_RETENTION_HOURS, query: d.query,
  }

  /* 导出（P0-1）：诊断卡卡头的 Excel/PDF 按钮，与旧页同一套工单摘要，
   * 另多两张工作台表（链路状态 / 根因排行）。
   * P3-2b：再附一张「小区交叉验证」（判据：CCA 指向小区 vs 用户实际驻留），
   * 与区域 2 卡片同一份纯函数结果，点击导出时才算（不新增取数/不占渲染）。 */
  const exportExcel = () => {
    if (!d.diag || !d.verdict) return
    void exportVmaxDiagnosisExcel({
      msisdn: d.query?.msisdn || d.msisdn,
      win: d.diag.window,
      complaint: d.complaint,
      verdict: d.verdict,
      override: d.override,
      scores: d.scores,
      sources: d.diag.sources,
      timeline: d.timeline,
      voice: d.voice,
      flowXdr: d.flowXdr,
      chain: ws.chain,
      rankedCauses: ws.rankedCauses,
      crossCheck: buildCellCrossCheck({ radio: d.radio, cca: d.result }),
    }, t)
  }

  /* 空态按钮跳证据：DiagnosisCard 的「查看连接过程/无线质量」接到证据抽屉，
   * 不让用户点到无响应的按钮。 */
  const gotoEvidence = (v: 'flow' | 'connect' | 'radio') => {
    openDrawer(v === 'connect' ? 'xdr' : v === 'radio' ? 'radio' : 'flow')
  }

  return (
    <VmaxWindowContext.Provider value={ctxValue}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Input
            allowClear
            prefix={<MobileOutlined style={{ color: 'var(--wh-text-dim)' }} />}
            placeholder={t('vmaxq.inputPlaceholder')}
            value={d.msisdn}
            onChange={(e) => d.setMsisdn(e.target.value)}
            onPressEnter={() => void d.run(d.msisdn)}
            style={{ width: 240 }}
            maxLength={24}
          />
          <RangePicker
            value={d.range}
            onChange={(v) => {
              if (v && v[0] && v[1]) d.setRange(clampRange([v[0], v[1]]))
            }}
            allowClear={false}
            showTime={{ format: 'HH:mm' }}
            format="YYYY-MM-DD HH:mm"
            minuteStep={5}
            {...rangePickerProps}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={d.diagLoading || d.loading}
            onClick={() => void d.run(d.msisdn)}
          >
            {t('vmaxq.search')}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.ws.queryHint')}</Text>
        </Space>
      </CardBase>

      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <VmaxComplaintTabs
          value={d.complaint}
          onChange={d.setComplaint}
          disabled={!d.anyData}
        />
      </CardBase>

      {!!d.diagError && (
        <Alert
          type="error" showIcon message={d.diagError}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={d.refresh}>{t('vmaxq.retry')}</Button>}
        />
      )}

      {/* 终端画像 + 限速推断（2026-11-08，用户要求放最上面：先看对象，再看结论） */}
      {d.searched && <VmaxTerminalCard profile={terminal} />}
      {d.searched && <VmaxRateCard rate={rate} />}

      {/* ---------- 区域 1 · 故障概览（VmaxDiagnosisCard 整卡：结论 + 覆写 +
                     四维评分悬浮说明 + 数据源/截断 + 导出） ---------- */}
      <VmaxDiagnosisCard
        payload={d.diag}
        scores={d.scores}
        verdict={d.verdict}
        complaint={d.complaint}
        loading={d.diagLoading}
        error={d.diagError}
        overrides={d.override}
        onOverride={() => d.setOverrideOpen(true)}
        onExportExcel={exportExcel}
        onExportPdf={exportVmaxPrintPdf}
        onRefresh={d.refresh}
        onGotoView={gotoEvidence}
      />

      {/* ---------- 区域 2 · 故障分析 ---------- */}
      <VmaxWorkspaceAnalysis
        metrics={ws.metrics}
        chain={ws.chain}
        complaint={d.complaint}
        voice={d.voice}
        ott={d.ott}
        game={d.game}
        timeline={ws.enrichedTimeline}
        radio={d.radio}
        flowXdr={d.flowXdr}
        scores={d.scores}
        cca={d.result}
        loading={d.diagLoading}
        onOpenEvidence={openDrawer}
      />

      {/* ---------- 区域 3 · 根因与建议（CCA 失败常驻红条，区别于「无根因」） ----------
          P3-1：四源串行 ≈21s，取数期间区域 3 显示「取数 x/4 源」进度而不是
          「暂无根因候选」——半份数据不先下判断。 */}
      <VmaxWorkspaceVerdict
        rankedCauses={ws.rankedCauses}
        recommendations={ws.recommendations}
        ccaError={d.error}
        ccaLoading={d.loading}
        diagLoading={d.diagLoading}
        diagLoaded={d.loadedKeys.length}
        diagTotal={d.diagTotal}
        hypotheses={d.verdict?.hypotheses}
        missingEvidence={d.verdict?.missingEvidence}
        onOpenEvidence={openDrawer}
      />

      <VmaxEvidenceDrawer
        kind={drawer.kind}
        open={drawer.open}
        onClose={() => setDrawer((s) => ({ ...s, open: false }))}
        msisdn={d.msisdn}
        ctx={ctxValue}
        radio={d.radio}
        diagLoading={d.diagLoading}
        flowXdr={d.flowXdr}
        cca={d.result}
      />

      <VmaxOverrideModal
        open={d.overrideOpen}
        autoVerdict={d.verdict ? renderI18n(t, d.verdict.headline) : ''}
        existing={d.override}
        saving={d.overrideSaving}
        onCancel={() => d.setOverrideOpen(false)}
        onSubmit={(v, r) => void d.submitOverride(v, r)}
        onRevoke={() => void d.revokeOverride()}
      />
    </div>
    </VmaxWindowContext.Provider>
  )
}

