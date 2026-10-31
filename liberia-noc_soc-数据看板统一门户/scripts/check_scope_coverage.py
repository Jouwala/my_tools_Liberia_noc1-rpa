#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_scope_coverage.py —— 团队门户的**作用域覆盖度对账**
================================================================================
它解决什么问题
--------------
团队门户（/v3/{fo,bo,flm,smc,cxo}_portal/）的可见性由「一张矩阵 + 一组薄钩子」实现。
钩子是**白名单式**的：只有被显式打过钩子的渲染点才会查矩阵。

于是有一个致命缺口：
    **上游 /v3/olbrportal/ 新增一个 section 时，它会默认出现在全部五个团队门户里。**

这与门户的既定语义（「矩阵缺项 = 不显示」）正好相反 —— 是 fail-open。
手工发现这件事要等到「某个团队看到了不该看的内容」被投诉才知道。

本脚本把这件事变成**机器可验证**：
    1. 扫描上游 index.html 的全部内容容器（<section>/<div> 等带 id 的块）；
    2. 扫描上游 olbr.js 的全部渲染函数与它们的写入目标；
    3. 与 v3/team_portal/block-manifest.json 对账；
    4. **上游多出任何一个未登记的区块 → 退出码非零**，强制维护者显式登记。

对账的两个方向
--------------
  · **上游 → 清单**：上游新增了块，清单里没有 → 报错（漏登记 = 会漏给所有团队）
  · **清单 → 上游**：清单里写了块，上游没有了 → 报错（清单过期 = 忘了删钩子）

用法
----
    python scripts/check_scope_coverage.py            # 对账，退出码非零 = 有问题
    python scripts/check_scope_coverage.py --verbose  # 附带列出已登记的块

退出码：0 = 通过；1 = 有问题（打印详情）；2 = 用法/环境错误。

依赖：仅标准库（不读 Excel、不需要 openpyxl）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
# 钩子（.git/hooks/pre-commit -> check-team-scope.mjs）与 CI 里 stdout 是管道，
# Windows 下 Python 默认按 cp1252 编码，打印中文/✓ 会抛 UnicodeEncodeError 让
# 校验误判失败（校验本身是通过的）。见 .qoder/rules/shell_safe.md 第 2 条。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

UPSTREAM_HTML = os.path.join(ROOT, "v3", "olbrportal", "index.html")
UPSTREAM_JS = os.path.join(ROOT, "v3", "olbrportal", "assets", "olbr.js")
TEAM_HTML = os.path.join(ROOT, "v3", "team_portal", "index.html")
TEAM_JS = os.path.join(ROOT, "v3", "team_portal", "assets", "olbr.js")
SCOPE_MAP = os.path.join(ROOT, "v3", "team_portal", "scope-map.json")
BLOCK_MANIFEST = os.path.join(ROOT, "v3", "team_portal", "block-manifest.json")


def read(path: str) -> str:
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
# 扫描上游
# --------------------------------------------------------------------------
# 顶层内容容器：<section ... id="xxx"> / <div ... id="xxx">
# 只取 id，因为渲染点都是按 id 找节点的（$('#band')）。
# header/footer 也在列：顶栏 #mast 与页脚是页面骨架的一部分，
# 对账时要能看到它们，才能判断「清单里登记了但上游改名/删除了」。
_CONTAINER_RE = re.compile(
    r"<(?:section|div|aside|main|nav|header|footer)\b[^>]*\bid=\"([A-Za-z0-9_-]+)\"", re.I
)

# 「纯 UI 壳」容器：它们不是业务内容，不该纳入团队矩阵。
# 判定依据是**用途**而不是 id 名字 —— 名字会变，用途不会。
#  · 浮层 / 弹窗：点击才出现，且内容由被点的对象决定（其可见性已由宿主元素管控）
#  · 登录闸门 / 页脚 / 提示条 / 页面骨架：外壳
#  · 编辑态浮层：只在管理员进入编辑态时出现，与团队可见性无关
SHELL_IDS = {
    # 登录闸门、页面骨架、提示条
    "gate", "main", "foot", "footSrc", "toast",
    # 编辑态浮层与编辑条（只在管理员编辑态出现）
    "editBar", "editPop", "grpPop",
    # QC 下钻弹窗的内部结构（内容由被点的 QC 卡决定 → 已由卡片本身管控）
    "qcMask", "qcScroll",
    # 用户管理弹窗的内部结构（管理员工具 → 由 #umMask 管控）
    "umBody", "umFoot",
}

# 渲染函数里明确写了「不参与矩阵」的（与 block-manifest.json 的 always 段对应）。
# 这里只列**上游**那侧的浮层与外壳，团队门户专有的（complaintSlot）不在其中。

# 「渲染点」= 形如 $('#id') 或 var el = $('#id') 的元素查找。
# 用它找出「哪些容器被 JS 写内容」—— 纯静态容器（页脚等）不算渲染点。
_RENDER_TARGET_RE = re.compile(r"\$\('#([A-Za-z0-9_-]+)'\)")


