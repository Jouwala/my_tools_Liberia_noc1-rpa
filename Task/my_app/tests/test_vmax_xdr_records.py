# -*- coding: utf-8 -*-
"""XDR Records 分表查询的协议守卫（纯离线，不碰上游、不连库）。

为什么要有这个文件：
    分表查询的参数结构（`XDRTable` 填表名、不传 `serviceName`、`colModel`
    回填列名、列头走 `queryType=1`）是从前端 `show_table_module.js` 复刻的，
    上游对参数错配只回一个 `3100100303`，看不出是哪一项错。
    2026-10-27 接入时又赶上 VMAX 门户会话被探测占满，没法反复真机试错，
    于是把这几个约束固化成本文件的断言：改坏了立刻红，不用等线上报「无数据」。

运行：
    cd D:/01_RPA/Task/my_app
    python tests/test_vmax_xdr_records.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows 控制台默认 cp1252，中文断言名会直接抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.services.vmax_cca import vmax_xdr_client as mod   # noqa: E402
from backend.services.vmax_cca.vmax_xdr_client import (        # noqa: E402
    DOMAIN_RAN, VmaxXdrClient, VmaxXdrUnsupported, _build_condition,
)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


def test_condition_fields():
    """域不同 -> 时间字段与号码字段名必须跟着变；号码条件类型固定为 1。

    号码条件如果退回 `type="6"`（页面组件的 SELECT_INPUT 类型），上游既不报错
    也不按号码过滤 —— 分表查询会回 3100100202（有数据却说没数据），合并查询
    会把整窗数据全吐出来。详见 `_build_condition` 的 docstring。
    """
    print("[1] condition 字段随域变化")
    ran = _build_condition({"domain": DOMAIN_RAN, "time_field": "btime"},
                           "32", "231773777115",
                           "2026-10-27 08:00:00.000", "2026-10-27 10:00:00.000")
    check("RAN 时间字段是 btime", ran[0]["field"] == "btime", ran[0])
    check("RAN 号码列是隐藏列 $msisdn", ran[3]["field"] == "$msisdn", ran[3])
    check("RAN 号码字段名是 User Number", ran[3]["name"] == "User Number", ran[3])
    check("RAN 号码条件用文本类型 1", ran[3]["type"] == "1", ran[3])
    check("serviceType 条件取请求值", ran[1]["value"] == "32", ran[1])

    five = _build_condition({"domain": "5gsa", "time_field": "start_time"},
                            "1100", "231773777115",
                            "2026-10-27 08:00:00.000", "2026-10-27 10:00:00.000")
    check("5gsa 时间字段是 start_time", five[0]["field"] == "start_time", five[0])
    check("5gsa 号码列是 msisdn", five[3]["field"] == "msisdn", five[3])
    check("5gsa 号码字段名是 MSISDN", five[3]["name"] == "MSISDN", five[3])
    check("5gsa 号码条件用文本类型 1（不能用组件类型 6）", five[3]["type"] == "1", five[3])


def test_table_whitelist():
    """表名必须来自 get_tabinfo 清单：XDRTable 会进上游 SQL 的 FROM。"""
    print("[2] 表名白名单")
    c = VmaxXdrClient.__new__(VmaxXdrClient)
    c.tables = lambda sid: [{"table_name": "fact_lte_uemr", "xdr_name": "UEMR_XDR"}]
    try:
        c.query_table("231773777115", "32", "fact_lte_uemr; DROP TABLE x",
                      "2026-10-27 08:00:00.000", "2026-10-27 10:00:00.000")
        check("非法表名被拒", False, "没有抛错")
    except VmaxXdrUnsupported as exc:
        check("非法表名被拒", "不属于 serviceType" in str(exc), str(exc))
    except Exception as exc:                                        # noqa: BLE001
        check("非法表名被拒", False, "抛了别的异常: %r" % exc)


def test_query_payload_shape():
    """query_table 的报文字段：XDRTable=表名、无 serviceName、colModel=列名。"""
    print("[3] 分表报文字段")
    captured = {}
    c = VmaxXdrClient.__new__(VmaxXdrClient)
    c.tables = lambda sid: [{"table_name": "fact_lte_uemr", "xdr_name": "UEMR_XDR"}]
    c.fetch_headers = lambda st, condition=None, domain=None, table="": {
        "field": ["btime", "imsi", "$msisdn"], "header": ["Time", "IMSI", "MSISDN"]}
    c._post = lambda path, data, domain=None, retry_on_session=True: captured.update(
        {"path": path, "data": data, "domain": domain}) or {
        "status": 0, "page": 1, "total": 1, "records": 1,
        "rows": [{"id": 0, "cell": ["2026-10-27 09:00:00.000", "123", "231773777115"]}]}

    # 把 RSA 加密换掉，才能断言明文参数（真实链路仍然走 _encrypt）
    mod._encrypt = lambda obj: json.dumps(obj, ensure_ascii=False)
    try:
        out = c.query_table("231773777115", "32", "UEMR_XDR",
                            "2026-10-27 08:00:00.000", "2026-10-27 10:00:00.000")
    finally:
        import importlib
        importlib.reload(mod)                                       # 还原 _encrypt

    param = json.loads(captured["data"]["params"])
    check("走 exec_query", captured["path"] == "exec_query", captured["path"])
    check("XDRTable 是表名", param.get("XDRTable") == "fact_lte_uemr", param.get("XDRTable"))
    check("不传 serviceName", "serviceName" not in param, list(param))
    check("colModel 是列名数组", param.get("colModel") == ["btime", "imsi", "$msisdn"],
          param.get("colModel"))
    check("isFirst 首页为 True", param.get("isFirst") is True, param.get("isFirst"))
    check("domain 用 RAN", captured["domain"] == DOMAIN_RAN, captured["domain"])
    check("返回 table_label 用 xdr_name", out.get("table_label") == "UEMR_XDR", out.get("table_label"))
    check("行按列头绑定字段", out["rows"][0].get("imsi") == "123", out["rows"][0])


def main():
    test_condition_fields()
    test_table_whitelist()
    test_query_payload_shape()
    print()
    if FAILS:
        print("FAILED: %d 项 -> %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
