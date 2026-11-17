# -*- coding: utf-8 -*-
"""eflow_wo_close 离线测试：taskId 缺失时的预检/提交闸门 + 48990049 的错误映射。

全部不联网：只 monkeypatch 掉 detail / process / woNum→woId 三处 IO。

运行：
    cd D:/01_RPA/Task/my_app
    python tests/test_eflow_wo_close.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import eflow_wo_close as wc  # noqa: E402

WO = "WO202611090037"


def _detail(task_id=None, status="WaitConfirm", op_name="Confirm", pending_op=True):
    ops = [{"id": 121495, "opName": "Confirm", "woId": 26484, "verifyKey": "OpEntity"}]
    if not pending_op:
        ops[0]["operationResult"] = "7"
    return {
        "flowEntity": {
            "woId": 26484, "woNum": WO, "status": status, "opName": op_name,
            "taskId": task_id, "procId": "p-1", "createTime": 1794229126867,
            "displayName": "4487 [Kingsville] RRU - R8862 S1800(B6A) [2pcs]",
            "candidateOperator": "G:ZTE_NOC_FO", "creator": "NOC_FO_101",
        },
        "opEntities": ops,
    }


class _Env:
    """临时替换服务层的三处 IO，退出时还原。"""

    def __init__(self, detail=None, process_body='{"message":"TaskId not exist","code":48990049}',
                 process_status="HTTP/1.1 500 Server Error"):
        self.detail_obj = detail or _detail()
        self.process_body = process_body
        self.process_status = process_status
        self.process_calls = 0

    def __enter__(self):
        self._orig = (wc._wo_id_from_num, wc.get_detail, wc._process)
        wc._wo_id_from_num = lambda wo_num: 26484
        wc.get_detail = lambda wo_id: self.detail_obj
        wc._process = self._fake_process
        return self

    def _fake_process(self, payload):
        self.process_calls += 1
        return self.process_status, self.process_body

    def __exit__(self, *exc):
        wc._wo_id_from_num, wc.get_detail, wc._process = self._orig
        return False


def test_check_flags_missing_task():
    with _Env(_detail(task_id=None)):
        r = wc.check_one(WO)
    assert r["closable"] is False, r
    assert r.get("task_missing") is True, r
    assert "48990049" in r["reason"], r["reason"]
    assert r["candidate"].startswith("G:ZTE_NOC_FO"), r
    assert r["task_id"] is None, r


def test_check_closable_when_task_present():
    with _Env(_detail(task_id=987654)):
        r = wc.check_one(WO)
    assert r["closable"] is True, r
    assert r["task_id"] == 987654, r
    assert not r.get("task_missing"), r


def test_check_rejects_wrong_status():
    with _Env(_detail(task_id=987654, status="WaitProcess", op_name="Process")):
        r = wc.check_one(WO)
    assert r["closable"] is False, r
    assert "WaitConfirm" in r["reason"], r


def test_close_does_not_call_process_without_task():
    env = _Env(_detail(task_id=None))
    with env:
        r = wc.close_one(WO)
    assert env.process_calls == 0, "没有待办任务时不应发出写请求"
    assert r["action"] == "failed", r
    assert r["error_code"] == wc.ERR_CODE_TASK_MISSING, r
    assert "48990049" in r["message"], r["message"]


def test_close_maps_server_task_error():
    """taskId 有值但服务端仍说任务不存在（任务过期）→ 保留原始返回。"""
    env = _Env(_detail(task_id=987654))
    with env:
        r = wc.close_one(WO)
    assert env.process_calls == 1, r
    assert r["action"] == "failed", r
    assert r["error_code"] == 48990049, r
    assert "eFlow 原始返回" in r["message"], r["message"]


def test_close_success_path_reads_back():
    d = _detail(task_id=987654)
    env = _Env(d, process_status="HTTP/1.1 200 OK", process_body='{"status":true}')
    calls = {"n": 0}

    def fake_detail(wo_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return d
        # 回读：已关闭
        closed = _detail(task_id=None, status="Closed", op_name="Closed", pending_op=False)
        return closed

    orig = wc.get_detail
    wc.get_detail = fake_detail
    # close_one 里有 0.8s 回读等待，测试里替换掉
    orig_sleep = wc.time.sleep
    wc.time.sleep = lambda *_: None
    try:
        with env:
            wc.get_detail = fake_detail
            r = wc.close_one(WO)
    finally:
        wc.time.sleep = orig_sleep
        wc.get_detail = orig
    assert r["action"] == "closed", r
    assert r["ok"] is True, r


def test_error_code_parser_is_forgiving():
    assert wc._error_code_of('{"message":"x","code":48990049}') == 48990049
    assert wc._error_code_of("not json") is None
    assert wc._error_code_of('{"code":"abc"}') is None


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL {name}: {e}")
    print("FAILED" if fails else "ALL PASSED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())