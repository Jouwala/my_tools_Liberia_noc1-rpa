# -*- coding: utf-8 -*-
"""VMAX 用户查询页的视图保活 + 条件恢复守卫（纯离线，只看源码文本）。

为什么要有这个文件：
    「概览 / 信令详单 / XDR 记录」三个视图最初用 `{view === 'xdr' && <Panel/>}`
    条件渲染，切回概览时面板被 React 卸载，面板里的查询结果、已选表、时间窗、
    分页（全在组件自己的 state 里）一并销毁 —— 用户实测「查完 XDR 回概览看一眼，
    再回来数据就没了」。

    修法是访问过即挂载、切走只 `display:none`。这类「看起来能省一次渲染」的
    改法很容易被人手改回条件渲染，且改回去之后单测/构建都不会红，只能等用户
    再报一次。所以把约束固化成文本断言：谁把条件渲染写回来，这里立刻失败。

    第二部分守的是「URL 恢复」：组件 state 只活到卸载为止，刷新、浏览器前进
    后退、把链接发给同事都会重新挂载，号码/窗口/视角因此必须落在 URL 里
    （`src/urlState.ts`）。用 pushState 会污染后退栈，所以只允许 replaceState。

运行：
    cd D:/01_RPA/Task/my_app
    python tests/test_vmax_user_query_keepalive.py
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
PAGE = SRC / "pages" / "VmaxUserQuery.tsx"
MERGE = SRC / "components" / "VmaxXdrPanel.tsx"
TABLE = SRC / "components" / "VmaxXdrRecordsPanel.tsx"
URLSTATE = SRC / "urlState.ts"
# 2026-10-30 统一时间窗后，窗口的唯一真相源搬到了 vmaxWindow.ts
# （三个页签共用一份 RangePicker，URL 参数 vqStart/vqEnd 也由它读写）。
# 父页与两个子面板都不再各自读自己的 mxStart/rtStart。
WINDOW = SRC / "pages" / "vmaxWindow.ts"

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s%s" % (name, ("  -> " + detail) if detail else ""))
        FAILS.append(name)


def main():
    src = PAGE.read_text(encoding="utf-8")

    # 1) 重面板都由 mounted 门控（首次点开才挂载，避免概览首屏多打请求）
    for key in ("flow", "xdr", "records"):
        check("mounted.%s 门控存在" % key, ("{mounted.%s && (" % key) in src,
              "缺少 `{mounted.%s && (`，面板可能又变回条件渲染" % key)

    # 2) 切走用 display 隐藏，而不是不渲染
    check("flow 视图 display 切换",
          re.search(r"display:\s*view === 'flow' \? 'flex' : 'none'", src) is not None)
    check("xdr 视图 display 切换",
          re.search(r"display:\s*view === 'xdr' \? 'block' : 'none'", src) is not None)
    check("records 视图 display 切换",
          re.search(r"display:\s*view === 'records' \? 'block' : 'none'", src) is not None)
    check("概览视图 display 切换",
          re.search(r"display:\s*view === 'overview' \? 'flex' : 'none'", src) is not None)

    # 3) 反例：不再有直接按 view 短路渲染面板的写法
    for key, comp in (("xdr", "VmaxXdrPanel"), ("records", "VmaxXdrRecordsPanel")):
        bad = re.search(
            r"\{view === '%s' &&\s*\(?\s*(//[^\n]*\n\s*)*<%s" % (key, comp), src)
        check("%s 未被条件渲染直接卸载" % comp, bad is None,
              "出现 `{view === '%s' && < %s ...>`，切页签会丢数据" % (key, comp))

    # 4) 视图切换必须走 switchView（它负责置 mounted 标记）
    check("分类流量页签已独立（顶层 flow 视图）",
          "'flow'" in src and "VmaxFlowCategoryTabs" in src,
          "VmaxUserQuery 里没有 flow 视图，分类页签可能又被塞回概览")
    check("概览不再嵌流量卡（VmaxCcaCards 不收 flow）",
          "flow={result.flow}" not in src,
          "概览还在拼 flow={result.flow}，分类流量没真正独立")
    # 4) 视图切换必须走 switchView（它负责置 mounted 标记）
    check("Segmented 走 switchView", "onChange={(v) => switchView(" in src,
          "切回 setView 会导致面板不挂载 / 挂载后不再保活")

    # ---- URL 恢复 ----
    check("urlState.ts 存在", URLSTATE.exists())
    if URLSTATE.exists():
        u = URLSTATE.read_text(encoding="utf-8")
        check("urlState 只用 replaceState（不污染后退栈）",
              "replaceState" in u and "pushState" not in u)
        check("urlState 写入保留 history.state",
              "window.history.state" in u,
              "覆盖 state 会打乱 App 的 ?page= 后退恢复")

    check("父页从 URL 读号码", "readParam('msisdn')" in src)
    check("父页从 URL 读视角", "readParam('vmaxView')" in src)
    # 2026-10-31 起时间窗滚动：首屏永远是「当时」的最近 3 小时，
    # URL 里不再记窗口（旧链接残留的 vqStart/vqEnd 忽略并清掉）。
    win = WINDOW.read_text(encoding="utf-8")
    check("首屏窗口滚动（不再重放 URL 里旧窗口）",
          "readParam('vqStart')" not in win and "readParam('vqEnd')" not in win,
          "vmaxWindow.ts 还在读 vqStart/vqEnd，旧链接会落回固定时间")
    check("首屏窗口走 defaultRange（最近 3 小时）",
          "return defaultRange()" in win)
    check("父页引用统一时间窗模块",
          "from './vmaxWindow'" in src or 'from "./vmaxWindow"' in src)
    check("父页查询时写号码（不是每次按键写）",
          re.search(r"writeParams\(\{\s*msisdn: q", src) is not None)
    check("父页首屏自动重放（URL 带号码才跑一次）", "bootRef" in src)

    merge = MERGE.read_text(encoding="utf-8")
    check("合并表面板读 mxSvc", "readParam('mxSvc')" in merge)
    # 窗口不再由面板自己读 URL，而是从页面级 context 取（三个页签同一份）
    check("合并表面板从 context 取窗口", "useVmaxWindow()" in merge)
    check("合并表面板查询后写回条件", "mxSvc: data.service_type" in merge)

    table = TABLE.read_text(encoding="utf-8")
    check("分表面板读 rtSvc/rtTable",
          "readParam('rtSvc')" in table and "readParam('rtTable')" in table)
    check("分表面板不再自己读窗口 URL（统一由 vmaxWindow.ts 管）",
          "readParam('rtStart')" not in table and "readParam('rtEnd')" not in table)
    check("分表面板从 context 取窗口", "useVmaxWindow()" in table)
    check("分表面板查询后写回条件", "rtTable: data.table" in table)
    check("分表面板换类型时保留仍在清单里的表",
          re.search(r"setTable\(\(cur\) =>", table) is not None,
          "直接 setTable(preferred) 会把 URL 恢复出来的表名冲掉")

    print("")
    if FAILS:
        print("FAILED: %d 项" % len(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
