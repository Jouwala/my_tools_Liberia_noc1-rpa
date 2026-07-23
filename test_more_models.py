"""Quick concurrent test for more models"""
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)

models_to_test = [
    "deepseek-ai/deepseek-v4-pro",
    "deepseek-ai/deepseek-v4-flash",
    "google/gemma-2-2b-it",
    "google/gemma-4-31b-it",
    "meta/llama-3.2-1b-instruct",
    "meta/llama-3.2-3b-instruct",
    "meta/llama-3.2-11b-vision-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "meta/llama-4-maverick-17b-128e-instruct",
    "microsoft/phi-3.5-moe-instruct",
    "microsoft/phi-4-mini-instruct",
    "microsoft/phi-4-multimodal-instruct",
    "mistralai/codestral-22b-instruct-v0.1",
    "mistralai/ministral-14b-instruct-2512",
    "mistralai/mistral-7b-instruct-v0.3",
    "mistralai/mistral-large",
    "mistralai/mistral-large-3-675b-instruct-2512",
    "mistralai/mistral-medium-3.5-128b",
    "mistralai/mistral-nemotron",
    "mistralai/mixtral-8x22b-v0.1",
    "mistralai/mixtral-8x7b-instruct-v0.1",
    "nvidia/cosmos-reason2-8b",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/llama-3.1-nemotron-nano-8b-v1",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-4-340b-instruct",
    "nvidia/nemotron-mini-4b-instruct",
    "nvidia/llama3-chatqa-1.5-70b",
    "qwen/qwen3-next-80b-a3b-instruct",
    "qwen/qwen3.5-397b-a17b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "stepfun-ai/step-3.5-flash",
    "stepfun-ai/step-3.7-flash",
    "writer/palmyra-creative-122b",
    "writer/palmyra-fin-70b-32k",
    "writer/palmyra-med-70b",
    "writer/palmyra-med-70b-32k",
    "minimaxai/minimax-m2.7",
    "minimaxai/minimax-m3",
]

# ---------- Agnes AI (separate host + key) ----------
AGNES_API_KEY = "sk-p2urnUzv9gyCRGh8iyfqc1ilJrXBJ4hSHtcCFOJW981Q4Iq6"
agnes_client = OpenAI(
    base_url="https://apihub.agnes-ai.com/v1",
    api_key=AGNES_API_KEY,
)

# 文本模型（chat.completions）
agnes_text_models = [
    "agnes-2.0-flash",
]

# 图片模型（images.generate）
agnes_image_models = [
    "agnes-image-2.1-flash",
]

results = {}

def test_model(model_id):
    try:
        completion = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "Say OK"}],
            temperature=0.7,
            max_tokens=20,
            stream=False
        )
        return model_id, "OK", completion.choices[0].message.content
    except Exception as e:
        return model_id, "FAIL", str(e)[:100]

def test_agnes_text(model_id):
    try:
        completion = agnes_client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "Say OK"}],
            temperature=0.7,
            max_tokens=20,
            stream=False
        )
        return model_id, "OK", completion.choices[0].message.content
    except Exception as e:
        return model_id, "FAIL", str(e)[:200]

def test_agnes_image(model_id):
    try:
        resp = agnes_client.images.generate(
            model=model_id,
            prompt="a cute orange cat wearing sunglasses on a surfboard at sunset, cartoon style",
            n=1,
            size="1024x1024",
        )
        urls = [d.url for d in resp.data if getattr(d, "url", None)]
        b64 = [d.b64_json for d in resp.data if getattr(d, "b64_json", None)]
        info = f"returned url={len(urls)} b64={len(b64)}"
        return model_id, "OK", info
    except Exception as e:
        return model_id, "FAIL", str(e)[:200]

# 汇总所有测试：NVIDIA 文本 + Agnes 文本 + Agnes 图片
all_tests = [(m, test_model) for m in models_to_test]
all_tests += [(m, test_agnes_text) for m in agnes_text_models]
all_tests += [(m, test_agnes_image) for m in agnes_image_models]

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(fn, m): (m, fn) for m, fn in all_tests}
    for future in as_completed(futures):
        model_id, fn = futures[future]
        model_id, status, info = future.result()
        tag = "agnes" if fn in (test_agnes_text, test_agnes_image) else "nvidia"
        key = f"{tag}/{model_id}"
        results[key] = (status, info)
        if status == "OK":
            sys.stdout.write(f"[+] {key}: {info}\n")
        else:
            sys.stdout.write(f"[-] {key}: {info}\n")
        sys.stdout.flush()

print("\n" + "=" * 60)
print("AVAILABLE MODELS:")
for m, (s, _) in results.items():
    if s == "OK":
        print(f"  + {m}")
print(f"\nTotal available: {sum(1 for s,_ in results.values() if s == 'OK')}/{len(results)}")
