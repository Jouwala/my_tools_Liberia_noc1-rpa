# -*- coding: utf-8 -*-
"""无提示重测：A=纯规则, B=规则+现场数据(不点破答案)。记录时延与结果。

用法：cd backend/services/eflow_rules && python llm_test_alarm2114322696.py
依赖：本机 Ollama 可达（默认 http://localhost:11434）。
产出：llm_test_results_round2.json（同目录）。
"""
import json, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENDPOINT = "http://localhost:11434/api/generate"
BASE = (HERE / "llm_test_prompt_A.txt").read_text(encoding="utf-8")

# B 组：在规则后追加一段“现场查库结果”，但不点破结论
EXTRA_B = """

【补充：现场数据库查询结果】
在 eflow_tt（工单表）中按 alarm_code='2114322696' 查询：命中 0 条。
在 realtime_alarm（实时告警表）中按 alarmcode='2114322696' 查询：命中 0 条。
在 history_alarm（历史告警表）中按 alarmcode='2114322696' 查询：命中 0 条。
（该告警码在整个系统中是否存在：否）"""

PROMPT_A = BASE
PROMPT_B = BASE + EXTRA_B

MODELS = ["qwen2.5:3b", "gemma3:4b", "qwen2.5:7b-instruct"]

def run(model, prompt, tag):
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    resp = json.load(urllib.request.urlopen(req, timeout=600))
    wall = time.perf_counter() - t0
    return {
        "model": model, "tag": tag,
        "wall_s": round(wall, 2),
        "load_ms": round(resp.get("load_duration", 0) / 1e6, 1),
        "eval_ms": round(resp.get("eval_duration", 0) / 1e6, 1),
        "out_tok": resp.get("eval_count", 0),
        "output": resp.get("response", ""),
    }

results = []
for m in MODELS:
    for tag, prompt in [("A_无提示", PROMPT_A), ("B_带数据", PROMPT_B)]:
        print(f"\n{'='*72}\n{m}  [{tag}]\n{'='*72}", flush=True)
        try:
            r = run(m, prompt, tag)
            results.append(r)
            print(f"  墙钟 {r['wall_s']}s | 加载 {r['load_ms']}ms | "
                  f"推理 {r['eval_ms']}ms | {r['out_tok']} tok "
                  f"({r['out_tok']/(r['eval_ms']/1000):.1f} tok/s)")
            print(f"  --- 输出 ---\n{r['output']}")
        except Exception as e:
            print("  ERROR:", e)
            results.append({"model": m, "tag": tag, "error": str(e)})

# 带时间戳输出：每次运行都是独立样本，不覆盖历史（LLM 输出有漂移，需保留多次运行对比）
_stamp = time.strftime("%Y%m%d_%H%M%S")
_out = HERE / f"llm_test_results_round2_{_stamp}.json"
with open(_out, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n结果已写入: {_out.name}")

print("\n\n" + "="*72)
print("汇总")
print("="*72)
print(f"{'模型':<24}{'组':<10}{'墙钟s':>8}{'加载ms':>9}{'推理ms':>9}{'tok':>7}")
for r in results:
    if "error" in r:
        print(f"{r['model']:<24}{r['tag']:<10}  ERR {r['error']}")
    else:
        print(f"{r['model']:<24}{r['tag']:<10}{r['wall_s']:>8}{r['load_ms']:>9}{r['eval_ms']:>9}{r['out_tok']:>7}")
