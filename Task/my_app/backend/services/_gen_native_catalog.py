# -*- coding: utf-8 -*-
"""把 _native_catalog_raw.json 加工为可直接 import 的 Python 目录模块。

加工内容：
  1. 解析 text 组件的 HTML → 纯标题文本（去掉 FineBI 外链与内联样式噪声）
  2. 清理 pivot / limit / pct 等展示元数据
  3. 生成 SLUG（URL ?page=xxx 用的短名）
  4. 输出 backend/services/native_catalog.py

用法：python backend/services/_gen_native_catalog.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict

HERE = Path(__file__).resolve().parent
RAW = HERE / "_native_catalog_raw.json"
OUT = HERE / "native_catalog.py"

# 文本组件标题里的装饰字符（FineBI 原版用 ❯❯❯ xxx ❮❮❮ 做标题栏）
_DECOR_RE = re.compile(r"[❯❮\s\u00a0]+")
_TAG_RE = re.compile(r"<[^>]+>")
# 原版标题栏里指向 FineBI 的 <a href="http://localhost/webroot/decision/link/xxx">
_HREF_RE = re.compile(r"<a\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)


def html_to_title(html: str, fallback: str) -> str:
    """从 FineBI 文本组件 HTML 中提取纯标题。

    关键：先删掉整个 <a>...</a>（原版指向 FineBI 的外链），
    否则 FineBI 退役后点进去就是死链。
    """
    s = html or ""
    s = _HREF_RE.sub("", s)
    s = _TAG_RE.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = _DECOR_RE.sub(" ", s).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s or fallback


# 数据源覆盖：默认沿用 my-finebi 的 settings.data_sources 映射（连接名 → 逻辑库文件）。
#
# 例外：备件看板（id=17, slug=spare）在 my-finebi 里指向 LBR_SP → inventory.db，
# 那个库在远端 C:\FineBI6.0\...\WareHouseDashBoard\inventory.db，实测被长期占用
# （SELECT 1 也 42s 后报 "database is locked"，且 my_app 的 task_registry 里已记录
# 该库单次锁 1~9min、最坏 2h+ 的历史事故）。
#
# 关键事实：inventory.db 只是**镜像库**，其唯一写入方就是 my_app 自己的
# sp_data_sync 任务（backend/services/get_sp_table.py → 镜像写入 UNC inventory.db）。
# 而它镜像的源头，正是本机 db/app.db 里的 inband_details / outband_details /
# inventory_details 三张表（实测：inventory_details 133031 行，且 12 条 SQL 全部通过）。
#
# 因此 spare 直接改读本机 app.db —— 既绕开远端锁，又少一跳网络，
# 且与 my_app 既有 sp_dashboard 服务的数据口径完全一致。
LOCAL_DB_OVERRIDES = {
    # slug → (widget_id → 本地逻辑库名)
    17: "__local_app_db__",  # 整页改读本机 db/app.db
}

# 本地逻辑库名（供 dashboard_service 识别，不发远端 HTTP）
LOCAL_APP_DB = "__local_app_db__"

# 按「看板 + 原数据源」覆盖成另一个逻辑库。
#
# 与整页覆盖（LOCAL_DB_OVERRIDES）的区别：可用率那几个看板是**混源**页 ——
# 可用率趋势读 avail_recon，TT 明细读 db.sqlite3，不能整页换源。
#
# 背景（2026-09-21 事故）：`avail_recon.sqlite3` 原本只是 my-finebi 项目
# `data/` 目录下的**手工 ETL 快照**（`TMP/etl_avail_recon_v2.py`，
# my-finebi 的 PROJECT_DOCS 把它归类为「ETL 快照刷新 …… 变更后重跑」）。
# my-finebi 门户退役后**没有任何调度再跑它**，表就冻结在 2026-09-13，
# `?page=finebi_daily_availability` 静默停更了两周才被人肉发现。
#
# 现在由 my_app 自己的定时任务 `avail_recon_sync`
# （backend/services/avail_recon_sync.py）重建到本机 `data/avail_recon.sqlite3`，
# 因此这些组件改读本机逻辑库 `__local_avail_recon__`
# （见 dashboard_service.LOCAL_SQLITE_FILES）。
WIDGET_DB_OVERRIDES: Dict[int, Dict[str, str]] = {
    9: {"avail_recon.sqlite3": "__local_avail_recon__"},   # Daily Availability KPI
    11: {"avail_recon.sqlite3": "__local_avail_recon__"},  # Availability Dashboard (TT Related)
}

# 手写 slug：URL 友好、稳定、可读（不用 name 的哈希，方便用户手输）
SLUGS = {
    3: "cn_kpi",
    4: "metro_ring",
    5: "ipran_hq",
    6: "ipran_4region",
    7: "fw_daily",
    8: "cn_kpi_monthly",
    9: "daily_availability",
    10: "availability_daily",
    11: "availability_tt",
    12: "kpi_4g",
    13: "kpi_3g",
    14: "kpi_2g",
    15: "mttr",
    16: "cm_dashboard",
    17: "spare",
    18: "progress",
    19: "progress_v3",
}

# 短标题（页面标题栏显示；原版标题栏文本已从 HTML 解析，这里提供更规整的备选）
TITLES = {
    3: "CCN_Daily_KPI",
    4: "IP RAN Metor Ring KPI",
    5: "IP RAN (IPCORE HQ-ODC & Banjor/ELWA & OLT)",
    6: "IP RAN 4 Region KPI",
    7: "FW_Daily_KPI",
    8: "CN KPI Monthly",
    9: "Daily Availability_KPI",
    10: "Availability Daily Dashboard",
    11: "Availability Dashboard (TT Related)",
    12: "4G KPI",
    13: "3G KPI",
    14: "2G_Daily_KPI",
    15: "MTTR Dashboard Monthly & Weekly",
    16: "Corrective Maintenance",
    17: "Spare Management Dashboard",
    18: "Progress",
    19: "Progress V3",
}


def main() -> int:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    dashboards = []
    for d in raw:
        did = d["id"]
        if did not in SLUGS:
            print(f"!! dashboard {did} 没有 slug，跳过", file=sys.stderr)
            continue
        widgets = []
        # 本页是否整体改读本机 app.db（见 LOCAL_DB_OVERRIDES 说明）
        use_local = LOCAL_DB_OVERRIDES.get(did) == LOCAL_APP_DB
        # 本页按原数据源做的逐条覆盖（见 WIDGET_DB_OVERRIDES 说明）
        db_map = WIDGET_DB_OVERRIDES.get(did, {})
        for w in d["widgets"]:
            chart = w["chart"]
            src_db = w.get("db") or ""
            item = {
                "id": w["id"],
                "title": w["title"],
                "chart": chart,
                "pivot": w.get("pivot") or False,
                "pct": w.get("pct") or False,
                "db": LOCAL_APP_DB if use_local else db_map.get(src_db, src_db),
                "sql": (w.get("sql") or "").strip(),
                "limit": w.get("limit"),
            }
            if chart == "text":
                item["title_text"] = html_to_title(w.get("html") or "",
                                                   TITLES.get(did, ""))
                item["bg"] = (w.get("bg") or "").strip()
                item["color"] = (w.get("color") or "").strip()
            widgets.append(item)
        dashboards.append({
            "id": did,
            "slug": SLUGS[did],
            "name": d["name"],
            "title": TITLES.get(did, ""),
            "category": d["category"],
            "tags": d.get("tags") or "",
            "desc": (d.get("desc") or "").strip(),
            "widgets": widgets,
        })

    # 生成 Python 模块（用 repr 保证字符串转义正确）
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""原生看板目录（自动生成，请勿手改）。',
        "",
        "由 _gen_native_catalog.py 从 my-finebi 的 app.db dashboards.native_config 提取，",
        "覆盖除两个示例页（Sample · Embedded / Sample · Open in new tab）之外的全部看板。",
        "",
        "每个 widget：",
        "  id/title/chart(line|bar|kpi|table|text)/pivot/pct/db/sql/limit",
        "  text 组件额外带 title_text（已剥离 FineBI 外链）",
        "",
        "sql 取自 FineBI 原始数据集定义，逐条保留；db 由 my-finebi 的",
        "settings.data_sources 映射而来（连接名 → 逻辑库文件名）。",
        "",
        "db 的两种本机覆盖（见 _gen_native_catalog.py 的 LOCAL_DB_OVERRIDES /",
        "WIDGET_DB_OVERRIDES）：",
        "  __local_app_db__        → 本机 db/app.db（spare 整页）",
        "  __local_avail_recon__   → 本机 data/avail_recon.sqlite3（可用率派生表，",
        "                            由定时任务 avail_recon_sync 重建）",
        '"""',
        "from __future__ import annotations",
        "",
        "from typing import Any, Dict, List",
        "",
        "# slug → 看板定义；供路由按 ?page=<slug> 取数",
        "DASHBOARDS: List[Dict[str, Any]] = [",
    ]
    for d in dashboards:
        lines.append("    {")
        for k in ("id", "slug", "name", "title", "category", "tags", "desc"):
            lines.append(f"        {k!r}: {d[k]!r},")
        lines.append("        'widgets': [")
        for w in d["widgets"]:
            lines.append("            {")
            for k in ("id", "title", "chart", "pivot", "pct", "db", "sql", "limit"):
                lines.append(f"                {k!r}: {w[k]!r},")
            if w["chart"] == "text":
                for k in ("title_text", "bg", "color"):
                    lines.append(f"                {k!r}: {w[k]!r},")
            lines.append("            },")
        lines.append("        ],")
        lines.append("    },")
    lines.append("]")
    lines.append("")
    lines.append("# slug → 看板定义（路由/前端用）")
    lines.append("BY_SLUG: Dict[str, Dict[str, Any]] = {d['slug']: d for d in DASHBOARDS}")
    lines.append("")
    lines.append("# 前端菜单用：轻量清单（不含 SQL，避免首屏传大 JSON）")
    lines.append("CATALOG: List[Dict[str, Any]] = [")
    lines.append("    {")
    lines.append("        'slug': d['slug'],")
    lines.append("        'page': 'finebi_' + d['slug'],")
    lines.append("        'title': d['title'] or d['name'],")
    lines.append("        'name': d['name'],")
    lines.append("        'category': d['category'],")
    lines.append("        'tags': d['tags'],")
    lines.append("        'widgets': len(d['widgets']),")
    lines.append("    }")
    lines.append("    for d in DASHBOARDS")
    lines.append("]")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK -> {OUT}")
    print(f"dashboards={len(dashboards)} widgets={sum(len(d['widgets']) for d in dashboards)}")
    for d in dashboards:
        ch = {}
        for w in d["widgets"]:
            ch[w["chart"]] = ch.get(w["chart"], 0) + 1
        dbs = sorted({w["db"] for w in d["widgets"] if w["db"]})
        print(f"  {d['id']:2} {d['slug']:20} n={len(d['widgets']):3} {ch} dbs={dbs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
