/* ============================================================================
 * 下钻状态与取数（县维度可用率）
 * ----------------------------------------------------------------------------
 * 从 `AvailCounty.tsx` 抽出的独立 hook：把「弹窗开关 + 目标 + 明细取数」
 * 这条状态机收在一起，页面主体只负责筛选与渲染。
 *
 * 三层下钻：
 *   county_sites  县 × 制式 -> 该县的站点明细
 *   site_daily    站点 -> 该站点的逐日明细
 *   tt            县（或某站点）-> TT 工单
 *
 * 抽出来的两个理由：
 *   ① 工作区 AGENTS.md 第三节原则 2：新增文件 ≤500 行。页面主体与「状态机」
 *      分开，改下钻不会把页面主体顶破上限。
 *   ② 下钻失败只影响弹窗（数字本身不受影响），把失败态收在 hook 里，
 *      页面主体不必再关心弹窗的取数细节。
 * ========================================================================== */
import { useCallback, useState } from 'react'

import { getAvailCountyDrilldown } from '../../api'
import { CellTarget, Drill, DrillLevel, Gran, SiteRow } from './availCountyTypes'

export interface DrillState {
  /** 弹窗是否打开 */
  open: boolean
  /** 弹窗锚点（点击处坐标，让弹窗贴着被点的数字出现） */
  anchor: { x: number; y: number } | null
  /** 当前下钻目标（县 × 制式） */
  target: CellTarget | null
  /** 下钻取数用的周期值 */
  drillValue: string
  /** 下钻结果 */
  drill: Drill | null
  drillLoading: boolean
  /** 弹窗页签 */
  modalTab: DrillLevel
  /** 关闭弹窗 */
  close: () => void
  /** 切换页签并按新页签重新取数 */
  changeTab: (lv: DrillLevel) => void
  /** 取明细 */
  loadDrill: (level: DrillLevel, tg: CellTarget, value: string) => Promise<void>
  /** 打开弹窗（矩阵单元格 / 曲线点触发） */
  openDrill: (tg: CellTarget, at?: { x: number; y: number }, value?: string) => void
  /** 站点明细里再点站点 -> 该站点的逐日明细 */
  openSiteDaily: (row: SiteRow) => void
}

export function useAvailCountyDrill(params: {
  /** 当前档位（日 / 周） */
  gran: Gran
  /** 当前统计月份 */
  curMonth: string
  /** 未达标阈值（比率） */
  thr: number
  /** 矩阵当前展示的周期值（后端解析后的规范值），优先于 reqValue */
  matrixValue: string
  /** 当前档位的选中周期值（空 = 该月最后一期） */
  reqValue: string
}): DrillState {
  const { gran, curMonth, thr, matrixValue, reqValue } = params

  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [target, setTarget] = useState<CellTarget | null>(null)
  /** 打开弹窗时的县（站点逐日后 target.county 会变成 site_key，
   *  切回“站点明细/ TT”页签时仍要用这个县取数，否则县名对不上 site_key 会查出空表） */
  const [rootCounty, setRootCounty] = useState('')
  const [drillValue, setDrillValue] = useState('')
  const [drill, setDrill] = useState<Drill | null>(null)
  const [drillLoading, setDrillLoading] = useState(false)
  const [modalTab, setModalTab] = useState<DrillLevel>('county_sites')

  const loadDrill = useCallback(async (
    level: DrillLevel, tg: CellTarget, value: string,
  ) => {
    setDrillLoading(true)
    try {
      const r = await getAvailCountyDrilldown({
        level, period: gran, month: curMonth, value,
        county: tg.county, tech: tg.tech, threshold: thr,
      })
      setDrill(r.data as Drill)
    } catch (e: any) {
      // 下钻失败只影响弹窗：可用率数字本身不受影响，错误挂在 meta 上由弹窗显示
      setDrill({
        meta: {
          level, period: gran, value, county: tg.county, tech: tg.tech,
          total: 0, returned: 0, truncated: false, warnings: ['drilldown_failed'],
          error: e?.message || String(e),
        },
        rows: [],
      })
    } finally {
      setDrillLoading(false)
    }
  }, [gran, curMonth, thr])

  const openDrill = useCallback((
    tg: CellTarget, at?: { x: number; y: number }, value?: string,
  ) => {
    const v = value || matrixValue || reqValue || ''
    setDrillValue(v)
    setTarget(tg)
    setRootCounty(tg.county)
    setAnchor(at || null)
    setDrill(null)
    setModalTab('county_sites')
    setOpen(true)
    void loadDrill('county_sites', tg, v)
  }, [loadDrill, matrixValue, reqValue])

  const openSiteDaily = useCallback((row: SiteRow) => {
    const tg: CellTarget = {
      county: row.site_key,
      tech: target?.tech || '',
      label: `${row.site_name}`,
    }
    setTarget(tg)
    setModalTab('site_daily')
    setDrill(null)
    void loadDrill('site_daily', tg, drillValue)
  }, [loadDrill, drillValue, target])

  const close = useCallback(() => setOpen(false), [])

  const changeTab = useCallback((lv: DrillLevel) => {
    setModalTab(lv)
    if (!target) return
    // 站点逐日后 target.county 已变成 site_key：切回县级页签时用打开时的县取数
    if (lv === 'county_sites' || lv === 'tt') {
      const tg = { ...target, county: rootCounty || target.county }
      void loadDrill(lv, tg, drillValue)
      return
    }
    // 切到“逐日明细”时 target.county 必须是 site_key：
    // 若用户还没在站点明细里点过站点（target.county 仍是县名），
    // 直接拿县名查站点逐日必定 site_not_found（空表），故自动带上当前站点明细的第一行；
    // 站点明细还没出来时则不发请求，只给一句引导，避免空表让人以为接口坏了。
    if (lv === 'site_daily' && target.county === (rootCounty || target.county)) {
      const first = (drill?.rows || [])[0] as SiteRow | undefined
      if (first && (first as SiteRow).site_key) {
        const tg: CellTarget = {
          county: (first as SiteRow).site_key,
          tech: target.tech,
          label: `${(first as SiteRow).site_name}`,
        }
        setTarget(tg)
        void loadDrill(lv, tg, drillValue)
      } else {
        setDrill({
          meta: {
            level: lv, period: gran, value: drillValue,
            county: target.county, tech: target.tech,
            total: 0, returned: 0, truncated: false, warnings: ['pick_site_first'],
          },
          rows: [],
        })
      }
      return
    }
    void loadDrill(lv, target, drillValue)
  }, [loadDrill, target, drillValue, rootCounty, drill, gran])

  return {
    open, anchor, target, drillValue, drill, drillLoading, modalTab,
    close, changeTab, loadDrill, openDrill, openSiteDaily,
  }
}
