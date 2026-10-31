/* ============================================================================
 * vmaxDiagnosisRules.ts —— 投诉诊断的判据、阈值、评分与结论规则
 * ============================================================================
 *
 * 【为什么规则放前端】
 *   方案 §4.2 要求「切换投诉类型不重新取数，只重算诊断」——秒切。
 *   若把评分与结论放后端，每切一次页签就要多打一次上游（上游限并发、
 *   1300 三页要 12s），体验与上游压力都不允许。
 *   因此：**取数在后端（/api/vmax-diagnosis 一次拉齐四个源），
 *   评分与结论在前端**（纯函数，入参是原始行）。
 *
 *   代价是规则要前后端一致 —— 所以阈值集中在本文件的 `THRESHOLDS`
 *   与后端 `vmax_diag_rules.json` 两处，改动必须同步（后端只做透传，
 *   真正生效的是这里）。这一点写在文档里，避免日后漂移。
 *
 * 【判据来源，全部为实测可用字段】（2026-10-31 现网 645 条样本回放）
 *   1100 会话/信令面：interface / procedure_type / procedure_status / request_cause
 *   1300 用户面       ：$first_resp_delay / $tcp_resp_delay / ul|dl_avg_rtt /
 *                       retrans_pkt / disorder_pkt / duration / service / subservice
 *   32   RAN          ：serving_rsrp / ulsinr / cqi（按 IMSI 查，见方案 §5.1）
 *
 * 【三条不许越界的红线】（写进帮助文档，也在页面上明说）
 *   1. XDR 里**没有 SIP / RTP**（实测 protocol ∈ {SIP,RTP} 命中 0）
 *      → OTT 语音只能给「通话期网络质量」，不能给「对方拒接/注册失败」。
 *   2. RAN 表的 `$msisdn` 列全为空 → 拿不到 IMSI 的用户**无法定位无线侧**，
 *      结论必须写「无数据可判」，绝不能写「正常」。
 *   3. `qci=0` 的记录实测是 DNS 小包，不是语音承载 → 判 VoLTE 只认 `qci=1`。
 * ========================================================================== */

import type { Dayjs } from 'dayjs'

/* ---------------------------------------------------------------------------
 * 〇、国际化：本文件所有「会显示给人看的文字」一律不写字符串字面量
 * ------------------------------------------------------------------------ *
 * 规则层是纯函数、不依赖 React，拿不到 `t()`。而它产出的结论、证据、建议
 * 全是要渲染到页面上（以及导出 Excel/PDF）的文案 —— 早期版本这些文案直接
 * 写成中文字面量，导致**英文界面下整个诊断结论区都是中文**，而
 * `check:i18n` 扫不到（它只扫 JSX 文本与 t() 的入参）。
 *
 * 因此规则层只产出 `{ key, params }`，由渲染层 `t(key, params)` 翻译。
 * 好处：① 规则层仍是纯函数、可单测；② 中英两版文案都在字典里，跑
 * `check:i18n` 就能保证不缺键；③ 参数与文案分离，改文案不用动逻辑。
 *
 * 约定：key 一律以 `vmaxq.vd.` 开头（vd = verdict/diagnosis 规则层）。
 */
export type I18nText = {
  /** 字典键，如 `vmaxq.vd.headline.voiceNone` */
  key: string
  /** 插值参数（字典里写成 `{{name}}`） */
  params?: Record<string, string | number | I18nText>
}

/**
 * 构造 I18nText 的简写。
 *
 * `params` 里允许再放 `I18nText`（嵌套），用于「一句话里嵌一个可变短语」的场景，
 * 例如「无线侧不可判：{{why}}」的 why 本身又是一句已翻译的话。
 * 嵌套项**不在这里展开**（规则层没有 t），而是原样保留，交给渲染层的
 * `renderI18n()` 递归解析 —— 这样规则层仍不需要知道当前语言。
 */
export const tx = (key: string, params?: Record<string, string | number | I18nText>): I18nText =>
  (params ? { key, params } : { key })

/** 判断某个值是不是 I18nText（渲染层递归解析时用） */
export const isI18nText = (v: unknown): v is I18nText =>
  !!v && typeof v === 'object' && typeof (v as I18nText).key === 'string'

/* ---------------------------------------------------------------------------
 * 一、类型：四个数据源的行与诊断结果
 * ------------------------------------------------------------------------ */

/** 投诉类型（一级页签）—— 决定「先看哪一维」，不是过滤器 */
export type ComplaintKey = 'all' | 'voice' | 'ott' | 'video' | 'game' | 'slow'

export const COMPLAINT_KEYS: ComplaintKey[] = ['all', 'voice', 'ott', 'video', 'game', 'slow']

export const isComplaintKey = (v: string): v is ComplaintKey =>
  (COMPLAINT_KEYS as string[]).includes(v)

/** 视图页签 —— 每个页签回答一个问题 */
export type DiagViewKey = 'diagnosis' | 'flow' | 'connect' | 'radio'

export const isDiagViewKey = (v: string): v is DiagViewKey =>
  v === 'diagnosis' || v === 'flow' || v === 'connect' || v === 'radio'

/** 上游 XDR 行：字段名随表而变，统一按字符串字典处理 */
export type XdrRow = Record<string, string | number | null | undefined>

/** 单个数据源的取数结果（单源失败不影响其它源） */
export type SourceResult = {
  /** 上游表名，如 1300 / 1100 / 32 / 1301 */
  key: string
  /**
   * i18n key（后端给，如 `vmaxq.diag.src.1300`）。
   * 有它就按当前语言渲染；没有则回退 `label`（中文原文）。
   * 为什么不由前端按 key 反查：`key` 是表号，"32" 这种还要拼 "RAN"，
   * 语义分散在服务端，让服务端直接给 key 最不容易漂移。
   */
  label_key?: string
  /** 人类可读名（界面上「已查数据源」那一行），中文兜底 */
  label: string
  ok: boolean
  rows: XdrRow[]
  /** ok=false 时的原因（超时 / 无 IMSI 映射 / 上游报错） */
  error?: string
  /** 是否因为条数上限被截断（要在界面上明说） */
  truncated?: boolean
}

/** 诊断接口的整体响应 */
export type DiagnosisPayload = {
  window: { start: string; end: string }
  sources: SourceResult[]
  /** MSISDN → IMSI 的映射结果；空 = 拿不到，无线侧无法判 */
  imsi?: string
  cell?: string
  /**
   * P0'-1：诊断附带的流量聚合（复用 1300/1301 行算好，不再打上游）。
   * 前端优先用它渲染「业务流量」页签；为 null 时回退调 /api/vmax-flow-xdr。
   * 类型用 unknown 避免循环 import（FlowData 在组件层定义）。
   */
  flow?: unknown | null
  /** flow 是否复用成功（false = 前端需要回退单查） */
  flow_reused?: boolean
}

/* ---------------------------------------------------------------------------
 * 二、阈值（与后端 vmax_diag_rules.json 同步）
 * ------------------------------------------------------------------------ */

export const THRESHOLDS = {
  /** 过程失败率告警线 */
  failRate: 5,
  /** 首包时延 P90 告警线（ms）：实测均值 455ms、峰值 118765ms */
  firstRespP90: 3000,
  /** TCP 应答时延均值告警线（ms） */
  tcpResp: 500,
  /** 重传率告警线（%）：实测命中样本均值 ~0.2% */
  retrans: 1,
  /** 弱覆盖：serving_rsrp 低于此值（dBm） */
  rsrp: -110,
  /** 上行受限：ulsinr 低于此值（dB） */
  sinr: 0,
  /** CSFB 回落耗时偏慢线（ms） */
  csfbFallback: 2000,
  /** OTT 通话最短判定时长（s） */
  ottMinDuration: 10,
  /** 评分分档：>= 此值算正常 */
  scoreGood: 80,
  /** 评分分档：< 此值算异常 */
  scoreBad: 50,
} as const

/* ---------------------------------------------------------------------------
 * 三、小工具
 * ------------------------------------------------------------------------ */

const num = (v: unknown): number => {
  if (v === null || v === undefined || v === '') return 0
  const n = typeof v === 'number' ? v : Number(String(v))
  return Number.isFinite(n) ? n : 0
}

const str = (v: unknown): string => (v == null ? '' : String(v).trim())

const strU = (v: unknown): string => str(v).toUpperCase()

/* ---------------------------------------------------------------------------
 * RAN(32) 字段取值 —— 上游用**哨兵值**表示「未上报」，不是空串
 *
 * 2026-10-31 用真号码跑通 RAN 取数后实测（216 行 UEMR）：
 *   - `cqi`      全部是 **65535**（= 0xFFFF，该次没上报 CQI）
 *   - `ulsinr`   出现 **255**（UL SINR 实测正常范围 -10~30 dB）
 *   - `phr`      出现 **255** 与 0
 * 这些值如果直接进统计，会被算成真实电平：CQI 平均会变成 65535，
 * SINR 的 P10/均值被拉高，结论从「干扰」翻成「正常」——比缺数据更危险。
 * 所以三个字段各自按**物理取值范围**过滤，超范围一律当「无采样」。
 * ------------------------------------------------------------------------ */

/** RSRP：真实值必为负（-140 ~ -40 dBm）；0/正数是缺采样或哨兵 */
const rsrpOf = (r: XdrRow): number => {
  const v = num(r.serving_rsrp)
  return v < 0 ? v : 0
}

