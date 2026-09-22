# 02 DESIGN.md —— 本项目的视觉规则

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总则：`D:\01_RPA\DESIGN.md`（全域通用部分不在此重复）
> **权威来源**：`frontend\src\theme.ts`（设计令牌）、`frontend\src\index.css`（样式）。本文是这些源码的**解读与约定**，冲突时以源码为准。

## 一、双层主题机制（本项目最重要的设计决策）

前端有**两套并行的主题取值方式**，这是刻意设计，不是重复：

| 层 | 导出 | 值的形式 | 用在哪 |
| --- | --- | --- | --- |
| **DOM 层** | `WH` | CSS 变量引用 `var(--wh-*)` | 页面内联样式。随 `<html data-theme>` **自动切换**，无需感知主题、无需重渲染 |
| **Canvas 层** | `DARK` / `LIGHT` | **具体色值** | ECharts 图表。canvas **无法解析 CSS 变量**，必须取实值，由 `useTheme()` 按当前主题返回 |

```ts
// DOM 层：写样式用它，主题切换自动生效
import { WH } from '../theme';
<div style={{ background: WH.cardBg, border: WH.cardBorder }} />

// Canvas 层：图表配置用它，按当前主题取实值
import { useTheme, DARK, LIGHT } from '../theme';
const { mode } = useTheme();
const C = mode === 'dark' ? DARK : LIGHT;
option = { xAxis: { axisLabel: { color: C.textMuted } } };
```

> **不要把 ECharts 配置写成 `WH.xxx`** —— 图表会拿到字符串 `var(--wh-teal)` 而不是颜色，渲染异常。这是本项目最容易犯的样式错误。

主题持久化键：`myapp-theme`（`THEME_STORAGE_KEY`）。

## 二、色彩令牌

### 深色主题（`DARK`）—— 默认

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `bg` | `linear-gradient(180deg, #02050c 0%, #050d22 100%)` | 页面底（深海军蓝渐变） |
| `cardBg` | `linear-gradient(145deg, #08122c 0%, #050d22 100%)` | 卡片底 |
| `cardBorder` | `1px solid rgba(0,217,255,0.18)` | 卡片边框（青色低透明） |
| `cardBorderHover` | `1px solid rgba(0,217,255,0.55)` | hover 边框（发光感） |
| `teal` | `#00d9ff` | **品牌主色**（青） |
| `blue` | `#258cff` | 次强调 |
| `indigo` | `#7c8ff0` | 三强调 |
| `text` / `textMuted` / `textDim` | `#f5f7ff` / `#aebbd4` / `#6f8cb4` | 三级文字 |
| `accentGrad` | `linear-gradient(135deg, #00d9ff, #258cff)` | 主按钮/强调渐变 |

### 浅色主题（`LIGHT`）

| 令牌 | 值 |
| --- | --- |
| `bg` | `linear-gradient(180deg, #f2f7fc 0%, #e8f0f8 100%)` |
| `cardBg` | `linear-gradient(145deg, #ffffff 0%, #f4f9fd 100%)` |
| `cardBorder` | `1px solid rgba(13,148,136,0.28)` |
| `teal` | `#0d9488` |
| `blue` | `#0e7490` |
| `text` / `textMuted` / `textDim` | `#16233b` / `#3f5468` / `#5b7288` |

> **注意浅色的 teal 是 `#0d9488`（深青）而非深色的 `#00d9ff`（亮青）** —— 深色主题用亮色系、浅色主题用深色系，是为了**保证对比度**。不要跨主题复用同一个色值。

### 序列色（图表 / 强调背景）

| 主题 | 数组 |
| --- | --- |
| 深色 | `WH_COLORS`：`#00d9ff` `#258cff` `#7c8ff0` `#f6cf00` `#ff5c6c` `#0bc78c` `#a99cff` `#ff922b` `#6ef0b4` `#7c8ff0` |
| 浅色 | `LIGHT_COLORS`：`#0d9488` `#0e7490` `#6366f1` `#b45309` `#d92d20` `#15803d` `#7c3aed` `#ea580c` `#0f766e` `#1d4ed8` |

图表按索引取色，**不要自己写死颜色**。

## 三、告警严重度色（`sev`）

| 级别 | 深色 | 浅色 |
| --- | --- | --- |
| Critical | `#ff5c6c` | `#d92d20` |
| Major | `#ff922b` | `#ea580c` |
| Warning | `#f6cf00` | `#b45309` |
| Info | `#258cff` | `#0369a1` |

**四级的颜色语义必须全站一致**（告警页、地图、图表、徽标用同一套）。新增可视化时从 `C.sev[level]` 取，不要另配色。

## 四、形态与交互

### 卡片（2026-09-24 起统一）

**卡片一律用 `components\cards` 的 `CardBase`**，不要直接 `import { Card } from 'antd'`，更不要在页面里写 `style={cardStyle}` 的裸卡片。详见 `component-api.md` 第二节。

```tsx
import { CardBase } from '../components/cards'
<CardBase title="标题" level="crit">…</CardBase>
```

皮肤由**三层**下发，改外观只动第一层：

| 层 | 位置 | 职责 |
| --- | --- | --- |
| ① 令牌层 | `index.css` 的 `:root` / `:root[data-theme='light']` | `--wh-card-accent*`、`--wh-card-shadow`、`--wh-card-glow` |
| ② 类规则层 | `index.css` 的「卡片层」区块 | `.wh-card` / `.ant-card` / `.wh-stat-card` 共用规则 |
| ③ 组件层 | `components\cards\CardBase.tsx` | 只挂 className，**不写样式值** |

