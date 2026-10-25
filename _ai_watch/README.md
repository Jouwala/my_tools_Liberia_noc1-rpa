# AI 动态观测 · X 一手信源扫描

> **已设定时任务：每周自动执行本流程并产出周报。**
> automation id `4b46d5de-5698-41c3-978a-33f90e83a348`，工作目录 `D:\01_RPA\_ai_watch`。
> 运行时会删除旧 raw/ 后重新抓取（首次构建用的 skip-if-exists 逻辑不适用于周报），清洗→交叉核对→注入模板→playwright 验证→展示。
> 报告文件名：`AI动态观测周报_YYYYMMDD.html`。

## 流水线

| 步骤 | 脚本 | 说明 |
| --- | --- | --- |
| 1. 抓取 | `fetch_batch.py` | 删旧文件 → `r.jina.ai` HTML 模式抓取 → `html2md.py` 转成 jina 同构 markdown |
| 2. 清洗 | `parse.py` | **未改动**，输出 `tweets.json` |
| 3. 加工 | `finalize.py` | 剔除噪声账号 + snowflake 解出绝对日期 + 去重排序 → `tweets_final.json` |
| 4. 生成 | `build_report.py` | 替换 `report_template.html` 的 `__DATA__` 等占位符 → `AI动态观测周报_YYYYMMDD.html` |
| 5. 验证 | `verify_report.py` | Playwright（`channel="chrome"`）验渲染、筛选、搜索、空状态、横向溢出 |

一条命令跑完：

```bash
"D:/01_RPA/Task/my_app/scripts/python.exe" fetch_batch.py \
  && "D:/01_RPA/Task/my_app/scripts/python.exe" parse.py \
  && "D:/01_RPA/Task/my_app/scripts/python.exe" finalize.py \
  && "D:/01_RPA/Task/my_app/scripts/python.exe" build_report.py \
  && "D:/01_RPA/Task/my_app/scripts/python.exe" verify_report.py
```

## 关键坑（本周新增/修正）

1. **jina 的 markdown 模式对部分账号返回「降级」渲染** —— 有正文，但缺 status 链接、时间戳和互动量，且**同一账号反复抓取结果不一致**（可能命中缓存）。**解法：统一走 HTML 模式**（`curl -H "x-respond-with: html"`），DOM 结构始终完整，再用 `html2md.py` 还原成 `parse.py` 期望的 markdown 行格式，**parse.py 无需改动**。
2. **HTML 模式里 `<article>` 会嵌套**（引用推文是嵌套的 article），非贪婪正则 `<article>.*?</article>` 会切错。必须用嵌套感知的解析器（`html2md.ArticleSplitter`）取顶层 article。
3. **正文容器要用 `whitespace-pre-wrap` + `text-primary` 定位** —— 页头昵称块是 `font-bold`、handle 块是 `flex`，只匹配 `text-body` 会抓到页头。
4. **`data-engagement-action` 与 `aria-label` 两种 engagement 标记并存**，需同时覆盖；计数在 `x-animated-count-visual` 里。顺序为 reply / retweet / like / generic(=views)。
5. **雪flake ID 可直接解出绝对时间**：`ms = (id >> 22) + 1288834974657`，用来补全 `parse.py` 拿不到的日期（它只能解析 `19h` 这类相对值）。
6. **账号名会失效或指向无关主体**：`MetaAI` → 已迁移到 `AIatMeta`；`QwenLM`/`GitHubAI` → 404，正确是 `Alibaba_Qwen`/`GitHub`；`moonshotai` → 荷兰足球俱乐部，正确是 `Kimi_Moonshot`；`MiniMaxAI` → 正确是 `MiniMax_AI`。抓取后需核对 `<title>`。
7. **长推文在未登录视图下被 X 折叠**，展开需登录，因此约 28% 的推文正文在源侧即被截断（末尾的 "Show more" 标记已清掉，但句子本身不全）。
8. **噪声账号**：DeepSeekAI（搬运他人推文）、TogetherAI（抓到骚扰内容）、ylecun（政治吐槽）—— 抓取阶段已跳过，`finalize.py` 再兜一层。

