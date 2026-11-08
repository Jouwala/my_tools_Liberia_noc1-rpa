/* ============================================================================
 * vmaxVerdictSnapshot —— 覆写记录随附的「诊断快照」（P3-3，可审计）
 * ============================================================================
 *
 * 【为什么需要快照】
 *   `verdict`（结论 / 四维分 / 证据）是**纯前端**按 `pages/vmaxDiagnosisRules.ts`
 *   的规则算出来的，接口不下发分数与结论。所以覆写记录里的 `verdict_auto`
 *   只是「客户端声明的一句话」，事后从库里无法复现「当时凭什么这么判」——
 *   审计视角不可复现。P3-3 的做法：提交覆写时把**当时的输入/输出状态**
 *   随记录存一份 JSON（后端 `vmax_diagnosis_override.verdict_snapshot`），
 *   页面上可展开查看、导出里带一行摘要。
 *
 * 【快照里放什么、不放什么】
 *   放：结论（headline/basis/suggestion/置信度/是否复现/触发维度）、四维分与
 *       该维口径数字、语音/OTT/游戏**汇总指标**、各数据源 ok/truncated/error/条数、
 *       时间窗、投诉类型、IMSI（若接口有）。
 *   不放：**原始话单行**（体积大且含号码明文）、号码明文（号码只在表里的
 *        `msisdn_mask`）、渲染后的中文句子（存 i18n key + 参数，切语言不漂移）。
 *   因此快照体积极小（典型 3~6KB，上限 20KB 由后端校验）。
 *
 * 【版本号】
 *   `version` 是读取端的兼容锚点：以后字段有增删时递增，老快照按老版本读，
 *   不在读取端猜缺字段（`parseVerdictSnapshot` 对不认识的结构返回 null）。
 *
 * 【不动口径】
 *   本模块只做「打包/解包」，**不重新计算任何指标** —— 所有值都从既有状态取，
 *   否则会出现「快照里的分与页面上的分不一致」这种新的不可审计。
 * ========================================================================== */

import { renderI18n } from '../renderI18n'
import type {
  ComplaintKey, DimensionScore, GameResult, I18nText, OttResult,
  SourceResult, Verdict, VoiceResult,
} from '../pages/vmaxDiagnosisRules'

/** 快照结构版本（读取端按它兼容；字段增删时递增） */
export const SNAPSHOT_VERSION = 1 as const

/** 游戏命中明细最多存多少条：只用于审计「当时判成了哪些游戏」，超出的截掉防撑大 */
const MAX_GAME_HITS = 10

/** 单个数据源状态（**只存条数**，不存 rows —— 原始行体积大且含敏感值） */
export type SnapshotSource = {
  key: string
  label: string
  label_key: string
  ok: boolean
  /** rows 的条数（不是 rows 本身） */
  rows: number
  truncated: boolean
  error: string
}

export type SnapshotScore = {
  key: string
  score: number | null
  sub: I18nText | null
  detail: Record<string, number | string>
  evidence: I18nText[]
}

/** 语音汇总指标（明细 steps 不入快照：多且与结论无关） */
export type SnapshotVoice = {
  mode: VoiceResult['mode']
  sgsCount: number
  csfbTrigger: number
  esrCount: number
  pagingCount: number
  badCount: number
  successRate: number | null
  fallbackMs: number | null
  qci1: number
}

/** OTT 汇总指标（sessions 明细不入快照） */
export type SnapshotOtt = {
  totalSessions: number
  totalDurationS: number
  avgDlRtt: number
  jitter: number
  retransRate: number
  baselineRtt: number
}

export type SnapshotGame = {
  totalSessions: number
  hits: Array<{
    app: string
    tier: string
    records: number
    avgRtt: number
    jitter: number
    retransRate: number
  }>
}

export type VerdictSnapshot = {
  version: number
  /** 客户端生成时间（ISO 字符串；服务端另有 created_at/updated_at） */
  generated_at: string
  complaint: ComplaintKey
  window: { start: string; end: string }
  /** MSISDN→IMSI 映射结果；无则 null。号码明文**不**入快照 */
  imsi: string | null
  verdict: {
    headline: I18nText
    basis: I18nText[]
    suggestion: I18nText
    confidence: Verdict['confidence']
    reproduced: boolean
    focus: Verdict['focus']
  } | null
  scores: SnapshotScore[]
  sources: SnapshotSource[]
  voice: SnapshotVoice | null
  ott: SnapshotOtt | null
  game: SnapshotGame | null
}

export type SnapshotInput = {
  complaint: ComplaintKey
  window: { start: string; end: string }
  verdict: Verdict | null
  scores: DimensionScore[]
  sources: SourceResult[]
  voice: VoiceResult | null
  ott: OttResult | null
  game: GameResult | null
  imsi?: string | null
}

/**
 * 从既有页面状态打包快照。**纯函数，不重算口径**（值全部原样取自入参）。
 *
 * @param input 当前 hook 里的 verdict / scores / voice / ott / game / sources 等
 */