def scan_upstream_containers() -> dict:
    """返回 {id: 说明}，上游 index.html 里的全部带 id 的块。"""
    html = read(UPSTREAM_HTML)
    found: dict[str, str] = {}
    for m in _CONTAINER_RE.finditer(html):
        bid = m.group(1)
        if bid in found:
            continue
        # 取该标签的完整开始标签，用于取 class
        tag = html[m.start(): html.find(">", m.start()) + 1]
        cls = ""
        cm = re.search(r'class="([^"]*)"', tag)
        if cm:
            cls = cm.group(1)
        found[bid] = cls
    return found


def scan_render_targets(js_text: str) -> set[str]:
    """上游 olbr.js 里被 $('#id') 引用过的元素 id 集合。"""
    return set(_RENDER_TARGET_RE.findall(js_text))


def scan_sections(js_text: str) -> list[str]:
    """上游 olbr.js 里定义的 render* 函数名。"""
    return re.findall(r"function (render[A-Za-z0-9_]*)\s*\(", js_text)


# --------------------------------------------------------------------------
# 读取清单
# --------------------------------------------------------------------------
def load_manifest() -> dict:
    if not os.path.exists(BLOCK_MANIFEST):
        sys.exit("找不到块清单：%s" % BLOCK_MANIFEST)
    with io.open(BLOCK_MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)


def load_scope_domains() -> set[str]:
    if not os.path.exists(SCOPE_MAP):
        sys.exit("找不到 scope-map.json：%s" % SCOPE_MAP)
    with io.open(SCOPE_MAP, "r", encoding="utf-8") as f:
        data = json.load(f)
    doms = {d["key"] for d in data.get("domains", [])}
    for extra in data.get("extra_domains", []) or []:
        doms.add(extra["key"])
    return doms


