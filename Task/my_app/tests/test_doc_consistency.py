"""文档一致性守卫：手册/帮助文档里的「数字类事实」必须与代码真相源一致。

为什么需要它（2026-10-31 新增）：
    手册里的任务数、页面数、分组数、worker 组数、路由数、文件体积这类**事实**
    一直在悄悄过期。实测一次审计就抓到 9 处：

      - `01-overview.md` 说「41 个定时任务 / 23 个功能页」→ 实际 80 个任务 / 54 个页面
      - `04-task-system.md` 分组表 n=17 / v=3 → 实际 18 / 4（漏登记 soc_trend_sync）
      - `04-task-system.md` 全量任务清单表漏了 `soc_trend_sync` 整行
      - `13-operations.md` 说「worker × 5 组」→ 实际 10 组（u/n/s/w/v/m/c/x/g/p）
      - `13-operations.md` 说「队列保留 3 天」→ 实际默认 7 天
      - `90-appendix.md` 说「25 处 include_router」→ 实际 75 处
      - `AGENTS.md` 里 task_registry.py 标 68KB → 实际 ≈109KB

    这些错**不影响功能**，所以没有任何运行时症状能暴露它们 —— 只有人工比对才发现。
    靠"提醒 agent 记得改文档"治不住（这正是本文件存在的原因），
    必须让**跑测试就失败**。

与 `test_worker_group_coverage.py` 的分工：
    那个守「任务 ↔ 分组 ↔ 启动脚本 ↔ 前端帮助」四者一致（代码与代码之间）；
    本文件守「**文档里写的数字** ↔ 代码真相源」一致（文档与代码之间）。

不用 pytest 断言框架（同 `test_worker_group_coverage.py` 的理由：本机 venv 没装 pytest，
跑不起来的守卫等于没有）。纯 assert + __main__ 计数器。

真相源取法见 `tests/doc_truth.py`：那里用 **AST 静态解析源码**取「任务数 / 分组表 /
保留天数 / 路由数」，**不 import 业务模块** —— 因此本守卫零第三方依赖、
跨平台（Windows / Linux / macOS 都能跑），可以直接放进 CI。
（早前版本直接 `from backend.task_registry import TASK_SPECS`，
在 Linux 上会因 `ctypes.wintypes` 直接失败，且要求整套后端运行环境。）

运行（任何有 Python 3.10+ 的机器均可）：
    cd D:/01_RPA/Task/my_app
    python tests/test_doc_consistency.py
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MANUAL = ROOT / "docs" / "manual"


# ────────────────────────── 取代码真相源 ──────────────────────────

def _task_specs():
    """已注册任务 id 列表（AST 静态解析 task_registry.py 的 TASK_SPECS）。"""
    from doc_truth import task_ids
    return task_ids()


def _group_task_map():
    """worker 分组 -> 任务 id 列表（AST 静态解析 worker_watchdog.py）。"""
    from doc_truth import group_task_map
    return group_task_map()


# ────────────────────────── 文档解析小工具 ──────────────────────────

def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _task_list_table_rows() -> set:
    r"""从 04-task-system.md 的「全量任务清单」表里取出所有 task_id。

    表从 `## 全量任务清单` 到下一个 `### ` 小节为止；
    行格式 `| `task_id` | 名称 | cron | 组 |`。
    """
    doc = _read("docs/manual/04-task-system.md")
    start = doc.index("## 全量任务清单")
    rest = doc[start + 1:]
    end = rest.find("\n### ")
    seg = rest if end < 0 else rest[:end]
    return set(re.findall(r"^\| `([a-z0-9_]+)` \|", seg, re.M))


def _group_table_counts() -> dict:
    r"""从 04-task-system.md 的分组表读出 `| `x` | N | ...` 的 N。"""
    doc = _read("docs/manual/04-task-system.md")
    return {g: int(n) for g, n in re.findall(r"^\| `([a-z])` \| (\d+) \|", doc, re.M)}


def _help_page_keys() -> tuple:
    """从 helpContent.ts 解析 PAGE_LIST 与 PAGE_DOCS 的键集合。

    PAGE_DOCS 里的大小写混杂（cxoDashboard / mwRealTime / ap_center），
    正则必须带 A-Za-z 字符类 —— 只写 `[a-z0-9_]` 会漏掉 5 个 iframe 页，
    得出「这些页没写文档」的假结论（本守卫第一版就踩了这个坑）。
    """
    src = _read("frontend/src/pages/helpContent.ts")
    pl_start = src.index("export const PAGE_LIST")
    pl = src[pl_start:src.index("\n]", pl_start)]
    pages = set(re.findall(r"key:\s*'([A-Za-z0-9_]+)'", pl))

    pd = src[src.index("export const PAGE_DOCS"):]
    zh = pd[pd.index("zh: {"):pd.index("en: {")]
    en = pd[pd.index("en: {"):]
    keyre = r"^ {4}([A-Za-z0-9_]+):\s*\{"
    return pages, set(re.findall(keyre, zh, re.M)), set(re.findall(keyre, en, re.M))


def _app_page_meta_keys() -> set:
    """从 App.tsx 的 PAGE_META 取页面 key 集合（菜单真相源）。"""
    src = _read("frontend/src/App.tsx")
    i = src.index("const PAGE_META")
    seg = src[i:src.index("\n}", i)]
    return set(re.findall(r"^ {2}([a-zA-Z0-9_]+):\s*\{", seg, re.M))


def _file_size_kb(rel: str) -> int:
    return round(os.path.getsize(ROOT / rel) / 1024)


def _doc_mentions(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


# ────────────────────────── 各条检查 ──────────────────────────

def test_task_count_in_docs_matches_registry():
    """文档里写的「N 个定时任务」必须等于 TASK_SPECS 的实际条数。

    过去散落在 5 处（01-overview / 04-task-system 首句 / manual README /
    user-guide / project-overview），一处漏改就留下矛盾数字。
    这里逐个文件核对，并给出具体位置。
    """
    n = len(_task_specs())
    doc = _read("docs/manual/01-overview.md")
    assert re.search(rf"\*\*{n} 个定时任务\*\*", doc), (
        f"docs/manual/01-overview.md 的任务数不是 {n}（与 TASK_SPECS 不符）"
    )

    doc = _read("docs/manual/04-task-system.md")
    assert re.search(rf"{n} 个定时任务", doc), (
        f"docs/manual/04-task-system.md 首句的任务数不是 {n}"
    )

    for rel in ("docs/manual/README.md", "user-guide.md", "project-overview.md"):
        doc = _read(rel)
        assert re.search(rf"{n} 个任务", doc), (
            f"{rel} 里没有写「{n} 个任务」（任务数与 TASK_SPECS 不符）"
        )


def test_task_list_table_covers_every_registered_task():
    """04-task-system.md 的「全量任务清单」表必须列出 TASK_SPECS 里的每个 task_id。

    漏一行 = 新任务上线但手册没有它，运维查手册根本查不到这个任务。
    （2026-10-31 审计就抓到 `soc_trend_sync` 漏登记。）
    """
    specs = set(_task_specs())
    rows = _task_list_table_rows()
    missing = sorted(specs - rows)
    assert not missing, f"04-task-system.md 任务清单表漏了这些已注册任务: {missing}"
    ghost = sorted(rows - specs)
    assert not ghost, f"04-task-system.md 任务清单表里有已下线的 task_id: {ghost}"


def test_group_counts_in_doc_match_code():
    """04-task-system.md 分组表的每组任务数必须等于 GROUP_TASK_MAP 的实际条数。

    组数错 = 读者按文档估工作量会估错；且新增组时最容易漏改这一处。
    """
    doc_counts = _group_table_counts()
    code = _group_task_map()
    bad = {
        g: (doc_counts.get(g), len(tasks))
        for g, tasks in code.items()
        if doc_counts.get(g) != len(tasks)
    }
    assert not bad, (
        f"04-task-system.md 分组表的任务数与代码不符（文档, 代码）: {bad}"
    )
    missing = sorted(set(code) - set(doc_counts))
    assert not missing, f"04-task-system.md 分组表缺这些组: {missing}"


def test_worker_group_count_in_docs():
    """手册里「worker × N 组」必须等于实际组数（2026-10-31 实测文档写 5 组、实际 10 组）。"""
    n = len(_group_task_map())
    doc = _read("docs/manual/13-operations.md")
    assert re.search(rf"worker × {n} 组", doc), (
        f"13-operations.md 的「worker × N 组」不是 {n}（与 GROUP_TASK_MAP 的组数不符）"
    )
    doc = _read("docs/manual/04-task-system.md")
    assert re.search(rf"托管 \*\*{n} 组\*\* worker", doc), (
        f"04-task-system.md 的看门狗托管组数不是 {n}"
    )
    doc = _read("docs/manual/10-quickstart.md")
    assert re.search(rf"当前 {n} 组", doc), (
        f"10-quickstart.md 的当前 worker 组数不是 {n}"
    )


def test_queue_retention_days_matches_code():
    """手册写的「队列保留 N 天」必须等于 TASK_LOG_RETENTION_DAYS 的默认值。

    代码默认值 7 天（2026-09-11 由 3 天放宽），但 13-operations.md 仍写 3 天。
    """
    from doc_truth import task_retention_days
    days = task_retention_days()
    doc = _read("docs/manual/13-operations.md")
    assert re.search(rf"系统自动保留 {days} 天", doc), (
        f"13-operations.md 写的队列保留天数不是 {days}（与代码默认值不符）"
    )
    doc = _read("docs/manual/04-task-system.md")
    assert re.search(rf"保留 \*\*{days} 天\*\*", doc), (
        f"04-task-system.md 写的队列保留天数不是 {days}"
    )


def test_router_count_in_appendix_matches_code():
    """90-appendix.md 写的 include_router 处数必须等于 main.py 实际值。"""
    from doc_truth import router_count
    n = router_count()
    doc = _read("docs/manual/90-appendix.md")
    assert re.search(rf"实测 {n} 处 `include_router`", doc), (
        f"90-appendix.md 写的 include_router 处数不是 {n}"
    )


def test_iframe_page_count_in_feature_guide():
    """11-feature-guide.md 说的 iframe 页数量必须等于 helpContent.ts PAGE_LIST 里 iframe:true 的数量。

    少写一个 = 有个 iframe 页在手册里没标，读者会以为改 React 代码能生效。
    """
    src = _read("frontend/src/pages/helpContent.ts")
    pl_start = src.index("export const PAGE_LIST")
    pl = src[pl_start:src.index("\n]", pl_start)]
    n = len(re.findall(r"key:\s*'[A-Za-z0-9_]+',\s*iframe:\s*true", pl))
    doc = _read("docs/manual/11-feature-guide.md")
    assert re.search(rf"有 \*\*{n} 个页面是 iframe 壳\*\*", doc), (
        f"11-feature-guide.md 写的 iframe 页数不是 {n}（与 PAGE_LIST 不符）"
    )

def test_help_page_docs_cover_page_list():
    """helpContent.ts 里 PAGE_LIST 的每个页面都要有中英双份 PAGE_DOCS。

    只加 PAGE_DOCS 不够（页面清单由 PAGE_LIST 驱动）；
    只加 PAGE_LIST 不加 PAGE_DOCS 则是帮助页上有页面名、点进去空白。
    """
    pages, zh, en = _help_page_keys()
    miss_zh = sorted(pages - zh)
    miss_en = sorted(pages - en)
    assert not miss_zh, f"PAGE_DOCS.zh 缺这些页面: {miss_zh}"
    assert not miss_en, f"PAGE_DOCS.en 缺这些页面: {miss_en}"


def test_help_page_list_matches_app_page_meta():
    """helpContent.ts 的 PAGE_LIST 与 App.tsx 的 PAGE_META 应当一致。

    允许的差异只有两类（都是刻意设计，不算漏）：
      - PAGE_META 独有：`help`（帮助页自身，不该在帮助清单里列自己）；
      - PAGE_LIST 独有：`alarmManagement` / `cxoDashboard` / `mwRealTime` /
        `mwUmeTopology` / `portalLogin`（iframe 壳与门户页，在菜单里以
        其它形态呈现，但仍需在帮助页有说明）。
    除这两类外的差异 = 一边加了页面另一边忘了加。
    """
    ALLOWED_META_ONLY = {"help"}
    ALLOWED_LIST_ONLY = {
        "alarmManagement", "cxoDashboard", "mwRealTime", "mwUmeTopology", "portalLogin",
    }
    pages, _, _ = _help_page_keys()
    meta = _app_page_meta_keys()
    only_meta = sorted(meta - pages - ALLOWED_META_ONLY)
    only_list = sorted(pages - meta - ALLOWED_LIST_ONLY)
    assert not only_meta, (
        f"App.tsx PAGE_META 有这些页面但帮助页 PAGE_LIST 没有（两处都要加）: {only_meta}"
    )
    assert not only_list, (
        f"帮助页 PAGE_LIST 有这些页面但 App.tsx PAGE_META 没有（两处都要加）: {only_list}"
    )


def test_feature_guide_table_matches_menu():
    """11-feature-guide.md 顶部页面表必须与 App.tsx 的菜单结构一致。

    表里的 key 集合、iframe 形态列、菜单名（i18n `nav.*`）都必须对得上，
    否则手册里的「按导航顺序」就失去意义 —— 读者按手册找页找不到。

    判定方式：
      - 菜单 key 顺序 = `DEFAULT_GROUPS` 展平（`grp_finebi` 用 `FINEBI_BOARDS` 展开）；
      - 形态列 = `helpContent.ts` 的 `PAGE_LIST` 里 `iframe:true` 的集合；
      - 菜单名 = `PAGE_META` 的 `labelKey` → `i18n.tsx` zh 字典的值。

    允许的差异：`finebi_<slug>` 在手册里合并成一行（`58–73`），
    `ap_center` 单列在表外（既有布局里它挂在 `grp_finebi` 目录）。
    """
    guide = _read("docs/manual/11-feature-guide.md")
    tbl_start = guide.index("| # | 菜单 | key | 形态 |")
    tbl = guide[tbl_start:guide.index("\n\n", tbl_start)]

    # 表里显式列出的 key（`finebi_<slug>` 那行是通配，不算）
    doc_keys = set(re.findall(r"\| `([a-zA-Z0-9_]+)`", tbl))
    doc_keys.discard("slug")

    app = _read("frontend/src/App.tsx")
    i = app.index("const DEFAULT_GROUPS")
    seg = app[i:app.index("\n]\n", i)]
    order = []
    # 逐个 group 解析：key 与 items 一一对应。不能用一个大正则 ——
    # `grp_finebi` 的 items 是 `FINEBI_BOARDS.map(...)`（不是字面量数组），
    # 大正则会把它的 items 匹配成后面某个组的数组，导致整段错位。
    for gm in re.finditer(r"key:\s*'(grp_[a-z_]+)'", seg):
        gname = gm.group(1)
        tail = seg[gm.end():]
        im = re.search(r"items:\s*\[", tail)
        if not im:
            continue
        arr = tail[im.end():tail.index("]", im.end()) + 1]
        if "FINEBI_BOARDS.map" in arr:
            slugs = re.findall(r"\{ slug: '([\w]+)'", app)
            order += [f"finebi_{s}" for s in slugs]
        else:
            order += re.findall(r"'([A-Za-z0-9_]+)'", arr)

    # 手册里 finebi 合并成一行 → 从比对集合里剔除
    finebi = {k for k in order if k.startswith("finebi_")}
    code_keys = set(order) - finebi
    doc_cmp = {k for k in doc_keys if not k.startswith("finebi_")}
    missing = sorted(code_keys - doc_cmp)
    assert not missing, f"11-feature-guide.md 顶部页面表缺这些菜单页: {missing}"
    ghost = sorted(doc_cmp - code_keys)
    assert not ghost, f"11-feature-guide.md 顶部页面表有已下线的页: {ghost}"

    # 形态列：标了 iframe 的必须是 iframe 页
    for line in tbl.splitlines():
        m = re.match(r"^\| [^|]+ \| [^|]+ \| `([a-zA-Z0-9_]+)` \| ([^|]+) \|$", line)
        if not m:
            continue
        key, shape = m.group(1), m.group(2)
        if key.startswith("finebi_"):
            continue
        want_iframe = "**iframe**" in shape
        assert want_iframe == (key in _iframe_pages()), (
            f"11-feature-guide.md 里 {key} 的形态标注与实际不符"
            f"（文档标 iframe={want_iframe}，实际={key in _iframe_pages()}）"
        )


def _iframe_pages() -> set:
    src = _read("frontend/src/pages/helpContent.ts")
    pl_start = src.index("export const PAGE_LIST")
    pl = src[pl_start:src.index("\n]", pl_start)]
    return set(re.findall(r"key:\s*'([A-Za-z0-9_]+)',\s*iframe:\s*true", pl))


def _page_counts() -> tuple:
    """返回 (PAGE_META 条数, FINEBI_BOARDS 条数, PAGE_LIST 条数)。

    三个数各有各的口径，文档里也必须按同一个口径写：
      - PAGE_META（App.tsx）= 侧边栏/路由里的自研页面数，**含 help 自身**；
      - FINEBI_BOARDS = 16 个原生看板（FineBI 迁移），键是 `finebi_<slug>`；
      - PAGE_LIST（helpContent.ts）= 帮助页覆盖的页面数，**不含 help 自身**。

    「N 个功能页」在文档里的正确值 = PAGE_META + FINEBI_BOARDS（= 79）；
    「N 个页面指南」（指帮助文档覆盖的页数）= PAGE_LIST（= 62）。
    """
    app = _read("frontend/src/App.tsx")
    i = app.index("const PAGE_META")
    seg = app[i:app.index("\n}\n", i)]
    meta = len(re.findall(r"^ {2}([a-zA-Z0-9_]+):\s*\{", seg, re.M))
    boards = len(re.findall(r"\{ slug: '([\w]+)'", app))

    src = _read("frontend/src/pages/helpContent.ts")
    pl_start = src.index("export const PAGE_LIST")
    pl = src[pl_start:src.index("\n]", pl_start)]
    listed = len(re.findall(r"key:\s*'[A-Za-z0-9_]+'", pl))
    return meta, boards, listed


def test_page_counts_in_docs_match_code():
    """文档里写的「N 个功能页 / N 个页面指南」必须等于代码真相源。

    口径（见 `_page_counts`）：
      - 「功能页」= PAGE_META + FINEBI_BOARDS（侧边栏能进的全部页面）；
      - 「页面指南」= PAGE_LIST（帮助文档实际覆盖的页数）。

    实测（2026-10-31）：文档写 54，代码实际 79/62 —— 差了 25 个页面。
    """
    meta, boards, listed = _page_counts()
    total = meta + boards

    # 「N 个功能页」/「N 个页面」（11-feature-guide 逐页说明的那份）
    for rel in (
        "docs/manual/01-overview.md",
        "docs/manual/README.md",
        "AGENTS.md",
        "project-overview.md",
        "user-guide.md",
    ):
        doc = _read(rel)
        assert re.search(rf"{total} 个功能页", doc), (
            f"{rel} 里的「功能页数」不是 {total}（PAGE_META {meta} + FINEBI_BOARDS {boards}）"
        )

    # 「N 个页面指南」= PAGE_LIST
    for rel in (
        "docs/manual/README.md",
        "project-overview.md",
        "user-guide.md",
    ):
        doc = _read(rel)
        assert re.search(rf"{listed} 个页面指南", doc), (
            f"{rel} 里的「页面指南数」不是 {listed}（PAGE_LIST 条数）"
        )

    # 根 user-guide.md 也要跟
    root = (ROOT.parent.parent / "user-guide.md").read_text(encoding="utf-8", errors="replace")
    assert re.search(rf"{total} 个页面", root), f"根 user-guide.md 里的页面数不是 {total}"
    assert re.search(rf"{listed} 个页面指南", root), (
        f"根 user-guide.md 里的「页面指南数」不是 {listed}"
    )


def test_help_content_retention_days_matches_code():
    """站内帮助（helpContent.ts）里的「队列保留 N 天」必须等于 TASK_LOG_RETENTION_DAYS 默认值。

    实测（2026-10-31）：13-operations.md 已改成 7 天，但 helpContent.ts 仍写 3 天 ——
    站内帮助与手册对同一件事给出两个数，用户无从判断哪个对。

    2026-11-03 收窄匹配范围：只核对「队列/task_queue/执行日志」语境下的保留期，
    不再匹配页面各自的数据表保留期（如 ipt_power_snapshots 快照保留 2 天）——
    数据表保留期各有各的值，与队列保留期无关，混在一起会误伤。
    """
    default_days = 7
    m = re.search(
        r'TASK_LOG_RETENTION_DAYS["\'],?\s*["\']?(\d+)', _read("backend/worker.py")
    )
    if m:
        default_days = int(m.group(1))
    src = _read("frontend/src/pages/helpContent.ts")
    hits = re.findall(
        r"(?:队列|task_queue|task_execution_log|执行日志)[^\n]{0,40}保留 (\d+) 天", src)

    assert hits, "helpContent.ts 里找不到「保留 N 天」的表述（守卫本身失效了？）"
    for d in set(hits):
        assert int(d) == default_days, (
            f"helpContent.ts 写的队列保留期是 {d} 天，代码默认 {default_days} 天"
        )


def test_component_counts_in_component_api():
    """component-api.md 里的「N 个 `.tsx`」必须等于磁盘实际文件数。

    实测（2026-10-31）：写「60+ 个页面 / 8 个通用组件」→ 实际 71 / 27。
    这些数字是「新增文件前先看规模」的判断依据，差 10 倍就失去意义。
    """
    def count(rel: str) -> int:
        d = ROOT / rel
        return len([
            p for p in d.glob("*.tsx")
            if not p.name.startswith("_") and "_bak_" not in p.name
        ])

    pages = count("frontend/src/pages")
    comps = count("frontend/src/components")
    doc = _read("component-api.md")
    m = re.search(r"frontend\\src\\pages\\`\s*\|\s*(\d+)\s*个", doc)
    assert m, "component-api.md 里找不到前端页面数（守卫本身失效了？）"
    assert int(m.group(1)) == pages, (
        f"component-api.md 写 {m.group(1)} 个前端页面，实际 {pages} 个"
    )
    m = re.search(r"frontend\\src\\components\\`\s*\|\s*(\d+)\s*个", doc)
    assert m, "component-api.md 里找不到通用组件数（守卫本身失效了？）"
    assert int(m.group(1)) == comps, (
        f"component-api.md 写 {m.group(1)} 个通用组件，实际 {comps} 个"
    )


def test_credential_group_count_in_security_doc():
    """05-security-and-credentials.md 写的凭据分组数必须等于 credential_store 的实际条数。

    实测（2026-10-31）：文档写 18 个，实际 21 个 —— 漏了 `ume_alarm` /
    `gp_ran_control` / `gp_ran_master` 三个分组。用户按文档去「系统设置 → 凭据」
    排查时，会以为这三组不存在。
    """
    src = _read("backend/services/credential_store.py")
    keys = sorted(set(re.findall(r'"key":\s*"([a-z0-9_]+)"', src)))
    n = len(keys)
    doc = _read("docs/manual/05-security-and-credentials.md")
    m = re.search(r"\*\*(\d+) 个分组 key\*\*", doc)
    assert m, "05-security-and-credentials.md 里找不到「N 个分组 key」的表述（守卫本身失效了？）"
    claimed = int(m.group(1))
    assert claimed == n, (
        f"05-security-and-credentials.md 写 {claimed} 个凭据分组，实际 {n} 个：{keys}"
    )
    # 分组 key 本身也列全（漏一个就等于告诉用户这个分组不存在）
    for k in keys:
        assert f"`{k}`" in doc, f"05-security-and-credentials.md 的分组清单里漏了 `{k}`"


def test_file_sizes_in_agents_md_are_approximately_right():
    """AGENTS.md 里标的关键文件体积必须与磁盘实际值相符（容差 ±25%）。

    这些体积是「哪些文件已经超限、该重构了」的判断依据，
    长期不更新会让人以为 task_registry.py 还是 68KB（实际已 109KB）。
    """
    doc = _read("AGENTS.md")
    for rel, pat in (
        ("backend/task_registry.py", r"backend\\task_registry\.py`（≈?(\d+)KB）"),
        ("frontend/src/i18n.tsx", r"frontend\\src\\i18n\.tsx`（≈?(\d+)KB）"),
        ("frontend/src/App.tsx", r"frontend\\src\\App\.tsx`（≈?(\d+)KB）"),
    ):
        m = re.search(pat, doc)
        assert m, f"AGENTS.md 里找不到 {rel} 的体积标注"
        claimed = int(m.group(1))
        actual = _file_size_kb(rel)
        assert abs(claimed - actual) <= max(3, actual * 0.25), (
            f"AGENTS.md 标 {rel} 为 {claimed}KB，实际约 {actual}KB（偏差 >25%）"
        )


def _app_ar_defaults() -> dict:
    """从 App.tsx 取每页的建议刷新间隔 AR_PAGE_DEFAULTS = { page: 秒 }。"""
    src = _read("frontend/src/App.tsx")
    i = src.index("const AR_PAGE_DEFAULTS")
    seg = src[i:src.index("\n}", i)]
    return {k: int(v) for k, v in re.findall(r"([a-zA-Z0-9_]+):\s*(\d+)", seg)}


def _app_ar_options() -> set:
    """App.tsx 里可选的刷新间隔档位 AR_OPTIONS = [...]。"""
    src = _read("frontend/src/App.tsx")
    m = re.search(r"const AR_OPTIONS\s*=\s*\[([^\]]*)\]", src)
    assert m, "App.tsx 里找不到 AR_OPTIONS 数组"
    return {int(x) for x in re.findall(r"\d+", m.group(1))}


def test_every_page_has_refresh_setting():
    """每个页面都要有「按页刷新设置」—— 2026-11-04 用户定的项目硬要求。

    规则原文见 AGENTS.md 三.3d 与 docs/manual/16-new-page-guide.md 3.4d：
    顶栏的停止/开启刷新 + 间隔下拉对**所有页面**可用，选择按页记忆，默认关闭；
    每页在 AR_PAGE_DEFAULTS 里登记一个建议间隔（点「开启刷新」时落到的值）。

    守三件事，任何一条破了都说明「新增页面没做刷新设置」或「有人又把白名单加回来了」：
      1. PAGE_META 里的每个自研页面都在 AR_PAGE_DEFAULTS 登记了建议间隔
         （`finebi_*` 原生看板由 FINEBI_BOARDS 动态注入，落全局建议 AR_PAGE_DEFAULT_SEC，
         不在本条要求内）；
      2. 建议间隔必须是 AR_OPTIONS 里的档位 —— 否则点「开启」后下拉显示不出该值；
      3. 不得再出现「按页禁用刷新控件」的白名单：AR_BOARD_PAGES 已删除，
         控件上也不得挂 `disabled={!arIsBoard` 这类条件。
    """
    src = _read("frontend/src/App.tsx")
    pages = _app_page_meta_keys()
    defaults = _app_ar_defaults()
    options = _app_ar_options()

    assert pages, "App.tsx 的 PAGE_META 解析出 0 个页面（取法失效了，修取法而不是放行）"

    own = {p for p in pages if not re.fullmatch(r"finebi_\w+", p)}
    missing = sorted(own - set(defaults))
    assert not missing, (
        f"这些页面没在 App.tsx 的 AR_PAGE_DEFAULTS 里登记建议刷新间隔（新增页面必须做按页刷新设置，"
        f"见 AGENTS.md 三.3d）: {missing}"
    )
    unknown = sorted(set(defaults) - own)
    assert not unknown, f"AR_PAGE_DEFAULTS 里有不属于 PAGE_META 的页面键（页面已改名或删除？）: {unknown}"

    bad = sorted(f"{k}={v}" for k, v in defaults.items() if v not in options)
    assert not bad, f"建议间隔必须是 AR_OPTIONS {sorted(options)} 里的档位，这些不是: {bad}"

    assert "const AR_BOARD_PAGES" not in src, (
        "App.tsx 里又出现了刷新白名单 AR_BOARD_PAGES —— 2026-11-04 起所有页面一视同仁，"
        "不得再按页禁用刷新控件"
    )
    assert "disabled={!arIsBoard" not in src, "顶栏刷新控件不得按页禁用"


def test_pg_freshness_covers_pushdown_tables():
    """看板时间下推涉及的每张表，都必须同时被本机 PG 巡检覆盖。

    背景（2026-11-05 复盘，这一条就是那次事故沉淀下来的）：
    IP RAN 四个看板自 11-04 起改读本机 PG 的 `ipran_ume` schema，而采集侧的
    `mirror_rows_to_local` **只追头部水位** —— 中间断掉的日子永远不会自己长回来。
    11-05 把默认窗口从 7 天改成 31 天时实测发现「近 31 天本机只有 10 天有数、
    远端 32 天齐全」，而这件事**当时没有任何巡检能查到**：
      - `db_freshness_check.REMOTE_CHECKS` 查的是远端库水位（远端一直新 → 永远绿）；
      - `LOCAL_CHECKS` 里那条「ipran 本地回退库」指的是 pg 模式下早就不写的 sqlite 文件；
      - 判据本身只问「最新 Begin Time 够不够新」，天生看不见「中间少了 20 天」。
    补齐手段见 `backend/services/pg_schema_freshness.md`。

    守三件事：
      1. `PUSH_DOWN_TABLES` 里每张表都在 `PG_SCHEMA_CHECKS[].tables` 里 ——
         给看板加了下推表却忘了配巡检，提交就会被拦下；
      2. 巡检的回看天数 = 看板默认窗口天数 —— 页面看 31 天而巡检只查 7 天等于没查；
      3. 缺档必须在页面上**常驻**可见（后端算 `meta.coverage`、前端渲染告警），
         按仓库 UI 硬要求「算错了 / 算不全必须常驻可见」（根 AGENTS.md 四.10），
         不许让「库里没数」在折线图上伪装成「流量真的是 0」。
    """
    from doc_truth import pg_freshness_scope, pushdown_scope

    tables, days = pushdown_scope()
    scopes = pg_freshness_scope()

    checked = {t for ts, _lb in scopes for t in ts}
    uncovered = sorted(set(tables) - checked)
    assert not uncovered, (
        f"这些表被看板取数层按时间下推（会决定页面默认看几天），却不在 "
        f"backend/services/pg_schema_freshness.py 的 PG_SCHEMA_CHECKS 里，"
        f"于是本机库断档没人知道: {uncovered}"
    )

    mismatched = [lb for _ts, lb in scopes if lb and lb != days]
    assert not mismatched, (
        f"看板默认窗口是 PUSH_DOWN_DAYS={days} 天，但本机 PG 巡检的 lookback_days "
        f"配成了 {sorted(set(mismatched))} —— 窗口和巡检范围必须同档，否则页面看到的"
        f"那段正是巡检没查的那段"
    )

    backend_src = _read("backend/services/dashboard_service.py")
    assert '"coverage": _coverage_from_widgets' in backend_src, (
        "dashboard_service 不再输出 meta.coverage —— 缺档就不再可见了，"
        "见 backend/services/pg_schema_freshness.md"
    )
    fe_src = _read("frontend/src/pages/NativeBoard.tsx")
    assert "nb.coverageTitle" in fe_src and 'type="warning"' in fe_src, (
        "NativeBoard 必须有缺档的常驻告警（type=\"warning\" + nb.coverageTitle）；"
        "解释怎么算的可以收起，算不全必须常驻可见（根 AGENTS.md 四.10）"
    )


CHECKS = [
    test_task_count_in_docs_matches_registry,
    test_task_list_table_covers_every_registered_task,
    test_group_counts_in_doc_match_code,
    test_worker_group_count_in_docs,
    test_queue_retention_days_matches_code,
    test_router_count_in_appendix_matches_code,
    test_iframe_page_count_in_feature_guide,
    test_feature_guide_table_matches_menu,
    test_help_page_docs_cover_page_list,
    test_help_page_list_matches_app_page_meta,
    test_page_counts_in_docs_match_code,
    test_help_content_retention_days_matches_code,
    test_credential_group_count_in_security_doc,
    test_component_counts_in_component_api,
    test_file_sizes_in_agents_md_are_approximately_right,
    test_every_page_has_refresh_setting,
    test_pg_freshness_covers_pushdown_tables,
]


if __name__ == "__main__":
    passed = failed = 0
    for fn in CHECKS:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001 - 守卫自身崩了也要报出来
            failed += 1
            print(f"[ERROR] {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"[PASS] {fn.__name__}")
    print(f"\nPASS={passed} FAIL={failed}")
    sys.exit(1 if failed else 0)
