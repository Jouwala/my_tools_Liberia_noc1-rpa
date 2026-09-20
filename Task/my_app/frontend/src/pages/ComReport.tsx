import SpReportBase from './SpReportBase'

/**
 * 耗材汇总报表（page=com_report）
 *
 * 数据源：`data/sp_email/Comsumables Inbound&Outbound&Inventory <时间戳>.xlsx`
 * （任务 sp_report_generate 每天 05:15 产出；文件名前缀沿用生成端的拼写
 * "Comsumables"，不要"顺手修正"，否则匹配不到文件）。
 * 与备件页（`?page=sp_report`）共用 SpReportBase，只是 kind 不同。
 */
export default function ComReport() {
  return <SpReportBase kind="consumables" />
}
