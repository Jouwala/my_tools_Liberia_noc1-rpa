# -*- coding: utf-8 -*-
"""tests/test_vmax_diagnosis_stream.py —— 按源渐进渲染（P3-1）的离线守卫
=============================================================================

为什么要有这个文件（2026-11-07，续做 ZCode「CCA优化」会话的 P3-1）：
    诊断是四个源**串行**取、总耗时 ≈21s（1300 约 12s 是瓶颈，见
    services/vmax_cca/vmax_diagnosis.py 模块头）。新增 SSE 端点
    `GET /api/vmax-diagnosis/stream` 让前端每跑完一个源就渲染一帧。
    这套编排有三处最容易被后续改动弄坏、且**线上很难肉眼发现**：

      1. 事件顺序与「done 必须最后」—— 前端靠 done 才敢出结论；
      2. RAN(32) 必须用 1300/1100 解析出的 IMSI 查（模块头纪律 2），
         传空就恒 0 条，看起来像「用户没数据」；
      3. 单源失败隔离 —— 一个源挂了其余三个照常推，不能整条流断掉。

    另外 `fetch_all()` 被重构成消费 `iter_sources()`，必须断言两者
    **口径一致**（源顺序、window、imsi、默认字段），否则老接口悄悄变脸。

运行：
    cd D:/01_RPA/Task/my_app
    python tests/test_vmax_diagnosis_stream.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows 控制台默认 cp1252，中文断言名会直接抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi import HTTPException                                            # noqa: E402

from backend.routers.vmax_diagnosis import (                                # noqa: E402
    _iter_stream_frames, _resolve_window, _sse_frame,
)
from backend.services.vmax_cca.vmax_diagnosis import (                      # noqa: E402
    DONE_EVENT, SOURCE_EVENT, VmaxDiagnosis,
)

MSISDN = "231777777322"
START = "2026-11-07 09:00:00"
END = "2026-11-07 11:00:00"
IMSI = "231010123456789"

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILS.append(name)


class FakeXdr:
    """假 XDR 客户端：按 service_type 返回固定行，并记录调用（不打上游）。"""

    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def query_table(self, msisdn, service_type, table, start, end,
                    page=1, page_size=200, imsi=None, columns=None):
        self.calls.append({"service_type": service_type, "table": table,
                           "imsi": imsi, "page": page, "msisdn": msisdn})
        if service_type in self.fail:
            raise RuntimeError("The maximum number of connections for the user is reached")
        if service_type == "1300":
            rows = [{"msisdn": msisdn, "imsi": IMSI,
                     "start_time": "2026-11-07 10:00:00", "service": "video"}]
        elif service_type == "1100":
            rows = [{"imsi": IMSI, "procedure_start_time": "2026-11-07 10:00:00"}]
        elif service_type == "1301":
            rows = [{"vmos": 3.9, "start_time": "2026-11-07 10:00:00"}]
        else:  # "32"
            rows = [{"serving_rsrp": -95, "cellname": "CELL-A"}]
        return {"rows": rows, "records": len(rows)}


def collect(diag):
    return list(diag.iter_sources(MSISDN, START, END))


def parse_frames(text):
    """把 SSE 文本拆成 [(event, data), ...]。"""
    frames = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        frames.append((event, data))
    return frames


# ---------------------------------------------------------------- 1. 事件编排
def test_event_order_and_done_last():
    print("\n=== 1. iter_sources 事件顺序（done 必须最后） ===")
    diag = VmaxDiagnosis(FakeXdr())
    events = collect(diag)
    keys = [d["key"] for e, d in events if e == SOURCE_EVENT]
    check("四个源都产出且顺序 1300→1100→1301→32",
          keys == ["1300", "1100", "1301", "32"], str(keys))
    check("最后一个事件是 done", events[-1][0] == DONE_EVENT, str(events[-1][0]))
    check("done 里带 window 与 imsi",
          events[-1][1].get("window", {}).get("start") == START
          and events[-1][1].get("imsi") == IMSI, json.dumps(events[-1][1])[:200])


def test_generator_is_lazy():
    print("\n=== 2. 生成器惰性（调用方不 next 就不打上游） ===")
    fake = FakeXdr()
    gen = VmaxDiagnosis(fake).iter_sources(MSISDN, START, END)
    check("创建生成器时零上游调用", fake.calls == [], str(fake.calls))
    next(gen)
    check("第一次 next 后只打了 1300",
          [c["service_type"] for c in fake.calls] == ["1300"],
          str([c["service_type"] for c in fake.calls]))
    gen.close()


def test_ran_uses_parsed_imsi():
    print("\n=== 3. RAN(32) 必须用 1300/1100 解析出的 IMSI 查 ===")
    fake = FakeXdr()
    collect(VmaxDiagnosis(fake))
    ran = [c for c in fake.calls if c["service_type"] == "32"]
    check("32 的查询带上了 IMSI", bool(ran) and ran[0]["imsi"] == IMSI,
          json.dumps(ran[:1], ensure_ascii=False))
    check("1300 的查询不带 IMSI（此时还没解析）",
          [c for c in fake.calls if c["service_type"] == "1300"][0]["imsi"] is None)


def test_single_source_failure_isolated():
    print("\n=== 4. 单源失败不拖垮整条流 ===")
    diag = VmaxDiagnosis(FakeXdr(fail={"1100"}))
    events = collect(diag)
    by_key = {d["key"]: d for e, d in events if e == SOURCE_EVENT}
    check("失败源仍产出且 ok=False", by_key["1100"]["ok"] is False)
    check("失败源带人话错误（会话满被翻译）",
          "会话" in (by_key["1100"].get("error") or ""), by_key["1100"].get("error"))
    check("其余三个源 ok=True",
          all(by_key[k]["ok"] is True for k in ("1300", "1301", "32")),
          str({k: by_key[k]["ok"] for k in by_key}))
    check("流仍然跑到 done", events[-1][0] == DONE_EVENT)


def test_fetch_all_matches_iter():
    print("\n=== 5. fetch_all 与 iter_sources 口径一致 ===")
    fake = FakeXdr()
    payload = VmaxDiagnosis(fake).fetch_all(MSISDN, START, END)
    check("源定序 [1300, 1100, 32, 1301]",
          [s["key"] for s in payload["sources"]] == ["1300", "1100", "32", "1301"],
          str([s["key"] for s in payload["sources"]]))
    check("window 原样回传", payload["window"] == {"start": START, "end": END},
          str(payload["window"]))
    check("imsi 回传", payload["imsi"] == IMSI)
    check("每源都有 error/truncated 默认字段",
          all("error" in s and "truncated" in s for s in payload["sources"]))


def test_empty_msisdn_rejected():
    print("\n=== 6. 空号码必须显式报错（不许静默全空） ===")
    try:
        list(VmaxDiagnosis(FakeXdr()).iter_sources("", START, END))
        check("空号码抛 ValueError", False, "没有抛异常")
    except ValueError as exc:
        check("空号码抛 ValueError", "msisdn" in str(exc), str(exc))


# ---------------------------------------------------------------- 2. SSE 协议
def test_sse_frame_single_line():
    print("\n=== 7. SSE 帧格式（data 必须单行） ===")
    frame = _sse_frame("source", {"key": "1300", "rows": [{"a": 1}], "note": "中文"})
    check("以 event: 开头", frame.startswith("event: source\n"), frame[:40])
    check("以空行结束", frame.endswith("\n\n"))
    data_lines = [ln for ln in frame.splitlines() if ln.startswith("data: ")]
    check("恰好一行 data:", len(data_lines) == 1, str(len(data_lines)))
    check("data 是合法 JSON（含中文不转义）",
          json.loads(data_lines[0][6:])["key"] == "1300"
          and "中文" in data_lines[0])


def test_stream_frame_sequence():
    print("\n=== 8. _iter_stream_frames 帧序（source×4 → flow → done） ===")
    diag = VmaxDiagnosis(FakeXdr())
    frames = parse_frames("".join(_iter_stream_frames(diag, MSISDN, START, END)))
    names = [n for n, _ in frames]
    check("四个 source 帧", names.count("source") == 4, str(names))
    check("flow 帧在 done 之前",
          "flow" in names and names.index("flow") < names.index("done"), str(names))
    check("最后一帧是 done", names[-1] == "done", str(names))
    done = frames[-1][1]
    check("done 带 msisdn/window/imsi",
          done.get("msisdn") == MSISDN
          and done.get("window", {}).get("end") == END
          and done.get("imsi") == IMSI, json.dumps(done, ensure_ascii=False)[:200])
    src_keys = [d["key"] for n, d in frames if n == "source"]
    check("source 帧顺序 1300→1100→1301→32",
          src_keys == ["1300", "1100", "1301", "32"], str(src_keys))


def test_stream_frames_survive_failure():
    print("\n=== 9. 单源失败时流仍以 done 收尾（前端才敢标记完成） ===")
    diag = VmaxDiagnosis(FakeXdr(fail={"1300", "1301"}))
    frames = parse_frames("".join(_iter_stream_frames(diag, MSISDN, START, END)))
    names = [n for n, _ in frames]
    check("仍然有 4 个 source 帧", names.count("source") == 4, str(names))
    check("仍然以 done 收尾", names[-1] == "done", str(names))
    flow_frames = [d for n, d in frames if n == "flow"]
    check("仍有 flow 帧且明说未取到（flow=None, flow_reused=False）",
          len(flow_frames) == 1 and "flow" in flow_frames[0]
          and flow_frames[0]["flow_reused"] is False,
          json.dumps(flow_frames[:1], ensure_ascii=False)[:160])


# ---------------------------------------------------------------- 3. 窗口校验
def test_resolve_window_guards():
    print("\n=== 10. 窗口/号码校验（两端口径同一份） ===")
    try:
        _resolve_window("231777777322", "2026-11-06 00:00:00", "2026-11-07 11:00:00")
        check("超过 24h 拒绝", False, "没有抛 422")
    except HTTPException as exc:
        check("超过 24h 拒绝", exc.status_code == 422, str(exc.status_code))

    normalized, start_dt, end_dt = _resolve_window(
        "231777777322", "2026-11-07 11:00:00", "2026-11-07 09:00:00")
    check("start>end 自动互换", start_dt < end_dt)
    check("号码归一化", normalized == "231777777322", normalized)

    try:
        _resolve_window("abc", None, None)
        check("非数字号码拒绝", False, "没有抛 422")
    except HTTPException as exc:
        check("非数字号码拒绝", exc.status_code == 422, str(exc.status_code))


def main():
    for fn in (test_event_order_and_done_last, test_generator_is_lazy,
               test_ran_uses_parsed_imsi, test_single_source_failure_isolated,
               test_fetch_all_matches_iter, test_empty_msisdn_rejected,
               test_sse_frame_single_line, test_stream_frame_sequence,
               test_stream_frames_survive_failure, test_resolve_window_guards,
               test_stream_endpoint_wiring):
        fn()
    print("\n" + "=" * 60)
    if FAILS:
        print("FAIL=%d: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("全部通过（SSE 帧序 / IMSI 传递 / 单源失败隔离 / fetch_all 口径）")
    return 0


# ---------------------------------------------------------------- 4. 端点接线
def test_stream_endpoint_wiring():
    print("\n=== 11. /stream 端点接线（媒体类型 / 反缓冲头 / 帧真正可流出） ===")
    import asyncio
    import backend.routers.vmax_diagnosis as router_mod

    original = router_mod.get_xdr_client
    router_mod.get_xdr_client = lambda: FakeXdr()
    try:
        resp = router_mod.stream_diagnosis(msisdn=MSISDN, start=START, end=END)
        check("media_type 是 text/event-stream",
              resp.media_type == "text/event-stream", str(resp.media_type))
        check("带 X-Accel-Buffering: no（不改 nginx 也能逐帧）",
              resp.headers.get("x-accel-buffering") == "no",
              str(dict(resp.headers)))
        check("带 Cache-Control: no-cache",
              resp.headers.get("cache-control") == "no-cache",
              str(dict(resp.headers)))

        async def _drain():
            chunks = []
            async for chunk in resp.body_iterator:
                chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))
            return "".join(chunks)

        frames = parse_frames(asyncio.run(_drain()))
        names = [n for n, _ in frames]
        check("端点真的把 4 个 source + flow + done 流出去了",
              names.count("source") == 4 and "flow" in names and names[-1] == "done",
              str(names))
    finally:
        router_mod.get_xdr_client = original


if __name__ == "__main__":
    sys.exit(main())
