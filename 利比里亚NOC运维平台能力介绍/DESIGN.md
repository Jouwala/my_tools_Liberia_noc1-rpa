# DESIGN.md — OLR MS O&M Platform · Customer Presentation

## 0. Design basis

- **Route**: universal design principles (customer capability deck for a managed-services review — not academic, not consulting, not government).
- **User overrides applied** (highest priority):
  - Language: **English** deck.
  - Audience: **customer management** → lead with value and outcome, keep implementation detail to one layer deep.
  - Palette: **ZTE-blue business** — light ground, `#0072BC` as primary. Confirmed by the user in the alignment step.
- Derived constants below are fixed for the whole deck.

## 1. Canvas & master (px)

| Region | Vertical band | Height | Content rule |
|:--|:--|:--|:--|
| **A · Title block** | 32–120px | 88px | Page title 34px bold `#0F2C4D`; a 4px × 40px `#0072BC` bar sits 12px left of the title baseline |
| **B · Content** | 132–648px | 516px | All body, diagrams, cards, images. Never invade A/C |
| **C · Footer bar** | 660–700px | 40px | Left: `OLR MS O&M Tools Platform` 14px `#94A3B8`. Right: page number `NN / 17` 14px `#94A3B8` |
| Padding | top 32 / bottom 20 / left 64 / right 64 | — | Content width = 1280 − 128 = **1152px** |

Cover / chapter / ending pages use a full-bleed custom layout: no A/B/C bands, image fills 1280×720 with a `#0F2C4D` overlay at 55–62% opacity.

## 2. Colour system

| Role | Hex | Use |
|:--|:--|:--|
| Primary | `#0072BC` | Title bars, big numeral accents, key borders, footer accent rule, icon fills |
| Deep | `#0F2C4D` | Headline text, chapter/cover/ending grounds, dark cards |
| Accent | `#FF922B` | **Focus only**: threshold/critical markers, the one number that must jump, active segment |
| Light ground | `#F2F6FA` | Card fills, alternated panel backgrounds |

Neutral (not counted in the pool): `#FFFFFF` page ground, `#1A2B3D` body text, `#64748B` secondary text, `#94A3B8` footer, `#E2E8F0` hairline dividers.

**Area budget per page type**

| Page type | Primary | Deep | Accent | Neutral/rest |
|:--|:--|:--|:--|:--|
| Supporting content | ≤ 45% | ≤ 20% | ≤ 5% | rest |
| Hero (p01 / p09 / p15 / p17) | ≤ 50% | ≤ 35% | 15–20% | rest |
| Chapter opener | ≤ 15% | ≥ 60% | ≤ 5% | rest |
| Catalog | ≤ 30% | ≤ 20% | ≤ 5% | rest |

At least two pages (p09, p17) deviate from the supporting ratio by > 10%. ✓

**Gradient & transparency policy**
- Cardinal gradient, used **only** on the cover and ending grounds: `linear-gradient(120deg, #0F2C4D 0%, #0072BC 100%)`.
- Card elevation: `boxShadow: '0 4px 20px rgba(15,44,77,0.08)'`.
- Full-bleed photos carry a flat `#0F2C4D` overlay at `opacity 0.55–0.62` — no gradient scrim, keeps white text legible and the look corporate.
- Accent tint panels: `rgba(255,146,43,0.10)` fill with a 3px `#FF922B` left border.
- No radial glows, no neon, no multi-hue gradients.

## 3. Type system

Family: **Inter** throughout (headings Bold 700, body Regular 400, numerals Black 900). Chinese fallback: 思源黑体 / Source Han Sans SC. Two families only. ✓

| Level | Size | Weight | Line height | Where |
|:--|:--|:--|:--|:--|
| Cover title | 64px | 700 | 1.15 | p01 |
| Chapter numeral + title | 72px (numeral) / 40px (title) | 900 / 700 | 1.0 / 1.25 | p03/05/07/11/14 |
| **Anchor numeral** | **72–120px** | **900** | **1.0** | p09 (110px), p12 (96px), p16 (56px ×4) |
| Page title (band A) | 34px | 700 | 1.3 | every content page |
| Card / block subtitle | 24px | 600 | 1.35 | card heads |
| Body | 19px | 400 | 1.55 | paragraphs |
| Caption / evidence line | 16px | 400 | 1.5 | under figures, source notes |
| Footer / page number | 14px | 400 | 1.4 | band C |

Letter spacing: titles `0.5px`, anchor numerals `-1px`, body `0`.

## 4. Density gates

- Content page body text ≥ 180 words (card-group pages ≥ 100 words per card).
- Container fill ≥ 85%: every card ends with a pinned bottom strip (`marginTop: 'auto'`) — a caption, a metric or a tag row. Never let a card end mid-air.
- Whitespace ≤ 35% on content pages; hero pages may reach 40–45% but the whitespace must ring the anchor element, not spread evenly.
- Focus whitespace: ≥ 40px clear around every anchor numeral / L1 image.
- Images per page ≤ 3, total image area ≤ 60% of band B.

## 5. Image plan