# --------------------------------------------------------------------------
# 主检查
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="列出已登记的块")
    args = ap.parse_args()

    for path in (UPSTREAM_HTML, UPSTREAM_JS, SCOPE_MAP, BLOCK_MANIFEST):
        if not os.path.exists(path):
            print("找不到文件：%s" % path, file=sys.stderr)
            return 2

    manifest = load_manifest()
    scope_domains = load_scope_domains()
    upstream_js = read(UPSTREAM_JS)
    upstream_html = read(UPSTREAM_HTML)

    containers = scan_upstream_containers()
    render_targets = scan_render_targets(upstream_js)
    sections = scan_sections(upstream_js)

    blocks = manifest.get("blocks", [])
    registered_selectors = {b.get("selector", "") for b in blocks}

    # 清单里声明的容器 id（主块 + 团队专有 + 运行时 + children）
    manifest_ids: set[str] = set()
    for b in blocks:
        for sel in [b.get("selector", "")] + list(b.get("children", []) or []):
            m = re.search(r"#([A-Za-z0-9_-]+)", sel)
            if m:
                manifest_ids.add(m.group(1))

    problems: list[str] = []
    warnings: list[str] = []

    # —— 检查 1：清单里的每个块，其选择器必须在上游存在 ——
    # 团队门户专有的块（complaintSlot）上游没有 —— 由 manifest 的 teamOnly 标记豁免。
    # runtime 的块（qaFab）是运行时 createElement 出来的，上游 HTML 里没有 —— 同样豁免。
    for b in blocks:
        if b.get("teamOnly") or b.get("runtime"):
            continue
        sel = b.get("selector", "")
        # 选择器形如 '#band' 或 '#kpi (Benchmark 行)' —— 取第一个 #id
        m = re.search(r"#([A-Za-z0-9_-]+)", sel)
        if not m:
            problems.append("块 %s 的 selector 解析不出元素 id：%r" % (b.get("id"), sel))
            continue
        bid = m.group(1)
        if bid not in containers:
            problems.append(
                "块清单里的 %s（%s）指向 #%s，但上游 index.html 里已经没有这个容器了 —— "
                "清单过期，请删除该条或改对选择器" % (b.get("id"), b.get("title", ""), bid)
            )

    # —— 检查 2：上游的每个「静态内容容器」必须在清单里 ——
    # 判据：容器出现在上游 index.html，且它**不是**已知的外壳/浮层。
    # ⚠️ 这里**不**要求「被 olbr.js 用 $('#id') 引用过」——
    #   那个条件太宽松：上游新增一个 section 但 JS 还没写它的渲染逻辑时，
    #   它不会出现在 render_targets 里，于是检查放行 —— 可它已经在页面上了
    #   （空壳也是露出来的），仍是 fail-open。
    #   正确做法：**静态出现的容器一律要登记**，登记时写明它受哪个域控制。
    #   「还没接渲染逻辑」不是豁免理由 —— 恰恰相反，那时它最需要被记下来。
    unmapped: list[str] = []
    for bid in sorted(containers):
        if bid in SHELL_IDS:
            continue
        if bid in manifest_ids:
            continue
        unmapped.append(bid)

    if unmapped:
        problems.append(
            "上游有 %d 个内容容器未被块清单登记：%s\n"
            "    ↑ 这些区块**不会**受团队矩阵控制 —— 上游新增内容时会默认出现在全部五个团队门户里。\n"
            "    处理办法：把它们登记进 v3/team_portal/block-manifest.json\n"
            "      ① 归入某个域（受矩阵控制，需在 scope-map.json 里给该域补 items）\n"
            "      ② 或标为 always（不受矩阵控制，必须写明 reason）\n"
            "      ③ 若是纯外壳/浮层，加进 check_scope_coverage.py 的 SHELL_IDS"
            % (len(unmapped), ", ".join("#" + x for x in unmapped))
        )

    # —— 检查 3：清单里的 dom 必须存在于 scope-map.json ——
    for b in blocks:
        dom = b.get("dom")
        if not dom:
            continue
        if dom not in scope_domains:
            problems.append(
                "块 %s 用的域 %r 在 scope-map.json 里不存在 —— 那个域永远匹配不到任何勾选，"
                "等于该区块对所有团队都隐藏（静默失效）" % (b.get("id"), dom)
            )

    # —— 检查 4：always 的块必须写 reason ——
    for b in blocks:
        if b.get("dom") is None and not b.get("always"):
            problems.append(
                "块 %s 既没有 dom 也没有标 always —— 请明确它受不受矩阵控制" % b.get("id")
            )
        if b.get("always") and not (b.get("reason") or "").strip():
            problems.append(
                "块 %s 标了 always 但没写 reason —— 那是给下一个维护者看的理由，不能空着" % b.get("id")
            )

    # —— 检查 5：团队门户的 olbr.js 必须与上游一致（钩子没脱节）——
    if os.path.exists(TEAM_JS):
        team_js = read(TEAM_JS)
        if "window.OLBR_SCOPE" not in team_js:
            problems.append("team_portal/assets/olbr.js 里没有 SCOPE 声明 —— 钩子已脱节")
        # 逐块核对**判据原文片段**：片段缺失 = 该块的过滤钩子不在了。
        # 判据取自 block-manifest.json 的 probe 字段，必须具体到方法调用 ——
        # 只写域名会让两个共用一个域的块互相顶包（kpi 与 kpi-bf 都是 kpi/bf 域）。
        for b in blocks:
            probe = (b.get("probe") or "").strip()
            if not probe:
                if not b.get("always"):
                    problems.append(
                        "块 %s 没有写 probe（判据原文片段）—— 无法核对它的钩子是否还在"
                        % b.get("id")
                    )
                continue
            # probeFile 缺省 = 团队门户的 olbr.js；qa-assistant.js 那个块要单独看
            target_path = os.path.join(ROOT, b.get("probeFile") or "v3/team_portal/assets/olbr.js")
            if not os.path.exists(target_path):
                problems.append(
                    "块 %s 的 probeFile 不存在：%s" % (b.get("id"), b.get("probeFile"))
                )
                continue
            with io.open(target_path, "r", encoding="utf-8") as f:
                haystack = f.read()
            if probe not in haystack:
                problems.append(
                    "块 %s 的判据 %r 在 %s 里找不到 —— 钩子可能已脱节，"
                    "请重跑 scripts/patch_team_portal.py"
                    % (b.get("id"), probe, b.get("probeFile") or "team_portal/assets/olbr.js")
                )
    else:
        problems.append("找不到 team_portal/assets/olbr.js")

    # —— 检查 6：团队门户 index.html 必须含清单里的容器 ——
    if os.path.exists(TEAM_HTML):
        team_html = read(TEAM_HTML)
        for b in blocks:
            if b.get("runtime"):
                continue  # 运行时创建，HTML 里没有
            m = re.search(r"#([A-Za-z0-9_-]+)", b.get("selector", ""))
            if not m:
                continue
            bid = m.group(1)
            if ('id="%s"' % bid) not in team_html:
                problems.append(
                    "块清单里的 %s（#%s）在 team_portal/index.html 里没有对应容器 —— "
                    "团队门户的 index.html 需要同步上游的新增容器" % (b.get("id"), bid)
                )

    # —— 输出 ——
    if args.verbose:
        print("上游内容容器：")
        for bid, cls in sorted(containers.items()):
            mark = "" if bid in SHELL_IDS else ("  ← 矩阵内" if bid in manifest_ids else "  ← ⚠ 未登记")
            print("  #%-14s %s%s" % (bid, cls, mark))
        print("\n上游渲染函数（%d 个）：%s" % (len(sections), ", ".join(sections)))
        print("\n已登记的块（%d 个）：" % len(blocks))
        for b in blocks:
            kind = "always" if b.get("always") else ("dom=%s" % b.get("dom"))
            print("  %-16s %-22s %s" % (b.get("id"), b.get("selector", ""), kind))
        print()

    if problems:
        print("✗ 作用域覆盖度对账未通过：\n", file=sys.stderr)
        for p in problems:
            print("  · " + p, file=sys.stderr)
            print("", file=sys.stderr)
        if warnings:
            print("提示：", file=sys.stderr)
            for w in warnings:
                print("  · " + w, file=sys.stderr)
        return 1

    print("✓ 作用域覆盖度对账通过：上游的每个内容容器都已登记，钩子未脱节。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
