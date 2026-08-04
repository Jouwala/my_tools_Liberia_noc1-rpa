// DataSync 页面共享工具与配置（P3#10 拆分自 DataSync.tsx）
import type { ReactNode } from 'react'
import {
  CloudServerOutlined,
  WifiOutlined,
  CameraOutlined,
  MessageOutlined,
  BarChartOutlined,
  FundOutlined,
  AppstoreOutlined,
  GlobalOutlined,
  MailOutlined,
  SettingOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'

// 取错误首行（截断），用于卡片/横幅的一行摘要
export const firstLine = (s: string | null | undefined): string =>
  (s || '').split('\n')[0].slice(0, 80)

// ===== Cron Helpers =====
export const CRON_PRESETS: Record<string, { label_zh: string; label_en: string; cron: string }[]> = {
  hourly: [
    { label_zh: '每小时', label_en: 'Every Hour', cron: '0 * * * *' },
    { label_zh: '每小时第22分', label_en: 'Every Hour :22', cron: '22 * * * *' },
    { label_zh: '每2小时', label_en: 'Every 2 Hours', cron: '0 */2 * * *' },
    { label_zh: '每4小时', label_en: 'Every 4 Hours', cron: '0 */4 * * *' },
    { label_zh: '每6小时', label_en: 'Every 6 Hours', cron: '0 */6 * * *' },
    { label_zh: '每12小时', label_en: 'Every 12 Hours', cron: '0 */12 * * *' },
  ],
  daily: [
    { label_zh: '每天 00:00', label_en: 'Daily 00:00', cron: '0 0 * * *' },
    { label_zh: '每天 01:00', label_en: 'Daily 01:00', cron: '0 1 * * *' },
    { label_zh: '每天 02:00', label_en: 'Daily 02:00', cron: '0 2 * * *' },
    { label_zh: '每天 03:00', label_en: 'Daily 03:00', cron: '0 3 * * *' },
    { label_zh: '每天 06:00', label_en: 'Daily 06:00', cron: '0 6 * * *' },
    { label_zh: '每天 08:00', label_en: 'Daily 08:00', cron: '0 8 * * *' },
    { label_zh: '每天 12:00', label_en: 'Daily 12:00', cron: '0 12 * * *' },
    { label_zh: '每天 18:00', label_en: 'Daily 18:00', cron: '0 18 * * *' },
  ],
  weekly: [
    { label_zh: '周一 08:00', label_en: 'Mon 08:00', cron: '0 8 * * 1' },
    { label_zh: '周五 18:00', label_en: 'Fri 18:00', cron: '0 18 * * 5' },
    { label_zh: '工作日 08:00', label_en: 'Weekdays 08:00', cron: '0 8 * * 1-5' },
    { label_zh: '工作日 18:00', label_en: 'Weekdays 18:00', cron: '0 18 * * 1-5' },
  ],
}

export function cronToHuman(cron: string, locale: 'zh' | 'en'): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [min, hr, day, mon, dow] = parts

  // Every N hours
  if (hr.startsWith('*/')) {
    const n = hr.slice(2)
    return locale === 'zh' ? `每 ${n} 小时（第 ${min} 分钟）` : `Every ${n}h (at :${min})`
  }
  // Every hour
  if (hr === '*' && min !== '*') {
    return locale === 'zh' ? `每小时第 ${min} 分钟` : `Every hour at :${min}`
  }
  if (hr === '*' && min === '*') {
    return locale === 'zh' ? '每分钟' : 'Every minute'
  }
  // Specific time daily
  if (day === '*' && mon === '*' && dow === '*') {
    return locale === 'zh' ? `每天 ${hr.padStart(2, '0')}:${min.padStart(2, '0')}` : `Daily ${hr.padStart(2, '0')}:${min.padStart(2, '0')}`
  }
  // Day of week
  if (dow !== '*') {
    const dowMap: Record<string, string> = {
      '1': locale === 'zh' ? '周一' : 'Mon',
      '2': locale === 'zh' ? '周二' : 'Tue',
      '3': locale === 'zh' ? '周三' : 'Wed',
      '4': locale === 'zh' ? '周四' : 'Thu',
      '5': locale === 'zh' ? '周五' : 'Fri',
      '6': locale === 'zh' ? '周六' : 'Sat',
      '0': locale === 'zh' ? '周日' : 'Sun',
      '1-5': locale === 'zh' ? '工作日' : 'Weekdays',
    }
    const dowLabel = dowMap[dow] || dow
    return locale === 'zh' ? `${dowLabel} ${hr.padStart(2, '0')}:${min.padStart(2, '0')}` : `${dowLabel} ${hr.padStart(2, '0')}:${min.padStart(2, '0')}`
  }
  return cron
}

export const CATEGORY_CONFIG: Record<string, { color: string; icon: ReactNode; label_zh: string; label_en: string }> = {
  eflow: { color: '#1677ff', icon: <CloudServerOutlined />, label_zh: 'eFlow 数据', label_en: 'eFlow Data' },
  ran_ume: { color: '#52c41a', icon: <WifiOutlined />, label_zh: 'RAN UME', label_en: 'RAN UME' },
  site_outage: { color: '#fa8c16', icon: <CameraOutlined />, label_zh: 'Site Outage', label_en: 'Site Outage' },
  whatsapp: { color: '#25D366', icon: <MessageOutlined />, label_zh: 'WhatsApp', label_en: 'WhatsApp' },
  ms_sla: { color: '#722ed1', icon: <BarChartOutlined />, label_zh: 'MS SLA/NUR', label_en: 'MS SLA/NUR' },
  main_kpi: { color: '#13c2c2', icon: <FundOutlined />, label_zh: 'Main KPI', label_en: 'Main KPI' },
  network_kpi: { color: '#eb2f96', icon: <BarChartOutlined />, label_zh: 'Network KPI', label_en: 'Network KPI' },
  cnn_kpi: { color: '#fa541c', icon: <CloudServerOutlined />, label_zh: 'CNN UME', label_en: 'CNN UME' },
  general: { color: '#8c8c8c', icon: <SettingOutlined />, label_zh: '通用', label_en: 'General' },
  sp: { color: '#faad14', icon: <AppstoreOutlined />, label_zh: 'SP 备件', label_en: 'SP Spare' },
  ipran_kpi: { color: '#2f54eb', icon: <GlobalOutlined />, label_zh: 'iPRAN UME', label_en: 'iPRAN UME' },
  email: { color: '#08979c', icon: <MailOutlined />, label_zh: '邮件报告', label_en: 'Email Report' },
  kpi_email: { color: '#722ed1', icon: <MailOutlined />, label_zh: 'KPI/SP/RAN 报告邮件', label_en: 'KPI/SP/RAN Report Email' },
  packet_loss: { color: '#eb2f96', icon: <WifiOutlined />, label_zh: 'Packet Loss', label_en: 'Packet Loss' },
  fw_kpi: { color: '#d4380d', icon: <SafetyCertificateOutlined />, label_zh: 'FW 吞吐 KPI', label_en: 'FW Throughput KPI' },
}

export function formatTime(isoStr: string | null): string {
  if (!isoStr) return '-'
  return isoStr.replace('T', ' ').substring(0, 19)
}
