import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * SOC 多维趋势组合看板（socTrendDashboard）。
 *
 * 与 vmaxCxoDashboard 三兄弟完全独立：
 * - 数据源 data/soc_trend/soc_trend.sqlite3（任务 47 soc_trend_sync 直连 VMAX 数仓 GBase
 *   **只读**拉取落盘），接口 /api/soc-trend/*
 * - 页面为「数据 / 语音」双页签 × 8 类目 × 区域/网元维度的三日（D / D-1 / D-7）对比看板，
 *   带双基线（D-1 与 D-7 同时越限）重大告警分析与局部异常雷达
 * - 控制面与语音页签在数仓暂无对应数据，先做空态占位（meta.cats.*.ready 控制）
 *
 * ⚠️ 改显示名要同时改 2 处：本文件的 nav.socTrendDashboard（i18n.tsx zh/en 各一处）
 * 与 public/soc_trend_dashboard.html 的 <title> / #appTitle / 内联 I18N 的 app.title（zh+en）。
 */
export default function SocTrendDashboard() {
  const { t } = useI18n()
  return <LegacyToolFrame file="soc_trend_dashboard.html" title={t('nav.socTrendDashboard')} />
}
