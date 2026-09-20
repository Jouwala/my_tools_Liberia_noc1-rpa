import SpReportBase from './SpReportBase'

/**
 * SP 备件汇总报表（page=sp_report）
 *
 * 数据源：`data/sp_email/SpareParts Inbound&Outbound&Inventory <时间戳>.xlsx`
 * （任务 sp_report_generate 每天 05:15 产出）。
 * 与耗材页（`?page=com_report`）共用 SpReportBase，只是 kind 不同。
 */
export default function SpReport() {
  return <SpReportBase kind="spareparts" />
}
