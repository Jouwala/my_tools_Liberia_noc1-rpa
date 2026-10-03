# STORY.md — OLR MS O&M Platform · Customer Presentation

## ① Intent alignment

- **Audience & occasion**: Customer-side management of the Orange Liberia / LONESTAR managed-services project, in a review meeting. They own the SLA numbers, the headcount and the escalation chain — not the code.
- **Core goal**: After this deck they should believe three things and act on one.
  1. *Believe* — operational data across 7+ upstream systems is now collected, checked and published **automatically**, not by people pasting spreadsheets.
  2. *Believe* — there is **one entry point** where every dashboard, quality figure and report lives, and every number can be traced down to the individual ticket.
  3. *Believe* — the same rules that used to live in engineers' heads are now **machine-checkable and explainable**, and an assistant in the WhatsApp duty group can answer them at 2 a.m.
  4. *Act* — endorse the platform as the operating baseline for the MS contract and extend it to the remaining domains.
- **Length**: 17 pages (cover + catalog + 5 chapter openers + 9 content pages + ending). Long enough to cover two products plus the AI assistant; short enough to present in 15 minutes.
- **Visual tone**: Credible · Structured · Operational · Restrained · ZTE-blue. No futuristic glow, no stock-photo clichés, no decorative gradients for their own sake.
- **Content boundary**:
  - **Must include**: what each of the two systems does, the concrete capability numbers, the drill-down story, the automation/reliability story, the AI assistant, and the business value framing.
  - **Must NOT include**: internal file paths, port numbers, database names, credentials, library/framework names, Baileys / ToS risk, known limitations, bug history.
  - **Careful**: numbers must be ones I actually verified in the codebase today (2026-10-01) — see §Data provenance.

## ② Skeleton

**Chapters (5) → chapter openers (5), one-to-one with the catalog:**

| Catalog entry | Chapter opener page | Page range |
| :-- | :-- | :-- |
| 01 The Operating Reality | p03 | p03–p04 |
| 02 One Platform | p05 | p05–p06 |
| 03 Unified Operations Portal | p07 | p07–p10 |
| 04 Data Insight MVP | p11 | p11–p13 |
| 05 AI Assistant & Value | p14 | p14–p17 |

**Hero pages (4 / 17 = 23.5%)**: p01 cover, p09 (QC & speed figures), p15 (AI assistant), p17 ending.
Non-adjacent: p01 → p09 → p15 → p17, each separated by ≥ 1 supporting page. ✓

**Rhythm**: p01 peak · p02 valley · p03 transition · p04 valley · p05 transition · p06 peak · p07 transition · p08 valley · p09 peak · p10 valley · p11 transition · p12 peak · p13 valley · p14 transition · p15 peak · p16 valley · p17 peak.
No run of ≥ 3 consecutive valleys. Every chapter boundary is a transition.

**Layout budget**: asymmetric ≥ 40% → 10 asymmetric (p02 p04 p06 p08 p09 p10 p12 p13 p15 p16) vs 7 symmetric (p01 p03 p05 p07 p11 p14 p17). `N-card row` used **0** times. `Left big image + right text` + `Asymmetric two-column` combined = 4 / 17 = 23.5% (≤ 40%).

## ③ Page outline

