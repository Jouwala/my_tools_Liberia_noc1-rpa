import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * IP 链路探测（IP Trace）
 *
 * 完整复用 Unified_Tools/IP_Trace_Tool/templates/index.html 的原版界面，
 * 由 TMP/patch_legacy_html.py 同步到 public/ip-trace.html，仅把接口基址
 * （window.APP_BASE_PATH）改写为 /api/ip-trace 指向本项目后端。
 *
 * 后端实现见 backend/services/ip_trace_service.py + backend/routers/ip_trace.py，
 * 提供 /trace /status /stop /analyze 四个端点，与原版 Flask 路由一一对应。
 */
export default function IpTrace() {
  const { t } = useI18n()
  return <LegacyToolFrame file="ip-trace.html" title={t('shell.ipTrace')} />
}