**深浅两档的差异**（刻意，别顺手统一）：

| 档 | 来源 | 效果 |
| --- | --- | --- |
| 深色 | my_app 原有体系 | 渐变底 + 青色低透明边框；hover 边框升到 `0.55` 透明度形成"发光"反馈。**未套 olbr 皮肤** |
| 浅色 | 对齐 `olbrportal` 的 `.qc-card` | accent 描边 + **内发光** `inset 0 0 14px accent/12%`；hover 上浮 2px、内发光加深到 20% + 彩色投影 |

> 浅色档的品牌青沿用 my_app 自己的 `--wh-teal(#0d9488)`，**不是** olbr 的 `#0e7490` —— 同一个页面里不能出现两种品牌青。若要逐像素对齐 olbr，需先确认是否全站改 `--wh-teal`（影响面远超卡片）。

**等级染色**：`level="ok" | "warn" | "crit"`，复用 `--wh-ok/--wh-warn/--wh-danger`，不自造色。

**两个坑（改卡片前必读）**：

1. **行内样式优先级高于所有 CSS 类。** `theme.ts` 的 `cardStyle` 是行内对象，里面**只允许放 `var(--wh-*)`**。历史 bug：`cardStyle.boxShadow` 写死 `var(--wh-shadow-1)`，导致全局卡片皮肤被永久锁死、怎么改 CSS 都不生效。
2. **CSS 自定义属性在「声明它的元素」上求值。** 在卡片上改 `--wh-card-accent` **不会**让 `:root` 那条 `--wh-card-glow` 重算。故 `index.css` 的 `.wh-card-lv-*` 必须把依赖 accent 的合成值**一并重算**。

**降级**：不支持 `color-mix()` 的浏览器由 `index.css` 末尾的 `@supports` 段退回纯 `--wh-shadow-*` 阴影与玻璃描边，卡片不会掉成裸块。

### 其余交互

- **主按钮**：用 `accentGrad` 渐变。
- **主题切换**：`useTheme()` 提供 `mode` 与切换函数；切换后 ECharts 需要**重新取 `DARK`/`LIGHT` 并重绘**（canvas 不响应 CSS 变量变化）。

## 五、排版与图表约定

- 图表文字颜色一律取自令牌（`text` / `textMuted` / `textDim`），**不写字面色值**，否则切主题后图例看不清。
- 数字用等宽字体；时间/倒计时定宽补零。
- 导出类产出（Excel 报表）遵循 `docs\EXCEL_EXPORT_STANDARD.md`，**不适用本文**（Excel 有自己的配色规范，不要往表里塞 Web 主题色）。

## 六、改样式的纪律

1. **先判断改的是哪一层**：页面样式 → `WH`；图表配置 → `DARK`/`LIGHT`；卡片外观 → `index.css` 的令牌层。搞混是最常见的 bug。
2. **改完必须看深色和浅色两套。** 只验一套等于漏测一半（本项目 `theme.ts` 的双套令牌就是为了这个）。
3. **改完必须看图表出图**，不是只看页面框架——图表取色错误只有渲染时才暴露。
4. **改 `theme.ts` / `index.css` 前建备份**（本项目既有习惯，如 `theme.ts_bak_20260918_vmax_dark`、`index.css_bak_20260918_vmax_dark`）。
5. **不要跨主题复用色值**（深浅 teal 不同是刻意的）。
6. **新建卡片走 `CardBase`**，不要在页面里重新发明卡片样式（理由见第四节）。
7. **改前端源码后必须重新构建**：产物在 `D:/01_RPA/Task/_fe_dist`，页面非 HMR 时要刷新才生效（见 `docs\manual\10-quickstart.md`）。

## 七、与门户的一致性

统一门户已主动对齐 my_app 的视觉语言（深海军蓝 + teal/cyan 点缀）。
**反向也对齐过一次**：2026-09-24 my_app 的**浅色档卡片**对齐了门户只读展示版 `olbrportal` 的 `.qc-card` 皮肤（描边 + 内发光 + 悬停上浮）。深色档未对齐，保持 my_app 原体系。

| 内容 | 门户 |
| --- | --- |
| 门户视觉规范 | `D:\01_RPA\liberia-noc_soc-数据看板统一门户\docs\DESIGN.md` |
| 卡片皮肤来源（只读参考） | `...\olbrportal\assets\olbr.css` 的 `.qc-card` / `.qc-lv-*` |
| 全域视觉总则 | `D:\01_RPA\DESIGN.md` |

## 八、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 设计令牌源码（权威） | `frontend\src\theme.ts` |
| 样式源码（权威） | `frontend\src\index.css` |
| **组件索引与卡片规范** | `component-api.md` |
| 卡片风格统一实施记录 | `docs\card-style-unification.md` |
| Excel 导出配色 | `docs\EXCEL_EXPORT_STANDARD.md` |
| 视觉相关改版记录 | 各页面的 `*_bak_20260918_vmax_dark` 快照 |
| 全域视觉总则 | `D:\01_RPA\DESIGN.md` |
| 统一门户视觉 | `..\..\liberia-noc_soc-数据看板统一门户\docs\DESIGN.md` |

> **工具负责整理，人与 AI 负责协作执行。**
