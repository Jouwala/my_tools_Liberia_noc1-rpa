/* ============================================================================
 * sseStream 单测（2026-11-07 P3-1，vitest）
 * ============================================================================
 * sseStream.ts 是诊断渐进渲染的协议层，出错的后果很隐蔽：
 *   - 帧被 chunk 边界劈开却没拼回来 → 少一帧 `done`，前端永远标记不了完成；
 *   - `\r\n` 没兼容 → nginx/网关换行风格一变就整条流解析不出来；
 *   - `data:` 多行没拼 → JSON 被截断，页面静默退回旧接口，用户看不到任何异常。
 * 这些在浏览器里肉眼极难复现，所以按协议逐条钉住。
 *
 * 只测纯逻辑 + 用假 fetch 注入流，不挂 React、不发真实请求。
 * ========================================================================== */

import { describe, expect, it } from 'vitest'

import { createSseParser, readSse, SseHttpError } from '../sseStream'

/** 把若干字符串片段拼成一个「假响应流」（模拟网络分块） */
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
}

const sseResponse = (chunks: string[], headers: Record<string, string> = {}) =>
  new Response(streamOf(chunks), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', ...headers },
  })

describe('createSseParser —— 协议解析', () => {
  it('解析单帧：event + JSON data', () => {
    const p = createSseParser()
    const out = p.feed('event: source\ndata: {"key":"1300"}\n\n')
    expect(out).toEqual([{ event: 'source', data: { key: '1300' } }])
  })

  it('一帧被 chunk 边界劈开也能拼回来', () => {
    const p = createSseParser()
    expect(p.feed('event: source\ndata: {"key":')).toEqual([])
    expect(p.feed('"1100"}\n\n')).toEqual([{ event: 'source', data: { key: '1100' } }])
  })

  it('一个 chunk 里有多帧时全部返回', () => {
    const p = createSseParser()
    const out = p.feed('event: a\ndata: not-json\n\nevent: b\ndata: {"x":2}\n\n')
    expect(out.map((e) => e.event)).toEqual(['a', 'b'])
    // 非 JSON 的 data 原样给字符串（诊断协议是 JSON，但解析器不该抛）
    expect(out.map((e) => e.data)).toEqual(['not-json', { x: 2 }])
  })

  it('兼容 CRLF 换行', () => {
    const p = createSseParser()
    const out = p.feed('event: done\r\ndata: {"imsi":"x"}\r\n\r\n')
    expect(out).toEqual([{ event: 'done', data: { imsi: 'x' } }])
  })

  it('多行 data 用 \\n 拼接后再解析 JSON', () => {
    const p = createSseParser()
    const out = p.feed('event: flow\ndata: {"a":\ndata: 1}\n\n')
    expect(out).toEqual([{ event: 'flow', data: { a: 1 } }])
  })

  it('忽略注释行（: 开头）与无 event 的帧（缺省 message）', () => {
    const p = createSseParser()
    const out = p.feed(': heartbeat\ndata: {"ok":true}\n\n')
    expect(out).toEqual([{ event: 'message', data: { ok: true } }])
  })

  it('只有注释、没有 data 的块不产出帧', () => {
    const p = createSseParser()
    expect(p.feed(': heartbeat\n\n')).toEqual([])
  })

  it('flush 收下末尾没有空行的残帧（服务端异常中断）', () => {
    const p = createSseParser()
    expect(p.feed('event: source\ndata: {"key":"32"}')).toEqual([])
    expect(p.flush()).toEqual([{ event: 'source', data: { key: '32' } }])
  })
})

describe('readSse —— 失败语义（前端据此决定是否回退旧接口）', () => {
  it('正常流按序回调所有帧', async () => {
    const seen: string[] = []
    await readSse('/api/x', {
      fetchImpl: (async () => sseResponse([
        'event: source\ndata: {"key":"1300"}\n\n',
        'event: done\ndata: {"imsi":"1"}\n\n',
      ])) as unknown as typeof fetch,
      onEvent: (ev) => seen.push(ev.event),
    })
    expect(seen).toEqual(['source', 'done'])
  })

  it('非 200 抛 SseHttpError（带服务端 detail）', async () => {
    await expect(readSse('/api/x', {
      fetchImpl: (async () => new Response(
        JSON.stringify({ detail: '会话已满' }), { status: 502 })) as unknown as typeof fetch,
      onEvent: () => undefined,
    })).rejects.toBeInstanceOf(SseHttpError)

    try {
      await readSse('/api/x', {
        fetchImpl: (async () => new Response(
          JSON.stringify({ detail: '会话已满' }), { status: 502 })) as unknown as typeof fetch,
        onEvent: () => undefined,
      })
    } catch (e) {
      expect((e as SseHttpError).status).toBe(502)
      expect((e as SseHttpError).detail).toBe('会话已满')
    }
  })

  it('Content-Type 不是 SSE 时抛错（多半是鉴权跳转/网关错误页）', async () => {
    await expect(readSse('/api/x', {
      fetchImpl: (async () => new Response('<html>login</html>', {
        status: 200, headers: { 'Content-Type': 'text/html' },
      })) as unknown as typeof fetch,
      onEvent: () => undefined,
    })).rejects.toThrow(/非 SSE/)
  })

  it('onEvent 抛错会终止读取并向上抛（调用方据此回退）', async () => {
    await expect(readSse('/api/x', {
      fetchImpl: (async () => sseResponse(['event: error\ndata: {"detail":"boom"}\n\n'])) as unknown as typeof fetch,
      onEvent: () => { throw new Error('boom') },
    })).rejects.toThrow('boom')
  })
})
