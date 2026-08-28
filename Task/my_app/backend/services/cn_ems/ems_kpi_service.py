# -*- coding: utf-8 -*-
"""CN EMS KPI 同步服务 —— 注册到 myapp 任务体系（sync 页面可见/可调度）

背景：CN EMS (ZTE U31, 10.100.2.240) 的 SFTP 原始 PM 测量文件只保留约 1 天，
但按天粒度取 KPI 需要完整一天的文件。方案是「白天持续增量缓存 + 次日凌晨本地聚合」：

  1. run_ems_kpi_cache_sync  每15分钟：增量下载当日(UTC)测量文件到本地 _pmcache
     （只下载缺失文件，不解析，轻量；把整天数据在服务器清理前保住）
  2. run_ems_kpi_daily       每天 00:20 GMT：先 best-effort 补抓前一日窗口
     （服务器若尚未清理则补齐尾部时段），再纯本地聚合并生成
     csv_out/<模板名>.csv（与 GUI History Performance 导出同格式）
  3. run_ems_kpi_direct      按需同步查询：通过 EmsKpiQueryDirect 使用
     requestxForNonGUI 绕过异步门槛（当 SFTP 文件已被清理时使用）

数据流：EmsKpiDaily.java (fetch/parse 模式) → daily_raw.json → 公式计算 → csv_out/
模板与公式来源：Query_Template.xml + samples/*.xlsx（见 ems_kpi_templates.py）
"""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
JAVA = r"D:\ems1\ems1\jdk\jdk\windows\bin\java.exe"
CP = ".;_kpi_launcher.jar"
HOST = "10.100.2.240"
# 7 个模板涉及的全部计数器前缀（从 Query_Template.xml 归纳）
COUNTERS = "40716.|40738.|40748.|40408.|40971.|4868.|48680.|40508.|43100."
PROC_TIMEOUT = 7200  # 秒（全量解析约 10 分钟，留足余量）

# java.exe 是控制台程序：worker 以 pythonw（无控制台）运行时若不加此标志，
# Windows 会为它新建一个标题为 java.exe 路径的黑色控制台窗口（每 15 分钟弹一次）。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_java(mode, start_day, end_day):
    """运行 EmsKpiDaily 指定模式，返回 (returncode, 输出文本)"""
    args = [JAVA, "-cp", CP, "EmsKpiDaily", HOST, start_day, end_day, COUNTERS, mode]
    p = subprocess.run(args, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=PROC_TIMEOUT,
                       creationflags=_CREATE_NO_WINDOW)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _summary_from(output):
    """从 java 输出提取机器可读汇总行"""
    m = re.search(r"\[daily\] RESULT mode=(\w+) downloaded=(\d+) total_in_window=(\d+) "
                  r"parsed=(\d+) matched=(\d+)", output)
    fm = re.search(r"\[daily\] FETCH_RESULT downloaded=(\d+) total_in_window=(\d+) "
                   r"cache_files=(\d+)", output)
    if m:
        return dict(mode=m.group(1), downloaded=int(m.group(2)),
                    total_in_window=int(m.group(3)), parsed=int(m.group(4)),
                    counters_matched=int(m.group(5)))
    if fm:
        return dict(mode="fetch", downloaded=int(fm.group(1)),
                    total_in_window=int(fm.group(2)), cache_files=int(fm.group(3)))
    return {}


