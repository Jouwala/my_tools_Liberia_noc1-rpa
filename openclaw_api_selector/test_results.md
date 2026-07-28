# OpenClaw API 优选 — 探测结果

运行时间: 2026-07-28 03:07  |  时延阈值: 5000 ms

## 汇总

| 提供者 | 可用 | 时延(ms) | 选用模型 | 状态/原因 |
|---|---|---|---|---|
| ZhiPu GLM 智谱 | 是 | 7947 | `glm-4-flash` | 正常 |
| NVIDIA NIM | 是 | 19699 | `meta/llama-3.2-3b-instruct` | 正常 |
| OpenRouter | 是 | 35038 | `google/gemma-4-26b-a4b-it:free` | 正常 |
| Ollama Cloud | 否 | - | `gemma3:27b` | <urlopen error [WinError 10060] A connection attempt failed because the connecte |
| ZhiPu GLM-5 智谱 | 否 | - | `glm-5` | 余额/配额不足 |
| SiliconFlow 硅基流动 | 否 | - | `THUDM/glm-4-9b-chat` | <urlopen error [WinError 10060] A connection attempt failed because the connecte |
| MiniMax CN | 否 | - | `MiniMax-M2` | 未配置密钥·跳过 |
| StepFun 阶跃星辰 | 否 | - | `step-2` | 需付费/余额不足 (402) |
| DAHL 推理 | 否 | - | `deepseek-chat` | 无权限 (403) |
| Together AI | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | 未配置密钥·跳过 |
| Groq | 否 | - | `llama-3.1-8b-instant` | 未配置密钥·跳过 |
| DeepInfra | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct` | 未配置密钥·跳过 |
| Fireworks AI | 否 | - | `accounts/fireworks/models/llama-v3p1-8b-instruct` | 未配置密钥·跳过 |
| Moonshot (Kimi) | 否 | - | `moonshot-v1-8k` | 未配置密钥·跳过 |
| Google Gemini | 否 | - | `gemini-2.0-flash` | 未配置密钥·跳过 |
| Local Ollama | 是 | 11841 | `phi4-mini:3.8b` | 正常 |
| SenseNova 商汤 | 否 | - | `deepseek-v4-flash` | <urlopen error [WinError 10060] A connection attempt failed because the connecte |

## 结论
- 主用 (primary): **ollama/phi4-mini:3.8b**（11841 ms）
- 备用 (fallbacks): ollama/gemma4-32k:latest, ollama-cloud/gemma3:27b, siliconflow/THUDM/glm-4-9b-chat, sensenova/deepseek-v4-flash

## 级联尝试明细

### ZhiPu GLM 智谱
- `glm-4-flash` → OK 7947 ms

### NVIDIA NIM
- `meta/llama-3.1-8b-instruct` → FAIL error
- `llama-3.1-8b` → FAIL error
- `meta/llama-3.2-3b-instruct` → OK 19699 ms

### OpenRouter
- `openrouter/free` → FAIL error
- `google/gemma-4-26b-a4b-it:free` → OK 35038 ms

### Ollama Cloud
- `gemma3:4b` → FAIL error
- `ministral-3:8b` → FAIL error
- `gemma3:12b` → FAIL http_error
- `ministral-3:14b` → FAIL http_error
- `gemma3:27b` → FAIL error

### ZhiPu GLM-5 智谱
- `glm-4-flash` → FAIL error
- `glm-z1-flash` → FAIL error
- `glm-5` → FAIL balance

### SiliconFlow 硅基流动
- `Qwen/Qwen3-8B` → FAIL error
- `Qwen/Qwen2.5-7B-Instruct` → FAIL error
- `Qwen/Qwen3-4B` → FAIL error
- `deepseek-ai/DeepSeek-R1-Distill-Qwen-7B` → FAIL error
- `THUDM/glm-4-9b-chat` → FAIL error

### StepFun 阶跃星辰
- `step-2-mini` → FAIL error
- `step-1.5v-mini` → FAIL error
- `step-1-flash` → FAIL error
- `step-3.5-flash` → FAIL error
- `step-2` → FAIL payment_required

### DAHL 推理
- `deepseek-chat` → FAIL forbidden

### Local Ollama
- `gemma4-16k` → FAIL model_unavailable
- `gemma3:4b` → FAIL model_unavailable
- `phi4-mini:3.8b` → OK 11841 ms

### SenseNova 商汤
- `sensenova-6.7-flash-lite` → FAIL error
- `sensenova-6.7-flash` → FAIL error
- `sensenova-v6.7` → FAIL error
- `sensenova-v6.7-lite` → FAIL error
- `deepseek-v4-flash` → FAIL error

