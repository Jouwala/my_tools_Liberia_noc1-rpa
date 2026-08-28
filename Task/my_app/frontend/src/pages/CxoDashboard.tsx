import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * CXO Dashboard（Service / Network / Summary 三层经营看板）
 *
 * 数据源为 VMAX 实时保障看板（ds_dashboard_Overseas），由 public/cxo_dashboard.html
 * 承载。该 HTML 内嵌一份完整数据快照，因此即使代理或 VMAX 不可用也能完整渲染；
 * 打开时会自动尝试拉取一次实时数据，成功则覆盖快照。
 *
 * 主题同步（与 AlarmManagement 同一套约定）：读取同源 localStorage['myapp-theme']，
 * 监听父页面 postMessage 的 __type:'myapp-theme' 事件，并跟随系统 prefers-color-scheme；
 * 图表侧注册 amDark / amLight 两套 ECharts 主题并在切换时重建实例，同时对快照里
 * 硬编码的白色文字做浅色模式改写，避免浅色下白字不可读。
 *
 * 实时数据经**独立**的 VMAX 代理拉取（scripts/realtime_proxy_vmax.py，127.0.0.1:8790）。
 * 注意：不能复用告警看板的 8787 代理 —— 那一路是 FMS 专用（目标主机与路径都做了
 * 白名单校验），且两侧鉴权方式不同（VMAX 需要门户 JSESSIONID + forgerydefense +
 * ECMA 模块激活）。代理同样由 scripts/start-app.mjs 随 myapp 启停。
 */
export default function CxoDashboard() {
  const { t } = useI18n()
  return <LegacyToolFrame file="cxo_dashboard.html" title={t('nav.cxoDashboard')} />
}