def run_ems_kpi_cache_sync():
    """【任务1】每15分钟：增量下载今日(UTC)原始PM测量文件到本地缓存。

    只下载缓存中缺失的文件并做完整性校验（已存在且非空则跳过），不解析、
    不写 JSON——单次运行通常仅拉取新增的几个文件。
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y/%m/%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y/%m/%d")
    rc, out = _run_java("fetch", today, tomorrow)
    if rc != 0:
        raise RuntimeError("EmsKpiDaily fetch failed rc=%s:\n%s" % (rc, out[-2000:]))
    s = _summary_from(out)
    s.update({"success": True, "window": [today, tomorrow]})
    return s


def run_ems_kpi_daily():
    """【任务2】每天 00:20 GMT：把前一个完整 UTC 日聚合成各模板日粒度 CSV。

    步骤：
      1) best-effort 补抓 [D-1 ~ D)：服务器未清理则补齐最后时段；已清理也无妨
      2) parse 模式纯本地聚合整个缓存 → daily_raw.json（不依赖服务器）
      3) ems_kpi_daily.build_csvs 按 Query_Template.xml + samples 公式出 CSV
    """
    import sys
    if HERE not in sys.path:
        sys.path.insert(0, HERE)

    now = datetime.now(timezone.utc)
    d0 = (now - timedelta(days=1)).strftime("%Y/%m/%d")  # 前一个完整 UTC 日
    d1 = now.strftime("%Y/%m/%d")

    # 1) best-effort 补抓（失败/被清理都不阻断）
    try:
        rc, out = _run_java("fetch", d0, d1)
        n = _summary_from(out).get("downloaded", 0) if rc == 0 else None
        fetch_note = "refetched=%s" % n if n is not None else "server_purged_or_error(rc=%s)" % rc
    except Exception as e:
        fetch_note = "refetch_failed(%s)" % e.__class__.__name__

    # 2) 纯本地聚合（整个缓存，多日共存时逐日分桶）
    rc, out = _run_java("parse", d0, d1)
    if rc != 0:
        raise RuntimeError("EmsKpiDaily parse failed rc=%s:\n%s" % (rc, out[-2000:]))
    ps = _summary_from(out)

    # 3) 公式计算 + CSV
    import ems_kpi_daily as D
    data = D.load_daily_raw()
    results = D.build_csvs(data)
    csvs = {}
    for name, path, n, msg in results:
        csvs[name] = ({"rows": n, "path": path} if path else {"rows": 0, "note": msg})

    return {
        "success": True,
        "window": [d0, d1],
        "fetch": fetch_note,
        "parsed_files": ps.get("parsed"),
        "counters_matched": ps.get("counters_matched"),
        "csvs": csvs,
    }


def run_ems_kpi_direct(strategy="hybrid", start_day=None, end_day=None):
    """【任务3】按需同步查询：通过 EmsKpiQueryDirect 使用 requestxForNonGUI。

    当 SFTP 原始文件已被服务器清理时，使用此模式绕过异步会话门槛。
    支持策略:
      - sync:   同步模式 (requestxForNonGUI, 不加 asyn)
      - hybrid: 先 sync, 失败则回退到 SFTP 下载 (默认)
      - sftp:   直接 SFTP 下载原始文件
    """
    now = datetime.now(timezone.utc)
    if start_day is None:
        start_day = (now - timedelta(days=1)).strftime("%Y/%m/%d")
    if end_day is None:
        end_day = now.strftime("%Y/%m/%d")

    args = [JAVA, "-cp", CP, "EmsKpiQueryDirect", HOST, "oss", "Tool123",
            start_day, end_day, strategy]
    p = subprocess.run(args, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=PROC_TIMEOUT,
                       creationflags=_CREATE_NO_WINDOW)
    output = (p.stdout or "") + (p.stderr or "")
    print(output)

    # 检查结果文件
    kpi_path = os.path.join(HERE, "kpi_result.json")
    raw_path = os.path.join(HERE, "daily_raw.json")
    if os.path.exists(kpi_path):
        with open(kpi_path, encoding="utf-8") as f:
            data = json.load(f)
        return {"success": True, "mode": "direct", "strategy": strategy,
                "window": [start_day, end_day], "result": data}
    if os.path.exists(raw_path):
        import ems_kpi_daily as D
        data = D.load_daily_raw(raw_path)
        results = D.build_csvs(data)
        csvs = {}
        for name, path, n, msg in results:
            csvs[name] = ({"rows": n, "path": path} if path else {"rows": 0, "note": msg})
        return {"success": True, "mode": "sftp", "strategy": strategy,
                "window": [start_day, end_day], "csvs": csvs}

    return {"success": False, "error": "No data produced", "window": [start_day, end_day]}


if __name__ == "__main__":
    import pprint
    pprint.pprint(run_ems_kpi_cache_sync())