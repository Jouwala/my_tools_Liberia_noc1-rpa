/* urlState 的读写语义验证（Node 24 直接跑 .ts，靠类型擦除）
 *
 * 为什么要有：
 *   frontend/src/urlState.ts 是「查询条件活过组件卸载」的唯一入口，
 *   它只该 replaceState（不能污染后退栈）、必须保留 history.state（App 的
 *   ?page= 导航存在里面）、并且不能动 ?page= / ?embed= / ?t= 这些系统参数。
 *   这些约束在浏览器里肉眼看不出来，改坏了只会表现为「后退键要按很多次」
 *   或「导航后页面错乱」，很难归因，所以固化成断言。
 *
 * 运行：
 *   cd D:/01_RPA/Task/my_app
 *   node tests/check_urlstate.mjs
 */
const store = { state: { page: 'vmax_user_query' } }
let href = 'http://127.0.0.1:7090/myapp/?page=vmax_user_query&embed=1'
let replaceCalls = 0

globalThis.window = {
    // 真实浏览器里 location.search 与 href 同源；这里按 href 派生，避免测试脚本失真
    get location() { return { href, search: new URL(href).search } },
    history: {
        get state() { return store.state },
        replaceState(s, _t, url) { replaceCalls += 1; store.state = s; href = String(url) },
    },
}

const { readParam, writeParams } = await import('../frontend/src/urlState.ts')

const fails = []
const check = (name, cond, extra = '') => {
    console.log(`${cond ? '  PASS' : '  FAIL'}  ${name}${cond ? '' : '  -> ' + extra}`)
    if (!cond) fails.push(name)
}

check('读已有参数', readParam('page') === 'vmax_user_query')
check('读不存在的参数得空串', readParam('nope') === '')

writeParams({ msisdn: '231773777115', vmaxView: 'records' })
check('写入后能读回', readParam('msisdn') === '231773777115' && readParam('vmaxView') === 'records')
check('系统参数未被动过', href.includes('page=vmax_user_query') && href.includes('embed=1'))
check('history.state 保留', store.state && store.state.page === 'vmax_user_query')
check('replaceState 被调用一次', replaceCalls === 1, `实际 ${replaceCalls}`)

writeParams({ msisdn: '231773777115' })
check('同值不重复写（不刷历史）', replaceCalls === 1, `实际 ${replaceCalls}`)

writeParams({ vmaxView: '' })
check('空值删除参数', readParam('vmaxView') === '' && !href.includes('vmaxView='))

writeParams({ msisdn: '  231000000000  ' })
check('两端空白被裁剪', readParam('msisdn') === '231000000000')

console.log('')
if (fails.length) { console.log('FAILED: ' + fails.length); process.exit(1) }
console.log('ALL PASS')
