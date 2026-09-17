import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * VMAX CXO 日粒度明细（Daily）。
 *
 * 与 vmaxCxoDashboard（原版 15 分钟粒度大屏）、vmaxCxoDashboard_90Days
 * （CXO Daily Dashboard，90 天经营视角）三者完全独立：
 * - 数据源为新任务 vmax_cxo_daily_sync 落盘的 data/vmax_cxo_daily/daily.json
 *   （VMAX 无原生日粒度，日值由 1hour 明细本地聚合），接口 /api/vmax-cxo-daily/*
 * - 图表为「周一~周日 × 本周 / 前一周 / 前两周」三条日粒度曲线
 * - 上游小时明细仅保留约 8 天，早于保留地板的日期以灰空格子 + 悬浮说明呈现
 *
 * ⚠️ 改显示名要同时改 4 处：本文件的 nav.vmaxCxoDashboardDaily（i18n.tsx zh/en 各一处）
 * 与 public/vmax_cxo_dashboard_daily.html 的 <title> / #appTitle / 内联 I18N 的 app.title（zh+en）。
 */
export default function VmaxCxoDashboardDaily() {
  const { t } = useI18n()
  return <LegacyToolFrame file="vmax_cxo_dashboard_daily.html" title={t('nav.vmaxCxoDashboardDaily')} />
}
