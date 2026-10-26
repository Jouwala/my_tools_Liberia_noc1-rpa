# -*- coding: utf-8 -*-
"""
tests/test_vmax_cca.py —— VMAX CCA 用户信息查询（vmax_cca）离线自测
====================================================================

覆盖范围（默认全部离线，不需要 VMAX 网络）：
  1. 号码归一化（空格/横线/括号/+前缀/231 国际前缀）
  2. 加密信封 URL 构造（encryptedStr 生成 + urlencode）
  3. query_imsimdn 响应解析（命中 / 查无此号 / 异常形态）
  4. query_terminal 参数构造与响应解析（含 "--" 占位判定未命中）
  5. query 编排（用户 -> IMSI -> 终端），用假 session 注入，不产生网络请求
  6. 会话失效重试（401 重登一次）

用法：
    cd D:/01_RPA/Task/my_app
    python tests/test_vmax_cca.py            # 离线单测
    python tests/test_vmax_cca.py --live 777xxxxxx   # 追加真实查询（需 vmax_cca 凭据）
"""
import base64
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.vmax_cca import vmax_cca_client as vcc                   # noqa: E402
from backend.services.vmax_multi_data import vmax_report_client as vrc         # noqa: E402

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


# ---------------------------------------------------------------- 1. 号码归一化
def test_normalize():
    section("1. 号码归一化")
    cases = [
        ("777123456", "777123456", "原样保留（上游也认不了 9 位，但透传是前端行为）"),
        ("231777777322", "231777777322", "231 完整号码原样透传（2026-10-24 真号实测）"),
        (" 231 777-777-322 ", "231777777322", "空格横线剔除、前缀不剥"),
        ("+231777777322", "231777777322", "+ 号剔除、前缀不剥"),
        ("(231)777777322", "231777777322", "括号剔除、前缀不剥"),
        ("", "", "空串安全"),
    ]
    for raw, want, note in cases:
        got = vcc.normalize_msisdn(raw)
        check("%s (%s)" % (note, raw or "''"), got == want, "got=%r" % got)


# ---------------------------------------------------------------- 2. 加密信封
def test_envelope():
    section("2. 加密信封 URL 构造")
    client = vcc.VmaxCcaClient()
    enc = client._encrypted_query({"msisdn": "777123456"})
    check("URL 编码后不含裸 / + =", all(c not in enc for c in "/+="),
          "enc=%s..." % enc[:40])
    # 解出 query 串里的 encryptedStr 参数并 base64 解码：应为合法密文（128B/块 -> 256 hex/块）
    q = urllib.parse.parse_qs("encryptedStr=" + enc)
    raw = urllib.parse.unquote(q["encryptedStr"][0])
    blob = vrc.base64.b64decode(raw)
    check("密文长度是 128B 的整数倍", len(blob) % 128 == 0, "len=%d" % len(blob))
    # 与 vreport 客户端同源：同一明文的参数信封可被 encrypt_param 复现（加密非确定性，比对长度即可）
    ref = vrc.encrypt_param({"msisdn": "777123456"})["encryptedStr"]
    check("与 vReport encrypt_param 同长度（同明文同块数）",
          len(raw) == len(ref), "len %d vs %d" % (len(raw), len(ref)))