/** UL SINR：合理区间 (-30, 40) dB；255 是哨兵 */
const sinrOf = (r: XdrRow): number => {
  const v = num(r.ulsinr)
  return v > -30 && v < 40 ? v : 0
}

/** CQI：LTE 上报 0~15（少数厂商 0~31）；65535 是哨兵 */
const cqiOf = (r: XdrRow): number => {
  const v = num(r.cqi)
  return v > 0 && v <= 31 ? v : 0
}

/** 小区名：RAN 表的列就叫 `cell`（不是 cellname / cell_name）。
 *  2026-10-31 实测只有 `cell` 有值（如 "Methodist Compound-X1"）；
 *  只读 cellname 会让所有行塌进「未知小区」，逐小区表和「最差点名」全失效。 */
const cellOf = (r: XdrRow): string =>
  str(r.cell) || str(r.cellname) || str(r.cell_name) || t_unknownCell()

/** 百分位（p ∈ [0,1]）—— 上游没有分位数字段，只能客户端算 */
function percentile(values: number[], p: number): number {
  if (!values.length) return 0
  const s = [...values].sort((a, b) => a - b)
  const idx = Math.min(s.length - 1, Math.max(0, Math.round((s.length - 1) * p)))
  return s[idx]
}

function mean(values: number[]): number {
  if (!values.length) return 0
  return values.reduce((a, b) => a + b, 0) / values.length
}

function stdDev(values: number[]): number {
  if (values.length < 2) return 0
  const m = mean(values)
  return Math.sqrt(mean(values.map((v) => (v - m) ** 2)))
}

/** 上游的时间字段名随域而变：5gsa 用 start_time，RAN 用 btime */
export function rowTime(row: XdrRow): string {
  for (const k of ['start_time', 'btime', 'time', 'stat_time', 'procedure_start_time']) {
    const v = str(row[k])
    if (v && v !== '-') return v
  }
  return ''
}

/** 把 "2026-10-31 08:14:23.123" 这类串截成 "2026-10-31 08:14" 作为分钟桶 */
export function minuteKey(t: string): string {
  const s = t.replace('T', ' ')
  // "YYYY-MM-DD HH:MM..." → 前 16 字符
  return s.length >= 16 ? s.slice(0, 16) : s
}

/** 只取 "HH:mm"，时间线表格里空间有限 */
export function hhmm(t: string): string {
  const s = t.replace('T', ' ')
  return s.length >= 16 ? s.slice(11, 16) : s
}

export const pct = (v: number, digits = 1): string => `${v.toFixed(digits)}%`

