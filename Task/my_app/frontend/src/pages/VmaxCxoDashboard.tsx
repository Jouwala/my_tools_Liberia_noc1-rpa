import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * VMAX CXO Dashboard 原版视觉复刻页。
 * 与现有 cxoDashboard 完全独立，避免影响生产中的简化版看板。
 */
export default function VmaxCxoDashboard() {
  const { t } = useI18n()
  return <LegacyToolFrame file="vmax_cxo_dashboard.html" title={t('nav.vmaxCxoDashboard')} />
}
