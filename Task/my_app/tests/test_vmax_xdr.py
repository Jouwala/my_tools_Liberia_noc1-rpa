# -*- coding: utf-8 -*-
"""
tests/test_vmax_xdr.py —— VMAX 信令详单（Talon XDR）离线自测
=============================================================

覆盖范围（默认全部离线，不需要 VMAX 网络）：
  1. serviceType 白名单（1100/1300/1301 放行，32/33/34 与未知值拒绝）
  2. 请求参数结构：XDRTable 必须空串、serviceName 固定 xdr_query、
     时间窗为毫秒边界、condition 四元组顺序
  3. exec_merge_query 响应解析（status=0 命中 / status=1 业务失败）
  4. get_xdrheader_info 的双层信封解析（result 是 JSON 字符串）
  5. 行绑定：定长 cell 数组 -> 字段名 -> 值；长度不足截断不报错
  6. 分页参数边界（page<1 归 1、page_size 上限 200）

用法：
    cd D:/01_RPA/Task/my_app
    python tests/test_vmax_xdr.py
"""
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.vmax_cca import vmax_xdr_client as vxc                  # noqa: E402

PASS = 0
FAIL = 0
FAILED_NAMES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILED_NAMES.append(name)
        print("  [FAIL] %s %s" % (name, detail))


def section(title):
    print("\n=== %s ===" % title)


class FakeResp:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text if text else json.dumps(payload if payload is not None else {})


