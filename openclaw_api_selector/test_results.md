# OpenClaw API 优选 — 探测结果

运行时间: 2026-09-07 03:13  |  时延阈值: 5000 ms

## 汇总

| 提供者 | 可用 | 时延(ms) | 选用模型 | 状态/原因 |
|---|---|---|---|---|
| ZhiPu GLM 智谱 | 否 | - | `glm-4-air` | 网络超时 |
| NVIDIA NIM | 否 | - | `mistral-7b` | <urlopen error [WinError 10060] A connection attempt failed because the connecte |
| OpenRouter | 否 | - | `openrouter/free` | DNS 解析失败 |
| Ollama Cloud | 否 | - | `gemma3:4b` | DNS 解析失败 |
| ZhiPu GLM-5 智谱 | 否 | - | `glm-4.5` | 网络超时 |
| SiliconFlow 硅基流动 | 否 | - | `Qwen/Qwen2.5-7B-Instruct` | DNS 解析失败 |
| MiniMax CN | 否 | - | `MiniMax-M2` | 未配置密钥·跳过 |
| StepFun 阶跃星辰 | 否 | - | `step-1-flash` | DNS 解析失败 |
| DAHL 推理 | 否 | - | `deepseek-chat` | <urlopen error [WinError 10060] A connection attempt failed because the connecte |
| Together AI | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | 未配置密钥·跳过 |
| Groq | 否 | - | `llama-3.1-8b-instant` | 未配置密钥·跳过 |
| DeepInfra | 否 | - | `meta-llama/Meta-Llama-3.1-8B-Instruct` | 未配置密钥·跳过 |
| Fireworks AI | 否 | - | `accounts/fireworks/models/llama-v3p1-8b-instruct` | 未配置密钥·跳过 |
| Moonshot (Kimi) | 否 | - | `moonshot-v1-8k` | 未配置密钥·跳过 |
| Google Gemini | 否 | - | `gemini-2.0-flash` | 未配置密钥·跳过 |
| Local Ollama | 否 | - | `qwen3:4b` | <urlopen error [WinError 10061] No connection could be made because the target m |
| SenseNova 商汤 | 否 | - | `sensenova-6.7-flash-lite` | 未配置密钥·跳过 |

## 结论
- 主用 (primary): **zhipu/glm-4-air**
- 备用 (fallbacks): ollama/qwen3:8b, ollama/qwen3:4b, nvidia/mistral-7b, zhipu5/glm-4.5, dahl/deepseek-chat

## 级联尝试明细

### ZhiPu GLM 智谱
- `glm-4-flash` → FAIL error
- `glm-4-flash-250414` → FAIL error
- `glm-z1-flash` → FAIL error
- `glm-4.5-flash` → FAIL timeout
- `glm-4-air` → FAIL timeout

### NVIDIA NIM
- `meta/llama-3.1-8b-instruct` → FAIL error
- `llama-3.1-8b` → FAIL error
- `llama-3.2-3b` → FAIL error
- `gemma-2-9b` → FAIL error
- `mistral-7b` → FAIL error

### OpenRouter
- `openrouter/free` → FAIL dns

### Ollama Cloud
- `gemma3:4b` → FAIL dns

### ZhiPu GLM-5 智谱
- `glm-4-flash` → FAIL error
- `glm-z1-flash` → FAIL timeout
- `glm-5` → FAIL timeout
- `glm-5-turbo` → FAIL error
- `glm-4.5` → FAIL timeout

### SiliconFlow 硅基流动
- `Qwen/Qwen3-8B` → FAIL timeout
- `Qwen/Qwen2.5-7B-Instruct` → FAIL dns

### StepFun 阶跃星辰
- `step-2-mini` → FAIL error
- `step-1.5v-mini` → FAIL error
- `step-1-flash` → FAIL dns

### DAHL 推理
- `deepseek-chat` → FAIL error

### Local Ollama
- `gemma4-16k` → FAIL error
- `gemma3:4b` → FAIL error
- `phi4-mini` → FAIL error
- `qwen3:4b` → FAIL error