## 本周结论速览（2026-10-24）

| 主题 | 内容 |
| --- | --- |
| 开源咬住闭源 | Kimi K3.1 Pro（2.8T/104B 激活，1M 上下文，多模态）Artificial Analysis 智能指数 **55 分全球第四**，距 Claude Opus 5.5（58）仅 3 分，上一代 K3 是 44 分。**权重 11/4 前才开放** |
| 开放 ≠ 能跑 | 三个维度必须分开看：2.8T 的 Kimi / 816B 的 Muse Spark Open 属「开放权重但本地跑不动」；真能跑的是 Muse Glimmer 30B（Apache 2.0，24GB 显存）、Flint（40B/2.5B 激活，MacBook 125+ tok/s）、Nemotron Bolt E4B（4GB 显存） |
| 美国开源旗舰 | Meta Muse Spark Open：816B/42B 激活、1M 上下文、原生多模态，BF16 约 1.6TB、NVFP4 约 530GB，官方方案要两台 512GB 的 M5 Ultra Mac Studio；Muse Model License（有限商用，>2000 万美元年收入需单独协议） |
| 端侧蒸馏 | Meta Muse Glimmer 30B（从 Muse Spark 蒸馏，Apache 2.0，4-bit 约 17GB，RTX 5090 上约 233 tok/s，10/19 发技术报告） |
| 国产密集 | MiniMax M3.1 Flash（428B/23B，10/23 开放权重，$0.15/$0.60）；Qwen-Image-2.1-Turbo（8 步去噪，开放权重）；Qwen3.8-Max 权重 8/12 已开放（自定义许可）；QwenGyre 弹性 RL（1.85× 加速） |
| 免费额度坑 | 阿里云百炼：新加坡地域每模型 100 万 token / 90 天，但**默认自动转按量计费**、**max/flash 默认开思考模式**（隐藏思维链按输出价计费）、旧免费 OAuth 层已于 4/15 下线。MiniMax M3.1 Flash 的 OpenRouter `:free` 与 Vercel AI Gateway 免费档**均已于 10/22 12:00 UTC 结束** |
| Claude 订阅转 API | Max 5x 每月 $100、Max 20x $200、Team 池化至 $500；Sonnet 5.5 缓存读取价 $0.20→$0.10 |
| agent 基建 | Perplexity 开源 SPACE 沙箱（Apache 2.0，Firecracker microVM，median 185ms→60ms，108 次逃逸尝试无一突破虚拟机边界 —— 厂商自测）；Vercel durable-sessions；Vercel 调查 1000+ SaaS 仅 8.4% 支持安全认证 |
| 值得注意 | OpenAI 移除前沿模型训练期间的实时互联网访问（离线世界）；红队演练挖出 Brotli 未授权 RCE（影响 Node.js/Bun/Envoy）；GitHub 把 99.99999% 仓库迁到 Azure；Claude 默认 auto 模式（拦下 89% 危险命令 vs 人工 14%） |

## 复用方式

改账号列表 → `fetch_batch.py` → `parse.py` → `finalize.py` → 改 `report_template.html` 正文 → `build_report.py` → `verify_report.py`。

模板占位符：`__DATA__`（tweets_final.json）、`__ACC_COUNT__`、`__TWEET_COUNT__`、`__DATE_CN__`、`__STATS__`、`__ACC_BTNS__`。

## 产出

- `AI动态观测周报_20261024.html` — 单文件无外部依赖，25 账号 / 97 条推文 / 11 张模型卡 / 8 张资源卡 / 13 行技能表 / 7 张信号卡 / 56 个属性徽章（已验证：筛选、搜索、空状态、无横向溢出）
- `raw/*.md` + `raw/html/*.html` — 26 个账号的抓取结果（md 是转换后中间格式，html 是原始 DOM）
- `parse.py` — 清洗脚本（未改动）、`html2md.py` / `finalize.py` / `build_report.py` / `verify_report.py` / `fetch_batch.py` — 本周新增