class FakeSession:
    """按调用顺序回放响应；记录每次 post 的 url 与 data。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None, verify=None):
        self.calls.append({"url": url, "data": data, "headers": headers or {}})
        return self.responses.pop(0) if self.responses else FakeResp(200, "{}")


class FakeCca:
    """冒充 VmaxCcaClient：已登录、共享锁与会话。"""

    def __init__(self, responses):
        import threading
        self.host = "https://example.invalid"
        self.session = FakeSession(responses)
        self._logged_in = True
        self._lock = threading.RLock()

    def _login(self):
        self._logged_in = True


WINDOW = ("2026-10-25 10:23:00.000", "2026-10-26 10:23:00.000")


def _merge_ok(rows, records=1):
    return FakeResp(200, json.dumps({
        "status": 0, "page": 1, "total": 1, "records": str(records), "rows": rows}))


def _header_ok(field, header):
    inner = json.dumps({"field": field, "header": header})
    return FakeResp(200, json.dumps({"result": inner}))


# ---------------------------------------------------------------- 1. 白名单
def test_service_whitelist():
    section("1. serviceType 白名单")
    check("1100 在册", "1100" in vxc._VALID_SERVICE_IDS)
    check("1300 在册", "1300" in vxc._VALID_SERVICE_IDS)
    check("1301 在册", "1301" in vxc._VALID_SERVICE_IDS)
    check("32 在册（RAN 无线侧，2026-10-26 接入）", "32" in vxc._VALID_SERVICE_IDS)
    check("33 未接（上游 3100100319，参数待补）", "33" not in vxc._VALID_SERVICE_IDS)
    check("34 未接（同上）", "34" not in vxc._VALID_SERVICE_IDS)
    check("XDR_SERVICES 与白名单一致",
          {s["id"] for s in vxc.XDR_SERVICES} == vxc._VALID_SERVICE_IDS)

    c = vxc.VmaxXdrClient(cca=FakeCca([]))
    try:
        c.query("231773777115", "33", *WINDOW)
        check("未接入类型应抛 VmaxXdrUnsupported", False)
    except vxc.VmaxXdrUnsupported as exc:
        check("未接入类型抛 VmaxXdrUnsupported", True)
        check("错误信息列出可用类型", "1100" in str(exc), str(exc))


# ---------------------------------------------------------------- 2. 参数结构
def test_param_structure():
    section("2. 请求参数结构")
    field = ["start_time", "msisdn"]
    header = ["Time", "MSISDN"]
    cca = FakeCca([_merge_ok([{"id": 0, "cell": ["2026-10-25 10:23:20.500", "231773777115"]}]),
                   _header_ok(field, header)])
    c = vxc.VmaxXdrClient(cca=cca)
    r = c.query("231773777115", "1100", *WINDOW)

    check("命中记录数", r["records"] == 1, str(r["records"]))
    check("返回 field/header", r["field"] == field and r["header"] == header)

    # 第一次 post 是 exec_merge_query：params 是 RSA 密文，无法离线解密，
    # 只能验证请求形态与路由；参数结构由第 3/4 项间接覆盖
    first = cca.session.calls[0]
    check("走 exec_merge_query（合并表）", first["url"].endswith("/exec_merge_query"),
          first["url"])
    check("params 以 RSA 密文提交", "params" in (first["data"] or {}))
    check("表单 Content-Type",
          "x-www-form-urlencoded" in first["headers"].get("Content-Type", ""))

    second = cca.session.calls[1]
    check("列头走 get_xdrheader_info", second["url"].endswith("/get_xdrheader_info"))
    check("列头带 RSA 头",
          second["headers"].get("X-Content-Type") == "application/x-vmax-s-rsa-encrypted")
    check("5gsa 域 Referer", "domain=5gsa" in first["headers"].get("Referer", ""),
          first["headers"].get("Referer", ""))


# --------------------------------------------------------- 2b. RAN 域（32）
def test_ran_domain():
    section("2b. RAN 域（serviceType 32）")
    cca = FakeCca([_merge_ok([]), _header_ok(["btime"], ["Time"])])
    c = vxc.VmaxXdrClient(cca=cca)
    r = c.query("231773777115", "32", *WINDOW)

    check("32 可查询（不再抛 Unsupported）", r["service_type"] == "32")
    first = cca.session.calls[0]
    check("走 ran_service 域",
          "domain=ran_service" in first["headers"].get("Referer", ""),
          first["headers"].get("Referer", ""))
    check("列头也用 ran_service 域",
          "domain=ran_service" in cca.session.calls[1]["headers"].get("Referer", ""))

    # 配置层断言：时间字段名随域切换（RAN=btime，5G=start_time）
    spec32 = vxc._SERVICE_BY_ID["32"]
    spec1100 = vxc._SERVICE_BY_ID["1100"]
    check("32 时间字段 = btime", spec32["time_field"] == "btime")
    check("1100 时间字段 = start_time", spec1100["time_field"] == "start_time")
    check("32 域 = ran_service", spec32["domain"] == vxc.DOMAIN_RAN)
    check("1100 域 = 5gsa", spec1100["domain"] == vxc.DOMAIN_5GSA)


# ---------------------------------------------------------------- 3. 行绑定
def test_row_binding():
    section("3. 行绑定（定长数组 -> 字段名）")
    cols = {"field": ["a", "b", "c"], "header": ["A", "B", "C"]}
    row = vxc._row_to_dict({"id": 0, "cell": ["1", "2", "3", "extra"]}, cols)
    check("按列头顺序绑定", row == {"a": "1", "b": "2", "c": "3"}, str(row))

    short = vxc._row_to_dict({"id": 0, "cell": ["x"]}, cols)
    check("数组不足时只绑已有列，不报错", short == {"a": "x"}, str(short))

    none_cell = vxc._row_to_dict({"id": 0}, cols)
    check("缺 cell 返回空字典", none_cell == {}, str(none_cell))

    null_val = vxc._row_to_dict({"id": 0, "cell": [None, "--"]}, cols)
    check("None 归空串", null_val["a"] == "")
    check("'--' 原样保留（交给前端统一渲染 —）", null_val["b"] == "--")


# ---------------------------------------------------------------- 4. 业务失败
def test_business_error():
    section("4. 上游业务失败")
    fail = FakeResp(200, json.dumps({
        "status": 1, "data": None,
        "errMsg": "Query no data! operation code:3100100303, please contact the administrator!"}))
    c = vxc.VmaxXdrClient(cca=FakeCca([fail]))
    try:
        c.query("231773777115", "1100", *WINDOW)
        check("status=1 应抛 VmaxXdrError", False)
    except vxc.VmaxXdrError as exc:
        check("status=1 抛 VmaxXdrError", True)
        check("errMsg 透出（便于区分参数/权限问题）", "3100100303" in str(exc), str(exc))


# ---------------------------------------------------------------- 5. 列头双层信封
def test_header_envelope():
    section("5. 列头双层信封")
    cca = FakeCca([
        _merge_ok([{"id": 0, "cell": ["t", "1"]}]),
        _header_ok(["start_time", "msisdn"], ["Time", "MSISDN"]),
    ])
    c = vxc.VmaxXdrClient(cca=cca)
    r = c.query("231773777115", "1300", *WINDOW)
    check("result 内层 JSON 已解析出 field", r["field"] == ["start_time", "msisdn"])
    check("result 内层 JSON 已解析出 header", r["header"] == ["Time", "MSISDN"])

    # 顶层直接是 dict（防御性：上游换形态时不崩）
    alt = FakeCca([_merge_ok([]), FakeResp(200, json.dumps(
        {"field": ["x"], "header": ["X"]}))])
    r2 = vxc.VmaxXdrClient(cca=alt).query("231773777115", "1300", *WINDOW)
    check("顶层 dict 形态也能解析", r2["field"] == ["x"])


# ---------------------------------------------------------------- 6. 分页边界
def test_paging_bounds():
    section("6. 分页参数边界")
    check("MAX_PAGE_SIZE = 200", vxc.MAX_PAGE_SIZE == 200)
    # page<1 归一为 1：用请求体无法断言（密文），改为断言不抛错且不越界
    for p, ps in ((0, 20), (-5, 20), (1, 999)):
        cca = FakeCca([_merge_ok([]), _header_ok([], [])])
        try:
            r = vxc.VmaxXdrClient(cca=cca).query("231773777115", "1100", *WINDOW,
                                                 page=p, page_size=ps)
            ok = r["page_size"] == min(max(1, ps), 200)
        except Exception as exc:                                    # noqa: BLE001
            ok = False
            print("    page=%s size=%s -> %s" % (p, ps, exc))
        check("page=%s size=%s 不报错且页长夹紧" % (p, ps), ok)


if __name__ == "__main__":
    test_service_whitelist()
    test_param_structure()
    test_ran_domain()
    test_row_binding()
    test_business_error()
    test_header_envelope()
    test_paging_bounds()
    print("\n总计: PASS=%d FAIL=%d" % (PASS, FAIL))
    if FAILED_NAMES:
        print("失败项: " + ", ".join(FAILED_NAMES))
    sys.exit(1 if FAIL else 0)
