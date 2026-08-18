#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把门户 UI 导出的配置保存为「默认配置」(self-service 工具)。

背景：
  门户的默认配置 = src/data/initialDashboards.ts(源码)；
  每个浏览器首次打开后会把自己的列表缓存进 localStorage
  (liberia_noc_dashboards_v<版本>),之后以缓存为准。
  因此「在 UI 里改完 → 想成为所有人的默认」必须两步：
    1) 用本脚本把导出的 JSON 重新生成 src/data/initialDashboards.ts
    2) 升级 src/App.tsx 的 STORAGE_KEY 版本号(+1),让所有浏览器丢弃旧缓存

用法：
  python scripts/save_ui_export_as_default.py                # 自动取门户目录里最新的导出
  python scripts/save_ui_export_as_default.py 路径/xxx.json  # 指定导出文件
  python scripts/save_ui_export_as_default.py --no-bump-key  # 只重生成,不升存储 key
  python scripts/save_ui_export_as_default.py --dry-run      # 只打印,不写文件

步骤：
  1) 浏览器打开门户 → 点「导出配置」(下载 enterprise-bi-dashboards-<时间戳>.json)
  2) 运行本脚本(默认自动选择最新的导出)
  3) 完成：所有浏览器下次打开门户自动加载新默认配置
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime

PORTAL_D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 部署目录(192.168.100.19 的 E: 共享)；不存在时跳过
PORTAL_Y = r"Y:\01_RPA\liberia-noc_soc-数据看板统一门户"

VALID_THEME = {'teal', 'indigo', 'emerald', 'cyan', 'purple', 'amber', 'rose', 'blue', 'green'}
VALID_STATUS = {'online', 'maintenance', 'beta'}
VALID_FREQ = {'实时流式', '每小时', '每日0点', '周度更新', '月度汇总'}
VALID_CATEGORIES = {'MS 综合运维管理', '告警与工单故障', '网络性能与无线/核心网', '传输承载与业务时延',
                    '现场动力与备件仓储', '自动化调度与数据集成', '其他'}


def ts_str(s):
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def to_url_expr(url, platform):
    if url.startswith("http://192.168.100.19/webroot/decision"):
        return f"`${{FINEBI_BASE}}{url[len('http://192.168.100.19/webroot/decision'):]}`"
    if url.startswith("http://192.168.100.20/myapp/?page="):
        return f"`${{MYAPP_BASE}}{url[len('http://192.168.100.20/myapp/?page='):]}`"
    if url.startswith("http://192.168.100.20/myapp/"):
        return "`http://${getMyappHost()}/myapp/`"
    if url.startswith("http://192.168.100.19/"):
        return "`http://${getFinebiHost()}" + url[len("http://192.168.100.19"):] + "`"
    if url.startswith("http://192.168.100.20/"):
        return "`http://${getMyappHost()}" + url[len("http://192.168.100.20"):] + "`"
    return ts_str(url)


def item_to_ts(d):
    fields = [
        ("id", ts_str(d["id"])),
        ("title", ts_str(d["title"])),
        ("description", ts_str(d.get("description", ""))),
        ("platform", ts_str(d["platform"])),
        ("url", to_url_expr(d["url"], d["platform"])),
        ("category", ts_str(d["category"])),
        ("tags", "[" + ", ".join(ts_str(t) for t in d.get("tags", [])) + "]"),
        ("iconName", ts_str(d.get("iconName", "LayoutGrid"))),
        ("updateFrequency", ts_str(d["updateFrequency"])),
        ("department", ts_str(d.get("department", ""))),
        ("owner", ts_str(d.get("owner", ""))),
        ("isFavorite", "true" if d.get("isFavorite") else "false"),
        ("isPinned", "true" if d.get("isPinned") else "false"),
        ("clickCount", str(int(d.get("clickCount", 0)))),
        ("lastVisited", ts_str(d.get("lastVisited", ""))),
        ("themeColor", ts_str(d.get("themeColor", "indigo"))),
        ("status", ts_str(d.get("status", "online"))),
    ]
    lines = ["    {"]
    for i, (k, v) in enumerate(fields):
        lines.append(f"      {k}: {v}{',' if i < len(fields) - 1 else ''}")
    lines.append("    },")
    return "\n".join(lines)


