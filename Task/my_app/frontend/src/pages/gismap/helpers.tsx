import { Tag } from 'antd'
import dayjs from 'dayjs'
import { exportAoaReport } from '../../utils/excelReport'
import type { TFn } from './types'

// 按关键字全字段过滤表格行
export const filterBySearch = (data: any[], search: string) => {
  if (!search.trim()) return data
  const lower = search.toLowerCase()
  return data.filter(row =>
    Object.values(row).some(v => v != null && String(v).toLowerCase().includes(lower))
  )
}

// 导出表格数据为 Excel
// 已迁统一格式 UNIFIED_EXCEL_V1：样式与邮件报表同源，见 docs/EXCEL_EXPORT_STANDARD.md
// 注意 filename 同时用作 sheet 名，可能含 Excel 禁用字符（如 "/"）—— 净化与重名去重
// 现由 excelReport 的 uniqueSheetName 统一处理，这里不再手写。
export const exportToExcel = (data: any[], filename: string, columns: { title: string; dataIndex: string }[]) => {
  if (!data.length) return
  const header = columns.map(c => c.title)
  const keys = columns.map(c => c.dataIndex)
  const rows = data.map(row => keys.map(k => {
    const v = row[k]
    return v == null ? '' : String(v)
  }))
  void exportAoaReport({
    filename: `${filename}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
    sheetName: filename,
    title: filename,
    header,
    rows,
    columnWidths: columns.map(() => 18),
  })
}

export const strSorter = (a: any, b: any, key: string) => {
  const va = a[key] ?? '', vb = b[key] ?? ''
  return String(va).localeCompare(String(vb))
}

export const getUniqueFilters = (data: any[], key: string) => {
  const vals = new Set<string>()
  data.forEach(r => { if (r[key] != null && r[key] !== '') vals.add(String(r[key])) })
  return Array.from(vals).map(v => ({ text: v, value: v }))
}

// 告警列名 -> 可读标题映射
export const ALARM_COL_TITLES: Record<string, string> = {
  alarm_title: 'Alarm Title', codename: 'Code Name', perceivedseverity: 'Severity',
  perceivedseverityname: 'Severity Name', durationname: 'Duration', duration: 'Duration(s)',
  alarmraisedtime: 'Alarm Raised', servertime: 'Server Time', alarmchangedtime: 'Alarm Changed',
  acktime: 'Ack Time', assigned_time: 'Assigned Time', assigned_status: 'Assigned Status',
  assign_start_time: 'Assign Start', assign_delay: 'Assign Delay', assigned_user: 'Assigned User',
  tt_id: 'TT ID', tt_info: 'TT Info', site_id: 'Site ID', site_name: 'Site Name',
  site_status: 'Site Status', site_attribute: 'Site Attr', site_class: 'Site Class',
  site_vip_level: 'VIP Level', networktype: 'Network', restypename: 'NE Type', restype: 'RE Type',
  neip: 'NE IP', region: 'Region', division: 'Division', district: 'District', thana: 'Thana',
  province: 'Province', ran_type: 'RAN Type', transmission_type: 'Transmission', moc: 'MOC',
  mocname: 'MOC Name', alarmtype: 'Alarm Type', alarmtypename: 'Alarm Type Name',
  alarmcode: 'Alarm Code', reasoncode: 'Reason Code', reasonname: 'Reason Name',
  ackstate: 'Ack State', clearstate: 'Clear State', positionname: 'Position',
  object_name: 'Object Name', me: 'ME', mename: 'ME Name', vendor: 'Vendor',
  additionaltext: 'Additional Text', alarmsource: 'Alarm Source', alarm_source: 'Alarm Source',
  ackstatename: 'Ack State Name', clearstatename: 'Clear State Name', admc: 'ADMC',
  admcname: 'ADMC Name', subcenter: 'Sub Center', circle: 'Circle',
}

export const humanizeCol = (col: string): string =>
  ALARM_COL_TITLES[col] || col.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')

export const fmtTs = (v: any): string => {
  if (v == null) return '-'
  if (typeof v === 'number') {
    let ms = v
    if (v > 1e11) ms = v
    else if (v > 1e8) ms = v * 1000
    else return String(v)
    const d = dayjs(ms)
    return d.isValid() ? d.format('YYYY-MM-DD HH:mm:ss') : String(v)
  }
  return String(v)
}

export const isTsCol = (col: string): boolean => col.endsWith('time') || col === 'duration'

/* 告警表**展示**用的列白名单（顺序即显示顺序）。
 *
 * 为什么需要白名单：后端 `_fetch_alarm_list` 是 `SELECT *`，而 eFlow 的
 * realtime_alarm 实测有 **146 列**（2026-10-15 实测）。其中约 66 列是
 * `{"displayname":{"en":"","zh":""}}` 这类给机器读的 JSON 结构、2 列（position /
 * positionname）是超长定位串、其余多为内部元数据（neuid/vimrespool/smcim…）——
 * 全部铺出来完全没法读。这里只保留排障与派单真正要看的字段。
 *
 * ⚠️ 与 `isTsCol` / `fmtTs` 的约定保持一致：时间列名以 `time` 结尾。
 * ⚠️ 白名单里某个键在某张表**可能不存在**（实测 `clearstatename` 只在
 *    realtime_alarm 有、history_alarm 没有），故构建时必须跳过缺失键，
 *    不能直接按白名单下标取值。
 * ⚠️ 白名单之外若出现空值列，由 `buildAlarmColumns` 的「隐藏空列」兜住；
 *    但要**导出完整字段**时用 `buildAlarmExportColumns`（不受本白名单限制）。 */
export const ALARM_DISPLAY_KEYS = [
  'perceivedseverity',   // 告警级别（渲染成彩色 Tag）
  'alarm_title',         // 告警标题
  'site_name',           // 站点
  'alarmraisedtime',     // 发生时间
  'durationname',        // 已持续
  'clearstatename',      // 清除状态（history_alarm 无此列，会被跳过）
  'ackstatename',        // 确认状态
  'alarmcode',           // 告警码
  'codename',            // 告警代码名
  'reasonname',          // 原因
  'tt_id',               // 关联 TT 号
  'region',              // 区域
  'restypename',         // 设备类型
  'transmission_type',   // 传输承载
  'object_name',         // 对象名
]

/** 单列是否「本批数据里完全没有可显示内容」（用于隐藏空列）。
 *  判定口径：null / 空白 / 'None' / '[]' / '{}' / '-' 都算空 ——
 *  这与各列 render 里回落的占位符一致，避免出现「整列都是 -」的白占位。 */
const _colIsEmpty = (rows: any[], key: string): boolean => {
  const blank = new Set(['', 'none', 'null', '[]', '{}', '-', 'nan'])
  return rows.every(r => {
    const v = r?.[key]
    if (v == null) return true
    return blank.has(String(v).trim().toLowerCase())
  })
}

/** 构造单个告警列（展示用）。severity 走彩色 Tag，时间走 fmtTs。 */
const _alarmCol = (t: TFn, k: string) => {
  const isTs = isTsCol(k)
  const isSev = k === 'perceivedseverity'
  return {
    title: humanizeCol(k),
    dataIndex: k,
    key: k,
    width: isSev ? 100 : isTs ? 170 : (k === 'alarm_title' ? 200 : 130),
    ellipsis: k === 'alarm_title' || k === 'codename',
    sorter: (a: any, b: any) => {
      const av = a[k], bv = b[k]
      if (av == null) return bv == null ? 0 : -1
      if (bv == null) return 1
      if (typeof av === 'number' && typeof bv === 'number') return av - bv
      return String(av).localeCompare(String(bv))
    },
    render: (v: any) => {
      if (isSev) {
        const map: Record<number, { label: string; color: string }> = {
          1: { label: t('gis.sev.critical'), color: 'red' }, 2: { label: t('gis.sev.major'), color: 'orange' },
          3: { label: t('gis.sev.warning'), color: 'gold' }, 4: { label: t('gis.sev.info'), color: 'blue' },
        }
        const item = map[v] || { label: `P${v}`, color: 'default' }
        return <Tag color={item.color}>{item.label}</Tag>
      }
      if (isTs) return fmtTs(v)
      if (v == null) return '-'
      if (typeof v === 'string' && v.length > 60) return <span title={v}>{v.slice(0, 60)}…</span>
      return v
    },
  }
}

/* 构建告警**展示**列：白名单 ∩ 本批数据里真实存在的键，再剔除整列为空者。
 * 顺序严格按 ALARM_DISPLAY_KEYS，不随后端返回的列顺序漂移。 */
export const buildAlarmColumns = (t: TFn, rows: any[]) => {
  if (!rows || rows.length === 0) return []
  const present = new Set(Object.keys(rows[0]))
  return ALARM_DISPLAY_KEYS
    .filter(k => present.has(k))
    .filter(k => !_colIsEmpty(rows, k))
    .map(k => _alarmCol(t, k))
}

/* 构建告警**导出**列：不受白名单限制，导出全部字段（含白名单之外的元数据），
 * 便于离线做完整分析 —— 屏幕上精简、导出仍完整，是刻意的取舍。
 * 仍按后端返回的列顺序，标题沿用 humanizeCol。 */
export const buildAlarmExportColumns = (rows: any[]) => {
  if (!rows || rows.length === 0) return []
  return Object.keys(rows[0]).map(k => ({ title: humanizeCol(k), dataIndex: k }))
}

// TT 下钻表格列
export const buildTTColumns = (t: TFn, data: any[]) => [
  { title: t('gis.drilldown.colTitle'), dataIndex: 'title', key: 'title', ellipsis: true, width: 180, sorter: (a: any, b: any) => strSorter(a, b, 'title') },
  { title: t('gis.drilldown.colTicketNo'), dataIndex: 'ticket_no', key: 'ticket_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'ticket_no') },
  { title: t('gis.drilldown.colWONo'), dataIndex: 'wo_no', key: 'wo_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'wo_no') },
  { title: t('gis.drilldown.colSiteId'), dataIndex: 'site_id', key: 'site_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_id') },
  { title: t('gis.drilldown.colSiteName'), dataIndex: 'site_name', key: 'site_name', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'site_name') },
  { title: t('gis.drilldown.colSiteClass'), dataIndex: 'site_class', key: 'site_class', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_class'),
    filters: getUniqueFilters(data, 'site_class'), onFilter: (v: any, r: any) => r.site_class === v },
  { title: t('gis.drilldown.colStatus'), dataIndex: 'status', key: 'status', width: 80,
    sorter: (a: any, b: any) => strSorter(a, b, 'status'),
    filters: getUniqueFilters(data, 'status'), onFilter: (v: any, r: any) => r.status === v,
    render: (v: string) => <Tag color="cyan">{v}</Tag> },
  { title: t('gis.drilldown.colCreator'), dataIndex: 'creator', key: 'creator', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'creator'),
    filters: getUniqueFilters(data, 'creator'), onFilter: (v: any, r: any) => r.creator === v },
  { title: t('gis.drilldown.colSeverity'), dataIndex: 'ticket_severity', key: 'ticket_severity', width: 90,
    sorter: (a: any, b: any) => strSorter(a, b, 'ticket_severity'),
    filters: getUniqueFilters(data, 'ticket_severity'), onFilter: (v: any, r: any) => r.ticket_severity === v },
  { title: t('gis.drilldown.colSLATime'), dataIndex: 'sla_time', key: 'sla_time', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'sla_time') },
  { title: t('gis.drilldown.colSLA'), dataIndex: 'sla_status', key: 'sla_status', width: 80,
    sorter: (a: any, b: any) => strSorter(a, b, 'sla_status'),
    filters: getUniqueFilters(data, 'sla_status'), onFilter: (v: any, r: any) => r.sla_status === v,
    render: (v: string) => v ? <Tag color={(v === 'Pass' || v === 'Within SLA') ? 'green' : 'red'}>{v}</Tag> : '-' },
  { title: t('gis.drilldown.colRegionId'), dataIndex: 'region_id', key: 'region_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'region_id') },
  { title: t('gis.drilldown.colCreated'), dataIndex: 'created_time', key: 'created_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'created_time') },
  { title: t('gis.drilldown.colAlarmOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 140,
    sorter: (a: any, b: any) => strSorter(a, b, 'alarm_occur_time'), defaultSortOrder: 'descend' as const },
  { title: t('gis.drilldown.colAlarmClear'), dataIndex: 'alarm_clear_time', key: 'alarm_clear_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'alarm_clear_time') },
  { title: t('gis.drilldown.colRootCause'), dataIndex: 'root_cause', key: 'root_cause', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'root_cause'),
    filters: getUniqueFilters(data, 'root_cause'), onFilter: (v: any, r: any) => r.root_cause === v },
  { title: t('gis.drilldown.colSubRootCause'), dataIndex: 'sub_root_cause', key: 'sub_root_cause', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'sub_root_cause') },
  { title: t('gis.drilldown.colRootCauseDesc'), dataIndex: 'root_cause_description', key: 'root_cause_description', ellipsis: true, width: 150, sorter: (a: any, b: any) => strSorter(a, b, 'root_cause_description') },
  { title: t('gis.drilldown.colSLARemain'), dataIndex: 'sla_remain_time', key: 'sla_remain_time', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'sla_remain_time') },
  { title: t('gis.drilldown.colFOProcess'), dataIndex: 'fo_process_detail', key: 'fo_process_detail', ellipsis: true, width: 150, sorter: (a: any, b: any) => strSorter(a, b, 'fo_process_detail') },
]

// WO 下钻表格列
export const buildWOColumns = (t: TFn, data: any[]) => [
  { title: t('gis.drilldown.colWONo'), dataIndex: 'wo_no', key: 'wo_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'wo_no') },
  { title: t('gis.drilldown.colTTNo'), dataIndex: 'tt_no', key: 'tt_no', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'tt_no') },
  { title: t('gis.drilldown.colTitle'), dataIndex: 'title', key: 'title', ellipsis: true, width: 180, sorter: (a: any, b: any) => strSorter(a, b, 'title') },
  { title: t('gis.drilldown.colStatus'), dataIndex: 'status', key: 'status', width: 80,
    sorter: (a: any, b: any) => strSorter(a, b, 'status'),
    filters: getUniqueFilters(data, 'status'), onFilter: (v: any, r: any) => r.status === v,
    render: (v: string) => <Tag color="cyan">{v}</Tag> },
  { title: t('gis.drilldown.colCreator'), dataIndex: 'creator', key: 'creator', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'creator'),
    filters: getUniqueFilters(data, 'creator'), onFilter: (v: any, r: any) => r.creator === v },
  { title: t('gis.drilldown.colCreated'), dataIndex: 'created_time', key: 'created_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'created_time') },
  { title: t('gis.drilldown.colLastModified'), dataIndex: 'last_modified_time', key: 'last_modified_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'last_modified_time') },
  { title: t('gis.drilldown.colOpStep'), dataIndex: 'operation_step', key: 'operation_step', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'operation_step') },
  { title: t('gis.drilldown.colSeverity'), dataIndex: 'ticket_severity', key: 'ticket_severity', width: 90,
    sorter: (a: any, b: any) => strSorter(a, b, 'ticket_severity'),
    filters: getUniqueFilters(data, 'ticket_severity'), onFilter: (v: any, r: any) => r.ticket_severity === v },
  { title: t('gis.drilldown.colNEType'), dataIndex: 'ne_type', key: 'ne_type', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'ne_type') },
  { title: t('gis.drilldown.colVendor'), dataIndex: 'vendor', key: 'vendor', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'vendor') },
  { title: t('gis.drilldown.colAlarmOccur'), dataIndex: 'alarm_occur_time', key: 'alarm_occur_time', width: 140,
    sorter: (a: any, b: any) => strSorter(a, b, 'alarm_occur_time'), defaultSortOrder: 'descend' as const },
  { title: t('gis.drilldown.colAlarmClear'), dataIndex: 'alarm_clear_time', key: 'alarm_clear_time', width: 140, sorter: (a: any, b: any) => strSorter(a, b, 'alarm_clear_time') },
  { title: t('gis.drilldown.colSource'), dataIndex: 'source', key: 'source', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'source') },
  { title: t('gis.drilldown.colProjectName'), dataIndex: 'project_name', key: 'project_name', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'project_name') },
  { title: t('gis.drilldown.colTemplate'), dataIndex: 'template', key: 'template', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'template') },
  { title: t('gis.drilldown.colDescription'), dataIndex: 'description', key: 'description', ellipsis: true, width: 150, sorter: (a: any, b: any) => strSorter(a, b, 'description') },
  { title: t('gis.drilldown.colAlarmSeverity'), dataIndex: 'alarm_severity', key: 'alarm_severity', width: 90,
    sorter: (a: any, b: any) => strSorter(a, b, 'alarm_severity'),
    filters: getUniqueFilters(data, 'alarm_severity'), onFilter: (v: any, r: any) => r.alarm_severity === v },
  { title: t('gis.drilldown.colFaultDuration'), dataIndex: 'fault_duration_time', key: 'fault_duration_time', width: 110, sorter: (a: any, b: any) => strSorter(a, b, 'fault_duration_time') },
  { title: t('gis.drilldown.colSLATime'), dataIndex: 'sla_time', key: 'sla_time', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'sla_time') },
  { title: t('gis.drilldown.colExpectedFinish'), dataIndex: 'expected_finish_time_e2e_sla_deadline_time', key: 'expected_finish_time', width: 160, sorter: (a: any, b: any) => strSorter(a, b, 'expected_finish_time_e2e_sla_deadline_time') },
  { title: t('gis.drilldown.colRegionId'), dataIndex: 'region_id', key: 'region_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'region_id') },
  { title: t('gis.drilldown.colSiteId'), dataIndex: 'site_id', key: 'site_id', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_id') },
  { title: t('gis.drilldown.colSiteName'), dataIndex: 'site_name', key: 'site_name', width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'site_name') },
  { title: t('gis.drilldown.colSiteType'), dataIndex: 'site_type', key: 'site_type', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_type') },
  { title: t('gis.drilldown.colSiteInfo'), dataIndex: 'site_information', key: 'site_information', ellipsis: true, width: 120, sorter: (a: any, b: any) => strSorter(a, b, 'site_information') },
  { title: t('gis.drilldown.colSiteClass'), dataIndex: 'site_class', key: 'site_class', width: 80, sorter: (a: any, b: any) => strSorter(a, b, 'site_class') },
  { title: t('gis.drilldown.colOrgId'), dataIndex: 'organization_id', key: 'organization_id', width: 100, sorter: (a: any, b: any) => strSorter(a, b, 'organization_id') },
  { title: t('gis.drilldown.colVipSite'), dataIndex: 'vip_site', key: 'vip_site', width: 70, sorter: (a: any, b: any) => strSorter(a, b, 'vip_site') },
  { title: t('gis.drilldown.colHubSite'), dataIndex: 'hub_site', key: 'hub_site', width: 70, sorter: (a: any, b: any) => strSorter(a, b, 'hub_site') },
]
