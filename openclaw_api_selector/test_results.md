# OpenClaw API 优选 — 探测结果

运行时间: 2026-07-21 03:00  |  时延阈值: 5000 ms

## 汇总

| 提供者 | 可用 | 时延(ms) | 选用模型 | 状态/原因 |
|---|---|---|---|---|
| ZhiPu GLM 智谱 | 是 | 1762 | `glm-4-flash` | 正常 |
| NVIDIA NIM | 是 | 836 | `meta/llama-3.1-8b-instruct` | 正常 |
| OpenRouter | 是 | 7695 | `openrouter/free` | 正常 |
| Ollama Cloud | 否 | - | `gemma3:27b` | HTTP 410 |
| ZhiPu GLM-5 智谱 | 是 | 1794 | `glm-4-flash` | 正常 |
| SiliconFlow 硅基流动 | 否 | - | `Qwen/Qwen3-8B` | 余额/配额不足 |
| MiniMax CN | 否 | - | `MiniMax-M2` | 余额/配额不足 |
| StepFun 阶跃星辰 | 否 | - | `step-2-mini` | 需付费/余额不足 (402) |
| DAHL 推理 | 否 | - | `deepseek-chat` | 无权限 (403) |
| Together AI | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | 未配置密钥·跳过 |
| Groq | 否 | - | `llama-3.1-8b-instant` | 未配置密钥·跳过 |
| DeepInfra | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct` | 未配置密钥·跳过 |
| Fireworks AI | 否 | - | `accounts/fireworks/models/llama-v3p1-8b-instruct` | 未配置密钥·跳过 |
| Moonshot (Kimi) | 否 | - | `moonshot-v1-8k` | 未配置密钥·跳过 |
| Google Gemini | 否 | - | `gemini-2.0-flash` | 未配置密钥·跳过 |
| Local Ollama | 是 | 7933 | `gemma4-16k:latest` | 正常 |
| SenseNova 商汤 | 是 | 3124 | `deepseek-v4-flash` | 正常 |

## 结论
- 主用 (primary): **nvidia/meta/llama-3.1-8b-instruct**（836 ms）
- 备用 (fallbacks): ollama/gemma4-16k:latest, ollama/gemma4-64k:latest, ollama/gemma4-32k:latest, ollama/gemma3:4b, ollama/phi4-mini:3.8b, ollama/gemma4:e2b, ollama/qwen3:4b, zhipu/glm-4-flash, zhipu5/glm-4-flash, sensenova/deepseek-v4-flash, ollama-cloud/gemma3:27b

## 级联尝试明细

### ZhiPu GLM 智谱
- `glm-4-flash` → OK 1762 ms

### NVIDIA NIM
- `meta/llama-3.1-8b-instruct` → OK 836 ms

### OpenRouter
- `openrouter/free` → OK 7695 ms

### Ollama Cloud
- `gemma3:4b` → FAIL http_error
- `ministral-3:8b` → FAIL http_error
- `gemma3:12b` → FAIL http_error
- `ministral-3:14b` → FAIL http_error
- `gemma3:27b` → FAIL http_error

### ZhiPu GLM-5 智谱
- `glm-4-flash` → OK 1794 ms

### SiliconFlow 硅基流动
- `Qwen/Qwen3-8B` → FAIL balance

### MiniMax CN
- `MiniMax-M2` → FAIL balance

### StepFun 阶跃星辰
- `step-2-mini` → FAIL payment_required

### DAHL 推理
- `deepseek-chat` → FAIL forbidden

### Local Ollama
- `gemma4-16k:latest` → OK 7933 ms

### SenseNova 商汤
- `sensenova-6.7-flash-lite` → FAIL server_error
- `sensenova-6.7-flash` → FAIL model_unavailable
- `sensenova-v6.7` → FAIL model_unavailable
- `sensenova-v6.7-lite` → FAIL model_unavailable
- `deepseek-v4-flash` → OK 3124 ms