export const ms = (v: number): string => (v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`)

/** 毫秒 / 秒转 "m:ss" 或 "N s"，给通话时长用 */
/**
 * 时长的可翻译表示。**不能返回字符串**：中文是「204 分 6 秒」、英文是
 * "204 min 6 s"，单位本身就是文案。返回 `I18nText` 由渲染层翻译。
 */
export function durText(v: number, unit: 'ms' | 's' = 's'): I18nText {
  const sec = unit === 'ms' ? v / 1000 : v
  if (sec < 60) return tx('vmaxq.vd.durSec', { v: Math.round(sec) })
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return tx('vmaxq.vd.durMinSec', { m, s })
}

/* ---------------------------------------------------------------------------
 * 四、四个分项评分
 * ------------------------------------------------------------------------ */

export type ScoreKey = 'availability' | 'latency' | 'transport' | 'radio'

export type DimensionScore = {
  key: ScoreKey
  /** 0-100，越低越差；null = 无数据（不是 0 分！） */
  score: number | null
  /** 卡片副标题里的关键数字（i18n key + 参数，由渲染层翻译） */
  sub: I18nText | null
  /** 该维的原始口径数字，供导出与证据展示 */
  detail: Record<string, number | string>
  /** 有哪几条证据支持这个分（证据条渲染用） */
  evidence: I18nText[]
}

const clamp = (v: number, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v))

/**
 * 分项评分：把「实测值 / 阈值」映射到 0-100。
 * 口径刻意做成**线性衰减**而不是阶梯：阶梯会让「刚过线」和「远超线」
 * 得到同一个分数，排障时看不出「差多少」。
 *
 * @param value 实测值（越大越差）
 * @param bad   阈值（到阈值时 = 60 分）
 * @param worst 极端值（到极端值时 = 0 分）
 */
function inverseScore(value: number, bad: number, worst: number): number {
  if (value <= 0) return 100
  if (value <= bad) return clamp(100 - 40 * (value / bad))
  if (value >= worst) return 0
  return clamp(60 - 60 * ((value - bad) / (worst - bad)))
}

/** 反向（越小越差，如 RSRP）：-85 好、-110 告警、-125 极端 */
function rsrpScore(rsrp: number): number {
  if (rsrp === 0) return 100 // 没采样不扣分（无数据在调用处单独处理）
  if (rsrp >= -85) return 100
  if (rsrp >= THRESHOLDS.rsrp) return clamp(100 - 40 * ((-85 - rsrp) / (-85 - THRESHOLDS.rsrp)))
  return clamp(60 - 60 * ((THRESHOLDS.rsrp - rsrp) / 15))
}

function sinrScore(sinr: number): number {
  if (sinr === 0) return 100
  if (sinr >= 12) return 100
  if (sinr >= THRESHOLDS.sinr) return clamp(100 - 40 * ((12 - sinr) / 12))
  return clamp(60 - 60 * ((-sinr) / 5))
}

/* ---------------------------------------------------------------------------
 * 五、四个维度的取数（每个函数只认自己那几条字段）
 * ------------------------------------------------------------------------ */

/** 从 sources 里按 key 取行 */
export function rowsOf(sources: SourceResult[], key: string): XdrRow[] {
  return sources.find((s) => s.key === key)?.rows || []
}

/**
 * 数据源显示名 —— 后端优先给 `label_key`，缺键时回退中文 `label`。
 *
 * 三个地方共用（数据源标签行 / 空态说明 / 失败原因拼接），必须同一个实现：
 * 曾经三处各自写 `s.label`，改造 i18n 时只改了其中一处，
 * 英文界面就出现「1300 是英文、空态那行还是中文」的割裂。
 */
export function sourceLabel(t: (k: string) => string, s: SourceResult): string {
  return s.label_key ? t(s.label_key) : s.label
}

/**
 * 业务可用性 —— 1100 的 procedure_status 分布 + S1-U Path Failure 硬扣分。
 *
 * 实测：754 Success / 8 Timeout / 4 Failure / 12 条 S1-U Path Failure。
 * `S1-U Path Failure` 单独看是因为它意味着**用户面断了**，
 * 但它在 procedure_status 里往往还是 Success（Failure 是"送达"，不是"成功"），
 * 只按 status 算会把「断网」算成「正常」——这是现场最容易误判的一处。
 */
export function scoreAvailability(sources: SourceResult[]): DimensionScore {
  const rows = rowsOf(sources, '1100')
  if (!rows.length) {
    return { key: 'availability', score: null, sub: null, detail: {}, evidence: [] }
  }
  let success = 0
  let timeout = 0
  let failure = 0
  let pathFail = 0
  for (const r of rows) {
    const st = strU(r.procedure_status)
    if (st === 'SUCCESS') success += 1
    else if (st === 'TIMEOUT') timeout += 1
    else if (st) failure += 1
    if (strU(r.request_cause).includes('S1-U PATH FAILURE')) pathFail += 1
  }
  const total = success + timeout + failure
  const bad = timeout + failure
  const failRate = total ? (bad / total) * 100 : 0
  // 基础分：失败率线性衰减；再叠 S1-U Path Failure 硬扣分
  let score = inverseScore(failRate, THRESHOLDS.failRate, 40)
  const pathPenalty = Math.min(40, pathFail * 3.5)
  score = clamp(score - pathPenalty)

  const evidence: I18nText[] = []
  if (bad) evidence.push(tx('vmaxq.vd.ev.availBad', { bad, timeout, failure, rate: pct(failRate) }))
  if (pathFail) evidence.push(tx('vmaxq.vd.ev.availPathFail', { n: pathFail }))
  if (!evidence.length) evidence.push(tx('vmaxq.vd.ev.availAllOk', { total }))

  return {
    key: 'availability',
    score: Math.round(score),
    sub: bad ? tx('vmaxq.vd.sub.avail', { total, bad }) : tx('vmaxq.vd.sub.availOk', { total }),
    detail: { total, success, timeout, failure, pathFail, failRate: +failRate.toFixed(2) },
    evidence,
  }
}

/**
 * 响应时延 —— 1300 的 `$first_resp_delay` P90 为主，`$tcp_resp_delay` 均值为辅。
 *
 * 为什么用 P90 而不是均值：实测同一窗口均值 455ms、峰值 118765ms。
 * 均值会被大量小包拉平 —— 用户抱怨的恰恰是那几个「卡住 2 分钟」的请求。
 */
export function scoreLatency(sources: SourceResult[]): DimensionScore {
  const rows = rowsOf(sources, '1300')
  if (!rows.length) {
    return { key: 'latency', score: null, sub: null, detail: {}, evidence: [] }
  }
  const first = rows.map((r) => num(r.$first_resp_delay)).filter((v) => v > 0)
  const tcp = rows.map((r) => num(r.$tcp_resp_delay)).filter((v) => v > 0)
  const ulRtt = rows.map((r) => num(r.ul_avg_rtt)).filter((v) => v > 0)
  const dlRtt = rows.map((r) => num(r.dl_avg_rtt)).filter((v) => v > 0)

  const p90 = percentile(first, 0.9)
  const tcpAvg = mean(tcp)
  // 首包时延是主判据（权重 0.7），TCP 应答时延是副判据（0.3）
  const s1 = p90 > 0 ? inverseScore(p90, THRESHOLDS.firstRespP90, 30000) : 100
  const s2 = tcpAvg > 0 ? inverseScore(tcpAvg, THRESHOLDS.tcpResp, 5000) : 100
  const hasSignal = p90 > 0 || tcpAvg > 0
  const score = hasSignal ? Math.round(s1 * 0.7 + s2 * 0.3) : null

  const evidence: I18nText[] = []
  if (p90 > 0) evidence.push(tx('vmaxq.vd.ev.latencyP90', { p90: ms(p90), mean: ms(mean(first)), max: ms(Math.max(...first)) }))
  if (tcpAvg > 0) evidence.push(tx('vmaxq.vd.ev.latencyTcp', { v: ms(tcpAvg) }))
  if (ulRtt.length) evidence.push(tx('vmaxq.vd.ev.latencyRtt', { ul: ms(mean(ulRtt)), dl: ms(mean(dlRtt)) }))

  return {
    key: 'latency',
    score,
    sub: p90 > 0 ? tx('vmaxq.vd.sub.latency', { v: ms(p90) }) : null,
    detail: {
      firstP90: Math.round(p90), firstAvg: Math.round(mean(first)),
      firstMax: Math.round(first.length ? Math.max(...first) : 0),
      tcpAvg: Math.round(tcpAvg),
      ulRtt: Math.round(mean(ulRtt)), dlRtt: Math.round(mean(dlRtt)),
    },
    evidence,
  }
}

/**
 * 传输质量 —— 重传率 + 乱序率。
 *
 * 单位坑：上游 `ul_retrans_pkt` 是"包数"，`ul_pkt` 也是"包数"，
 * 但有的记录单位是 KB（字段名不一致）→ 分母为 0 时不算率，只看绝对数。
 */
export function scoreTransport(sources: SourceResult[]): DimensionScore {
  const rows = rowsOf(sources, '1300')
  if (!rows.length) {
    return { key: 'transport', score: null, sub: null, detail: {}, evidence: [] }
  }
  let ulPkt = 0, dlPkt = 0, retrans = 0, disorder = 0
  for (const r of rows) {
    ulPkt += num(r.ul_pkt); dlPkt += num(r.dl_pkt)
    retrans += num(r.ul_retrans_pkt) + num(r.dl_retrans_pkt)
    disorder += num(r.ul_disorder_pkt) + num(r.dl_disorder_pkt)
  }
  const totalPkt = ulPkt + dlPkt
  const retransRate = totalPkt > 0 ? (retrans / totalPkt) * 100 : 0
  const disorderRate = totalPkt > 0 ? (disorder / totalPkt) * 100 : 0

  let score: number | null
  if (totalPkt > 0) {
    const s1 = inverseScore(retransRate, THRESHOLDS.retrans, 8)
    const s2 = inverseScore(disorderRate, THRESHOLDS.retrans * 2, 15)
    score = Math.round(s1 * 0.75 + s2 * 0.25)
  } else {
    score = null
  }

  const evidence: I18nText[] = []
  if (totalPkt > 0) {
    evidence.push(tx('vmaxq.vd.ev.transRetrans', { retrans: Math.round(retrans), total: Math.round(totalPkt), rate: pct(retransRate) }))
    evidence.push(tx('vmaxq.vd.ev.transDisorder', { n: Math.round(disorder), rate: pct(disorderRate) }))
  } else {
    evidence.push(tx('vmaxq.vd.ev.transNoPacket'))
  }

  return {
    key: 'transport',
    score,
    sub: totalPkt > 0 ? tx('vmaxq.vd.sub.transport', { v: pct(retransRate) }) : null,
    detail: {
      totalPkt: Math.round(totalPkt), retrans: Math.round(retrans), disorder: Math.round(disorder),
      retransRate: +retransRate.toFixed(3), disorderRate: +disorderRate.toFixed(3),
    },
    evidence,
  }
}

/**
 * 无线质量 —— RAN(32) 的 serving_rsrp / ulsinr / cqi 的 P10。
 *
 * 用 P10 而不是均值：弱覆盖是「最差的那几分钟」导致的，
 * 均值 -95 dBm 的用户照样可能在某个小区里掉到 -120 打不通电话。
 */
export function scoreRadio(sources: SourceResult[]): DimensionScore {
  const rows = rowsOf(sources, '32')
  if (!rows.length) {
    const src = sources.find((s) => s.key === '32')
    return {
      key: 'radio', score: null, sub: null,
      // detail 是「导出用的原始口径」，只放上游原文，不做翻译包装：
      // 上游 error 本身就是英文（VMAX 门户/接口原文），空则留空串。
      // 人要读的说明在 evidence 里（已走 i18n），两者职责不同。
      detail: { reason: src?.error || '' },
      evidence: src?.error ? [tx('vmaxq.vd.ev.radioSrcError', { msg: src.error })] : [tx('vmaxq.vd.ev.radioNoRecord')],
    }
  }
  const rsrp = rows.map(rsrpOf).filter((v) => v !== 0)
  const sinr = rows.map(sinrOf).filter((v) => v !== 0)
  const cqi = rows.map(cqiOf).filter((v) => v > 0)

  const rsrpP10 = percentile(rsrp, 0.1)
  const sinrP10 = percentile(sinr, 0.1)
  const cqiP10 = percentile(cqi, 0.1)

  const parts: number[] = []
  if (rsrp.length) parts.push(rsrpScore(rsrpP10))
  if (sinr.length) parts.push(sinrScore(sinrP10))
  if (!parts.length) {
    return {
      key: 'radio', score: null, sub: null,
      detail: {},
      evidence: [tx('vmaxq.vd.ev.radioNoSample')],
    }
  }
  const score = Math.round(mean(parts))

  const evidence: I18nText[] = []
  if (rsrp.length) evidence.push(tx('vmaxq.vd.ev.radioRsrp', { p10: rsrpP10, mean: Math.round(mean(rsrp)), n: rsrp.length }))
  if (sinr.length) evidence.push(tx('vmaxq.vd.ev.radioSinr', { p10: sinrP10, n: sinr.length }))
  if (cqi.length) evidence.push(tx('vmaxq.vd.ev.radioCqi', { p10: cqiP10 }))

  return {
    key: 'radio',
    score,
    sub: rsrp.length ? tx('vmaxq.vd.sub.radio', { v: rsrpP10 }) : null,
    detail: {
      rsrpP10, sinrP10, cqiP10,
      rsrpAvg: Math.round(mean(rsrp)), samples: rsrp.length,
    },
    evidence,
  }
}

/** 四维一次算齐（顺序即卡片顺序） */
export function scoreAll(sources: SourceResult[]): DimensionScore[] {
  return [
    scoreAvailability(sources),
    scoreLatency(sources),
    scoreTransport(sources),
    scoreRadio(sources),
  ]
}

/* ---------------------------------------------------------------------------
 * 六、投诉类型 → 判据权重（不是过滤器，只换入口判据）
 * ------------------------------------------------------------------------ */

/**
 * 每个投诉类型给四维的权重。
 *
 * 0 = 该维不参与本次判定（降权到底，但**仍然展示**分数 ——
 * 用户需要看到"这一维其实也差"，只是本次不拿它做结论）。
 * 这么做而不是隐藏：藏起来会让人以为我们没查。
 */
export const COMPLAINT_WEIGHTS: Record<ComplaintKey, Record<ScoreKey, number>> = {
  all: { availability: 1, latency: 1, transport: 1, radio: 1 },
  voice: { availability: 1.4, latency: 0.6, transport: 0.5, radio: 1.0 },
  ott: { availability: 0.8, latency: 1.3, transport: 1.3, radio: 0.6 },
  video: { availability: 0.8, latency: 1.3, transport: 1.0, radio: 1.0 },
  game: { availability: 0.7, latency: 1.2, transport: 1.2, radio: 1.1 },
  slow: { availability: 1.0, latency: 1.3, transport: 1.3, radio: 0.6 },
}

/** 加权总分（只在有分的维度上归一，避免「缺一维就低分」） */
export function weightedScore(scores: DimensionScore[], complaint: ComplaintKey): number | null {
  const w = COMPLAINT_WEIGHTS[complaint]
  let sum = 0
  let wsum = 0
  for (const s of scores) {
    if (s.score === null) continue
    sum += s.score * w[s.key]
    wsum += w[s.key]
  }
  return wsum ? Math.round(sum / wsum) : null
}

/* ---------------------------------------------------------------------------
 * 七、语音：CSFB / VoLTE 双模式（方案 §4.4）
 * ------------------------------------------------------------------------ */

export type VoiceStep = {
  time: string
  iface: string
  proc: string
  cause: string
  status: string
  cell: string
}

export type VoiceResult = {
  /** csfb / volte / none —— 本时段实际观察到的语音方式 */
  mode: 'csfb' | 'volte' | 'none'
  /** SGs 位置更新条数；0 且用户投诉语音 → CSFB 可能不可用 */
  sgsCount: number
  /** CS Fallback Triggered 次数 */
  csfbTrigger: number
  /** Extended Service Request（回落请求）条数 */
  esrCount: number
  /** 寻呼条数（被叫） */
  pagingCount: number
  /** 超时/失败条数 */
  badCount: number
  /** 起呼成功率（%），无起呼则 null */
  successRate: number | null
  /** 回落耗时（ms），只统计「ESR → UE context release」成对的样本 */
  fallbackMs: number | null
  /** 回落链明细（表格） */
  steps: VoiceStep[]
  /** 是否出现 QCI=1 承载（VoLTE 判据） */
  qci1: number
  /** 证据条文案 */
  evidence: I18nText[]
}

/**
 * 语音判定。
 *
 * CSFB 判据链（评审意见 3：「目前主要是 CSFB，要找 1100 的 SGs 接口记录来判」）：
 *   SGs 位置更新 → Extended Service Request(CS Fallback Triggered) → 回落
 *
 * VoLTE 判据（预埋，上线即用）：
 *   1100 出现 QCI=1 承载建立/修改，或 1300 出现 qci=1 话单。
 *   ⚠ 不能用 qci=0 冒充 —— 实测 qci=0 的 49 条是 DNS 小包。
 */
export function analyzeVoice(sources: SourceResult[]): VoiceResult {
  const r1100 = rowsOf(sources, '1100')
  const r1300 = rowsOf(sources, '1300')

  let sgsCount = 0, csfbTrigger = 0, esrCount = 0, pagingCount = 0, badCount = 0
  let esrOk = 0, esrTotal = 0
  const steps: VoiceStep[] = []
  // 回落耗时配对：按时间排序后，ESR 之后第一条 UE context release 视为该次回落完成
  const esrTimes: string[] = []
  const releaseTimes: string[] = []

  for (const r of r1100) {
    const iface = strU(r.interface)
    const proc = str(r.procedure_type)
    const procU = strU(proc)
    const cause = str(r.request_cause)
    const status = strU(r.procedure_status)
    const isBad = status === 'TIMEOUT' || status === 'FAILURE'

    if (iface === 'SGS') sgsCount += 1
    if (strU(cause).includes('CS FALLBACK TRIGGERED')) csfbTrigger += 1
    if (procU.includes('EXTENDED SERVICE REQUEST')) {
      esrCount += 1; esrTotal += 1
      if (!isBad) esrOk += 1
      esrTimes.push(rowTime(r))
    }
    if (procU.includes('PAGING')) {
      pagingCount += 1
      if (isBad) badCount += 1
    }
    if (isBad) badCount += 1
    if (procU.includes('UE CONTEXT RELEASE')) releaseTimes.push(rowTime(r))

    // 明细表只收语音相关的四类过程，否则 766 条会把表撑爆
    const relevant = iface === 'SGS'
      || procU.includes('EXTENDED SERVICE REQUEST')
      || procU.includes('PAGING')
      || strU(cause).includes('CS FALLBACK TRIGGERED')
    if (relevant) {
      steps.push({
        time: rowTime(r), iface: str(r.interface) || '—',
        proc: proc || '—', cause: cause || '—',
        status: str(r.procedure_status) || '—',
        cell: str(r.cellname || r.cell || r.cellid) || '—',
      })
    }
  }

  // 1300 的 qci=1（VoLTE 语音承载）
  let qci1 = 0
  for (const r of r1300) {
    if (str(r.qci) === '1') qci1 += 1
  }

  // 回落耗时：每次 ESR 找它之后最近的 release，差值 > 0 且 < 30s 才算有效样本
  let fallbackMs: number | null = null
  const deltas: number[] = []
  const parse = (t: string) => {
    const d = new Date(t.replace(' ', 'T').replace(/\.\d+$/, ''))
    return Number.isNaN(d.getTime()) ? null : d.getTime()
  }
  for (const et of esrTimes) {
    const e = parse(et)
    if (e === null) continue
    for (const rt of releaseTimes) {
      const r = parse(rt)
      if (r === null || r < e) continue
      const d = r - e
      if (d >= 0 && d <= 30000) { deltas.push(d); break }
    }
  }
  if (deltas.length) fallbackMs = Math.round(mean(deltas))

  const mode: VoiceResult['mode'] = qci1 > 0 ? 'volte' : (csfbTrigger > 0 || esrCount > 0 || sgsCount > 0 ? 'csfb' : 'none')
  const successRate = esrTotal ? +((esrOk / esrTotal) * 100).toFixed(1) : null

  const evidence: I18nText[] = []
  if (mode === 'none') evidence.push(tx('vmaxq.vd.ev.voiceNone'))
  if (sgsCount) evidence.push(tx('vmaxq.vd.ev.voiceSgs', { n: sgsCount }))
  if (csfbTrigger) evidence.push(tx('vmaxq.vd.ev.voiceCsfb', { n: csfbTrigger }))
  if (esrCount) evidence.push(tx('vmaxq.vd.ev.voiceEsr', { n: esrCount, ok: esrOk }))
  if (fallbackMs !== null) {
    // 「偏慢」单独成 key，不拼在句子尾巴上：中英文语序不同，
    // 英文里要写成 "… (slow)" 跟在数值后，中文是「…（偏慢）」，
    // 拼字符串的写法没法适配，所以用两个 key。
    evidence.push(fallbackMs > THRESHOLDS.csfbFallback
      ? tx('vmaxq.vd.ev.voiceFallbackSlow', { v: ms(fallbackMs) })
      : tx('vmaxq.vd.ev.voiceFallback', { v: ms(fallbackMs) }))
  }
  if (qci1) evidence.push(tx('vmaxq.vd.ev.voiceQci1', { n: qci1 }))
  if (pagingCount) {
    evidence.push(badCount
      ? tx('vmaxq.vd.ev.voicePagingBad', { n: pagingCount, bad: badCount })
      : tx('vmaxq.vd.ev.voicePaging', { n: pagingCount }))
  }

  return {
    mode, sgsCount, csfbTrigger, esrCount, pagingCount, badCount,
    successRate, fallbackMs, steps, qci1, evidence,
  }
}

/* ---------------------------------------------------------------------------
 * 八、OTT 语音视频（方案 §4.7）—— 间接判据，不是应用层结论
 * ------------------------------------------------------------------------ */

export type OttSession = {
  startTime: string
  app: string
  durationS: number
  dlTraffic: string
  dlRtt: number
  ulRtt: number
  retransRate: number
}

export type OttResult = {
  sessions: OttSession[]
  totalSessions: number
  totalDurationS: number
  avgDlRtt: number
  jitter: number
  retransRate: number
  /** 基线（非通话时段）下行 RTT，用于对照「通话期间是否更差」 */
  baselineRtt: number
  evidence: I18nText[]
}

/**
 * OTT 通话识别 —— 三路间接判据（方案 §4.7）。
 *
 * ⚠ 诚实的边界：**没有 SIP / RTP**。实测 1300 全量扫描 protocol ∈ {SIP,RTP}
 *   命中 0 条；`service=VoIP` 的 20 条全部是 `subservice=STUN`。
 *   所以这里只能识别「通话存在 + 通话期网络质量」，
 *   不能识别「对方拒接 / 注册失败」——这条要写在页面上（vmaxq.ott.limitBody）。
 */
export function analyzeOtt(sources: SourceResult[]): OttResult {
  const rows = rowsOf(sources, '1300')
  const sessions: OttSession[] = []
  const callRtts: number[] = []
  const otherRtts: number[] = []
  let retransSum = 0
  let pktSum = 0

  for (const r of rows) {
    const sub = strU(r.subservice)
    const app = strU(r.app_content_name)
    const proto = strU(r.protocol)
    const durMs = num(r.duration)
    const dlRtt = num(r.dl_avg_rtt)
    const dlTrafficKb = num(r.dl_traffic)

    // 判据 ①：STUN（WebRTC 打洞，微信/WhatsApp 通话必经）
    // 判据 ②：QUIC / WHATSAPP_* 长连接 + 时长 ≥ 10s + 码率低（长连接低码率 = 语音态）
    const isStun = sub === 'STUN' || proto === 'STUN'
    const lowBitrate = dlTrafficKb > 0 && (dlTrafficKb / Math.max(durMs / 1000, 1)) < 40
    const isLongCall = (app.includes('WHATSAPP') || proto === 'QUIC' || sub.includes('VOIP'))
      && durMs >= THRESHOLDS.ottMinDuration * 1000
      && lowBitrate

    if (isStun || isLongCall) {
      const ul = num(r.ul_pkt)
      const dl = num(r.dl_pkt)
      const rt = num(r.ul_retrans_pkt) + num(r.dl_retrans_pkt)
      sessions.push({
        startTime: rowTime(r),
        app: str(r.app_content_name) || str(r.subservice) || '—',
        durationS: Math.round(durMs / 1000),
        dlTraffic: dlTrafficKb >= 1024 ? `${(dlTrafficKb / 1024).toFixed(1)} MB` : `${Math.round(dlTrafficKb)} KB`,
        dlRtt: Math.round(dlRtt),
        ulRtt: Math.round(num(r.ul_avg_rtt)),
        retransRate: (ul + dl) > 0 ? +((rt / (ul + dl)) * 100).toFixed(2) : 0,
      })
      if (dlRtt > 0) callRtts.push(dlRtt)
      retransSum += rt
      pktSum += ul + dl
    } else if (dlRtt > 0) {
      otherRtts.push(dlRtt)
    }
  }

  const totalDurationS = sessions.reduce((a, s) => a + s.durationS, 0)
  const avgDlRtt = Math.round(mean(callRtts))
  const jitter = Math.round(stdDev(callRtts))
  const retransRate = pktSum > 0 ? +((retransSum / pktSum) * 100).toFixed(2) : 0
  const baselineRtt = Math.round(mean(otherRtts))

  const evidence: I18nText[] = []
  if (!sessions.length) {
    evidence.push(tx('vmaxq.vd.ev.ottNone'))
  } else {
    evidence.push(tx('vmaxq.vd.ev.ottSessions', { n: sessions.length, dur: durText(totalDurationS) }))
    evidence.push(tx('vmaxq.vd.ev.ottRtt', { rtt: avgDlRtt, jitter }))
    if (baselineRtt) {
      const ratio = baselineRtt ? +(avgDlRtt / baselineRtt).toFixed(1) : '—'
      evidence.push(tx('vmaxq.vd.ev.ottBaseline', { base: baselineRtt, ratio }))
    }
  }
  evidence.push(tx('vmaxq.vd.ev.ottNoSip'))

  return { sessions, totalSessions: sessions.length, totalDurationS, avgDlRtt, jitter, retransRate, baselineRtt, evidence }
}

/* ---------------------------------------------------------------------------
 * 九、游戏识别（方案 §4.3）—— 三档规则，关键词外置
 * ------------------------------------------------------------------------ */

/**
 * 游戏关键词（与后端 `vmax_game_apps.json` 同步）。
 * 评审意见 2：「话单里有时候会有 egame 之类的」→ 必须包含 egame。
 */
export const GAME_KEYWORDS = [
  'egame', 'e-game', 'pubg', 'freefire', 'free fire', 'garena', 'mlbb',
  'mobilelegends', 'mobile legends', 'genshin', 'honorofkings', 'honor of kings',
  'clashofclans', 'clash of clans', 'crossfire', 'pointblank', 'point blank',
  'callofduty', 'codmobile', 'roblox', 'minecraft', 'amongus', 'subwaysurf',
  'kingofglory', 'arenaofvalor', 'mobile game', 'gameloft', 'supercell',
  '王者荣耀', '和平精英', '原神', '崩坏', '荒野行动', '穿越火线', '皇室战争', '金铲铲',
]

/** 应用商店黑名单：名字里带 play / game 但不是游戏（实测误判源） */
export const GAME_EXCLUDE = ['palmplaystore', 'googleplay', 'play store', 'appstore', 'app store', 'huawei_appgallery']

export type GameHit = {
  app: string
  /** 命中档位：service / keyword / suspect */
  tier: 'service' | 'keyword' | 'suspect'
  records: number
  trafficKb: number
  avgRtt: number
  jitter: number
  retransRate: number
}

export type GameResult = {
  hits: GameHit[]
  totalSessions: number
  evidence: I18nText[]
}

export function analyzeGame(sources: SourceResult[]): GameResult {
  const rows = rowsOf(sources, '1300')
  const agg = new Map<string, {
    tier: GameHit['tier']; records: number; traffic: number
    rtts: number[]; retrans: number; pkt: number
  }>()

  for (const r of rows) {
    const service = strU(r.service)
    const blob = `${strU(r.subservice)} ${strU(r.app_content_name)}`
    const low = blob.toLowerCase()

    // 商店先排除，再判游戏 —— 否则 PALMPLAYSTORE 会被 ③ 兜底误收
    if (GAME_EXCLUDE.some((k) => low.includes(k))) continue

    let tier: GameHit['tier'] | null = null
    if (service === 'GAME' || service === 'GAMING') tier = 'service'
    else if (GAME_KEYWORDS.some((k) => low.includes(k))) tier = 'keyword'
    else if ((low.includes('game') || low.includes('play')) && service !== 'NETWORK STORAGE') tier = 'suspect'

    if (!tier) continue

    const app = str(r.app_content_name) || str(r.subservice) || str(r.service) || '—'
    const cur = agg.get(app) || { tier, records: 0, traffic: 0, rtts: [], retrans: 0, pkt: 0 }
    cur.records += 1
    cur.traffic += num(r.ul_traffic) + num(r.dl_traffic)
    cur.retrans += num(r.ul_retrans_pkt) + num(r.dl_retrans_pkt)
    cur.pkt += num(r.ul_pkt) + num(r.dl_pkt)
    const rtt = num(r.dl_avg_rtt) || num(r.ul_avg_rtt)
    if (rtt > 0) cur.rtts.push(rtt)
    agg.set(app, cur)
  }

  const hits: GameHit[] = [...agg.entries()].map(([app, v]) => ({
    app,
    tier: v.tier,
    records: v.records,
    trafficKb: Math.round(v.traffic),
    avgRtt: Math.round(mean(v.rtts)),
    jitter: Math.round(stdDev(v.rtts)),
    retransRate: v.pkt > 0 ? +((v.retrans / v.pkt) * 100).toFixed(2) : 0,
  })).sort((a, b) => b.records - a.records)

  const totalSessions = hits.reduce((a, h) => a + h.records, 0)
  const evidence: I18nText[] = []
  if (!hits.length) {
    evidence.push(tx('vmaxq.vd.ev.gameNone'))
  } else {
    evidence.push(tx('vmaxq.vd.ev.gameHits', { apps: hits.length, n: totalSessions }))
    const worst = [...hits].sort((a, b) => b.avgRtt - a.avgRtt)[0]
    if (worst && worst.avgRtt) evidence.push(tx('vmaxq.vd.ev.gameWorst', { app: worst.app, rtt: worst.avgRtt, jitter: worst.jitter }))
    const suspected = hits.filter((h) => h.tier === 'suspect')
    if (suspected.length) evidence.push(tx('vmaxq.vd.ev.gameSuspected', { n: suspected.length }))
  }

  return { hits, totalSessions, evidence }
}

/* ---------------------------------------------------------------------------
 * 十、证据时间线（方案 §4.9）
 * ------------------------------------------------------------------------ */

export type TimelineCell = {
  /** 该分钟该源的摘要文本（i18n key + 参数；纯数值/「—」也用 key，保持类型统一） */
  text: I18nText
  /** 严重度：驱动染色 */
  level: 'ok' | 'warn' | 'bad' | 'none'
  /** 下钻用的原始行 */
  rows: XdrRow[]
}

export type TimelineRow = {
  minute: string
  traffic: TimelineCell
  latency: TimelineCell
  transport: TimelineCell
  radio: TimelineCell
  voice: TimelineCell
  /** 本分钟的结论（由四源交叉得出） */
  judge: I18nText
  /** 结论严重度 */
  level: 'ok' | 'warn' | 'bad' | 'none'
}

/* ---------------------------------------------------------------------------
 * 六半、无线质量专项分析（Radio 页签）
 * ------------------------------------------------------------------------ */

/** 单个小区的 MR 聚合 */
export type RadioCell = {
  /** 小区名（上游原文，不翻译 —— 排障时要用它去对网管） */
  cell: string
  samples: number
  rsrpAvg: number
  /** 该小区最差的 10% 采样（边缘覆盖，比均值重要） */
  rsrpP10: number
  sinrAvg: number
  cqiAvg: number
  /** 综合严重度，驱动表格染色 */
  level: 'ok' | 'warn' | 'bad'
}

/** 分钟桶里的无线趋势点 */
export type RadioBucket = {
  minute: string
  rsrpAvg: number
  rsrpP10: number
  sinrAvg: number
  samples: number
}

export type RadioAnalysis = {
  /** 采样总数（0 = 本窗口没有 MR，后面所有字段都没意义） */
  samples: number
  rsrpAvg: number
  rsrpP10: number
  sinrAvg: number
  sinrP10: number
  cqiAvg: number
  /** 制式分布，如 [{name:'LTE', n:118}, {name:'NR', n:2}] */
  rats: { name: string; n: number }[]
  buckets: RadioBucket[]
  cells: RadioCell[]
  /** 最差的小区（按 rsrpP10 排序），没有小区时为空串 */
  worstCell: string
  /** 一句话结论 */
  headline: I18nText
  /** 判据（逐条，界面上列点展示） */
  basis: I18nText[]
  /** 结论严重度 */
  level: 'ok' | 'warn' | 'bad'
}

/**
 * 无线侧专项分析 —— Radio 页签的数据源。
 *
 * 与 scoreRadio 的区别：那边只产出一个 0~100 的分数（给四维卡用），
 * 这里要把「分数为什么是这个值」摊开：趋势、逐小区、结论与判据。
 * 两者**必须用同一批阈值与同一批采样**，否则会出现
 * 「评分卡说 62 分、Radio 页签说覆盖良好」这种自相矛盾。
 *
 * 只吃 source '32'（RAN/UEMR），不重新取数 —— 诊断接口已经拉过了。
 */
export function analyzeRadio(sources: SourceResult[]): RadioAnalysis | null {
  const rows = rowsOf(sources, '32')
  const src = sources.find((s) => s.key === '32')

  const empty = (headline: I18nText, basis: I18nText[]): RadioAnalysis => ({
    samples: 0, rsrpAvg: 0, rsrpP10: 0, sinrAvg: 0, sinrP10: 0, cqiAvg: 0,
    rats: [], buckets: [], cells: [], worstCell: '',
    headline, basis, level: 'warn',
  })

  if (!rows.length) {
    // 两种「空」要说清楚，否则用户只会以为「没数据」
    return empty(
      src?.error ? tx('vmaxq.radio.headline.err') : tx('vmaxq.radio.headline.empty'),
      src?.error
        ? [tx('vmaxq.radio.basis.err', { msg: src.error })]
        : [tx('vmaxq.radio.basis.empty')],
    )
  }

  const rsrpAll = rows.map(rsrpOf).filter((v) => v !== 0)
  const sinrAll = rows.map(sinrOf).filter((v) => v !== 0)
  const cqiAll = rows.map(cqiOf).filter((v) => v > 0)

  if (!rsrpAll.length && !sinrAll.length) {
    // 有 RAN 行但关键字段全空：上游表结构/权限变了，别当成"覆盖良好"
    return empty(
      tx('vmaxq.radio.headline.noSample'),
      [tx('vmaxq.radio.basis.noSample', { n: rows.length })],
    )
  }

  // ---- 制式分布 ----
  const ratMap = new Map<string, number>()
  for (const r of rows) {
    const name = str(r.rat_name) || '—'
    ratMap.set(name, (ratMap.get(name) || 0) + 1)
  }
  const rats = [...ratMap.entries()]
    .map(([name, n]) => ({ name, n }))
    .sort((a, b) => b.n - a.n)

  // ---- 逐小区 ----
  const cellMap = new Map<string, { rsrp: number[]; sinr: number[]; cqi: number[] }>()
  for (const r of rows) {
    const cell = cellOf(r)
    let b = cellMap.get(cell)
    if (!b) { b = { rsrp: [], sinr: [], cqi: [] }; cellMap.set(cell, b) }
    const rp = rsrpOf(r); if (rp !== 0) b.rsrp.push(rp)
    const sn = sinrOf(r); if (sn !== 0) b.sinr.push(sn)
    const cq = cqiOf(r); if (cq > 0) b.cqi.push(cq)
  }
  const cells: RadioCell[] = [...cellMap.entries()].map(([cell, b]) => {
    const p10 = b.rsrp.length ? percentile(b.rsrp, 0.1) : 0
    const sa = b.sinr.length ? Math.round(mean(b.sinr) * 10) / 10 : 0
    // 覆盖和干扰各判一次，取更差的那个：
    // 信号强度够但 SINR 差（干扰）同样打不了电话，只看 RSRP 会漏判。
    const lv = radioLevel(p10, sa)
    return {
      cell, samples: Math.max(b.rsrp.length, b.sinr.length),
      rsrpAvg: b.rsrp.length ? Math.round(mean(b.rsrp)) : 0,
      rsrpP10: p10,
      sinrAvg: sa,
      cqiAvg: b.cqi.length ? Math.round(mean(b.cqi) * 10) / 10 : 0,
      level: lv,
    }
  })
  // 最差的小区排前面 —— 投诉定位要的是"哪儿出的问题"，不是"一共几个小区"
  cells.sort((a, b) => (a.rsrpP10 || -999) - (b.rsrpP10 || -999))

  // ---- 分钟趋势（与证据时间线同一套桶） ----
  const bucketMap = new Map<string, { rsrp: number[]; sinr: number[] }>()
  for (const r of rows) {
    const m = minuteKey(rowTime(r))
    if (!m) continue
    let b = bucketMap.get(m)
    if (!b) { b = { rsrp: [], sinr: [] }; bucketMap.set(m, b) }
    const rp = rsrpOf(r); if (rp !== 0) b.rsrp.push(rp)
    const sn = sinrOf(r); if (sn !== 0) b.sinr.push(sn)
  }
  const buckets: RadioBucket[] = [...bucketMap.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([minute, b]) => ({
      minute,
      rsrpAvg: b.rsrp.length ? Math.round(mean(b.rsrp)) : 0,
      rsrpP10: b.rsrp.length ? percentile(b.rsrp, 0.1) : 0,
      sinrAvg: b.sinr.length ? Math.round(mean(b.sinr) * 10) / 10 : 0,
      samples: b.rsrp.length,
    }))

  const rsrpP10 = rsrpAll.length ? percentile(rsrpAll, 0.1) : 0
  const sinrP10 = sinrAll.length ? percentile(sinrAll, 0.1) : 0
  const rsrpAvg = rsrpAll.length ? Math.round(mean(rsrpAll)) : 0
  const sinrAvg = sinrAll.length ? Math.round(mean(sinrAll) * 10) / 10 : 0
  const cqiAvg = cqiAll.length ? Math.round(mean(cqiAll) * 10) / 10 : 0

  // ---- 结论：先判最硬的弱覆盖，再判干扰，最后才说正常 ----
  const basis: I18nText[] = []
  let level: 'ok' | 'warn' | 'bad' = 'ok'
  let headline: I18nText

  if (rsrpAll.length) {
    basis.push(tx('vmaxq.radio.basis.rsrp', {
      p10: rsrpP10, avg: rsrpAvg, n: rsrpAll.length,
    }))
  }
  if (sinrAll.length) {
    basis.push(tx('vmaxq.radio.basis.sinr', { p10: sinrP10, avg: sinrAvg }))
  }

  const weak = rsrpAll.length && rsrpP10 < THRESHOLDS.rsrp
  const noisy = sinrAll.length && sinrP10 < THRESHOLDS.sinr
  if (weak) {
    level = 'bad'
    headline = tx('vmaxq.radio.headline.weak', { v: rsrpP10 })
  } else if (noisy) {
    level = 'warn'
    headline = tx('vmaxq.radio.headline.noisy', { v: sinrP10 })
  } else {
    headline = tx('vmaxq.radio.headline.ok')
  }

  // 只在"确实存在明显更差的小区"时才点名，避免大窗口里正常波动也报小区
  const worst = cells.find((c) => c.level === 'bad') || cells.find((c) => c.level === 'warn')
  if (worst && (weak || noisy)) {
    basis.push(tx('vmaxq.radio.basis.worstCell', {
      cell: worst.cell, rsrp: worst.rsrpP10, sinr: worst.sinrAvg, n: worst.samples,
    }))
  }
  if (buckets.length > 1) {
    // 波动大 = 用户在移动/边缘来回切，比"平均差"更值得提示
    const vals = buckets.map((b) => b.rsrpAvg).filter((v) => v !== 0)
    if (vals.length > 1) {
      const lo = Math.min(...vals)
      const hi = Math.max(...vals)
      if (hi - lo >= 15) {
        basis.push(tx('vmaxq.radio.basis.fluctuate', { lo, hi }))
        if (level === 'ok') level = 'warn'
      }
    }
  }

  return {
    samples: Math.max(rsrpAll.length, sinrAll.length),
    rsrpAvg, rsrpP10, sinrAvg, sinrP10, cqiAvg,
    rats, buckets, cells,
    worstCell: worst?.cell || '',
    headline, basis, level,
  }
}

/** 未带 cellname 的行归到这一类（上游偶发缺字段） */
const t_unknownCell = (): string => '—'

/** 覆盖 + 干扰取更差（与 cells 里同一判据，抽出来避免两处漂移） */
function radioLevel(rsrpP10: number, sinrAvg: number): 'ok' | 'warn' | 'bad' {
  if (rsrpP10 !== 0 && rsrpP10 < THRESHOLDS.rsrp) return 'bad'
  if (sinrAvg !== 0 && sinrAvg < THRESHOLDS.sinr) return 'bad'
  if (rsrpP10 !== 0 && rsrpP10 < -100) return 'warn'
  if (sinrAvg !== 0 && sinrAvg < 5) return 'warn'
  return 'ok'
}

/**
 * 按分钟桶聚合四源。
 *
 * 为什么按分钟：投诉说的是「八点十几分视频卡」，分钟粒度刚好对得上，
 * 又不会被单条话单（秒级）淹没。跨源交叉判断必须落在同一个桶里。
 */
export function buildTimeline(sources: SourceResult[]): TimelineRow[] {
  type Bucket = {
    traffic: number; firstResp: number[]; retrans: number; pkt: number
    rsrp: number[]; sinr: number[]
    voiceBad: number; voiceOk: number; csfb: number
    rows: Record<string, XdrRow[]>
  }
  const buckets = new Map<string, Bucket>()
  const get = (m: string): Bucket => {
    let b = buckets.get(m)
    if (!b) {
      b = {
        traffic: 0, firstResp: [], retrans: 0, pkt: 0,
        rsrp: [], sinr: [], voiceBad: 0, voiceOk: 0, csfb: 0,
        rows: { '1300': [], '1100': [], '32': [] },
      }
      buckets.set(m, b)
    }
    return b
  }

  for (const r of rowsOf(sources, '1300')) {
    const m = minuteKey(rowTime(r))
    if (!m) continue
    const b = get(m)
    b.traffic += num(r.ul_traffic) + num(r.dl_traffic)
    const fr = num(r.$first_resp_delay)
    if (fr > 0) b.firstResp.push(fr)
    b.retrans += num(r.ul_retrans_pkt) + num(r.dl_retrans_pkt)
    b.pkt += num(r.ul_pkt) + num(r.dl_pkt)
    b.rows['1300'].push(r)
  }
  for (const r of rowsOf(sources, '1100')) {
    const m = minuteKey(rowTime(r))
    if (!m) continue
    const b = get(m)
    const st = strU(r.procedure_status)
    if (st === 'TIMEOUT' || st === 'FAILURE') b.voiceBad += 1
    else if (st === 'SUCCESS') b.voiceOk += 1
    if (strU(r.request_cause).includes('CS FALLBACK TRIGGERED')) b.csfb += 1
    b.rows['1100'].push(r)
  }
  for (const r of rowsOf(sources, '32')) {
    const m = minuteKey(rowTime(r))
    if (!m) continue
    const b = get(m)
    const rsrp = num(r.serving_rsrp)
    if (rsrp !== 0) b.rsrp.push(rsrp)
    const sinr = num(r.ulsinr)
    if (sinr !== 0) b.sinr.push(sinr)
    b.rows['32'].push(r)
  }

  const kb = (v: number) => (v < 1024 ? `${Math.round(v)} KB` : `${(v / 1024).toFixed(1)} MB`)

  const out: TimelineRow[] = [...buckets.entries()].map(([minute, b]) => {
    const traffic: TimelineCell = b.traffic > 0
      ? { text: tx('vmaxq.vd.tl.kb', { v: kb(b.traffic) }), level: 'none', rows: b.rows['1300'] }
      : { text: tx('vmaxq.vd.dash'), level: 'none', rows: [] }

    const p90 = percentile(b.firstResp, 0.9)
    const latency: TimelineCell = p90 > 0
      ? {
        text: tx('vmaxq.vd.tl.firstResp', { v: ms(p90) }),
        level: p90 > THRESHOLDS.firstRespP90 ? 'bad' : p90 > THRESHOLDS.firstRespP90 / 2 ? 'warn' : 'ok',
        rows: b.rows['1300'],
      }
      : { text: tx('vmaxq.vd.dash'), level: 'none', rows: [] }

    const rr = b.pkt > 0 ? (b.retrans / b.pkt) * 100 : 0
    const transport: TimelineCell = b.pkt > 0
      ? {
        text: tx('vmaxq.vd.tl.retrans', { v: pct(rr) }),
        level: rr > THRESHOLDS.retrans ? 'bad' : rr > THRESHOLDS.retrans / 2 ? 'warn' : 'ok',
        rows: b.rows['1300'],
      }
      : { text: tx('vmaxq.vd.dash'), level: 'none', rows: [] }

    const rsrpMin = b.rsrp.length ? Math.min(...b.rsrp) : 0
    const sinrMin = b.sinr.length ? Math.min(...b.sinr) : 0
    const radioLevel: TimelineCell['level'] = !b.rsrp.length && !b.sinr.length
      ? 'none'
      : (rsrpMin < THRESHOLDS.rsrp || sinrMin < THRESHOLDS.sinr) ? 'bad'
        : (rsrpMin < THRESHOLDS.rsrp + 10) ? 'warn' : 'ok'
    const radio: TimelineCell = {
      text: b.rsrp.length
        ? tx(b.sinr.length ? 'vmaxq.vd.tl.radioBoth' : 'vmaxq.vd.tl.radioRsrp', { rsrp: rsrpMin, sinr: sinrMin })
        : tx('vmaxq.vd.dash'),
      level: radioLevel,
      rows: b.rows['32'],
    }

    const voiceLevel: TimelineCell['level'] = b.voiceBad > 0 ? 'bad' : b.csfb > 0 ? 'warn' : b.voiceOk > 0 ? 'ok' : 'none'
    // 不做「片段拼接」：中文是「CSFB 41 / 失败 3」，英文语序是 "CSFB 41 / 3 failed"，
    // 拼字符串两个语言总有一个别扭。所以按情形各给一个整句 key。
    const voice: TimelineCell = {
      text: b.csfb
        ? (b.voiceBad
          ? tx('vmaxq.vd.tl.voiceMixed', { csfb: b.csfb, bad: b.voiceBad })
          : tx('vmaxq.vd.tl.voiceCsfb', { csfb: b.csfb }))
        : (b.voiceOk ? tx('vmaxq.vd.tl.voiceOk', { n: b.voiceOk }) : tx('vmaxq.vd.dash')),
      level: voiceLevel,
      rows: b.rows['1100'],
    }

    // 交叉结论：这是整个时间线存在的理由 —— 单看一列永远得不出下面这几句
    let judge = tx('vmaxq.vd.tl.normal')
    let level: TimelineRow['level'] = 'ok'
    if (voiceLevel === 'bad') { judge = tx('vmaxq.vd.tl.voiceFail'); level = 'bad' }
    else if (radioLevel === 'bad' && traffic.level !== 'none' && b.traffic > 0) {
      judge = tx('vmaxq.vd.tl.weakWithTraffic'); level = 'bad'
    } else if (radioLevel === 'bad') { judge = tx('vmaxq.vd.tl.weakCoverage'); level = 'warn' }
    else if (latency.level === 'bad') { judge = tx('vmaxq.vd.tl.firstRespBad'); level = 'bad' }
    else if (transport.level === 'bad') { judge = tx('vmaxq.vd.tl.retransHigh'); level = 'warn' }
    else if (latency.level === 'none' && traffic.level === 'none' && voiceLevel === 'none' && radioLevel === 'none') {
      judge = tx('vmaxq.vd.tl.noData'); level = 'none'
    }

    return { minute, traffic, latency, transport, radio, voice, judge, level }
  }).sort((a, b) => a.minute.localeCompare(b.minute))

  return out
}

/* ---------------------------------------------------------------------------
 * 十一、结论生成（方案 §4.8：确定性规则，不用 LLM）
 * ------------------------------------------------------------------------ */

export type Verdict = {
  /** 一句话结论 */
  headline: I18nText
  /** 判定依据（多行） */
  basis: I18nText[]
  /** 处理建议 */
  suggestion: I18nText
  /** 置信度 */
  confidence: 'high' | 'mid' | 'low'
  /** 是否复现了用户投诉的现象 */
  reproduced: boolean
  /** 触发结论的分项（用于把对应评分卡高亮） */
  focus: ScoreKey | 'voice' | 'ott' | 'game' | 'none'
}

/**
 * 按投诉类型生成结论。
 *
 * 顺序很重要：**先看该投诉类型专属的那条判据链**，再回落到四维评分。
 * 这样「语音投诉」不会因为用户同时看了 300MB 视频而被判成「上网慢」。
 */
export function buildVerdict(
  complaint: ComplaintKey,
  scores: DimensionScore[],
  voice: VoiceResult,
  ott: OttResult,
  game: GameResult,
  sources: SourceResult[],
): Verdict {
  const by = (k: ScoreKey) => scores.find((s) => s.key === k)?.score ?? null
  const av = by('availability'), la = by('latency'), tr = by('transport'), ra = by('radio')

  // 无线侧拿不到数据时，结论必须说清楚「查不到」，不能装正常
  const radioSrc = sources.find((s) => s.key === '32')
  const radioUnavailable = ra === null
  const radioWhy: I18nText = radioSrc?.error
    ? tx('vmaxq.vd.ev.radioSrcError', { msg: radioSrc.error })
    : tx(radioSrc?.ok ? 'vmaxq.vd.ev.radioNoRecord' : 'vmaxq.vd.radioNotQueried')

  switch (complaint) {
    case 'voice': {
      if (voice.mode === 'none') {
        return {
          headline: tx('vmaxq.vd.headline.voiceNone'),
          basis: [
            tx('vmaxq.vd.basis.voiceNone1'),
            tx('vmaxq.vd.basis.voiceNone2'),
            voice.sgsCount === 0
              ? tx('vmaxq.vd.basis.voiceNoSgs')
              : tx('vmaxq.vd.basis.voiceSgsOk', { n: voice.sgsCount }),
            tx('vmaxq.vd.basis.voiceNoneHint'),
          ],
          suggestion: tx('vmaxq.vd.sugg.voiceNone'),
          confidence: 'low',
          reproduced: false,
          focus: 'voice',
        }
      }
      const bad = voice.badCount > 0 || (voice.successRate !== null && voice.successRate < 90)
      const slow = voice.fallbackMs !== null && voice.fallbackMs > THRESHOLDS.csfbFallback
      if (bad || slow) {
        return {
          headline: voice.mode === 'volte'
            ? tx('vmaxq.vd.headline.voiceVolteBad', { n: voice.qci1 })
            : tx(bad ? 'vmaxq.vd.headline.voiceCsfbFail' : 'vmaxq.vd.headline.voiceCsfbSlow'),
          basis: voice.evidence,
          suggestion: tx(bad ? 'vmaxq.vd.sugg.voiceFail' : 'vmaxq.vd.sugg.voiceSlow'),
          confidence: 'high',
          reproduced: true,
          focus: 'voice',
        }
      }
      return {
        headline: tx('vmaxq.vd.headline.voiceOk', { mode: voice.mode === 'volte' ? 'VoLTE' : 'CSFB' }),
        basis: voice.evidence,
        suggestion: tx('vmaxq.vd.sugg.voiceOk'),
        confidence: 'mid',
        reproduced: false,
        focus: 'voice',
      }
    }

    case 'ott': {
      if (!ott.totalSessions) {
        return {
          headline: tx('vmaxq.vd.headline.ottNone'),
          basis: ott.evidence,
          suggestion: tx('vmaxq.vd.sugg.ottNone'),
          confidence: 'low',
          reproduced: false,
          focus: 'ott',
        }
      }
      const badRtt = ott.avgDlRtt > 150
      const badJitter = ott.jitter > 60
      const badRetrans = ott.retransRate > THRESHOLDS.retrans
      const worse = badRtt || badJitter || badRetrans
      return {
        headline: worse
          ? tx('vmaxq.vd.headline.ottWorse', { rtt: ott.avgDlRtt, jitter: ott.jitter })
          : tx('vmaxq.vd.headline.ottOk', { n: ott.totalSessions }),
        basis: [
          ...ott.evidence,
          tx(worse ? 'vmaxq.vd.basis.ottWorse' : 'vmaxq.vd.basis.ottNormal'),
        ],
        suggestion: tx(worse ? 'vmaxq.vd.sugg.ottWorse' : 'vmaxq.vd.sugg.ottNormal'),
        confidence: worse ? 'mid' : 'mid',
        reproduced: worse,
        focus: 'ott',
      }
    }

    case 'video': {
      if (la !== null && la < THRESHOLDS.scoreBad) {
        return {
          headline: tx('vmaxq.vd.headline.videoLatency'),
          basis: scores.find((s) => s.key === 'latency')?.evidence || [],
          suggestion: tx('vmaxq.vd.sugg.videoLatency'),
          confidence: 'high', reproduced: true, focus: 'latency',
        }
      }
      if (ra !== null && ra < THRESHOLDS.scoreBad) {
        return {
          headline: tx('vmaxq.vd.headline.videoRadio'),
          basis: scores.find((s) => s.key === 'radio')?.evidence || [],
          suggestion: tx('vmaxq.vd.sugg.videoRadio'),
          confidence: 'high', reproduced: true, focus: 'radio',
        }
      }
      // P0'-5 无分类时代判（单账号约束下上游常无 Video/Game 专类）：
      // 上游 service 取值域里只有 Video/Web Browse 等 10 类能直接对上页签，
      // 实测多数窗口没有 Video 专类行 —— 此时不说「无法判定」，
      // 改用传输/时延/无线三维代理指标给结论（重传率/首包P90/RSRP P10）。
      // 只有三维全空（1300/32 都无行）才保留 unknown。
      if (radioUnavailable) {
        const trScore = scores.find((s) => s.key === 'transport')?.score ?? null
        const trBad = trScore !== null && trScore < THRESHOLDS.scoreBad
        const laBad = la !== null && la < THRESHOLDS.scoreBad
        if (trBad || laBad) {
          const basis = [
            ...(scores.find((s) => s.key === 'transport')?.evidence || []),
            ...(scores.find((s) => s.key === 'latency')?.evidence || []),
            tx('vmaxq.vd.basis.videoProxyRadio', { why: radioWhy }),
          ]
          return {
            headline: tx('vmaxq.vd.headline.videoProxyBad'),
            basis,
            suggestion: tx('vmaxq.vd.sugg.videoProxyBad'),
            confidence: 'mid', reproduced: true, focus: 'transport',
          }
        }
        // 业务面有行（1300 非空）但无线不可判：代理判正常，不断言弱覆盖
        const hasTraffic = rowsOf(sources, '1300').length > 0
        if (hasTraffic) {
          return {
            headline: tx('vmaxq.vd.headline.videoProxyOk'),
            basis: [
              ...(scores.find((s) => s.key === 'latency')?.evidence || []),
              ...(scores.find((s) => s.key === 'transport')?.evidence || []),
              tx('vmaxq.vd.basis.videoProxyRadio', { why: radioWhy }),
            ],
            suggestion: tx('vmaxq.vd.sugg.videoProxyOk'),
            confidence: 'low', reproduced: false, focus: 'none',
          }
        }
        return {
          headline: tx('vmaxq.vd.headline.videoRadioUnknown', { why: radioWhy }),
          basis: [tx('vmaxq.vd.basis.videoRadioUnknown1'), tx('vmaxq.vd.basis.videoRadioUnknown2', { why: radioWhy })],
          suggestion: tx('vmaxq.vd.sugg.radioUnknown'),
          confidence: 'low', reproduced: false, focus: 'none',
        }
      }
      return {
        headline: tx('vmaxq.vd.headline.videoOk'),
        basis: [...(scores.find((s) => s.key === 'latency')?.evidence || []), ...(scores.find((s) => s.key === 'radio')?.evidence || [])],
        suggestion: tx('vmaxq.vd.sugg.videoOk'),
        confidence: 'mid', reproduced: false, focus: 'none',
      }
    }

    case 'game': {
      // P0'-5 无分类时代判：上游 service 无 GAME 类是常态（实测 1558 条 0 命中），
      // analyzeGame 关键词也未命中时，不直接说「无数据」，改看三维代理指标。
      // 三维全空才保留 gameNone（真无话单，不是分类缺失）。
      if (!game.totalSessions) {
        const trScore = scores.find((s) => s.key === 'transport')?.score ?? null
        const hasAnySignal = la !== null || trScore !== null || ra !== null
        if (hasAnySignal) {
          const badProxy = (la !== null && la < THRESHOLDS.scoreBad)
            || (trScore !== null && trScore < THRESHOLDS.scoreBad)
            || (ra !== null && ra < THRESHOLDS.scoreBad)
          const basis = [
            tx('vmaxq.vd.basis.gameProxyNoHit'),
            ...(scores.find((s) => s.key === 'latency')?.evidence || []),
            ...(scores.find((s) => s.key === 'transport')?.evidence || []),
            ...(ra !== null
              ? (scores.find((s) => s.key === 'radio')?.evidence || [])
              : [tx('vmaxq.vd.basis.videoProxyRadio', { why: radioWhy })]),
          ]
          if (badProxy) {
            return {
              headline: tx('vmaxq.vd.headline.gameProxyBad'),
              basis,
              suggestion: tx('vmaxq.vd.sugg.gameProxyBad'),
              confidence: 'mid', reproduced: true, focus: 'game',
            }
          }
          return {
            headline: tx('vmaxq.vd.headline.gameProxyOk'),
            basis,
            suggestion: tx('vmaxq.vd.sugg.gameProxyOk'),
            confidence: 'low', reproduced: false, focus: 'game',
          }
        }
        return {
          headline: tx('vmaxq.vd.headline.gameNone'),
          basis: game.evidence,
          suggestion: tx('vmaxq.vd.sugg.gameNone'),
          confidence: 'low', reproduced: false, focus: 'game',
        }
      }
      const worst = [...game.hits].sort((a, b) => b.jitter - a.jitter)[0]
      const badGame = worst && (worst.avgRtt > 100 || worst.jitter > 40 || worst.retransRate > THRESHOLDS.retrans)
      if (badGame) {
        return {
          headline: tx('vmaxq.vd.headline.gameBad', { app: worst.app, rtt: worst.avgRtt, jitter: worst.jitter }),
          basis: [...game.evidence, ...(ra !== null && ra < THRESHOLDS.scoreBad ? scores.find((s) => s.key === 'radio')?.evidence || [] : [])],
          suggestion: tx('vmaxq.vd.sugg.gameBad'),
          confidence: 'high', reproduced: true, focus: 'game',
        }
      }
      return {
        headline: tx('vmaxq.vd.headline.gameOk', { n: game.totalSessions }),
        basis: game.evidence,
        suggestion: tx('vmaxq.vd.sugg.gameOk'),
        confidence: 'mid', reproduced: false, focus: 'game',
      }
    }

    case 'slow':
    default: {
      // 「全部投诉」与「上网慢」共用四维链，但上网慢把语音降权
      if (av !== null && av < THRESHOLDS.scoreBad) {
        return {
          headline: tx('vmaxq.vd.headline.availBad'),
          basis: scores.find((s) => s.key === 'availability')?.evidence || [],
          suggestion: tx('vmaxq.vd.sugg.availBad'),
          confidence: 'high', reproduced: true, focus: 'availability',
        }
      }
      if (la !== null && la < THRESHOLDS.scoreBad) {
        return {
          headline: tx('vmaxq.vd.headline.latencyBad'),
          basis: scores.find((s) => s.key === 'latency')?.evidence || [],
          suggestion: tx('vmaxq.vd.sugg.latencyBad'),
          confidence: 'high', reproduced: true, focus: 'latency',
        }
      }
      if (ra !== null && ra < THRESHOLDS.scoreBad) {
        return {
          headline: tx('vmaxq.vd.headline.radioBad'),
          basis: scores.find((s) => s.key === 'radio')?.evidence || [],
          suggestion: tx('vmaxq.vd.sugg.radioBad'),
          confidence: 'mid', reproduced: true, focus: 'radio',
        }
      }
      if (tr !== null && tr < THRESHOLDS.scoreBad) {
        return {
          headline: tx('vmaxq.vd.headline.transportBad'),
          basis: scores.find((s) => s.key === 'transport')?.evidence || [],
          suggestion: tx('vmaxq.vd.sugg.transportBad'),
          confidence: 'mid', reproduced: true, focus: 'transport',
        }
      }
      if (av === null && la === null && radioUnavailable) {
        return {
          headline: tx('vmaxq.vd.headline.allEmpty'),
          basis: [tx('vmaxq.vd.basis.allEmpty1'), tx('vmaxq.vd.basis.allEmpty2')],
          suggestion: tx('vmaxq.vd.sugg.allEmpty'),
          confidence: 'low', reproduced: false, focus: 'none',
        }
      }
      return {
        headline: tx('vmaxq.vd.headline.allOk'),
        basis: scores.filter((s) => s.score !== null).flatMap((s) => s.evidence),
        suggestion: tx('vmaxq.vd.sugg.allOk'),
        confidence: 'mid', reproduced: false, focus: 'none',
      }
    }
  }
}

/* ---------------------------------------------------------------------------
 * 十二、工具：窗口 → 参数串 / 时长
 * ------------------------------------------------------------------------ */

export const toApiTime = (d: Dayjs): string => d.format('YYYY-MM-DD HH:mm:ss')

export const rangeLabel = (start: Dayjs, end: Dayjs): string =>
  `${start.format('YYYY-MM-DD HH:mm')} ~ ${end.format('HH:mm')}`
