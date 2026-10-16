# AI 动态观测 · X 一手信源扫描（2026-10-13）

> **已设定时任务：每周五 17:00 自动执行本流程并产出周报。**
> automation id `4b46d5de-5698-41c3-978a-33f90e83a348`，工作目录 `D:\01_RPA\_ai_watch`。
> 运行时会删除旧raw/ 后重新抓取（首次构建用的 skip-if-exists 逻辑不适用于周报），清洗→交叉核对→注入模板→playwright 验证→展示。
> 报告文件名：`AI动态观测周报_YYYYMMDD.html`。

## 结论速览

| 主题 | 内容 |
| --- | --- |
| 开源三连发 | 10/3 Aleph Alpha Kolibri（780M亿? 实为 780 亿总参）→ 10/5 Reflection AI Beam（5010亿总参/230亿激活，100万上下文，10月 Apache 2.0 开放）→ 10/6 Mistral Large 4「Le Chonk」（1.05 万亿总参/490 亿激活，原生多模态）。均以中国开源模型为对标物 |
| 竞争焦点 | 从参数转向推理成本。Beam 称1/3~1/4 算力追平 GLM-5.2。斯坦福 2026 AI 指数：闭源仅领先开源 3.3% |
| 闭源新品 | GPT-6 + Intelligent UI（ChatGPT 全量）、Gemini 4 Argon（全球）、Meta Muse Wonder / Muse Wonder Full + Muse Realtime Avatar |
| 端侧免费 | MiniCPM-V 4.7 35B-A3B（350亿总参/激活30亿，~3GB内存可跑，15+ tok/s）、EmbeddingGemma 2（740M 多模态嵌入，手机可跑） |
| 免费/开源资源 | Cloudflare Clef 27B / Clef-flash 9B（决策模型，209ms/38.8ms）、NVIDIA Kumo Tabular（TabArena 第一，17x 提速）、AWS Strands Decider 2B、Ollama 0.9.x、Mistral La Plateforme 免费档（注意 small/medium/mixtral 免费key 返回 429） |
| 技能工具 | Strata 推理引擎（15k stars/数日）、HF 多 harness RL 指南（同权重 62% vs 33%）、Claude Managed Agents（公开 beta）、DeepSeek Harness v0.2（桌面端+插件管理器）、llama.cpp 0.6.0 新增 /v1/systemone、Muse Gadgets ESP32 固件、HF MCP 接入 chat、karpathy的 ASD-STE100 与 /voice 漫谈技巧 |
| 工程信号 | Anthropic 5月2500次/天 → 9月 3万次/天代码合并，被迫自研源码控制系统 |
| 合规信号 | OpenAI 因欧盟要求推文本水印（承认技术局限）、Anthropic 加固反蒸馏、SynthID Detector 全球开放 |

## 关键坑

1. **r.jina.ai 是免登录抓 X 的可行通道**（200，拿到完整时间线含互动量），优于装agent-browser + 登录。nitter.net 也返回 200 但内容未必完整。
2. jina 返回的 markdown 中，**互动量格式不统一**：可能是 `[451](compose/post链接)` 也可能是裸数字，且常被拆行。提取要从行尾向前吞最多 4 个数字 token，反转后对齐 回复/转发/点赞/浏览。见 `parse.py:extract_metrics`。
3. 推文正文起点不固定：有的在 `](/status/xxx)` 之后，有的用 `](xxx/time)` 时间锚点。用 STATUS_RE 找锚点比剥昵称/handle 可靠。
4. **DeepSeek、Together AI、ylecun 三个账号抓取质量差**：DeepSeek 官方号内容是搬运他人推文且仅 1 条；Together AI 抓到印尼语/骚扰推文；ylecun 是政治吐槽。已从报告剔除。
5. Playwright 已装在 `D:\01_RPA\Task\my_app\scripts\python.exe`（含 playwright），配 `channel="chrome"` 可直接驱动本机 Chrome，**无需下载 Chromium**。agent-browser 全局安装被中断（改用此方案）。
6. `parse.py` 的分块靠 `\n\*\s+`，且需过滤掉 `## Log in or sign up` 之后内容（登录墙）。

## 产出

- `AI动态观测报告_20261013.html` — 可视化报告，单文件无外部依赖，含账号筛选 + 关键词搜索（已验证：66 条推文、18 卡片、筛选/搜索均正常）
- `raw/*.md` — 24 个账号原始抓取（TogetherAI/ylecun 可删）
- `parse.py` — 清洗脚本，可复用
- `tweets.json` / `tweets_final.json` — 结构化数据

## 复用方式

改账号列表 → 重新 curl `https://r.jina.ai/https://x.com/<acct>` 到 raw/ → 跑 `parse.py` → 改 `report_template.html` 的 `__DATA__` 占位符注入。