# -*- coding: utf-8 -*-
"""一次性迁移（2026-09-21）：门户里原来是 FineBI 的卡片改用 my_app 的 FINEBI Board 原生页。

覆盖两个门户、四处真源
----------------------
MsPortal（http://localhost/MsPortal/）
  1. Task/my_app/backend/data/portal_catalog.json  服务端目录真源（GET /api/portal-catalog 实时读盘）
  2. MsPortal/assets/data.js                       内置兜底目录
  3. MsPortal/assets/access.js                     权限映射 —— 单独补丁，见该文件 FINEBI_PAGE_ACCESS_IDS
uniplam（http://localhost/uniplam/）
  4. portal-default.json                           服务端全局目录（GET /uniplam/api/portal-default 实时读盘）
  5. src/data/initialDashboards.ts                 内置兜底目录（vite dev server 直接读 src，改完刷新即生效）

背景与依据
----------
· my_app 侧栏分组 grp_finebi（i18n: nav.grp.finebi = "FineBI 看板" / "FineBI Boards"）
  共 16 个 `?page=finebi_<slug>` 页面，由 pages/NativeBoard 渲染，
  后端 GET /api/native-boards/{slug} 驱动（routers/native_boards.py）。
· 映射不是猜的：backend/services/native_catalog.py 每条 desc 里直接写着原 FineBI 链接码，
  例如 mttr 的 desc 以 "NGk1 原生重建" 开头，cn_kpi 的 desc 写 "公开链接 iYiQ"。
· iYiQ（CN KPI _V2）的原生重建页是 `?page=cn_kpi`（该页不在 grp_finebi 组内，
  挂在监控组）—— 已与需求方确认采用此映射。
· qXUp / B7E3 在 my_app 侧没有原生页，两个门户都保持 FineBI 直链（脚本尾部会报告）。

不改：no / groups / subOf / order / qc / 标题 / 描述 —— no 是卡片锚点与 localStorage
      分组归属键，动它会丢归属。
不改：uniplam 的 localStorage 缓存 —— PREFS_KEY 只存 isFavorite/isPinned/clickCount/
      lastVisited/hidden（按 id），url/platform 一律以目录为准，因此无需升版本号。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT_PORTAL = r"D:\01_RPA\liberia-noc_soc-数据看板统一门户"
CATALOG = r"D:\01_RPA\Task\my_app\backend\data\portal_catalog.json"
DATA_JS = os.path.join(ROOT_PORTAL, "MsPortal", "assets", "data.js")
PORTAL_DEFAULT = os.path.join(ROOT_PORTAL, "portal-default.json")
INITIAL_DASHBOARDS = os.path.join(ROOT_PORTAL, "src", "data", "initialDashboards.ts")

# 原 FineBI 公开链接码 -> my_app 页面键
# 前 11 条是服务端目录 portal_catalog.json 里现存的卡片；
# 后 4 条（AIfA/3GnT/1neE/2XPO）服务端目录已下架，但仍留在兜底目录 data.js 里，一并迁移。
# 未列入的 qXUp / B7E3 在 my_app 侧没有原生页，保持 FineBI 直链（见脚本尾部报告）。
FINEBI_TO_MYAPP: dict[str, str] = {
    "NGk1": "finebi_mttr",
    "435X": "finebi_availability_tt",
    "dXv0": "finebi_kpi_2g",
    "51Le": "finebi_kpi_3g",
    "wJmG": "finebi_kpi_4g",
    "uq6f": "finebi_fw_daily",
    "iYiQ": "cn_kpi",
    "cCc5": "finebi_cn_kpi_monthly",
    "k74G": "finebi_ipran_4region",
    "Dv5z": "finebi_ipran_hq",
    "PUVx": "finebi_metro_ring",
    # ---- 仅存在于兜底目录 data.js ----
    "AIfA": "finebi_availability_daily",
    "3GnT": "finebi_cm_dashboard",
    "1neE": "finebi_daily_availability",
    "2XPO": "finebi_spare",
}

MYAPP_HOST = "192.168.100.20"
FINEBI_HOST = "192.168.100.19"

# 已迁移的页面键 —— status 提升的判定集合（只有这些卡才从 beta 提到 online）
MIGRATED_PAGE_KEYS = set(FINEBI_TO_MYAPP.values())

# 2026-09-21 追加决策（需求方确认）：这批卡改为自研原生页后不再算「试运行」，
# 因此 status 由 beta 提到 online —— 去掉 MsPortal 卡片标题前那个 β 徽章。
# 只动已迁移的这批；qXUp / B7E3 仍是 FineBI 直链，保持 beta。
# 各文件里应被提升的条数，用来做写入前的断言（对不上就拒绝写）。
EXPECTED_STATUS_COUNTS = {
    "portal_catalog": 11,      # MsPortal 服务端目录里现存 11 张
    "data_js": 15,             # 兜底目录含服务端已下架的 4 张
    "portal_default": 15,      # uniplam 服务端目录（17 张里 2 张无原生页）
    "initial_dashboards": 15,  # uniplam 内置兜底
}


def new_url(page_key: str) -> str:
    """与目录里既有 myapp 条目同格式；不带 &t= 令牌（viewer.js 用门户 token 换会话 Cookie）。"""
    return f"http://{MYAPP_HOST}/myapp/?page={page_key}"


def link_code(url: str) -> str | None:
    m = re.search(r"/webroot/decision/link/([A-Za-z0-9]+)", url or "")
    return m.group(1) if m else None


# --------------------------------------------------------------- 1) 服务端目录
def patch_catalog() -> None:
    with open(CATALOG, encoding="utf-8") as f:
        doc = json.load(f)

    items = doc.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"[catalog] 结构异常：items 不是数组 ({CATALOG})")

    changed, skipped = [], []
    for it in items:
        if it.get("platform") != "finebi":
            continue
        code = link_code(it.get("url", ""))
        key = FINEBI_TO_MYAPP.get(code or "")
        if not key:
            skipped.append((it.get("no"), code, it.get("url")))
            continue
        changed.append((it["no"], it.get("titleZh", ""), code, it["url"], new_url(key)))
        it["platform"] = "myapp"
        it["url"] = new_url(key)

    if not changed:
        print("[catalog] 没有待迁移的 finebi 条目（可能已迁移过），未写入")
        return

    doc["savedAt"] = datetime.now().isoformat(timespec="seconds")
    with open(CATALOG, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    print(f"[catalog] 已改 {len(changed)} 条 -> {CATALOG}")
    for no, title, code, old, new in changed:
        print(f"    no={no:<3} {code:<5} {title[:44]:<46} {new}")
    if skipped:
        print(f"[catalog] ⚠️ 未映射、保持 finebi 的条目 {len(skipped)} 条：")
        for no, code, url in skipped:
            print(f"    no={no} code={code} {url}")


# --------------------------------------------------------------- 2) 兜底目录
def patch_data_js() -> None:
    with open(DATA_JS, encoding="utf-8") as f:
        text = f.read()

    nl = "\r\n" if "\r\n" in text else "\n"
    pattern = re.compile(
        r'      "platform": "finebi",\r?\n'
        r'      "platformZh": "FineBI 报表",\r?\n'
        r'      "url": "http://' + re.escape(FINEBI_HOST) + r'/webroot/decision/link/([A-Za-z0-9]+)",'
    )

    hits = pattern.findall(text)
    unmapped = sorted(set(hits) - set(FINEBI_TO_MYAPP))
    if unmapped:
        print(f"[data.js] ℹ️ my_app 侧无原生页、保持 FineBI 直链的链接码：{unmapped}")

    migrated = 0

    def repl(m: re.Match) -> str:
        nonlocal migrated
        code = m.group(1)
        key = FINEBI_TO_MYAPP.get(code)
        if not key:
            return m.group(0)
        migrated += 1
        return (
            f'      "platform": "myapp",{nl}'
            f'      "platformZh": "自研 my_app",{nl}'
            f'      "url": "{new_url(key)}",'
        )

    text2 = pattern.sub(repl, text)

    # stats 计数同步：myapp 32 -> +migrated，finebi 17 -> -migrated
    m_my = re.search(r'"myapp": (\d+),', text2)
    m_fb = re.search(r'"finebi": (\d+),', text2)
    if m_my and m_fb:
        old_my, old_fb = int(m_my.group(1)), int(m_fb.group(1))
        text2 = text2.replace(f'"myapp": {old_my},', f'"myapp": {old_my + migrated},', 1)
        text2 = text2.replace(f'"finebi": {old_fb},', f'"finebi": {old_fb - migrated},', 1)
        print(f"[data.js] stats: myapp {old_my} -> {old_my + migrated}, finebi {old_fb} -> {old_fb - migrated}")

    if text2 == text:
        print("[data.js] 内容无变化（可能已迁移过），未写入")
        return

    with open(DATA_JS, "w", encoding="utf-8", newline="") as f:
        f.write(text2)
    print(f"[data.js] 已改 {migrated} 条 -> {DATA_JS}")


# ------------------------------------------------- 4) uniplam 服务端全局目录
def patch_portal_default() -> None:
    """portal-default.json：platform finebi->custom，url + rel 一起改。

    rel 必须同步改 —— 运行时的 resolveUrl() 优先用 rel 拼地址（改 IP 即时生效），
    url 只是没有 rel 时的兜底。rel 留着旧的 /webroot/... 就会把地址拼回 FineBI。
    """
    with open(PORTAL_DEFAULT, encoding="utf-8") as f:
        doc = json.load(f)

    dashboards = doc.get("dashboards")
    if not isinstance(dashboards, list):
        raise SystemExit(f"[portal-default] 结构异常：dashboards 不是数组 ({PORTAL_DEFAULT})")

    changed, skipped = [], []
    for d in dashboards:
        if d.get("platform") != "finebi":
            continue
        code = link_code(d.get("url", ""))
        key = FINEBI_TO_MYAPP.get(code or "")
        if not key:
            skipped.append((d.get("id"), code, d.get("url")))
            continue
        changed.append((d.get("id"), code, key))
        d["platform"] = "custom"
        d["url"] = new_url(key)
        d["rel"] = f"/myapp/?page={key}"

    if not changed:
        print("[portal-default] 没有待迁移的 finebi 条目（可能已迁移过），未写入")
        return

    doc["savedAt"] = datetime.now().isoformat(timespec="seconds")
    with open(PORTAL_DEFAULT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    print(f"[portal-default] 已改 {len(changed)} 条 -> {PORTAL_DEFAULT}")
    for did, code, key in changed:
        print(f"    {did:<34} {code:<5} -> /myapp/?page={key}")
    if skipped:
        print(f"[portal-default] ℹ️ my_app 侧无原生页、保持 finebi 的条目 {len(skipped)} 条：")
        for did, code, url in skipped:
            print(f"    {did} code={code}")


# ------------------------------------------------- 5) uniplam 内置兜底目录
def patch_initial_dashboards() -> None:
    """initialDashboards.ts：platform 'finebi' -> 'custom'，url 表达式换成 ${MYAPP_BASE}<key>。

    只做这两处定点替换；文件头的说明注释与 FINEBI_BASE 常量的去留另行处理
    （常量若不再被引用要一并删掉，否则 lint 会报未使用）。
    """
    with open(INITIAL_DASHBOARDS, encoding="utf-8") as f:
        text = f.read()

    nl = "\r\n" if "\r\n" in text else "\n"
    pattern = re.compile(
        r"      platform: 'finebi',\r?\n"
        r"      url: `\$\{FINEBI_BASE\}/link/([A-Za-z0-9]+)`,"
    )

    hits = pattern.findall(text)
    unmapped = sorted(set(hits) - set(FINEBI_TO_MYAPP))
    if unmapped:
        print(f"[initialDashboards] ℹ️ my_app 侧无原生页、保持 FineBI 直链的链接码：{unmapped}")

    migrated = 0

    def repl(m: re.Match) -> str:
        nonlocal migrated
        key = FINEBI_TO_MYAPP.get(m.group(1))
        if not key:
            return m.group(0)
        migrated += 1
        return f"      platform: 'custom',{nl}      url: `${{MYAPP_BASE}}{key}`,"

    text2 = pattern.sub(repl, text)
    if text2 == text:
        print("[initialDashboards] 内容无变化（可能已迁移过），未写入")
        return

    with open(INITIAL_DASHBOARDS, "w", encoding="utf-8", newline="") as f:
        f.write(text2)
    print(f"[initialDashboards] 已改 {migrated} 条 -> {INITIAL_DASHBOARDS}")


# ------------------------------------------------- 6) 已迁移卡片 status 提升
def _promote_text(text: str, url_re: "re.Pattern[str]", status_re: "re.Pattern[str]"):
    """在文本文件里做「url 命中已迁移页面键 → 紧随其后的 status 从 beta 改 online」。

    用位置法而不是整块解析：两个文本文件的条目缩进/嵌套不完全规整
    （initialDashboards.ts 的 4 空格块数 50 ≠ 条目数 51，data.js 里还夹着 /* */ 注释，
    不是合法 JSON），按块切容易误判。每个条目里 url 都在 status 之前且各只出现一次，
    所以「从 url 往后找第一个 status」定位是准的。
    """
    edits = []
    for m in url_re.finditer(text):
        if m.group(1) not in MIGRATED_PAGE_KEYS:
            continue
        sm = status_re.search(text, m.end())
        if sm and sm.group(1) == "beta":
            edits.append((sm.start(1), sm.end(1)))
    for s, e in reversed(edits):
        text = text[:s] + "online" + text[e:]
    return text, len(edits)


def _write_json(path: str, doc: dict) -> None:
    doc["savedAt"] = datetime.now().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def promote_status_online() -> None:
    """把已迁移的这批卡 status 由 beta 提到 online（MsPortal 11 张 / 兜底与 uniplam 各 15 张）。

    只改 status 字段，不碰 url/platform/rel；qXUp / B7E3 仍是 FineBI 直链，保持 beta。
    写入前逐文件断言命中条数：只接受「期望条数」或 0（0 = 已经提升过）。
    其他数字说明目录结构变了，拒绝写入并报错，避免误伤。
    """
    steps = []  # (name, path, 本次提升条数, 内容是否变化, 写盘函数)

    # ---- 1) MsPortal 服务端目录（JSON）
    with open(CATALOG, encoding="utf-8") as f:
        doc = json.load(f)
    n = 0
    for it in doc.get("items", []):
        m = re.search(r"[?&]page=([A-Za-z0-9_]+)", it.get("url", ""))
        if m and m.group(1) in MIGRATED_PAGE_KEYS and it.get("status") == "beta":
            it["status"] = "online"
            n += 1
    steps.append(("portal_catalog", CATALOG, n, n > 0,
                  lambda p=CATALOG, d=doc: _write_json(p, d)))

    # ---- 2) MsPortal 兜底 data.js（文本）
    with open(DATA_JS, encoding="utf-8") as f:
        t = f.read()
    t2, n2 = _promote_text(
        t,
        re.compile(r'"url": "http://' + re.escape(MYAPP_HOST) + r'/myapp/\?page=([A-Za-z0-9_]+)"'),
        re.compile(r'"status": "(beta|online)"'),
    )
    # stats 里的 online/beta 计数**按条目实际值重算**（幂等、可自愈；增量法在二次运行时
    # 会因 n2=0 而漏改）。portal.js 并不消费 DATA.stats，但它是文件自述，留着旧数会误导人。
    # "online": N / "beta": N 在整份文件里各只出现 1 次（都在 stats 块内），定位安全。
    n_on = len(re.findall(r'"status": "online"', t2))
    n_be = len(re.findall(r'"status": "beta"', t2))
    m_on = re.search(r'"online": (\d+),', t2)
    m_be = re.search(r'"beta": (\d+),', t2)
    if m_on and m_be and (int(m_on.group(1)) != n_on or int(m_be.group(1)) != n_be):
        t2 = t2.replace(f'"online": {m_on.group(1)},', f'"online": {n_on},', 1)
        t2 = t2.replace(f'"beta": {m_be.group(1)},', f'"beta": {n_be},', 1)
        print(f"[status] data.js stats: online {m_on.group(1)} -> {n_on}, beta {m_be.group(1)} -> {n_be}")
    steps.append(("data_js", DATA_JS, n2, t2 != t,
                  lambda p=DATA_JS, s=t2: _write_text(p, s)))

    # ---- 3) uniplam 服务端目录（JSON）
    with open(PORTAL_DEFAULT, encoding="utf-8") as f:
        pd = json.load(f)
    n3 = 0
    for d in pd.get("dashboards", []):
        m = re.search(r"[?&]page=([A-Za-z0-9_]+)", d.get("url", ""))
        if m and m.group(1) in MIGRATED_PAGE_KEYS and d.get("status") == "beta":
            d["status"] = "online"
            n3 += 1
    steps.append(("portal_default", PORTAL_DEFAULT, n3, n3 > 0,
                  lambda p=PORTAL_DEFAULT, d=pd: _write_json(p, d)))

    # ---- 4) uniplam 内置兜底 initialDashboards.ts（文本）
    with open(INITIAL_DASHBOARDS, encoding="utf-8") as f:
        ts = f.read()
    ts2, n4 = _promote_text(
        ts,
        re.compile(r"url: `\$\{MYAPP_BASE\}([A-Za-z0-9_]+)`"),
        re.compile(r"status: '(beta|online)'"),
    )
    steps.append(("initial_dashboards", INITIAL_DASHBOARDS, n4, ts2 != ts,
                  lambda p=INITIAL_DASHBOARDS, s=ts2: _write_text(p, s)))

    # ---- 断言后统一写入
    for name, path, count, changed, write in steps:
        want = EXPECTED_STATUS_COUNTS[name]
        if count not in (0, want):
            print(f"[status] ✗ {name}: 命中 {count} 条，期望 {want} 条 —— 拒绝写入 {os.path.basename(path)}")
            continue
        if not changed:
            print(f"[status] · {name}: 无变化（已提升过）")
            continue
        write()
        detail = f"{count} 条 beta -> online" if count else "stats 计数校正"
        print(f"[status] ✓ {name}: {detail}  ({os.path.basename(path)})")


if __name__ == "__main__":
    patch_catalog()
    print()
    patch_data_js()
    print()
    patch_portal_default()
    print()
    patch_initial_dashboards()
    print()
    promote_status_online()