| # | title | type | role | rhythm | layout | visual | visual_role | density | anti_pattern | description |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| 01 | OLR MS O&M Tools Platform | cover | hero | peak | 全屏视觉+骑线文字 | L1: hero_noc.png (full-bleed, left title riding 45%) | anchor | 40 words / 1 img / 40% white | 禁止把标题缩到中间小字；禁止三色以上装饰块 | Two products, one operating picture for the Liberia NOC/SOC — presented as a single capability, not as two tools. |
| 02 | Contents | catalog | supporting | valley | 左标题+右内容 | L3: 蓝色竖条角标 | — | 150 words / 0 img / 25% white | 禁止每章只写一个词；禁止图标堆砌 | Five chapters: the problem, the platform, the portal, the insight engine, the assistant and the value. |
| 03 | 01 · The Operating Reality | section | transition | transition | 全屏视觉+大标题 | L1: chapter_bg.png 暗化 60% | atmosphere | 30 words / 1 img / 45% white | 禁止四卡预览；禁止铺正文 | Chapter opener — why this started. |
| 04 | Three breaks in the chain | content | supporting | valley | 非对称双栏 60:40 | L2: SVG 三段断点链 (左侧 60%) | evidence | 210 words / 1 diagram / 28% white | 禁止等宽三卡；禁止只列现象不给后果 | Data lives in 7+ upstream systems, dashboards in two places, reports assembled by hand — so a number is always one sync behind and nobody can prove which rule sent a ticket where. **Consequence: SLA disputes are settled by memory, not by record.** |
| 05 | 02 · One Platform | section | transition | transition | 全屏视觉+大标题 | L1: chapter_bg.png 暗化 55% | atmosphere | 30 words / 1 img / 45% white | 禁止四卡预览 | Chapter opener. |
| 06 | From source system to decision | content | supporting | peak | 上大图+下方卡片 | L1: SVG 数据流架构图 (上 58%) + 3 张下方卡 | anchor | 190 words / 1 diagram + 3 cards / 22% white | 禁止左右等分；禁止只画箭头不标系统名 | One pipeline: collect on schedule → land in the database → publish as dashboards, Excel reports and email/WhatsApp notifications. **The point for management: no step in this chain requires a person.** |
| 07 | 03 · Unified Operations Portal | section | transition | transition | 全屏视觉+大标题 | L1: chapter_bg.png 暗化 55% | atmosphere | 30 words / 1 img / 45% white | 禁止四卡预览 | Chapter opener. |
| 08 | Every dashboard, one screen | content | supporting | valley | 左大图+右侧文字 | L1: portal_screen.png (左 56%) | anchor | 200 words / 1 img / 26% white | 禁止 50:50 等分；禁止缩成 200×70 | 56 dashboards organised into 10 business domains, four views, bilingual, day/night, QR-to-phone. **Meaning: a duty engineer stops hunting across two platforms — the catalogue is the product.** |
| 09 | Quality and speed, at a glance | content | hero | peak | 巨型数字+洞察 | L1: 7 项 QC 指标条 + 巨型达标数字 (≥96px) | anchor | 120 words / 1 diagram / 35% white | 禁止等宽卡片横排；禁止把核心数字塞进图表角落 | Seven quality objects ( uncleared alarms, TT, WO, change, maintenance, spare parts, SLA ) with warn/critical thresholds and trend, plus Ookla-backed download/uplink benchmarking between Orange and LONESTAR. **Management read: quality is a number with a threshold, not an argument.** |
| 10 | Who to call, and where the file is | content | supporting | valley | 左标题+右内容 | L2: SVG 升级阶梯 + 报告中心清单 | evidence | 200 words / 1 diagram / 25% white | 禁止等宽四卡 | Escalation matrix with dual-network duty contacts one tap to copy, plus a report centre holding mail attachments, BI reports and rule-check output. **This is the page that answers "what happens at 2 a.m."** |
| 11 | 04 · Data Insight MVP | section | transition | transition | 全屏视觉+大标题 | L1: chapter_bg.png 暗化 55% | atmosphere | 30 words / 1 img / 45% white | 禁止四卡预览 | Chapter opener. |
| 12 | The automation engine | content | supporting | peak | 非对称双栏 65:35 | L1: 巨型 68 (72px) + 右列四条保障 | anchor | 190 words / 0 img / 30% white | 禁止等宽卡片；禁止只说"有很多任务" | 68 scheduled tasks declared in one registry, covering sync, KPI, reporting and delivery across every upstream system; failures auto-retry, missed runs are back-filled, and both backend and workers are watchdog-supervised. **So the question changes from "did someone run it" to "what did the run produce".** |
| 13 | Every number is a door | content | supporting | valley | 左大图+右侧文字 | L1: insight_screen.png (左 56%) | anchor | 200 words / 1 img / 26% white | 禁止 50:50 等分；禁止只写"支持下钻" | 24 functional pages across TT&WO, alarms, NUR, MS SLA, packet loss, GIS and CXO; click any figure and the underlying tickets open. **This is what turns a dashboard from a picture into evidence.** |
| 14 | 05 · AI Assistant & Value | section | transition | transition | 全屏视觉+大标题 | L1: chapter_bg.png 暗化 55% | atmosphere | 30 words / 1 img / 45% white | 禁止四卡预览 | Chapter opener. |
| 15 | An assistant in the duty group | content | hero | peak | 全幅图+骑线文字 | L1: whatsapp_ai.png (right 55%) + 骑入文字 | anchor | 170 words / 1 img / 32% white | 禁止文字压在人脸/主体上；禁止小图配大段 | Ask in the WhatsApp duty group: knowledge questions are answered from a local knowledge base, and a ticket number returns its level, the matched rule, the dispatch basis, the handling chain and SLA status in seconds. **Field-validated on 500 tickets: dispatch-rule attribution was correct on 100% of confirmable cases, 99.2% explainable.** |
| 16 | What this changes | content | supporting | valley | 巨型数字+洞察 (四联数字条) | L1: 4 个 56px 数字 + 洞察行 | anchor | 180 words / 0 img / 24% white | 禁止四张等宽卡片；禁止只堆数字 | Four shifts: manual → scheduled, scattered → single entry, opaque → traceable, memory-based → rule-based. Each number carries the "so what". |
| 17 | One operating picture | ending | hero | peak | 全屏视觉+大标题 | L1: hero_noc.png 暗化 | anchor | 30 words / 1 img / 45% white | 禁止再列功能清单 | Closing line: the platform is already running in the Liberia NOC/SOC today — the next step is extending it to the remaining domains. |

## Data provenance (verified 2026-10-01 on Y:)

| Figure | Source of truth |
|:--|:--|
| 68 scheduled tasks | `Task/my_app/backend/task_registry.py` — 68 `dict(task_id=...)` entries in `TASK_SPECS` |
| 24 functional pages | `Task/my_app/docs/manual/11-feature-guide.md` — menu table 1–24 |
| 56 dashboards / 10 domains | `liberia-noc_soc-数据看板统一门户/src/data/initialDashboards.ts` — 56 entries, 10 distinct `category` values |
| 7 QC objects + thresholds | `olbrportal/assets/olbr-data.js` — `QC_TARGETS` (alarm/tt/wo/cr/pmt/spms/sla) |
| Ookla benchmarking | `olbr-data.js` — `KPI_META` (speed/scores/bp) + `BENCH_BRANDS` + Ookla logo asset |
| Escalation matrix | `olbr-data.js` — 值班升级联系人 · Orange / LONESTAR 双网号码 |
| 100% / 99.2% rule attribution | `Task/whatsapp-kb-bot/README.md` — 500-ticket field validation |
| 810 knowledge chunks | `Task/whatsapp-kb-bot/README.md` — ingest output |