export function buildVerdictSnapshot(input: SnapshotInput): VerdictSnapshot {
  const { complaint, window, verdict, scores, sources, voice, ott, game, imsi } = input
  return {
    version: SNAPSHOT_VERSION,
    generated_at: new Date().toISOString(),
    complaint,
    window: { start: window.start, end: window.end },
    imsi: imsi || null,
    verdict: verdict
      ? {
        headline: verdict.headline,
        basis: verdict.basis,
        suggestion: verdict.suggestion,
        confidence: verdict.confidence,
        reproduced: verdict.reproduced,
        focus: verdict.focus,
      }
      : null,
    scores: scores.map((s) => ({
      key: s.key,
      score: s.score,
      sub: s.sub,
      detail: s.detail,
      evidence: s.evidence,
    })),
    sources: sources.map((s) => ({
      key: s.key,
      label: s.label,
      label_key: s.label_key || '',
      ok: s.ok,
      rows: s.rows?.length || 0,
      truncated: !!s.truncated,
      error: s.error || '',
    })),
    voice: voice
      ? {
        mode: voice.mode,
        sgsCount: voice.sgsCount,
        csfbTrigger: voice.csfbTrigger,
        esrCount: voice.esrCount,
        pagingCount: voice.pagingCount,
        badCount: voice.badCount,
        successRate: voice.successRate,
        fallbackMs: voice.fallbackMs,
        qci1: voice.qci1,
      }
      : null,
    ott: ott
      ? {
        totalSessions: ott.totalSessions,
        totalDurationS: ott.totalDurationS,
        avgDlRtt: ott.avgDlRtt,
        jitter: ott.jitter,
        retransRate: ott.retransRate,
        baselineRtt: ott.baselineRtt,
      }
      : null,
    game: game
      ? {
        totalSessions: game.totalSessions,
        hits: game.hits.slice(0, MAX_GAME_HITS).map((h) => ({
          app: h.app,
          tier: h.tier,
          records: h.records,
          avgRtt: h.avgRtt,
          jitter: h.jitter,
          retransRate: h.retransRate,
        })),
      }
      : null,
  }
}

/** 序列化成后端 `verdict_snapshot` 字段要的字符串（JSON） */
export function serializeVerdictSnapshot(snap: VerdictSnapshot): string {
  return JSON.stringify(snap)
}

/**
 * 解析后端回读的 `verdict_snapshot`（可能为 null / 老行 / 未来版本 / 坏数据）。
 * 解析失败一律返回 null —— 快照只用于「查看审计依据」，不该让页面报错。
 *
 * 结构校验是**必要**的：后端只校验「是 JSON 对象」（不绑定字段结构），
 * 万一库里存了版本号对但字段缺失的数据，宽松解析会让覆写弹窗在渲染
 * `snap.verdict.basis.length` 时直接抛 TypeError、整块弹窗白屏。
 */
export function parseVerdictSnapshot(raw?: string | null): VerdictSnapshot | null {
  if (!raw) return null
  try {
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object') return null
    // 只认结构版本号一致的老/当前快照；未来版本字段含义可能变，宁可不显示也不误读
    if (obj.version !== SNAPSHOT_VERSION) return null
    // 必填骨架（弹窗渲染直接用到，缺了会崩）
    if (typeof obj.generated_at !== 'string') return null
    if (typeof obj.complaint !== 'string') return null
    if (!obj.window || typeof obj.window.start !== 'string' || typeof obj.window.end !== 'string') {
      return null
    }
    if (!Array.isArray(obj.scores) || !Array.isArray(obj.sources)) return null
    if (obj.verdict !== null && obj.verdict !== undefined) {
      if (typeof obj.verdict !== 'object') return null
      if (!Array.isArray(obj.verdict.basis)) return null
      if (typeof obj.verdict.headline?.key !== 'string') return null
      if (typeof obj.verdict.suggestion?.key !== 'string') return null
    }
    return obj as VerdictSnapshot
  } catch {
    return null
  }
}

/** 快照摘要（导出 Excel 的一行）：全部取快照既有值，不重算 */
export type SnapshotTFn = (key: string, params?: Record<string, string | number>) => string

export function snapshotSummary(snap: VerdictSnapshot | null, t: SnapshotTFn): string {
  if (!snap) return ''
  const score = (k: string): string => {
    const s = snap.scores.find((x) => x.key === k)
    return s && s.score !== null ? String(s.score) : '—'
  }
  const srcText = snap.sources.map((s) => `${s.key}:${s.rows}${s.ok ? '' : '!'}`).join(' ')
  return t('vmaxq.override.snapshotSummary', {
    verdict: snap.verdict ? renderI18n(t, snap.verdict.headline) : '—',
    conf: snap.verdict ? t(`vmaxq.diag.confidence.${snap.verdict.confidence}`) : '—',
    repro: snap.verdict
      ? t(snap.verdict.reproduced ? 'vmaxq.diag.reproduced' : 'vmaxq.diag.notReproduced')
      : '—',
    scores: `${score('availability')}/${score('latency')}/${score('transport')}/${score('radio')}`,
    sources: srcText || '—',
  })
}
