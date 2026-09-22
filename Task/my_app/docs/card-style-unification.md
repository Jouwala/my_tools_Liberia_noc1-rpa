# 卡片风格统一实施记录（2026-09-24）

> 目标：让 `http://localhost/myapp/` 所有页面的卡片，统一为 `http://localhost/olbrportal/` 的卡片风格。
> 状态：**已完成皮肤层统一 + 建立默认组件入口**；存量页面按「改到哪页顺手换哪页」渐进收敛。

---

## 一、需求与范围决定

| 决策点 | 结论 | 理由 |
| --- | --- | --- |
| 统一到哪一层 | **只统一视觉皮肤** | olbr 的卡片还有一套「图标+徽章+大数字+趋势线」的信息结构。若连结构一起搬，要重写 173 处 JSX，回归面过大且改变既有交互语义 |
| 深色档 | **不对齐** | my_app 深色已有成熟的深空蓝+电光青体系；套 olbr 深色档会造成两套深色规范并存 |
| 浅色档 | **对齐** | 这是用户明确要的效果 |

## 二、olbr 卡片皮肤的本质

来源 `liberia-noc_soc-数据看板统一门户\olbrportal\assets\olbr.css:419-443`（`.qc-card` / `.qc-lv-*`）。

皮肤 = 四件事，不是「一套完整的卡片组件」：

1. 描边 `--qc-accent-line`（accent 色 32% 透明）
2. **内发光** `inset 0 0 14px color-mix(accent 12%)` ← 招牌特征
3. 悬停上浮 2px + 内发光加深到 20% + 彩色投影
4. 一组 `--qc-accent*` 变量同时驱动描边/内发光/数字/徽章四个通道

## 三、关键发现（决定方案成败）

### 3.1 my_app 已有卡片收敛层 —— 所以不必改 173 处 JSX

实测：`theme.ts` 的 `cardStyle` 被 **143 处**引用（25 个文件），`index.css` 已有统一的 `.ant-card / .wh-stat-card` 玻璃规则。
故只需改**令牌层 + 类规则层**，全部卡片自动继承。

### 3.2 ⚠️ 坑 1：`cardStyle` 是行内样式，优先级高于所有 CSS 类

`theme.ts` 的 `cardStyle` 对象会以行内样式下发。历史上它写死：

```ts
boxShadow: 'var(--wh-shadow-1)'   // ← 这一行让全局卡片皮肤永远改不动
```

**任何写进 `cardStyle` 的具体值都会永久锁死该属性。** 已改为间接引用：

```ts
boxShadow: 'var(--wh-card-shadow)'   // 总成令牌，浅/深各定义一次
```

这是整个统一工作**最关键的一处改动** —— 不改它，后面所有 CSS 都不会生效。

### 3.3 ⚠️ 坑 2：CSS 自定义属性在「声明它的元素」上求值

```css
:root { --wh-card-glow: inset 0 0 14px color-mix(in srgb, var(--wh-card-accent) 12%, transparent); }
```

这条在 `:root` 上就**算完了**。之后在卡片元素上把 `--wh-card-accent` 改成 `--wh-ok`，
`--wh-card-glow` **不会**跟着变，仍是青色。

所以 `.wh-card-lv-*` 等级档里必须**把依赖 accent 的合成值一并重算**（`--wh-card-glow` / `--wh-card-glow-hover` / `--wh-card-drop-hover` / `--wh-card-shadow`）。

> 同源记录：`olbr.css:1001-1017` 也踩过这个坑（其深色档要把 `--qc-*` 整块重新映射一遍）。

### 3.4 ⚠️ 坑 3：antd 的 Card 组件 token 覆盖不到卡片皮肤

实测 `node_modules/antd/es/card/style/index.d.ts`（antd 6.5.0），`Card` 的 ComponentToken 只有：
`headerBg` / `headerFontSize` / `headerHeight` / `bodyPadding` / `extraColor` 等**头部与内边距**。

**没有圆角、没有阴影、没有描边色。**

> 结论：**不要试图用 `ConfigProvider` 的 `components.Card` 来做卡片统一** —— 皮肤四个通道里它一个都覆盖不到。

## 四、实际改动

### 4.1 令牌层（`frontend/src/index.css`）

深色 `:root` 新增（**保持原值，零回归**）：

```css
--wh-card-shadow: var(--wh-shadow-1);   /* = 改动前的 cardStyle.boxShadow */
--wh-card-glow: none;
--wh-card-accent: var(--wh-teal);
--wh-card-accent-line: var(--wh-glass-border);
--wh-card-elevate: -2px;
```

