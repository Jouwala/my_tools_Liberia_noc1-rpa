#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
clone_doctor.py —— 新克隆环境自检（一条命令回答「我还缺什么」）

背景
----
本仓库有大量「运行时必需但刻意不入库」的资产（见 `docs\\新机器部署清单.md`）：
PostgreSQL 数据库、`data\\` 派生库、`nginx` 配置、`backend\\.env`、前端构建产物等。
它们各自缺失时的**故障现象完全不同，且大多不明显**：

  · 缺 `_fe_dist`        → 后端**照常启动**，只是 `main.py` 不挂静态目录 → 前端白屏
  · 缺 `data\\`           → 页面能开、上排卡片空 → 看起来像"今天没数据"
  · 连不上 PG            → /api/health 仍返回 200，但各业务端点报错或空
  · 装错解释器           → watchdog 起来就 ImportError 退出，只报"45s 内未监听"

这个脚本把这些隐性缺失变成一份**可读的清单**：每项标明状态、为什么需要、
以及缺了该怎么补。它**只读**，不修改任何东西、不写任何文件、不启动任何服务。

用法
----
    python scripts\\clone_doctor.py            # 人类可读报告
    python scripts\\clone_doctor.py --json     # 机器可读（给 CI / 其他 agent 用）
    python scripts\\clone_doctor.py --quiet    # 只打印 FAIL 项，有 FAIL 时退出码 1

退出码：0 = 无 FAIL（WARN 允许）；1 = 有 FAIL；2 = 脚本自身出错。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
from pathlib import Path

# ---------- 路径基准：本文件在 <my_app>/scripts/ 下 ----------
MY_APP = Path(__file__).resolve().parent.parent
REPO_ROOT = MY_APP.parent.parent          # D:\01_RPA
PORTAL = REPO_ROOT / "liberia-noc_soc-数据看板统一门户"
NGINX = REPO_ROOT / "nginx-1.28.0"

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"

# 结果收集：(状态, 名称, 说明, 修复建议)
RESULTS: list[tuple[str, str, str, str]] = []