| File | Level | Origin | Content | Pages |
|:--|:--|:--|:--|:--|
| `hero_noc.png` | L1 | ImageGen | Network operations centre: wall of monitoring screens, calm blue light, two operators at a desk, no readable text on screen | 01, 17 |
| （未生成） | L1 | **渐变 + SVG** | 章节页改用 `linear-gradient(120deg,#0F2C4D,#0072BC)` 打底 + 抽象电信拓扑线条 SVG（opacity 0.16）。理由：5 个章节页共用同一张照片会单调，且抽象几何属 SVG 允许范围，同时省一次生图 | 03, 05, 07, 11, 14 |
| `portal_screen.png` | L1 | ImageGen | Clean dark-navy dashboard catalogue UI mock: card grid of dashboard tiles, grouped by domain, bilingual labels rendered as soft blurred text | 08 |
| `insight_screen.png` | L1 | ImageGen | Analytics dashboard mock: KPI cards plus a bar+line chart, one card visually opened into a detail list | 13 |
| `whatsapp_ai.png` | L1 | ImageGen | Smartphone in a working hand showing a group chat with an assistant reply, workshop/field background, no readable personal data | 15 |

Style lock for all ImageGen output: **photorealistic corporate**, cool blue-white grading, shallow depth of field, wide 16:9, no text overlays, no logos, no watermarks, no faces close-up.

SVG is permitted (and only used) for: the data-flow architecture diagram (p06), the three-break chain diagram (p04), the escalation ladder (p10), QC threshold bars (p09), and the L3 corner mark.

## 6. Page map (contract)

| # | File | Type | Role | Layout | L1 | Words | White | Colour split | Anchor |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| 01 | 01.slide | cover | hero | 全屏视觉+骑线文字 | hero_noc.png | 40 | 40% | deep 55% + primary 30% + accent 15% | 64px title |
| 02 | 02.slide | catalog | supporting | 左标题+右内容 | — | 150 | 25% | primary 30% + deep 20% | 5 chapter rows |
| 03 | 03.slide | section | transition | 全屏视觉+大标题 | chapter_bg.png | 30 | 45% | deep 65% + primary 15% | 72px numeral |
| 04 | 04.slide | content | supporting | 非对称双栏 60:40 | SVG chain diagram | 210 | 28% | primary 45% + deep 20% + accent 5% | diagram 60% width |
| 05 | 05.slide | section | transition | 全屏视觉+大标题 | chapter_bg.png | 30 | 45% | deep 65% + primary 15% | 72px numeral |
| 06 | 06.slide | content | supporting | 上大图+下方卡片 | SVG data-flow | 190 | 22% | primary 40% + deep 20% | diagram 58% height |
| 07 | 07.slide | section | transition | 全屏视觉+大标题 | chapter_bg.png | 30 | 45% | deep 65% + primary 15% | 72px numeral |
| 08 | 08.slide | content | supporting | 左大图+右侧文字 | portal_screen.png | 200 | 26% | primary 40% + deep 20% | image 56% width |
| 09 | 09.slide | content | hero | 巨型数字+洞察 | SVG QC bars | 120 | 35% | primary 45% + deep 25% + accent 18% | 110px numeral |
| 10 | 10.slide | content | supporting | 左标题+右内容 | SVG escalation ladder | 200 | 25% | primary 40% + deep 20% + accent 5% | 260px ladder |
| 11 | 11.slide | section | transition | 全屏视觉+大标题 | chapter_bg.png | 30 | 45% | deep 65% + primary 15% | 72px numeral |
| 12 | 12.slide | content | supporting | 非对称双栏 65:35 | 96px numeral | 190 | 30% | primary 45% + deep 25% + accent 8% | 96px numeral |
| 13 | 13.slide | content | supporting | 左大图+右侧文字 | insight_screen.png | 200 | 26% | primary 40% + deep 20% | image 56% width |
| 14 | 14.slide | section | transition | 全屏视觉+大标题 | chapter_bg.png | 30 | 45% | deep 65% + primary 15% | 72px numeral |
| 15 | 15.slide | content | hero | 全幅图+骑线文字 | whatsapp_ai.png | 170 | 32% | primary 40% + deep 30% + accent 15% | image 55% width |
| 16 | 16.slide | content | supporting | 巨型数字+洞察 | 4 × 56px numerals | 180 | 24% | primary 42% + deep 22% + accent 6% | 56px × 4 |
| 17 | 17.slide | ending | hero | 全屏视觉+大标题 | hero_noc.png | 30 | 45% | deep 60% + primary 25% + accent 15% | 56px line |

## 7. 交付方式与已知工程约束

**语言**：正稿为中文（用户 2026-10-01 确认）。术语保留英文缩写：TT / WO / CR / SLA / NUR / UME / eFlow。

**生成链路（本机实测约束）**：`slidep upsert-dsl` 的保存服务在本机当前状态下**对每个目标文件只允许成功落一页**，
第二次及以后一律返回 `/localapi/save HTTP 500 [10005]`（与文件名中英文无关，换新目录、清缓存、延长间隔均无效）。
因此采用两步法：

1. 每一页单独 `slidep create pNN.pptx` + `upsert-dsl`（每个文件只用一次成功写入）；
2. `python merge.py` 用 python-pptx 把 17 个单页合并成一份（脚本在同目录，图片分片按原始字节复制，
   因为 slidep 会产出 `image/svg+xml` 分片，PIL 无法解析、不能走 `get_or_add_image_part`）。

以后在同一台机器上继续改这份稿子时，沿用这套两步法；若保存服务已修复，可直接 `upsert-dsl --page-index N` 换页。

## 8. Hard rules for every page

1. Master bands present on all content pages; footer page number `NN / 17` bottom-right.
2. Never place a small decorative image in band A.
3. Anchor numeral or L1 image must occupy ≥ 30% of band B (≥ 40% on hero pages).
4. Only the 4 pool hexes + neutrals; accent `#FF922B` appears only on the focus element.
5. No two adjacent pages share a layout; no two adjacent pages have equal visual weight.
6. Numbers on slides must be the verified figures listed in `STORY.md §Data provenance` — no invented statistics.
