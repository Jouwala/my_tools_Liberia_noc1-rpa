# -*- coding: utf-8 -*-
"""
ems_kpi_query.py — ZTE U31 EMS KPI 查询统一入口 (2026-08-25 版)

【能力】
  A. 模板驱动日粒度 CSV (推荐, 当前可用):
       按 Query_Template.xml 的模板 + samples/*.xlsx 的公式,
       把每个 KPI 按天聚合, 输出 csv_out/<模板名>.csv (与 GUI 导出一致格式)。
       数据源: SFTP 原始测量文件 (EmsKpiDaily.java), 但服务器只保留最近约 1 天,
       因此该路径目前只能取最近一天; 取一个月需协议查询 (见下)。

  B. 协议查询 cmd 2720/2686 (实验性):
       通过 FServerBroker 提交模板查询; 服务端回显 queryId 但异步执行
       存在未定位的会话级门槛 (登录/JMS/回显均成功, 但不出结果文件),
       属于待攻克项。

  C. 直接同步查询 (新增, 推荐优先尝试):
       使用 EmsKpiQueryDirect 通过 requestxForNonGUI 同步提交查询,
       不加 asyn 标志, 绕过会话验证门槛。支持三种策略:
       - sync:   同步模式 (首选, requestxForNonGUI 不加 asyn)
       - hybrid: 先尝试 sync, 失败则回退到 SFTP 下载 (默认)
       - sftp:   直接 SFTP 下载原始文件 (同 EmsKpiDaily)

用法:
  python ems_kpi_query.py --mode daily --start 2026/08/24 --end 2026/08/26
        # 按模板输出最近窗口的日粒度 CSV (数据源: SFTP 原始文件)
  python ems_kpi_query.py --mode daily --reuse
        # 复用已有的 daily_raw.json 直接重建 CSV (不联网, 秒级)
  python ems_kpi_query.py --mode direct --start 2026/08/24 --end 2026/08/25
        # 直接同步查询 (requestxForNonGUI, 绕过异步门槛)
  python ems_kpi_query.py --mode direct --strategy sftp --start ...
        # 强制 SFTP 下载
  python ems_kpi_query.py --mode protocol --start 2026/08/24 --end 2026/08/25
        # cmd 2720 协议路径 (实验性, 推荐用 direct 替代)
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JDK = r"D:\ems1\ems1\jdk\jdk\windows\bin\java.exe"
CP = ".;_kpi_launcher.jar"

# java.exe 是控制台程序：从 pythonw（无控制台）的 worker 里拉起时若不加此标志，
# Windows 会为它新建一个标题为 java.exe 路径的黑色控制台窗口。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def build_csvs_from_existing():
    """复用已有 daily_raw.json 直接重建 CSV (不联网)"""
    raw_path = os.path.join(HERE, "daily_raw.json")
    if not os.path.exists(raw_path):
        print("[!] daily_raw.json 不存在, 请先运行 --mode daily (不带 --reuse)")
        return None
    import ems_kpi_daily as D
    data = D.load_daily_raw(raw_path)
    results = D.build_csvs(data)
    print("\n[daily] CSV outputs:")
    for name, path, n, msg in results:
        print("  %-36s rows=%-4s %s" % (name, n, msg if path is None else path))
    return results


def run_daily(host, start, end, counters=None):
    """通路A-日: SFTP 原始文件按天聚合 → 公式计算 → <模板名>.csv"""
    if counters is None:
        # 7 个模板涉及的全部 poid 前缀 (从 Query_Template.xml 归纳)
        counters = ("40716.|40738.|40748.|40408.|40971.|4868.|48680.|40508.|43100.")
    args = [JDK, "-cp", CP, "EmsKpiDaily", host, start, end, counters]
    print("[run] " + " ".join(args))
    p = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=_CREATE_NO_WINDOW)
    for line in p.stdout:
        try:
            sys.stdout.write(line.decode("utf-8", errors="replace"))
        except Exception:
            pass
    rc = p.wait()
    raw_path = os.path.join(HERE, "daily_raw.json")
    if rc != 0 or not os.path.exists(raw_path):
        print("[!] EmsKpiDaily failed rc=%s" % rc)
        return None
    # 公式计算 + CSV
    import ems_kpi_daily as D
    data = D.load_daily_raw(raw_path)
    results = D.build_csvs(data)
    print("\n[daily] CSV outputs:")
    for name, path, n, msg in results:
        print("  %-36s rows=%-4s %s" % (name, n, msg if path is None else path))
    return results


def run_direct(host, user, pwd, start, end, strategy="hybrid"):
    """通路C: 直接同步查询 (EmsKpiQueryDirect, requestxForNonGUI)

    strategy: sync | jms | sftp | hybrid
    """
    args = [JDK, "-cp", CP, "EmsKpiQueryDirect", host, user, pwd, start, end, strategy]
    print("[run] " + " ".join(args))
    p = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=_CREATE_NO_WINDOW)
    for line in p.stdout:
        try:
            sys.stdout.write(line.decode("utf-8", errors="replace"))
        except Exception:
            pass
    rc = p.wait()

    # 检查结果: 可能输出到 kpi_result.json 或 daily_raw.json
    kpi_path = os.path.join(HERE, "kpi_result.json")
    raw_path = os.path.join(HERE, "daily_raw.json")
    if os.path.exists(kpi_path):
        with open(kpi_path, encoding="utf-8") as f:
            return json.load(f)
    if os.path.exists(raw_path):
        print("[direct] raw data -> daily_raw.json")
        import ems_kpi_daily as D
        data = D.load_daily_raw(raw_path)
        results = D.build_csvs(data)
        print("\n[direct] CSV outputs:")
        for name, path, n, msg in results:
            print("  %-36s rows=%-4s %s" % (name, n, msg if path is None else path))
        return {"success": True, "source": "sftp", "csvs": results}
    print("[!] no result file (direct query did not produce data, rc=%s)" % rc)
    return None


def run_protocol(host, user, pwd, start, end):
    """通路B: cmd 2720 协议路径 (实验性: 推荐用 direct 替代)"""
    args = [JDK, "-cp", CP, "EmsKpiQuery", host, user, pwd, start, end, "2720", "noasyn,replay"]
    print("[run] " + " ".join(args))
    p = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=_CREATE_NO_WINDOW)
    for line in p.stdout:
        try:
            sys.stdout.write(line.decode("utf-8", errors="replace"))
        except Exception:
            pass
    rc = p.wait()
    dst = os.path.join(HERE, "kpi_result.json")
    if os.path.exists(dst):
        with open(dst, encoding="utf-8") as f:
            return json.load(f)
    print("[!] no result file (protocol path did not produce rows, see log)")
    return None


def main():
    ap = argparse.ArgumentParser(description="U31 EMS KPI query (template-driven daily CSV)")
    ap.add_argument("--mode", choices=["daily", "protocol", "direct"], default="daily")
    ap.add_argument("--host", default="10.100.2.240")
    ap.add_argument("--user", default="oss")
    ap.add_argument("--pwd", default="Tool123")
    ap.add_argument("--start", default=None, help="yyyy/MM/dd GMT inclusive")
    ap.add_argument("--end", default=None, help="yyyy/MM/dd GMT exclusive")
    ap.add_argument("--counters", default=None, help="raw counter substrings '|' separated")
    ap.add_argument("--reuse", action="store_true",
                    help="daily 模式: 复用已有 daily_raw.json 直接重建 CSV")
    ap.add_argument("--strategy", choices=["sync", "jms", "sftp", "hybrid"], default="hybrid",
                    help="direct 模式: 查询策略 (默认 hybrid, 先同步后SFTP)")
    a = ap.parse_args()

    if not a.start or not a.end:
        import datetime
        now = datetime.datetime.utcnow()
        a.end = now.strftime("%Y/%m/%d")
        a.start = (now - datetime.timedelta(days=1)).strftime("%Y/%m/%d")

    if a.mode == "daily":
        if a.reuse:
            build_csvs_from_existing()
        else:
            run_daily(a.host, a.start, a.end, a.counters)
    elif a.mode == "direct":
        run_direct(a.host, a.user, a.pwd, a.start, a.end, a.strategy)
    else:
        run_protocol(a.host, a.user, a.pwd, a.start, a.end)


if __name__ == "__main__":
    main()