def add(status: str, name: str, detail: str, fix: str = "") -> None:
    RESULTS.append((status, name, detail, fix))


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def dir_size(p: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


# =========================================================================
# 1) Python 解释器与依赖 —— 对应「装错地方」那个坑
# =========================================================================
def check_python() -> None:
    import importlib.util

    required = ["fastapi", "uvicorn", "sqlalchemy"]
    missing = [m for m in required if importlib.util.find_spec(m) is None]
    if missing:
        add(
            FAIL,
            "Python 依赖",
            f"当前解释器缺: {', '.join(missing)}",
            f"pip install -r requirements.txt  （当前解释器: {sys.executable}）",
        )
    else:
        add(OK, "Python 依赖", f"fastapi/uvicorn/sqlalchemy 就绪（{sys.executable}）")

    # 本仓库特有的坑：仓库内 Scripts\ / .venv\ 不是后端在用的解释器
    for venv in (MY_APP / ".venv", MY_APP / "Scripts"):
        exe = venv / ("python.exe" if os.name == "nt" else "bin/python")
        if not exe.exists():
            continue
        note = ""
        if venv.name == "Scripts":
            note = "（这是 8787 FMS 实时代理用的 venv，不含后端依赖 —— 属正常）"
        if Path(sys.executable).resolve() != exe.resolve():
            add(
                WARN,
                f"未使用的虚拟环境 {venv.name}/",
                f"存在但当前没在用{note}",
                "确认依赖装进了**当前**解释器，而不是这里",
            )

    # psycopg2 只在 pg 模式下需要
    if importlib.util.find_spec("psycopg2") is None:
        add(WARN, "psycopg2", "未安装：若 MY_APP_DB_MODE=pg 将无法连接数据库",
            "pip install psycopg2-binary")


# =========================================================================
# 2) 配置文件 backend/.env
# =========================================================================
def check_env() -> dict:
    env_path = MY_APP / "backend" / ".env"
    example = MY_APP / "backend" / ".env.example"
    values: dict[str, str] = {}

    if not env_path.exists():
        add(
            FAIL,
            "backend/.env",
            "不存在 —— 后端将使用代码内默认值（多半连不上库）",
            "copy backend\\.env.example backend\\.env 然后填真实值"
            "（注意：该文件含凭据，**不入库**，需从原机器拷）",
        )
        return values

    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    except OSError as e:
        add(FAIL, "backend/.env", f"读取失败: {e}", "")
        return values

    add(OK, "backend/.env", f"存在，{len(values)} 个键")

    # 与 example 比对，提示漏配的键（只比键名，不打印值）
    if example.exists():
        ex_keys = set()
        for line in example.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                ex_keys.add(line.split("=", 1)[0].strip())
        absent = sorted(ex_keys - set(values))
        if absent:
            add(WARN, "backend/.env 未覆盖的键", f"{len(absent)} 个: {', '.join(absent[:8])}"
                + (" ..." if len(absent) > 8 else ""),
                "多数有代码默认值；按需从 .env.example 补齐")
    return values


# =========================================================================
# 3) 数据库 —— 本项目最大的坑：真数据在 PG，不在 db/app.db
# =========================================================================
def check_database(env_values: dict) -> None:
    mode = (env_values.get("MY_APP_DB_MODE") or os.environ.get("MY_APP_DB_MODE") or "").strip().lower()

    if mode == "pg":
        if not port_open("127.0.0.1", 5432):
            add(FAIL, "PostgreSQL (5432)",
                "MY_APP_DB_MODE=pg 但 5432 没有服务在监听",
                "启动 postgresql 服务；或用 pg_restore 从原机器迁库"
                "（见 docs\\新机器部署清单.md §3.3）")
        else:
            # 端口通不代表库有数据。
            # ⚠ 2026-10-03 修正：本库的表**不在 public**！实测 `show search_path` 为
            #   app, eflow, lte_pl, battery, ms_sla, fw, ipran_ume, ran_ume, public
            #   业务表分散在 app / eflow / lte_pl 等多个 schema 里，最初只查
            #   information_schema(public) 会得到 0 张表，**把有数据的库误判成空库**。
            #   改为按 search_path 逐 schema 统计，并用 n_live_tup 估行数。
            try:
                import psycopg2  # type: ignore
                url = env_values.get("DATABASE_URL", "")
                conn = psycopg2.connect(url, connect_timeout=5)
                cur = conn.cursor()
                cur.execute("show search_path")
                schemas = [s.strip() for s in cur.fetchone()[0].split(",") if s.strip()]
                cur.execute(
                    "select count(*) from pg_stat_user_tables "
                    "where schemaname = any(%s)", (schemas,))
                tables = cur.fetchone()[0]
                cur.execute(
                    "select count(*) from pg_stat_user_tables "
                    "where schemaname = any(%s) and n_live_tup > 0", (schemas,))
                nonempty = cur.fetchone()[0]
                cur.execute(
                    "select coalesce(sum(n_live_tup),0) from pg_stat_user_tables "
                    "where schemaname = any(%s)", (schemas,))
                rows = cur.fetchone()[0]
                conn.close()
                scope = "/".join(schemas)
                if tables == 0:
                    add(FAIL, "PostgreSQL 库内容",
                        f"连上了但 {scope} 下**一张表都没有** —— 迁移没跑或库是空的",
                        "alembic upgrade head；若要有真实数据则需从原机器 pg_dump/pg_restore")
                elif rows == 0:
                    add(WARN, "PostgreSQL 库内容",
                        f"{tables} 张表但**全部为空**（仅有结构，schema: {scope}）",
                        "迁移只建表、零 INSERT，页面要显示内容仍需导入真实数据")
                else:
                    add(OK, "PostgreSQL 库内容",
                        f"{tables} 张表 / 约 {rows:,} 行（schema: {scope}）")
            except ImportError:
                add(WARN, "PostgreSQL 连通性",
                    "端口在听，但没装 psycopg2，无法确认库内容",
                    "pip install psycopg2-binary")
            except Exception as e:  # noqa: BLE001 - 连接失败原因多样，统一呈现
                add(FAIL, "PostgreSQL 连接",
                    f"{type(e).__name__}: {str(e)[:120]}",
                    "核对 backend\\.env 的 DATABASE_URL；库未建时先 createdb")
    elif mode == "sqlite":
        db = MY_APP / "db" / "app.db"
        if db.exists():
            add(OK, "SQLite db/app.db", f"{human(db.stat().st_size)}")
        else:
            add(FAIL, "SQLite db/app.db",
                "MY_APP_DB_MODE=sqlite 但文件不存在",
                "从原机器拷贝 db\\app.db（约 1.5GB，不入库）")
    else:
        add(WARN, "数据库模式",
            f"MY_APP_DB_MODE 未设置（读到 '{mode}'）",
            "在 backend\\.env 里显式设置 pg 或 sqlite")


# =========================================================================
# 4) data/ 派生数据仓 —— 缺了表现为「页面能开但卡片空」
# =========================================================================
def check_data_dir() -> None:
    data = MY_APP / "data"
    if not data.is_dir():
        add(FAIL, "data/ 目录",
            "不存在 —— 多个看板的上排卡片会显示为空（页面本身能打开）",
            "从原机器拷贝 Task\\my_app\\data\\（约 1.8GB，被**根** .gitignore 的 data/ 忽略）")
        return

    size = dir_size(data)
    # 这些是被页面直读的关键库；缺哪个就点名哪个。
    # ⚠ 2026-10-03 修正：路径必须带子目录。最初只查 data/ 根目录，
    #   把 olib_soc_report.sqlite3 误报为缺失 —— 实际它在 data/olib_soc_report/ 下
    #   （见 backend/services/olib_soc_report/olib_soc_kpi_store.py:36-37
    #    的 DATA_DIR = _ROOT/"data"/"olib_soc_report"）。同理 eflow / ms_sla /
    #   packet_lost / ran_ume 等也各自有子目录。
    #   键写成相对 data/ 的路径，值是该库服务的页面。
    critical = {
        "olib_soc_report/olib_soc_report.sqlite3": "/api/olib-soc-dashboard/overview",
        "ran_kpi_avalability_1day.sqlite3": "可用率页",
        "bp_report.sqlite3": "bp_report 页",
        "eflow/eflow.sqlite3": "eFlow 相关页",
        "packet_lost/lte_pl.sqlite3": "丢包页",
        "ms_sla/lbr_ms_sla_kpi.sqlite3": "MS SLA 看板",
    }
    missing = [f for f in critical if not (data / f).exists()]
    if missing:
        names = "、".join(f"{f}（{critical[f]}）" for f in missing)
        add(WARN, "data/ 关键库缺失",
            f"{names}；目录当前 {human(size)}",
            "从原机器补拷这些 sqlite3 文件（保持相同的子目录结构）")
    else:
        add(OK, "data/ 目录", f"{human(size)}，{len(critical)} 个关键库齐全")


# =========================================================================
# 5) 前端构建产物
# =========================================================================
def check_fe_dist() -> None:
    fe = REPO_ROOT / "Task" / "_fe_dist"
    if not fe.is_dir() or not (fe / "index.html").exists():
        add(FAIL, "_fe_dist 前端产物",
            "不存在或缺 index.html —— 后端会照常启动但不挂静态目录 → 前端白屏",
            "cd Task\\my_app\\frontend && npm ci && npm run build"
            "（产物必须落 _fe_dist）")
        return
    assets = fe / "assets"
    n = len(list(assets.glob("*.js"))) if assets.is_dir() else 0
    add(OK, "_fe_dist 前端产物", f"index.html 存在，assets 下 {n} 个 js")


# =========================================================================
# 6) nginx —— 配置已入库为参考副本，二进制与瓦片仍需手工
# =========================================================================
def check_nginx() -> None:
    if not NGINX.is_dir():
        add(FAIL, "nginx-1.28.0/",
            "整目录不存在（被根 .gitignore:264 忽略，**不入库**）",
            "从 nginx.org 下载同版本解压到 D:\\01_RPA\\nginx-1.28.0，"
            "再用 docs\\nginx-reference\\ 的三份配置覆盖 conf\\")
        return

    add(OK, "nginx-1.28.0/", "发行包存在")

    conf = NGINX / "conf" / "nginx.conf"
    if conf.exists():
        text = conf.read_text(encoding="utf-8", errors="replace")
        # 每个页面入口都是新机器最容易漏的点，逐个点名。
        # ⚠ 2026-10-03 修正：不能只匹配 `location <path>` 字面 ——
        #   /tiles/ 那条写的是 `location ^~ /tiles/`（`^~` 是**必要**的，
        #   nginx.conf 注释解释了原因：正则 location 优先级高于普通前缀，
        #   将来瓦片若被命名成 liberia_bak_*.pmtiles 会被 B5 的 deny 规则 404 掉）。
        #   用正则允许 location 与路径之间存在 ^~ / = / ~ 等修饰符。
        import re as _re
        for loc, desc in (
            ("/v1/olbrportal/", "v1 门户页"),
            ("/olbrportal/", "olbrportal 页"),
            ("/MsPortal/", "MsPortal 静态壳"),
            ("/api/", "my_app 后端反代"),
            ("/tiles/", "GIS 瓦片"),
        ):
            pat = _re.compile(
                r"location\s+(?:[\^~=]+\s+|\s)*" + _re.escape(loc))
            if not pat.search(text):
                add(WARN, f"nginx.conf 缺 {loc}", f"{desc} 的路由不在配置里",
                    "用 docs\\nginx-reference\\nginx.conf.txt 覆盖 conf\\nginx.conf")
        add(OK, "nginx.conf 路由", "关键 location 检查完成")
    else:
        add(FAIL, "nginx.conf", "不存在",
            "用 docs\\nginx-reference\\nginx.conf.txt 覆盖到 conf\\nginx.conf")

    tiles = NGINX / "html" / "tiles" / "liberia.pmtiles"
    if not tiles.exists():
        add(WARN, "GIS 瓦片 liberia.pmtiles",
            "不存在 → GIS 地图全白（29MB，不入库）",
            "从原机器拷 nginx-1.28.0\\html\\tiles\\liberia.pmtiles")
    else:
        add(OK, "GIS 瓦片", human(tiles.stat().st_size))

    cert = NGINX / "certs" / "portal.crt"
    if not cert.exists():
        add(WARN, "HTTPS 证书 certs/",
            "不存在 → 443 起不来（配置里 80 会 301 到 https）",
            "从原机器拷 certs\\，或自签一对同名证书")


# =========================================================================
# 7) 门户（9267）
# =========================================================================
def check_portal() -> None:
    if not PORTAL.is_dir():
        add(FAIL, "门户目录", f"不存在: {PORTAL}", "确认仓库完整")
        return
    nm = PORTAL / "node_modules"
    if not nm.is_dir():
        add(FAIL, "门户 node_modules/",
            "不存在 → 9267 起不来，/uniplam/ 与 /uniplam/api/auth/*（登录）全挂",
            "cd liberia-noc_soc-数据看板统一门户 && npm ci")
    else:
        add(OK, "门户 node_modules/", "已安装")

    # /v1/olbrportal/ 依赖 MsPortal 的静态资产，二者都在库里，但值得确认
    for rel in ("v1/olbrportal/index.html", "MsPortal/assets/data.js",
                "olbrportal/assets/olbr.js"):
        if not (PORTAL / rel).exists():
            add(FAIL, f"门户静态壳 {rel}",
                "缺失 —— 本应是**已跟踪**的源码，说明仓库不完整",
                "git status 检查是否被误删；重新 clone")

    auth = PORTAL / "auth-data"
    if not auth.is_dir():
        add(WARN, "门户 auth-data/",
            "不存在 → 首次启动会自动播种 admin（随机口令写入 "
            "auth-data\\initial-admin-password.txt），但**历史账号与看板权限全丢**",
            "要原样还原则从原机器连 -wal/-shm 一起拷（该目录含密码哈希，严禁入库）")
    else:
        add(OK, "门户 auth-data/", "存在")


# =========================================================================
# 8) 服务运行状态（警告级：自检通常在启动前跑）
# =========================================================================
def check_services() -> None:
    for port, name in ((5432, "PostgreSQL"), (7038, "my_app 后端"),
                       (7090, "my_app 前端"), (9267, "门户 9267"),
                       (80, "nginx 80"), (443, "nginx 443")):
        if port_open("127.0.0.1", port):
            add(OK, f"端口 {port}", f"{name} 在监听")
        else:
            add(SKIP, f"端口 {port}", f"{name} 未监听（自检可在启动前运行，非错误）")


# =========================================================================
# 主流程
# =========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="新克隆环境自检（只读，不修改任何东西）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quiet", action="store_true", help="只打印 FAIL 项")
    args = ap.parse_args()

    try:
        check_python()
        env_values = check_env()
        check_database(env_values)
        check_data_dir()
        check_fe_dist()
        check_nginx()
        check_portal()
        check_services()
    except Exception as e:  # noqa: BLE001
        print(f"自检脚本自身出错: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    fails = [r for r in RESULTS if r[0] == FAIL]
    warns = [r for r in RESULTS if r[0] == WARN]

    if args.json:
        print(json.dumps({
            "my_app": str(MY_APP),
            "python": sys.executable,
            "results": [{"status": s, "name": n, "detail": d, "fix": f}
                        for s, n, d, f in RESULTS],
            "counts": {"ok": len(RESULTS) - len(fails) - len(warns),
                       "warn": len(warns), "fail": len(fails)},
        }, ensure_ascii=False, indent=2))
        return 1 if fails else 0

    icon = {OK: "[OK]  ", WARN: "[WARN]", FAIL: "[FAIL]", SKIP: "[--]  "}
    if not args.quiet:
        print("=" * 74)
        print(" 新克隆环境自检 —— 新机器部署清单的机器可验证版本")
        print(f" my_app : {MY_APP}")
        print(f" python : {sys.executable}")
        print("=" * 74)

    for status, name, detail, fix in RESULTS:
        if args.quiet and status != FAIL:
            continue
        print(f"{icon[status]} {name}")
        if detail:
            print(f"        {detail}")
        if fix and status in (FAIL, WARN):
            print(f"        → {fix}")

    if not args.quiet:
        print("=" * 74)
        print(f" 汇总: {len(fails)} FAIL / {len(warns)} WARN "
              f"/ {len(RESULTS) - len(fails) - len(warns)} OK")
        if fails:
            print(" 先解决 FAIL 项；完整说明见 docs\\新机器部署清单.md")
        else:
            print(" 无 FAIL —— 环境基本可用。WARN 项按需处理。")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
