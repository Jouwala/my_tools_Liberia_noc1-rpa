import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

/**
 * MW UME 微波网络拓扑 NOC 看板
 *
 * 数据源为 my_app 后端 API /api/mw-ume/topology（mw_ume_kpi_sync 每日 05:15
 * 写入主库 mw_ume_bw_ultilazation 后由 backend/services/mw_ume/mw_ume_topology.py
 * 转换为 Nodes/Edges/KPIs/TopRisks/Trends）。
 *
 * 页面由 public/mw_ume_topology.html 承载：逻辑/地理双布局拓扑 + 链路健康度
 * 分级（Healthy/Watch/Warning/Critical）+ Tx/Rx 分离展示 + Top Risk 定位 +
 * 链路详情抽屉 + 全网趋势（多日自动累积）。
 */
export default function MwUmeDashboard() {
  const { t } = useI18n()
  return <LegacyToolFrame file="mw_ume_topology.html" title={t('nav.mwUmeTopology')} />
}
