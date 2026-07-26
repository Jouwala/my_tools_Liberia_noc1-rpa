// 轻量级前端数据缓存：用于"切换页面再切回"时复用数据，避免重复请求与加载闪烁。
// TTL 较短（默认 30s），既能消除导航带来的重复拉取，又不会长期保留过期数据。

interface CacheEntry {
  ts: number
  data: unknown
}

const store = new Map<string, CacheEntry>()

/**
 * 带 TTL 的 GET 缓存。
 * @param key   缓存键（建议包含查询参数，使不同条件各自缓存）
 * @param fetcher 返回 axios 响应（含 .data）的取数函数
 * @param ttlMs 有效期（毫秒），默认 30000
 */
export function cachedGet<T = any>(
  key: string,
  fetcher: () => Promise<{ data: T }>,
  ttlMs = 30000,
): Promise<{ data: T }> {
  const hit = store.get(key)
  if (hit && Date.now() - hit.ts < ttlMs) {
    return Promise.resolve({ data: hit.data as T })
  }
  return fetcher().then((res) => {
    store.set(key, { ts: Date.now(), data: res.data })
    return res
  })
}

/** 失效缓存：传 prefix 仅清该前缀的键；不传则清空全部。 */
export function invalidateCache(prefix?: string) {
  if (!prefix) {
    store.clear()
    return
  }
  for (const k of Array.from(store.keys())) {
    if (k.startsWith(prefix)) store.delete(k)
  }
}