浅色 `:root[data-theme='light']` 新增（对齐 olbr）：

```css
--wh-card-accent: var(--wh-teal);
--wh-card-accent-line: color-mix(in srgb, var(--wh-teal) 32%, transparent);
--wh-card-glow: inset 0 0 14px color-mix(in srgb, var(--wh-card-accent) 12%, transparent);
--wh-card-glow-hover: inset 0 0 18px color-mix(in srgb, var(--wh-card-accent) 20%, transparent);
--wh-card-drop-hover: 0 8px 18px color-mix(in srgb, var(--wh-card-accent) 16%, transparent);
--wh-card-shadow: var(--wh-card-glow), var(--wh-shadow-2);
```

**为什么收敛成单一 `--wh-card-shadow` 总成令牌**：若写成 `box-shadow: var(--wh-card-glow), var(--wh-shadow-2)`，一旦某个 `--wh-card-glow` 未定义，guaranteed-invalid 会让**整条**简写声明失效，卡片掉成无阴影。收敛后兜底只需保证该令牌有值。

### 4.2 类规则层（`frontend/src/index.css`）

- 卡片层选择器新增 **`.wh-card`**（官方入口类）与 `.wh-card-head`。
- 浅色档描边改为 accent 线；悬停对齐 olbr（上浮 + 内发光加深 + 彩色投影）。
- 新增工具类：`.wh-card-glow`、`.wh-card-lv-ok|warn|crit`。
- 新增 `@supports not (color-mix(...))` 降级段：退回纯 `--wh-shadow-*` + 玻璃描边。

### 4.3 组件层（新增 `frontend/src/components/cards/`）

| 文件 | 作用 |
| --- | --- |
| `CardBase.tsx` | 统一卡片外壳。支持 `title`（字符串自动套统一排版）、`level` 等级染色、`interactive`、`as="div"` |
| `index.ts` | barrel —— **唯一推荐入口**，并 re-export 既有 `StatCard` |

```tsx
import { CardBase, StatCard } from '../components/cards'
<CardBase title="标题" level="crit">…</CardBase>
```

### 4.4 收敛案例

- `PacketLossDashboard.tsx`：4 处 `<Card size="small" title={<span style={{fontSize:'0.8125rem',...}}>…` → `<CardBase title="…">`。这是**参考实现**。
- `MsKpiShared.tsx` / `SpReportBase.tsx` / `SpDetailsReport.tsx`：页面内联 `StatCard` 原本硬编码 `background/border/borderRadius`，**绕过了皮肤层**，已改为挂 `.wh-stat-card` 类并删掉内联覆盖。

### 4.5 文档

- `component-api.md`：新增「卡片：项目默认组件」一节（入口约定、props、三层结构、两个坑、CSS 契约、收敛进度）。
- `DESIGN.md`：第四节改写为卡片皮肤的三层结构与深浅差异；第六节补纪律（卡片走 `CardBase`、改完必须重新构建）。

## 五、验证

| 项 | 结果 |
| --- | --- |
| `npx tsc --noEmit` | 通过 |
| `npm run build` | 成功，产物 `D:/01_RPA/Task/_fe_dist` |
| 服务端 CSS 实际下发 | 已确认 HTTP 拉取到 `--wh-card-shadow` / `wh-card-lv-crit` / `inset 0 0 14px` |
| 深色零回归 | 令牌解析值确认深色 = `var(--wh-shadow-1)`，与改动前一致 |
| 组件进入产物 | `CardBase` 已随 `PacketLossDashboard` 分包打包，含全部类名 |

## 六、遗留与后续

1. **存量卡片未全量替换**：仍有约 169 处 `<Card>` 直接用 antd。策略是渐进收敛，不批量替换。
2. **`StatCard` 有三份重复实现**：`MsKpiShared.tsx:172`、`SpReportBase.tsx:192`、`SpDetailsReport.tsx:170`，签名用 `label` 而非 `title`。合并需同步改调用方。新增页面**不要再加第四份**。
3. **`.wh-card-lv-*` 等级档尚未接入任何页面**：能力已备好，供告警类卡片按严重度染色时取用。
4. **色相差异是刻意的**：浅色档品牌青沿用 my_app 的 `--wh-teal(#0d9488)`，非 olbr 的 `#0e7490`。若要求逐像素一致，需全站改 `--wh-teal`（影响面远超卡片），需单独确认。
5. **未引入 ESLint**：当前 `package.json` 无 ESLint，故「禁止 `import { Card } from 'antd'`」目前只是文档约定，靠 code review 保证。若要硬拦截需先引入 ESLint。
