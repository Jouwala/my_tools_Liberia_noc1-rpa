import { useState, useEffect } from 'react'
import api from './api'
import { useI18n } from './i18n'

interface DataTimestamps {
  last_sync: string | null
  alarm_last_sync: string | null
  latest_data_time: string | null
  latest_tt_time: string | null
  latest_wo_time: string | null
}

/** 获取数据源时间信息的共享 hook */
export function useDataTimestamps() {
  const [timestamps, setTimestamps] = useState<DataTimestamps | null>(null)
  const { t } = useI18n()

  useEffect(() => {
    api.get('/data-source/timestamps')
      .then(res => setTimestamps(res.data))
      .catch(() => {})
  }, [])

  const formatTime = (isoStr: string | null) => {
    if (!isoStr) return null
    // ISO format: 2026-07-10T17:23:21.468956 -> 2026-07-10 17:23:21
    return isoStr.replace('T', ' ').substring(0, 19)
  }

  const lastSyncDisplay = timestamps?.last_sync
    ? formatTime(timestamps.last_sync)
    : null

  // 实时告警同步时间（与 Alarm Dashboard 口径一致）；无记录时回退到数据最新时间
  const alarmLastSyncDisplay = timestamps?.alarm_last_sync
    ? formatTime(timestamps.alarm_last_sync)
    : (timestamps?.latest_data_time || null)

  const latestDataDisplay = timestamps?.latest_data_time
    ? timestamps.latest_data_time
    : t('datasource.noData')

  return {
    lastSync: lastSyncDisplay,
    alarmLastSync: alarmLastSyncDisplay,
    latestData: latestDataDisplay,
    isSynced: !!lastSyncDisplay,
    raw: timestamps,
  }
}
