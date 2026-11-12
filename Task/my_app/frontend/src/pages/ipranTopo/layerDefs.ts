/* ============================================================================
 * 四层页签的静态定义与「按层」文案键组
 * ============================================================================
 * 层 key 与后端 services/ipran_topo/layers.py 的 LAYERS 一一对应（后端白名单，
 * 非法值 400）。层名走 i18n 而不是 GET /layers：语言切换自动生效、首屏少一次
 * 请求；/layers 保留给门户与排障用。
 *
 * 为什么 explain / calc 要按层分两套：ipran 层那套说明写死了实测数字
 * （93 网元 / 167 链路 / 具体 lid / M6000 型号），套到 IP Core / DWDM 上是错的。
 * 其余三层的口径目前是按抓包 moc 推断的默认值，待 probe_layers.py 实测校准，
 * 因此用通用说明，不复制实测数字。
 * ========================================================================== */
import type { LayerKey } from './types'

export const LAYER_KEYS: LayerKey[] = ['ipran', 'ipcore', 'metro', 'dwdm']

/** URL 里的 &layer= 必须命中白名单，避免把任意字符串透传给后端触发 400。 */
export function isLayerKey(v: string | null): v is LayerKey {
  return !!v && (LAYER_KEYS as string[]).includes(v)
}

export const LAYER_LABEL_KEY: Record<LayerKey, string> = {
  ipran: 'ipranTopo.layer.ipran',
  ipcore: 'ipranTopo.layer.ipcore',
  metro: 'ipranTopo.layer.metro',
  dwdm: 'ipranTopo.layer.dwdm',
}

export interface ExplainKeys {
  ne: string
  links: string
  down: string
  crit: string
}

export function explainKeys(layer: LayerKey): ExplainKeys {
  if (layer === 'ipran') {
    return {
      ne: 'ipranTopo.kpi.explain.ne',
      links: 'ipranTopo.kpi.explain.links',
      down: 'ipranTopo.kpi.explain.down',
      crit: 'ipranTopo.kpi.explain.crit',
    }
  }
  return {
    ne: 'ipranTopo.kpi.explain.generic.ne',
    links: 'ipranTopo.kpi.explain.generic.links',
    down: 'ipranTopo.kpi.explain.generic.down',
    crit: 'ipranTopo.kpi.explain.generic.crit',
  }
}

export interface CalcSectionKeys {
  title: string
  lines: string[]
}

export function calcSectionKeys(layer: LayerKey): CalcSectionKeys[] {
  if (layer === 'ipran') {
    return [
      { title: 'ipranTopo.calc.source.title', lines: ['ipranTopo.calc.source.l1', 'ipranTopo.calc.source.l2'] },
      { title: 'ipranTopo.calc.agg.title', lines: ['ipranTopo.calc.agg.l1', 'ipranTopo.calc.agg.l2'] },
      { title: 'ipranTopo.calc.alarm.title', lines: ['ipranTopo.calc.alarm.l1'] },
      { title: 'ipranTopo.calc.view.title', lines: ['ipranTopo.calc.view.l1', 'ipranTopo.calc.view.l2'] },
      { title: 'ipranTopo.calc.cache.title', lines: ['ipranTopo.calc.cache.l1'] },
    ]
  }
  return [
    { title: 'ipranTopo.calc.generic.source.title', lines: ['ipranTopo.calc.generic.source.l1'] },
    { title: 'ipranTopo.calc.generic.caliber.title', lines: ['ipranTopo.calc.generic.caliber.l1'] },
    { title: 'ipranTopo.calc.generic.cache.title', lines: ['ipranTopo.calc.generic.cache.l1'] },
  ]
}