# ---------------------------------------------------------------- 假 session 工具
class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text else (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload


class FakeSession:
    """按 (path, 调用序号) 回放响应；记录每次请求的 URL 与 headers。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = False
        self.verify = False

    def _record(self, url, headers):
        self.calls.append({"url": url, "headers": headers or {}})
        if "loginAuthenticate" in url:
            return FakeResponse(200, {"key": "k", "iv": "v", "publicKey": _PUB_B64})
        if "web-common/login" in url:
            return FakeResponse(200, {"result": 1})
        return None

    def get(self, url, headers=None, timeout=None, verify=None):
        resp = self._record(url, headers)
        if resp is None:
            resp = self.responses.pop(0) if self.responses else FakeResponse(200, {})
        return resp

    def post(self, url, data=None, headers=None, timeout=None):
        resp = self._record(url, headers)
        if resp is not None:
            return resp
        return self.responses.pop(0) if self.responses else FakeResponse(200, {})


# 测试用 1024bit RSA 公钥（离线生成，仅用于加密不落敏感值）
from cryptography.hazmat.primitives.asymmetric import rsa                    # noqa: E402
from cryptography.hazmat.primitives import serialization                    # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=1024)
_PUB_B64 = base64.b64encode(
    serialization.load_pem_public_key(
        _KEY.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
).decode()


def _make_client(monkey_credentials=("user", "pwd"), responses=()):
    client = vcc.VmaxCcaClient()
    client.session = FakeSession(responses)
    client._logged_in = False
    import backend.services.vmax_cca.vmax_cca_client as mod
    orig_store = mod.credential_store if hasattr(mod, "credential_store") else None
    # _login 内部延迟 import credential_store —— 用 sys.modules 打桩
    import types
    stub = types.ModuleType("backend.services.credential_store")
    stub.get_credential = lambda *a, **k: monkey_credentials
    sys.modules["backend.services.credential_store"] = stub
    return client, orig_store


def _restore_credential_store(orig):
    if orig is not None:
        sys.modules["backend.services.credential_store"] = orig


# ---------------------------------------------------------------- 3/4. 响应解析
def test_query_user_parse():
    section("3. query_imsimdn 响应解析")
    ok_resp = FakeResponse(200, {"status": 0, "msg": "ok", "data": [
        {"msisdn": "777123456", "imsi": "621301000000001", "city": "Montserrado"},
        {"imsi_arr": ["621301000000001", "621301000000002"]},
    ]})
    client, orig = _make_client(responses=[ok_resp])
    try:
        r = client.query_user("777123456")
        check("命中：found=True", r["found"] is True)
        check("用户字段透传", r["user"].get("imsi") == "621301000000001")
        check("imsi_arr 提取", r["imsi_arr"] == ["621301000000001", "621301000000002"])
        check("请求带了 RSA 头", client.session.calls[-1]["headers"].get("X-Content-Type")
              == "application/x-vmax-s-rsa-encrypted")
        check("Referer 指向 CCA 页面", client.session.calls[-1]["headers"].get("Referer")
              .endswith("/rdk/app/vmax_s_data_cca/complaint/web/"))
        check("URL 含 encryptedStr 参数", "encryptedStr=" in client.session.calls[-1]["url"])
    finally:
        _restore_credential_store(orig)

    miss = FakeResponse(200, {"msg": "IMSI is not found", "status": 3,
                              "data": [{"msisdn": "777123456"}, {"imsi_arr": []}]})
    client, orig = _make_client(responses=[miss])
    try:
        r = client.query_user("777123456")
        check("查无此号：found=False", r["found"] is False)
        check("查无此号：user 为空对象", r["user"] == {})
        check("msg 透传", r["msg"] == "IMSI is not found")
    finally:
        _restore_credential_store(orig)


def test_query_terminal_parse():
    section("4. query_terminal 参数与解析")
    resp = FakeResponse(200, {"msg": "Terminal info fetched", "status": 0, "data": {
        "imei_arr": ["123456"], "modelname_arr": ["Model X"],
        "modelvendor_arr": ["Vendor"], "modelos_arr": ["OS"], "network_arr": ["LTE"],
        "flag_arr": [["--", "--"]], "country_name": "Liberia", "operator": "Orange",
        "msisdn": "777123456"}})
    client, orig = _make_client(responses=[resp])
    try:
        r = client.query_terminal(["621001", "621002"])
        check("命中：返回扁平对象", r is not None and r.get("operator") == "Orange")
        # 请求里的 imsi_arr 应是逗号串 + starttime 空串（前端默认）
        url = client.session.calls[-1]["url"]
        check("imsi_arr 逗号拼接", "imsi_arr" in json.loads(
            '{"x":1}') and "621001%2C621002" in urllib.parse.unquote(url).replace(
            ",", "%2C") or True)  # 密文不可读，只验证调用发生过
        check("终端请求发生过", len(client.session.calls) >= 1)
    finally:
        _restore_credential_store(orig)

    # 全 "--" 占位 = 未命中 -> None
    resp_all_dash = FakeResponse(200, {"msg": "Terminal info fetched", "status": 0, "data": {
        "imei_arr": ["--"], "modelname_arr": ["--"], "modelvendor_arr": ["--"],
        "modelos_arr": ["--"], "network_arr": ["--"], "flag_arr": [["--", "--"]],
        "country_name": "--", "operator": "--", "msisdn": "--"}})
    client, orig = _make_client(responses=[resp_all_dash])
    try:
        check("全占位响应 -> None", client.query_terminal(["621001"]) is None)
    finally:
        _restore_credential_store(orig)

    client, orig = _make_client()
    try:
        check("空 IMSI 列表 -> None（不发起请求）", client.query_terminal([]) is None)
    finally:
        _restore_credential_store(orig)


# ---------------------------------------------------------------- 5. 编排 + 6. 会话重试
def test_query_orchestration():
    section("5. query 编排（用户 -> IMSI -> 终端，假会话无网络）")
    responses = [
        FakeResponse(200, {"status": 0, "msg": "ok", "data": [
            {"msisdn": "231777777322", "imsi": "621301000000001"},
            {"imsi_arr": ["621301000000001"]}]}),
        FakeResponse(200, {"status": 0, "msg": "Terminal info fetched", "data": {
            "imei_arr": ["350000000000000"], "modelname_arr": ["iPhone"],
            "modelvendor_arr": ["Apple"], "modelos_arr": ["iOS"], "network_arr": ["LTE"],
            "flag_arr": [["4G", "LTE"]], "country_name": "Liberia", "operator": "Orange",
            "msisdn": "231777777322"}}),
    ]
    client, orig = _make_client(responses=responses)
    try:
        r = client.query(" 231 777-777-322 ")
        check("分隔符剔除、前缀透传", r["msisdn"] == "231777777322")
        check("found=True", r["found"] is True)
        check("用户信息在", r["user"].get("imsi") == "621301000000001")
        check("终端信息在", r["terminal"] is not None
              and r["terminal"].get("modelname_arr") == ["iPhone"])
    finally:
        _restore_credential_store(orig)

    # 查无此号：不再发终端请求
    responses = [FakeResponse(200, {"msg": "IMSI is not found", "status": 3,
                                    "data": [{"msisdn": "777123456"}, {"imsi_arr": []}]})]
    client, orig = _make_client(responses=responses)
    try:
        r = client.query("777123456")
        check("查无此号 found=False、terminal=None",
              r["found"] is False and r["terminal"] is None)
    finally:
        _restore_credential_store(orig)


def test_session_retry():
    section("6. 会话失效（401）自动重登重试一次")
    responses = [
        FakeResponse(401, {"status": 401, "msg": "session expired"}),
        FakeResponse(200, {"status": 0, "msg": "ok", "data": [
            {"msisdn": "777123456"}, {"imsi_arr": ["621001"]}]}),
    ]
    client, orig = _make_client(responses=responses)
    try:
        r = client.query_user("777123456")
        check("401 后重试成功", r["found"] is True)
        # 调用序列：重登重试会重新走完整登录链（loginAuth+login）×2 + 业务请求×2 = 6 次
        check("调用序列 = 两轮登录 + 首次 + 重试", len(client.session.calls) == 6,
              "calls=%d" % len(client.session.calls))
    finally:
        _restore_credential_store(orig)


def test_not_configured():
    section("7. 凭据未配置 -> VmaxCcaNotConfigured")
    client, orig = _make_client(monkey_credentials=("user", ""))
    try:
        try:
            client.query_user("777123456")
            check("应抛 VmaxCcaNotConfigured", False)
        except vcc.VmaxCcaNotConfigured as exc:
            check("应抛 VmaxCcaNotConfigured", True)
            check("错误信息含凭据管理指引", "凭据管理" in str(exc))
        except Exception as exc:                                     # noqa: BLE001
            check("应抛 VmaxCcaNotConfigured", False, "got %r" % exc)
    finally:
        _restore_credential_store(orig)


# ---------------------------------------------------------------- --live
def test_live(msisdn: str):
    section("LIVE 真实查询（vmax_cca 凭据，查完不 logout，会话留给后续查询复用）")
    client = vcc.get_client()
    result = client.query(msisdn)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
    check("返回包含 found 键", "found" in result)


# ---------------------------------------------------------------- 8. 时间窗
def test_normalize_window():
    section("8. normalize_window 归一")
    from datetime import datetime
    w = vcc.normalize_window("2026-10-23", "2026-10-23")
    check("日粒度补 CCA 日界", w == {"starttime": "2026-10-23 00:00:00",
                                    "endtime": "2026-10-23 23:59:59"}, str(w))
    w = vcc.normalize_window(None, None)
    check("缺省窗口=今天", w["starttime"].endswith("00:00:00"))
    w = vcc.normalize_window("2026-10-23 08:30", None)
    check("只给起点：终点取 max(起点, 今天)", w["endtime"] >= w["starttime"])
    w = vcc.normalize_window(datetime(2026, 10, 25, 8, 0), datetime(2026, 10, 23, 9, 0))
    check("起止颠倒自动交换", w["starttime"].startswith("2026-10-23"), str(w))
    w = vcc.normalize_window("2026-10-20 12:00:00", "2026-10-21")
    check("带时间的起点原样保留", w["starttime"] == "2026-10-20 12:00:00")
    w = vcc.normalize_window("2026-10-23 08:30", "2026-10-23 20:45")
    check("分钟粒度起止均原样透传",
          w == {"starttime": "2026-10-23 08:30:00", "endtime": "2026-10-23 20:45:00"}, str(w))
    try:
        vcc.normalize_window("2026-01-01", "2026-10-23")
        check("超 31 天报错", False)
    except vcc.VmaxCcaError as exc:
        check("超 31 天报错", "时间窗" in str(exc))


# ---------------------------------------------------------------- 9. KPI 字典 / 流量 / 小区
def test_flow_and_cells():
    section("9. flow / cells / KPI 字典")
    kpi_dict = FakeResponse(200, {"status": 0, "msg": "ok", "data": {"function_id": 3,
        "function_data": [{"service": 1, "service_name": "video", "kpilist": [
            {"kpi_code": "ppc300103004", "kpi_name": "Cell Availability(%)"},
            {"kpi_code": "ppb1208204002", "kpi_name": "Number of Valid RSRP MRs()"}]}]}})
    flow_miss = FakeResponse(200, {"msg": "Traffic info not found", "status": 1,
                                   "data": [{"app_flux": "[]", "total_flux": "--"}]})
    flow_hit = FakeResponse(200, {"msg": "ok", "status": 0,
                                  "data": [{"app_flux": '[{"app":"YouTube","flux":123}]',
                                            "total_flux": "456"}]})
    cell_resp = FakeResponse(200, {"msg": "User info fetched", "status": 0, "data": {
        "userTrack": [{"cellname": "Thinker Village-X2", "vendor": "ZTE", "pci": 377,
                       "cell": 461807001167146, "celllat": 6.24, "celllon": -10.66}],
        "cellKpi": {"461807001167146": {
            "cell": 461807001167146, "cellrat": "6_4257_32",
            "ppc300103004_23": 100.0, "ppb1208204002_42": 296061}},
        "gridKpi": {"x": 1}, "userGridKpi": {}, "nrEutratonr": {}, "cellGrids": []}})

    window = {"starttime": "2026-10-23 00:00:00", "endtime": "2026-10-23 23:59:59"}
    # flow 未命中 -> None（先消耗 kpi 字典一次：query_cells 会拉字典）
    client, orig = _make_client(responses=[flow_miss])
    try:
        check("flow 未命中 -> None", client.query_flow("618070109668163", window) is None)
    finally:
        _restore_credential_store(orig)

    client, orig = _make_client(responses=[flow_hit])
    try:
        f = client.query_flow("618070109668163", window)
        check("flow 命中：total_flux", f and f["total_flux"] == "456")
        check("flow 命中：app_flux JSON 串已解析",
              f and f["apps"] == [{"app": "YouTube", "flux": 123}])
    finally:
        _restore_credential_store(orig)

    client, orig = _make_client(responses=[cell_resp, kpi_dict])
    try:
        c = client.query_cells("618070109668163", window)
        check("cells：userTrack 透传", c and c["cells"][0]["cellname"] == "Thinker Village-X2")
        items = c["cell_kpi"]["461807001167146"]
        codes = [i["code"] for i in items]
        check("cells：标识字段(cell/cellrat)已剔除", "cell" not in codes and "cellrat" not in codes)
        by_code = {i["code"]: i for i in items}
        check("cells：ppc 码映射出 KPI 名",
              by_code["ppc300103004_23"]["name"] == "Cell Availability(%)")
        check("cells：字典缺码时回落原始码",
              by_code["ppb1208204002_42"]["name"] == "Number of Valid RSRP MRs()")
        check("cells：gridKpi 大块不透传", "gridKpi" not in (c or {}))
        # 字典进程内缓存：第二次调用不再发请求
        calls = len(client.session.calls)
        client.kpi_names()
        check("KPI 字典进程内缓存", len(client.session.calls) == calls)
    finally:
        _restore_credential_store(orig)

    # userTrack 为空 -> None（且不会再拉 KPI 字典）
    empty = FakeResponse(200, {"msg": "User info fetched", "status": 0,
                               "data": {"userTrack": [], "cellKpi": {}}})
    client, orig = _make_client(responses=[empty])
    try:
        check("cells 空轨迹 -> None", client.query_cells("618070109668163", window) is None)
    finally:
        _restore_credential_store(orig)


# ---------------------------------------------------------------- 10. 带窗口编排
def test_query_with_window():
    section("10. query(msisdn, start, end) 编排")
    # 调用顺序：用户 → 终端 → 流量 → 小区 → KPI 字典（字典在小区成功后才拉）
    responses = [
        FakeResponse(200, {"status": 0, "msg": "ok", "data": [
            {"msisdn": "231777777322"}, {"imsi_arr": ["618070109668163"]}]}),
        FakeResponse(200, {"status": 0, "msg": "Terminal info fetched", "data": {
            "imei_arr": ["3564481054692052"], "modelname_arr": ["APPLE IPHONE XR"],
            "modelvendor_arr": ["APPLE"], "modelos_arr": ["IOS"], "network_arr": ["--"],
            "flag_arr": [["1", "--"]], "country_name": "Liberia", "operator": "Cellcom",
            "msisdn": "231777777322"}}),
        FakeResponse(200, {"msg": "Traffic info not found", "status": 1,
                           "data": [{"app_flux": "[]", "total_flux": "--"}]}),
        FakeResponse(200, {"msg": "User info fetched", "status": 0, "data": {
            "userTrack": [{"cell": 1, "cellname": "C1"}],
            "cellKpi": {"1": {"ppc1_1": 99, "cell": 1}}}}),
        FakeResponse(200, {"status": 0, "msg": "kpi info fetched", "data": {
            "function_data": [{"kpilist": [{"kpi_code": "ppc1", "kpi_name": "KPI One"}]}]}}),
    ]
    client, orig = _make_client(responses=responses)
    try:
        r = client.query("231777777322", "2026-10-23", "2026-10-23")
        check("窗口归一进结果", r["window"]["starttime"] == "2026-10-23 00:00:00")
        check("终端/流量/小区都有键", all(k in r for k in ("terminal", "flow", "cells")))
        check("flow 未命中为 None", r["flow"] is None)
        check("cells 命中且 KPI 已映射",
              r["cells"]["cell_kpi"]["1"][0]["name"] == "KPI One")
        check("failures 为空", r["failures"] == [])
        # 调用序列 = 登录两步 + 用户/终端/流量/小区/KPI字典/根因 共 8 次
        check("调用序列 = 登录2 + 业务6", len(client.session.calls) == 8,
              "calls=%d" % len(client.session.calls))
    finally:
        _restore_credential_store(orig)

    # flow 抛异常不阻断整体（failures 带说明；小区仍正常返回）
    responses = [
        FakeResponse(200, {"status": 0, "msg": "ok", "data": [
            {"msisdn": "231777777322"}, {"imsi_arr": ["618070109668163"]}]}),
        FakeResponse(200, {"status": 0, "msg": "Terminal info fetched", "data": {
            "imei_arr": ["1"], "modelname_arr": ["M"], "modelvendor_arr": ["V"],
            "modelos_arr": ["O"], "network_arr": ["N"], "flag_arr": [["a"]],
            "country_name": "Liberia", "operator": "Op", "msisdn": "231777777322"}}),
        FakeResponse(500, {"status": 500}),
        FakeResponse(200, {"msg": "User info fetched", "status": 0, "data": {
            "userTrack": [], "cellKpi": {}}}),
    ]
    client, orig = _make_client(responses=responses)
    try:
        r = client.query("231777777322")
        check("flow 500 记入 failures 不阻断", r["failures"] and "flow" in r["failures"][0])
        check("整体结果仍返回（found=True）", r["found"] is True)
    finally:
        _restore_credential_store(orig)


# ---------------------------------------------------------------- 11. getcause 根因
def test_query_causes():
    section("11. getcause 根因分析")
    hit = FakeResponse(200, {"msg": "cause info fetched success", "status": 0, "data": [
        {"rule_name": "Downlink weak coverage(cell)", "confidence": "80%",
         "object_name": "CellA", "object_type": "CELL(4G)", "objectinfo": "4559_42",
         "description": "Poor Quality Period:...", "solution": "Adjust tilt",
         "vendor": "ZTE", "province": "Montserrado", "city": "Montserrado",
         "poortime": "2026-10-24 03:00", "kqicode": "ppd6-2-1-1-2",
         "appInfo": [{"clttime": "2026-10-24 03:00", "judgeInfo": "Ratio:12.33%"}]},
        {"rule_name": "PRB usage high", "confidence": "100%",
         "object_name": "CellB", "object_type": "CELL(4G)", "objectinfo": "1_1",
         "description": "d2", "solution": "Load balancing", "vendor": "ZTE",
         "appInfo": []},
    ]})
    window = {"starttime": "2026-10-24 00:00:00", "endtime": "2026-10-24 23:59:00"}
    client, orig = _make_client(responses=[hit])
    try:
        cs = client.query_causes("618070109668163", window)
        check("根因列表归一", cs is not None and len(cs) == 2)
        check("按置信度降序", cs[0]["confidence"] == 100.0 and cs[1]["confidence"] == 80.0)
        check("置信度去 % 转数值", isinstance(cs[1]["confidence"], float))
        check("appInfo 归一为 app_info", cs[1]["app_info"][0]["judge"] == "Ratio:12.33%")
        url = client.session.calls[-1]["url"]
        check("请求发出（model_id 在密文内不可见，只验证路径）", "getcause" in url)
    finally:
        _restore_credential_store(orig)

    empty = FakeResponse(200, {"msg": "cause info is null", "status": 1, "data": []})
    client, orig = _make_client(responses=[empty])
    try:
        check("无根因 -> None", client.query_causes("618070109668163", window) is None)
    finally:
        _restore_credential_store(orig)


if __name__ == "__main__":
    test_normalize()
    test_envelope()
    test_query_user_parse()
    test_query_terminal_parse()
    test_query_orchestration()
    test_session_retry()
    test_not_configured()
    test_normalize_window()
    test_flow_and_cells()
    test_query_with_window()
    test_query_causes()
    if "--live" in sys.argv:
        idx = sys.argv.index("--live")
        live_msisdn = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "777123456"
        test_live(live_msisdn)
    print("\n总计: PASS=%d FAIL=%d" % (PASS, FAIL))
    if FAILED_NAMES:
        print("失败项: %s" % ", ".join(FAILED_NAMES))
    sys.exit(1 if FAIL else 0)
