# -*- coding: utf-8 -*-
"""第一轮（提示版）测试：prompt 内已含"库中 0 条"事实，故只能测"复述"。

用法：cd backend/services/eflow_rules && python llm_test_alarm2114322696_round1.py
产出：llm_test_results_round1.json（同目录）。
注意：本脚本的 prompt 提示了答案，有效性弱于 round2，仅作对照保留。
"""
import json, time, urllib.request, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENDPOINT = "http://localhost:11434/api/generate"
PROMPT = (HERE / "llm_test_prompt_round1.txt").read_text(encoding="utf-8")

MODELS = ["qwen2.5:3b", "gemma3:4b", "qwen2.5:7b-instruct"]

def unload_all():
    """卸载所有模型，确保每个测试都从冷启动开始。"""
    try:
        ps = json.load(urllib.request.urlopen("http://localhost:11434/api/ps", timeout=10))
        for m in ps.get("models", []):
            body = json.dumps({"model": m["name"], "keep_alive": 0}).encode()
            req = urllib.request.Request(ENDPOINT, data=body,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
        time.sleep(2)
    except Exception as e:
        print("[warn] unload:", e)

def run(model):
    body = json.dumps({
        "model": model,
        "prompt": PROMPT,
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    resp = json.load(urllib.request.urlopen(req, timeout=600))
    wall = time.perf_counter() - t0
    return {
        "model": model,
        "wall_seconds": round(wall, 2),
        "load_ms": round(resp.get("load_duration", 0) / 1e6, 1),
        "total_ms": round(resp.get("total_duration", 0) / 1e6, 1),
        "eval_ms": round(resp.get("eval_duration", 0) / 1e6, 1),
        "prompt_tokens": resp.get("prompt_eval_count", 0),
        "output_tokens": resp.get("eval_count", 0),
        "output": resp.get("response", ""),
    }

results = []
for m in MODELS:
    print(f"\n{'='*70}\n测试模型: {m}\n{'='*70}", flush=True)
    unload_all()
    try:
        r = run(m)
        results.append(r)
        print(f"  冷启动墙钟: {r['wall_seconds']}s | 加载 {r['load_ms']}ms | "
              f"推理 {r['eval_ms']}ms | 输出 {r['output_tokens']} tok "
              f"({r['output_tokens']/(r['eval_ms']/1000):.1f} tok/s)")
        print(f"  --- 输出 ---\n{r['output']}")
    except Exception as e:
        print("  ERROR:", e)
        results.append({"model": m, "error": str(e)})

with open(HERE / "llm_test_results_round1.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n\n" + "="*70)
print("汇总（冷启动端到端）")
print("="*70)
print(f"{'模型':<24}{'墙钟s':>8}{'加载ms':>10}{'推理ms':>10}{'输出tok':>9}")
for r in results:
    if "error" in r:
        print(f"{r['model']:<24}  ERROR: {r['error']}")
    else:
        print(f"{r['model']:<24}{r['wall_seconds']:>8}{r['load_ms']:>10}{r['eval_ms']:>10}{r['output_tokens']:>9}")
