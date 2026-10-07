# 16 新增功能页规范

> 基准日期：2026-09-24　|　项目根：`D:\01_RPA\Task\my_app`
> **配套模板（可编译骨架）**：`frontend\src\pages\_TemplatePage.tsx`
> 本文说明「为什么这么写」，模板展示「具体怎么写」。**两者配合使用**。

---

## 一、为什么要有这一份

新增页面时最容易出的问题不是 bug，而是**风格漂移**：

- 每页各写一套卡片内边距/描边，改一次全局风格要改 40+ 个文件；
- 每个导出各写一遍 `xlsx`，导出的 Excel 有的有样式有的没有；
- 图表颜色写死十六进制，切主题后图例看不清；
- 文案漏加英文，界面直接显示 `tpl.xxx`。

这些都不是功能错误，所以**测试不会发现，但会持续积累成维护债**。

本规范的目标是：**照抄模板就能写对**，不需要记住任何细节。

---

## 二、五步新增一个页面

### 第 1 步：复制模板

```powershell
cd D:\01_RPA\Task\my_app\frontend\src\pages
Copy-Item _TemplatePage.tsx YourPage.tsx
```

把 `TemplatePage` 改名成你的组件名，`tpl.*` 换成你的 i18n 键前缀（如 `mypage.*`）。

### 第 2 步：接口写进 `api.ts`

**不要在页面里裸写 `fetch`**。参照 `frontend\src\api.ts` 既有风格加函数，
页面里只调 `getXxx()`。这样超时、鉴权、错误提示才有一致的处理。

### 第 3 步：三处同步登记（漏一处就会出问题）

| # | 位置 | 漏了会怎样 |
| --- | --- | --- |
| 1 | `frontend\src\App.tsx` 菜单数组 | 页面存在但**点不进去** |
| 2 | `frontend\src\i18n.tsx` 的 `zh` **和** `en` | 界面显示 `tpl.xxx` 而不是文字 |
| 3 | `docs\manual\11-feature-guide.md` | 手册与界面对不上（按导航顺序插入） |

> 这是 `docs\manual\README.md`「手册维护约定」第 1 条，也是 `AGENTS.md` 硬性约束第 1 条。

### 第 4 步：构建并验证

```powershell
cd D:\01_RPA\Task\my_app\frontend
npm run check:i18n     # ① 国际化一致性（漏键/错签名，见 3.6）
npx tsc --noEmit       # ② 类型必须先过
npm run build          # ③ 产物必须落在 D:/01_RPA/Task/_fe_dist
```

> `npm run build` 已内置 `check:i18n`（`build` = `check-i18n.mjs && tsc && vite build`）：
> 检查不过就**中断构建**，不会带着 `tpl.xxx` 上线。
> 覆盖范围包括 `t('字面量')` 与 `labelKey: 'xxx'` 两种写法（侧栏标签走的是后者），
> 任一语言缺键都会拦下。想单独跑检查用 `npm run check:i18n`。

然后**刷新页面**看效果 —— 前端产物不是 HMR，不刷新看不到变化。

### 第 5 步：深浅两套都要看

本项目有深色/浅色两套主题（`theme.ts` 的双套令牌就是为此存在）。
**只验一套等于漏测一半**。右上角切主题后重新看图例、表格、卡片。

---

## 三、必须遵守的统一约定

### 3.1 卡片：一律用 `components/cards`

```tsx
// ❌ 禁止
import { Card } from 'antd'
<Card title={<span style={{fontSize:'0.8125rem',fontWeight:600}}>标题</span>} style={cardStyle}>

// ✅ 正确
import { CardBase, StatCard } from '../components/cards'
<CardBase title="标题">            {/* 字符串标题自动套统一排版 */}
<CardBase title="标题" level="crit"> {/* 语义等级染色 ok/warn/crit */}
<CardBase title="标题" interactive>  {/* 可点击：悬停上浮 */}
<CardBase as="div">                 {/* 纯布局容器，少一层 DOM */}
```

- 数字卡用 `StatCard`。
- **不要在页面里写 `style={cardStyle}` 的裸卡片** —— `cardStyle` 是行内样式，优先级高于所有 CSS 类，
  写进去就把统一皮肤锁死了（这是项目踩过的真实 bug，见 `docs\card-style-unification.md`）。
- 详细契约见 `component-api.md` 第二节。

### 3.2 导出 Excel：一律用 `utils/excelReport`

```tsx
import { exportAoaReport, exportReport } from '../utils/excelReport'

// 单表
await exportAoaReport({ filename, sheetName, title, header, rows, numericCols })

// 多表
await exportReport(sheets, filename)
```

- **禁止裸 `xlsx`**（`XLSX.utils.aoa_to_sheet` / `XLSX.writeFile`）。
- **sheet 名不用自己截断或去重** —— 模块已统一处理禁用字符、31 字符限制与重名。
- 详细规范见 `docs\EXCEL_EXPORT_STANDARD.md`。

### 3.3 图表取色：分两层，绝不能混

| 层 | 用什么 | 原因 |
| --- | --- | --- |
| **DOM 层**（div/style） | `WH.cardBg` 等（即 `var(--wh-*)`） | 随主题**自动切换** |
| **ECharts / canvas 层** | `useTheme()` 的 `isDark` + `DARK`/`LIGHT` **实值** | canvas **无法解析 CSS 变量** |