def build_ts(items, stamp):
    header = f"""import {{ DashboardItem }} from '../types/dashboard';
import {{ getFinebiHost, getMyappHost, buildRel }} from '../config';

// ============================================================================
// 看板目录数据（真实环境填充）
//  - custom 平台：Task\\my_app (Data Insight MVP) 前端页面，
//    直链格式 http://<myappHost>/myapp/?page=<PageKey>
//  - finebi 平台：看板全部使用 FineBI「公共链接」（匿名、免登录直达），
//    地址形如 http://<finebiHost>/webroot/decision/link/<code>
// 说明：主机（192.168.100.19 / .20）统一收口到 src/config.ts，此处仅描述相对路径；
// 完整 URL 在导出时由 withRel 计算，运行时再由配置 + rel 拼出，改 IP 只需改配置一处。
// 本文件由 scripts/save_ui_export_as_default.py 从门户 UI 导出 JSON 自动生成
// （{stamp}，{len(items)} 条）。
// ============================================================================

const MYAPP_BASE = `http://${{getMyappHost()}}/myapp/?page=`;
const FINEBI_BASE = `http://${{getFinebiHost()}}/webroot/decision`;

/** 为每条 finebi/custom 看板补算 rel（相对路径），使其跟随全局主机配置 */
function withRel(items: DashboardItem[]): DashboardItem[] {{
  return items.map((it) => (it.rel ? it : {{ ...it, rel: buildRel(it.platform, it.url) }}));
}}

const RAW_DASHBOARDS: DashboardItem[] = [
"""
    body = "\n".join(item_to_ts(d) for d in items)
    tail = """
];

export const INITIAL_DASHBOARDS: DashboardItem[] = withRel(RAW_DASHBOARDS);

export const CATEGORIES = [
  '全部',
  'MS 综合运维管理',
  '告警与工单故障',
  '网络性能与无线/核心网',
  '传输承载与业务时延',
  '现场动力与备件仓储',
  '自动化调度与数据集成',
  '其他'
] as const;

export const AVAILABLE_ICONS = [
  { name: 'LayoutGrid', label: '网格看板' },
  { name: 'Cpu', label: '计算芯片/核心' },
  { name: 'Gauge', label: '仪表盘/NUR' },
  { name: 'TrendingUp', label: '趋势增长/可用率' },
  { name: 'Factory', label: '现场维修/FLM' },
  { name: 'Boxes', label: '备件库存/Warehouse' },
  { name: 'Coins', label: '成本考核' },
  { name: 'Users', label: '人员排班' },
  { name: 'Truck', label: '现场巡检' },
  { name: 'Activity', label: '网络活动/时延' },
  { name: 'UserCheck', label: '组织考核' },
  { name: 'Zap', label: '电力电池/告警' },
  { name: 'BarChart3', label: '柱状图表' },
  { name: 'PieChart', label: '饼图分析' },
  { name: 'ShieldCheck', label: '安全合规/防护' },
  { name: 'Globe', label: 'GIS拓扑/传输' },
  { name: 'Database', label: '数据表/ETL' },
  { name: 'Compass', label: 'CXO战略指引' },
  { name: 'Clock', label: '时延/MTTR' },
  { name: 'BatteryCharging', label: '电池/动环' },
  { name: 'FileSearch', label: '事件调查/Incident' },
  { name: 'UploadCloud', label: '数据上传' },
  { name: 'History', label: '归档/历史' },
  { name: 'Settings', label: '系统设置' },
  { name: 'Settings2', label: '规则配置' }
];
"""
    return header + body + tail


def bump_storage_key(app_ts_path, dry_run=False):
    """Bump liberia_noc_dashboards_vN -> vN+1 in App.tsx."""
    if not os.path.exists(app_ts_path):
        return None
    src = open(app_ts_path, encoding="utf-8").read()
    m = re.search(r"liberia_noc_dashboards_v(\d+)", src)
    if not m:
        return None
    new_ver = int(m.group(1)) + 1
    new_src = src.replace(f"liberia_noc_dashboards_v{m.group(1)}",
                          f"liberia_noc_dashboards_v{new_ver}")
    if not dry_run:
        with open(app_ts_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_src)
    return new_ver


def main():
    ap = argparse.ArgumentParser(description="把门户 UI 导出配置保存为默认配置")
    ap.add_argument("export", nargs="?", help="导出 JSON 路径(默认取门户目录最新的 enterprise-bi-dashboards-*.json)")
    ap.add_argument("--no-bump-key", action="store_true", help="不升级 STORAGE_KEY 版本号")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = ap.parse_args()

    export = args.export
    if not export:
        exports = sorted(glob.glob(os.path.join(PORTAL_D, "enterprise-bi-dashboards-*.json")),
                         key=os.path.getmtime)
        if not exports:
            print("ERROR: 门户目录里没有导出 JSON,请先在 UI 点「导出配置」")
            return 1
        export = exports[-1]
        print(f"auto-selected export: {os.path.basename(export)}")

    data = json.load(open(export, encoding="utf-8"))
    print(f"export items: {len(data)}")

    for d in data:
        assert d["themeColor"] in VALID_THEME, d["id"]
        assert d["status"] in VALID_STATUS, d["id"]
        assert d["updateFrequency"] in VALID_FREQ, d["id"]
        assert d["category"] in VALID_CATEGORIES, d["id"]
        if d["platform"] == "finebi":
            assert "/link/" in d["url"], f"finebi 无公共链接: {d['id']}"

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_ts = build_ts(data, stamp)

    targets = [PORTAL_D]
    if os.path.exists(PORTAL_Y):
        targets.append(PORTAL_Y)
    for root in targets:
        dst = os.path.join(root, "src", "data", "initialDashboards.ts")
        bak = dst + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        if not args.dry_run:
            shutil.copy2(dst, bak)
            with open(dst, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_ts)
        print(f"{'[dry-run] would write' if args.dry_run else 'WROTE'}: {dst}  backup: {os.path.basename(bak)}")

    if not args.no_bump_key:
        for root in targets:
            app_ts = os.path.join(root, "src", "App.tsx")
            ver = bump_storage_key(app_ts, dry_run=args.dry_run)
            print(f"{'[dry-run] would bump' if args.dry_run else 'bumped'} STORAGE_KEY "
                  f"{os.path.relpath(app_ts, root)} -> v{ver}" if ver else f"skip {app_ts}")

    print("\nDONE: 默认配置已保存。所有浏览器下次打开门户会自动加载新配置(旧缓存失效)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
