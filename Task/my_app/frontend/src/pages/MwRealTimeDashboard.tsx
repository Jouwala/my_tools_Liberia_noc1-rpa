import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * MW UME 微波网络实时 NOC 看板
 *
 * 数据源为 my_app 后端 API /api/mw-ume/realtime（mw_ume_kpi_sync_rt 每 15 分钟
 * 以 15 分钟粒度（gr=900）取最近 2 小时写入主库 mw_ume_bw_ultilazation_rt，
 * 后端取最新一个 15 分钟槽位构建 Nodes/Edges/KPIs/TopRisks/Trends）。
 *
 * 页面由 public/mw_real_time.html 承载：与 MW 微波拓扑看板完全同构
 * （逻辑/地理双布局拓扑 + 链路健康度分级 + Tx/Rx 分离展示 + Top Risk 定位 +
 * 链路详情抽屉 + 15 分钟粒度趋势），数据每 15 分钟自动更新。
 */
export default function MwRealTimeDashboard() {
  const { t } = useI18n()
  return <LegacyToolFrame file="mw_real_time.html" title={t('nav.mwRealTime')} />
}
