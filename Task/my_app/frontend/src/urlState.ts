/* ============================================================================
 * urlState —— 让查询条件活到「组件卸载」之后
 * ============================================================================
 *
 * 为什么需要：
 *   页签保活只解决同页内切换。浏览器后退/前进、刷新、把链接发给同事，
 *   都会重新挂载组件 —— 号码、时间窗、当前视图这些条件必须落在 URL 里
 *   才找得回来（AGENTS.md：URL 是页面状态的唯一真相源）。
 *
 * 只存**条件**，不存**结果**：
 *   结果是上游快照，恢复旧结果而不加提示会让人误以为刚查的。回来后再点一次
 *   「查询」是几秒钟的事，看错数据是排障事故。
 *
 * 两条纪律：
 *   - 一律 replaceState：改个时间窗不该多一条历史记录，否则后退键要点很多次；
 *   - 每次写入都重新读 location，父页与两个面板各自只管自己那几个 key，
 *     互不覆盖（合并写会互相踩，因为三处 state 更新时机不同）。
 * ========================================================================== */

/** 读一个查询参数；空串按不存在处理 */
export function readParam(key: string): string {
  if (typeof window === 'undefined') return ''
  return new URLSearchParams(window.location.search).get(key)?.trim() || ''
}

/**
 * 批量合并写进地址栏（不产生历史记录）。
 * 值为空则删除该参数；与当前值相同则跳过，避免无意义的 replaceState。
 */
export function writeParams(patch: Record<string, string | null | undefined>): void {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  let changed = false
  Object.entries(patch).forEach(([key, raw]) => {
    const val = (raw ?? '').trim()
    if (!val) {
      if (url.searchParams.has(key)) {
        url.searchParams.delete(key)
        changed = true
      }
      return
    }
    if (url.searchParams.get(key) === val) return
    url.searchParams.set(key, val)
    changed = true
  })
  if (!changed) return
  // 保留 history.state：App 的导航在 state 里存了 page，覆盖成 null 会打乱后退恢复
  window.history.replaceState(window.history.state, '', url)
}
