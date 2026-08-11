import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * 事件总览（Incident Overview）
 *
 * 完整复用 Unified_Tools/incident_overview/index.html 的原版界面，
 * 由 TMP/patch_legacy_html.py 同步到 public/incident-overview.html，仅把
 * API_BASE_PATH 改写为 /api/incident-overview 指向本项目后端。
 *
 * 后端实现见 backend/services/incident_overview_service.py（Excel 七表解析、
 * mtime 缓存、GeoJSON、虚拟助理）与 incident_ai_service.py（6 家 AI 供应商代理），
 * 路由见 backend/routers/incident_overview.py。
 */
export default function IncidentOverview() {
  const { t } = useI18n()
  return <LegacyToolFrame file="incident-overview.html" title={t('shell.incidentOverview')} />
}