```tsx
const { isDark } = useTheme()
xAxis: { axisLabel: axisLabel(isDark), axisLine: axisLine(isDark) }
```

> ⚠️ **本项目最容易犯的样式错误**：在 ECharts 配置里写 `WH.text`。
> 图表会拿到字符串 `'var(--wh-text)'` 而不是颜色，渲染异常或图例看不清。
> 工具函数 `axisLabel/axisLine/splitLine/darkTooltip` 已封装好，直接用。

### 3.4 弹窗：下钻用 `DraggableClickModal`

```tsx
<DraggableClickModal open={open} title={...} anchor={anchor} onClose={...}>
```

以点击点为中心弹出、可拖动、点遮罩不关闭、Esc 关闭 —— 这套行为已统一，别自己再写。

### 3.5 其他

| 项 | 约定 |
| --- | --- |
| 文案 | `t('key')`，中英两处都加；**不写中文字面量**（详见 3.6） |
| 时间 | 走 `frontend\src\datetime.ts` |
| 间距/圆角 | `var(--wh-space-*)` / `var(--wh-radius-*)`，不写魔法数字 |
| 空值展示 | 统一 `-`，不要有的页 `-` 有的页 `N/A` |
| 加载/错误 | `loading` 与 `error` 都要有可见反馈（`<Alert>`），不要静默 |

### 3.6 国际化：一个键都不能漏（有自动守卫）

**`t()` 的真实签名是 `t(key, params?)`** —— 第二个参数是**插值参数**（如 `{ n: 3 }` 去替换文案里的 `{n}`），
**不是** options 对象：

```tsx
const t = (key, params) => {
  let text = translations[locale]?.[key] || translations['zh']?.[key] || key  // ← 找不到就返回 key 本身
  if (params) for (const [k, v] of Object.entries(params)) text = text.replace(`{${k}}`, String(v))
  return text
}
```

由此推出两个高频踩坑点：

| ❌ 错误写法 | 会发生什么 | ✅ 正确写法 |
| --- | --- | --- |
| `t('qa.refresh', { defaultValue: '刷新' })` | `qa.refresh` 键不存在 → 返回 key → 界面显示 **`qa.refresh`**；`defaultValue` 不生效（文案里没有 `{defaultValue}` 占位符） | 把 `xxx.refresh` 加进 zh/en，写 `t('xxx.refresh')` |
| 只在 `zh` 加了键，忘加 `en` | 中文界面正常，**切英文就露出 key 原文** | zh 与 en **两处都加** |

> **真实案例**：`NocAnalyst.tsx` 的「刷新」按钮曾因第一种写法，界面上直接显示 `qa.refresh`。
> TypeScript 查不出来（`t()` 的 key 是 `string` 而非联合类型），构建也不报错，**只有肉眼能发现**。

**所以本项目加了自动守卫**：

```powershell
cd frontend
npm run check:i18n     # 单独跑
npm run build          # 已内置：不通过就直接中断，tsc/vite 都不会执行
```

`scripts\check-i18n.mjs` 检查四件事：

1. 代码里 `t('xxx')` 用到的键，**zh 与 en 两份字典是否都存在**（漏任一侧都报错）；
2. 是否用了 `t(key, { defaultValue })` 这种**错误签名**；
3. `zh` / `en` 键集合的**差异**（任一侧多出或缺失）；
4. 非模板文件里是否**残留 `tpl.*` 占位键**（复制 `_TemplatePage.tsx` 后忘改前缀）。

它会额外提示"疑似硬编码中文"与"字典里未被引用的键"（仅提示，不阻断）。

> **`_TemplatePage.tsx` 里的 `tpl.*` 键是故意不入字典的** —— 复制者必须把前缀改成自己的。
> 守卫对模板文件豁免，但会抓"忘了改前缀"的残留。

---

## 四、页面标准骨架（与模板对应）

```
┌─────────────────────────────────────────────┐
│ ① 筛选条（CardBase）                          │
│    日期范围 / 下拉 / 搜索 / 刷新 / 导出        │
├─────────────────────────────────────────────┤
│ ② 错误与警告（Alert，必须可见）                │
├─────────────────────────────────────────────┤
│ ③ KPI 数字卡（StatCard × N）                  │
├─────────────────────────────────────────────┤
│ ④ 图表卡（CardBase + ReactECharts）           │
├─────────────────────────────────────────────┤
│ ⑤ 表格卡（CardBase + Table，可导出）           │
├─────────────────────────────────────────────┤
│ ⑥ 下钻弹窗（DraggableClickModal）             │
└─────────────────────────────────────────────┘
```

---

## 五、相关文档

| 内容 | 去哪里 |
| --- | --- |
| **新页面模板（源码）** | `frontend\src\pages\_TemplatePage.tsx` |
| 卡片与组件索引 | `component-api.md` |
| 视觉规则 | `DESIGN.md` |
| Excel 导出规范 | `docs\EXCEL_EXPORT_STANDARD.md` |
| 卡片风格统一实施记录 | `docs\card-style-unification.md` |
| 逐页功能说明 | `docs\manual\11-feature-guide.md` |
| 前端架构与分层 | `docs\manual\02-architecture.md` |
| AI 上手约束 | `AGENTS.md` |
