/* ============================================================================
 * sseStream.ts —— 极简 SSE 读取器（fetch + ReadableStream，2026-11-07 P3-1）
 * ============================================================================
 *
 * 为什么不用 EventSource：
 *   EventSource 只支持 GET 且**带不上自定义头**，也无法复用本仓库统一的
 *   same-origin Cookie 鉴权之外的错误语义（它拿不到 HTTP 状态码、不会把
 *   非 200 变成异常）。诊断流需要「非 200 / 非 SSE / 中途断开」都能被调用方
 *   捕获并回退到非流式接口，所以用 fetch + ReadableStream 自己解析。
 *
 * 为什么单独成文件：解析器是纯函数（`createSseParser`），可以单测；页面 hook
 * 只关心「收到哪个事件」。协议细节（\r\n、注释行、多行 data、chunk 边界）
 * 全部收在这里，别在业务代码里再写一遍。
 *
 * 协议参考 SSE 规范（HTML Living Standard）：
 *   帧 = 若干 `field: value` 行 + 一个空行；`data:` 多行用 \n 拼；
 *   以 `:` 开头的行是注释；`event:` 缺省为 "message"。
 * ========================================================================== */

export type SseEvent = { event: string; data: unknown }

/** 增量解析器：feed() 喂 chunk，返回本次能凑齐的完整帧（可能 0~n 个）。 */
export function createSseParser() {
  let buffer = ''

  function parseBlock(block: string): SseEvent | null {
    let event = 'message'
    const dataLines: string[] = []
    for (const rawLine of block.split('\n')) {
      const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
      if (!line || line.startsWith(':')) continue   // 空行/注释
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      // 冒号后允许一个空格（SSE 规范）
      let value = colon === -1 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') event = value
      else if (field === 'data') dataLines.push(value)
      // id / retry 本场景用不到，忽略
    }
    if (!dataLines.length) return null
    const text = dataLines.join('\n')
    let data: unknown = text
    try { data = JSON.parse(text) } catch { /* 非 JSON 就原样给字符串 */ }
    return { event, data }
  }

  return {
    feed(chunk: string): SseEvent[] {
      // 统一换行：帧分隔符在 CRLF 下是 `\r\n\r\n`，不归一就一帧都切不出来。
      // 先拼再替换（而不是先替换再拼）：chunk 边界可能正好落在 `\r` 与
      // `\n` 之间，先拼才能把它拼成完整的 CRLF。
      buffer += chunk
      if (buffer.includes('\r')) buffer = buffer.replace(/\r\n/g, '\n')
      const out: SseEvent[] = []
      for (;;) {
        const idx = buffer.indexOf('\n\n')
        if (idx < 0) break
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const ev = parseBlock(block)
        if (ev) out.push(ev)
      }
      return out
    },
    /** 流正常结束时调用；结尾若缺空行（服务端异常中断）也算残帧。 */
    flush(): SseEvent[] {
      const rest = buffer
      buffer = ''
      if (!rest.trim()) return []
      const ev = parseBlock(rest)
      return ev ? [ev] : []
    },
  }
}

export type ReadSseOptions = {
  signal?: AbortSignal
  /** 每个完整帧回调一次；抛异常会终止读取并向上抛给调用方。 */
  onEvent: (ev: SseEvent) => void
  /** 非 200 时的错误文案来源（默认只带状态码）。 */
  fetchImpl?: typeof fetch
}

/**
 * 读取一个 SSE 端点直到流结束。
 *
 * 失败语义（调用方据此决定是否回退到非流式接口）：
 *   - 非 2xx                      → 抛 `SseHttpError`（带 status/detail）
 *   - Content-Type 不是 SSE       → 抛 Error（多半是鉴权跳转/网关错误页）
 *   - 网络中断 / 流未以 done 结束   → 抛 Error（调用方检查是否收到过 done）
 */
export class SseHttpError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`)
    this.name = 'SseHttpError'
    this.status = status
    this.detail = detail
  }
}

export async function readSse(url: string, opts: ReadSseOptions): Promise<void> {
  const doFetch = opts.fetchImpl || fetch
  const res = await doFetch(url, {
    method: 'GET',
    credentials: 'same-origin',
    headers: { Accept: 'text/event-stream' },
    signal: opts.signal,
  })
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = String((body as any)?.detail || '')
    } catch { /* 错误体不一定是 JSON */ }
    throw new SseHttpError(res.status, detail)
  }
  const ct = res.headers.get('content-type') || ''
  if (!ct.includes('text/event-stream')) {
    throw new Error(`诊断流返回了非 SSE 响应（${ct || '无 Content-Type'}）`)
  }
  if (!res.body) throw new Error('诊断流响应没有 body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = createSseParser()
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      for (const ev of parser.feed(decoder.decode(value, { stream: true }))) {
        opts.onEvent(ev)
      }
    }
  } finally {
    // 调用方中途 abort 时确保底层连接释放（已关闭时 cancel 是安全空操作）
    try { await reader.cancel() } catch { /* ignore */ }
  }
  for (const ev of parser.flush()) opts.onEvent(ev)
}
