/* ============================================================================
 * 选项 / 矩阵 / 曲线取数（县维度可用率）
 * ----------------------------------------------------------------------------
 * 从 `AvailCounty.tsx` 抽出的独立 hook。
 *
 * ⚠️ 这里修掉了一个真实的故障态缺陷（原实现）：
 *   `/options` 失败时 `current_month` 为空 -> 页面 `curMonth` 为空 ->
 *   取矩阵的 `load()` 直接 early-return -> 页面既不报错、也没有数据，
 *   最终只显示「暂无数据」，运维会误判成「今天没数据」而不是「接口挂了」。
 *   现在选项失败会：① 落一条 `options_failed` 警告并带上真实错误信息；
 *   ② 即使拿不到月份，也**照样去请求矩阵**（月份为空由后端按当前月兜底），
 *   让真正的失败原因显式出现在页面上。
 *
 * 另一个细节：矩阵与曲线用 `Promise.allSettled` 一起取，避免
 * 「表已刷新、图还是上一期」的错位；曲线单独失败只丢图、不影响表格。
 * ========================================================================== */
import { useCallback, useEffect, useState } from 'react'

import {
  getAvailCountyMatrix, getAvailCountyOptions, getAvailCountyTrend,
} from '../../api'
import {
  Gran, Matrix, Options, TECHS, Trend,
} from './availCountyTypes'

/** 矩阵取数失败时的空壳（保持结构完整，页面据此显示失败态而不是崩溃） */
function emptyMatrix(month: string, period: Gran, thr: number): Matrix {
  return {
    meta: {
      month, period, value: '', start_day: '', end_day: '',
      prev_days: [], days: [], threshold: thr, counties: [], techs: [...TECHS],
      data_through: '', covered_days: [], month_covered_days: [],
      month_covered_count: 0, month_day_count: 0, latest_day: '',
      generated_at: '', elapsed_ms: 0, warnings: ['matrix_failed'],
      has_unmatched: false,
    },
    summary: { by_tech: {}, county_count: 0 },
    rows: [],
  }
}

/** 曲线取数失败时的空壳 */
function emptyTrend(month: string, period: Gran, county: string, thr: number): Trend {
  return {
    meta: {
      month, period, county, threshold: thr,
      points: 0, data_through: '', generated_at: '', warnings: ['trend_failed'],
    },
    categories: [], series: [],
  }
}

export interface AvailCountyData {
  options: Options | null
  matrix: Matrix | null
  trend: Trend | null
  loading: boolean
  trendLoading: boolean
  /** 页面级错误信息（矩阵取数失败的真实原因） */
  error: string
  /** 实际生效的月份：用户选中的优先，否则用后端给的当前月 */
  curMonth: string
  /** 重新取数（刷新按钮 / 换筛选条件后自动触发） */
  load: () => Promise<void>
  /** 重新取选项 */
  loadOptions: () => Promise<void>
}

export function useAvailCountyData(params: {
  /** 当前档位（日 / 周） */
  gran: Gran
  /** 用户选中的月份（空 = 用后端给的当前月） */
  month: string
  /** 当前档位的选中周期值（空 = 该月最后一期） */
  reqValue: string
  /** 未达标阈值（比率） */
  thr: number
  /** 曲线看哪个县（空 = 全网） */
  trendCounty: string
}): AvailCountyData {
  const { gran, month, reqValue, thr, trendCounty } = params

  const [options, setOptions] = useState<Options | null>(null)
  const [matrix, setMatrix] = useState<Matrix | null>(null)
  const [trend, setTrend] = useState<Trend | null>(null)
  const [loading, setLoading] = useState(false)
  const [trendLoading, setTrendLoading] = useState(false)
  const [error, setError] = useState('')

  /** 实际生效的月份：用户选中的优先，否则用后端给的当前月 */
  const curMonth = month || options?.current_month || ''

  /* ---- 选项：失败不阻塞页面主体，但要留下可见的失败痕迹 ---- */
  const loadOptions = useCallback(async () => {
    try {
      const r = await getAvailCountyOptions()
      setOptions(r.data as Options)
    } catch (e: any) {
      setOptions({
        months: [], current_month: '', counties: [], techs: [...TECHS],
        threshold: 0.9965, data_through: '', warnings: ['options_failed'],
        error: e?.message || String(e),
      })
    }
  }, [])

  /**
   * 矩阵与曲线**一起取**：两张表和一个图如果各取各的，会出现「表已刷新、
   * 图还是上一期」的错位（与 avail_ms 同源问题）。
   *
   * ⚠️ 这里**不再**因为 curMonth 为空就 early-return：
   *   `/options` 挂掉时月份可能取不到，但矩阵接口本身能按当前月兜底，
   *   提前 return 会把「接口失败」伪装成「暂无数据」。
   */
  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const value = reqValue
    const m = curMonth
    try {
      const [mx, tr] = await Promise.allSettled([
        getAvailCountyMatrix({ period: gran, month: m, value, threshold: thr }),
        getAvailCountyTrend({
          period: gran, month: m, value, county: trendCounty, threshold: thr,
        }),
      ])
      if (mx.status === 'fulfilled') {
        setMatrix(mx.value.data as Matrix)
      } else {
        const e: any = mx.reason
        setMatrix(emptyMatrix(m, gran, thr))
        setError(e?.message || String(e))
      }
      if (tr.status === 'fulfilled') {
        setTrend(tr.value.data as Trend)
      } else {
        // 曲线单独失败不影响表格可用：只丢图，表照常渲染
        setTrend(emptyTrend(m, gran, trendCounty, thr))
      }
    } finally {
      setLoading(false)
      setTrendLoading(false)
    }
  }, [curMonth, gran, reqValue, thr, trendCounty])

  useEffect(() => { void loadOptions() }, [loadOptions])
  useEffect(() => { void load() }, [load])

  return {
    options, matrix, trend, loading, trendLoading, error, curMonth,
    load, loadOptions,
  }
}
