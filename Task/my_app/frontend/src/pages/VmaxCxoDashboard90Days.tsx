import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * CXO Daily Dashboard（90 Days，原「VMAX 90 天经营看板」）—— 面向 CEO 的经营视角大屏。
 *
 * 与 vmaxCxoDashboard（VMAX CXO 原版看板，15 分钟大屏）、
 * vmaxCxoDashboard_Daily（VMAX CXO 日粒度明细，周一~周日三条曲线）并列独立，
 * 数据源是本项目自己的数仓直连结果：
 * - 任务 olib_soc_vmax_report / olib_soc_kpi_daily_sync 把日粒度 KPI 落到
 *   data/olib_soc_report/olib_soc_report.sqlite3 的 daily_kpi 表
 * - 接口 /api/olib-soc-dashboard/overview（只读，日/周趋势 + 昨日卡片 + 90 天极值）
 * - 页面文件 public/vmax_cxo_dashboard_90days.html
 *
 * ⚠️ 改显示名要同时改 6 处：i18n.tsx 的 nav.vmaxCxoDashboard90Days（zh/en）
 * 与 public/vmax_cxo_dashboard_90days.html 的 <title> / #appTitle / 内联 I18N 的
 * title（zh+en）—— 该页还会用 t('title') 覆写 document.title。
 */
export default function VmaxCxoDashboard90Days() {
  const { t } = useI18n()
  return <LegacyToolFrame file="vmax_cxo_dashboard_90days.html" title={t('nav.vmaxCxoDashboard90Days')} />
}
