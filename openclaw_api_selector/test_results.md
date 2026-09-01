# OpenClaw API 优选 — 探测结果

运行时间: 2026-09-01 03:00  |  时延阈值: 5000 ms

## 汇总

| 提供者 | 可用 | 时延(ms) | 选用模型 | 状态/原因 |
|---|---|---|---|---|
| ZhiPu GLM 智谱 | 是 | 1521 | `glm-4-flash` | 正常 |
| NVIDIA NIM | 否 | - | `mistralai/mistral-7b-instruct-v0.3` | 模型不可用/不存在 |
| OpenRouter | 是 | 1803 | `openrouter/free` | 正常 |
| Ollama Cloud | 否 | - | `gemma3:27b` | HTTP 410 |
| ZhiPu GLM-5 智谱 | 是 | 2031 | `glm-4-flash` | 正常 |
| SiliconFlow 硅基流动 | 否 | - | `Qwen/Qwen3-8B` | 需付费/余额不足 (402) |
| MiniMax CN | 否 | - | `MiniMax-M2` | 未配置密钥·跳过 |
| StepFun 阶跃星辰 | 否 | - | `step-2-mini` | 需付费/余额不足 (402) |
| DAHL 推理 | 否 | - | `deepseek-chat` | 无权限 (403) |
| Together AI | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | 未配置密钥·跳过 |
| Groq | 否 | - | `llama-3.1-8b-instant` | 未配置密钥·跳过 |
| DeepInfra | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct` | 未配置密钥·跳过 |
| Fireworks AI | 否 | - | `accounts/fireworks/models/llama-v3p1-8b-instruct` | 未配置密钥·跳过 |
| Moonshot (Kimi) | 否 | - | `moonshot-v1-8k` | 未配置密钥·跳过 |
| Google Gemini | 否 | - | `gemini-2.0-flash` | 未配置密钥·跳过 |
| Local Ollama | 否 | - | `qwen3:4b` | <urlopen error [WinError 10061] No connection could be made because the target m |
| SenseNova 商汤 | 否 | - | `sensenova-6.7-flash-lite` | 未配置密钥·跳过 |

## 结论
- 主用 (primary): **zhipu/glm-4-flash**（1521 ms）
- 备用 (fallbacks): ollama/phi4-mini:3.8b, ollama/gemma4-32k:latest, ollama/qwen3:4b, ollama/qwen3:1.7b, openrouter/openrouter/free, zhipu5/glm-4-flash, ollama-cloud/gemma3:27b

## 级联尝试明细

### ZhiPu GLM 智谱
- `glm-4-flash` → OK 1521 ms

### NVIDIA NIM
- `meta/llama-3.1-8b-instruct` → FAIL http_error
- `llama-3.1-8b` → FAIL model_unavailable
- `llama-3.2-3b` → FAIL model_unavailable
- `gemma-2-9b` → FAIL model_unavailable
- `mistralai/mistral-7b-instruct-v0.3` → FAIL model_unavailable

### OpenRouter
- `openrouter/free` → OK 1803 ms

### Ollama Cloud
- `gemma3:4b` → FAIL http_error
- `ministral-3:8b` → FAIL http_error
- `gemma3:12b` → FAIL http_error
- `ministral-3:14b` → FAIL http_error
- `gemma3:27b` → FAIL http_error

### ZhiPu GLM-5 智谱
- `glm-4-flash` → OK 2031 ms

### SiliconFlow 硅基流动
- `Qwen/Qwen3-8B` → FAIL payment_required

### StepFun 阶跃星辰
- `step-2-mini` → FAIL payment_required

### DAHL 推理
- `deepseek-chat` → FAIL forbidden

### Local Ollama
- `gemma4-16k` → FAIL error
- `gemma3:4b` → FAIL error
- `phi4-mini` → FAIL error
- `qwen3:4b` → FAIL error

