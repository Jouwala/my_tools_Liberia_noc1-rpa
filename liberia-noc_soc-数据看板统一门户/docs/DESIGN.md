# 02 DESIGN.md —— 本项目的视觉规则

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\liberia-noc_soc-数据看板统一门户`
> 上级总则：`D:\01_RPA\DESIGN.md`（全域通用部分不在此重复）
> 可视化呈现：站内「设计指南」弹窗（`src\components\DesignGuideModal.tsx`，文案键 `guide.*`）

## 一、品牌配色

门户对齐 my_app 的视觉语言：**深海军蓝底 + teal/cyan 点缀**。演进记录见 `MsPortal\配色对齐VMAX90天看板_可行性结论与实施记录_20260918.md`。

| 用途 | Tailwind | 说明 |
| --- | --- | --- |
| 品牌主渐变 | `from-teal-600 to-cyan-600` | 主按钮、弹窗标题图标容器（配 `shadow-md shadow-teal-600/20`） |
| 弹窗头部渐变 | `from-teal-50/50 via-white to-cyan-50/50` | 浅色；深色对应 `dark:from-teal-950/20 dark:via-slate-900 dark:to-cyan-950/20` |
| 深色主背景 | `slate-900` / `slate-950` | 默认主题 |
| 浅色主背景 | `white` / `slate-50` | 日间模式 |
| 卡片边框 | `border-slate-200/80`（浅）/ `dark:border-slate-800`（深） | 细边框 |
| 弹窗面板 | `bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl` | 配 `spatial-modal-surface` 类 |

### 平台色区分（重要）

| 平台 | 色系 | 目的 |
| --- | --- | --- |
| FineBI 生态 | 蓝紫（`indigo` / `violet`） | 让用户 0.1 秒识别技术源 |
| 自研 my_app | 青蓝（`teal` / `cyan`） | 同上 |

## 二、语义色

| 语义 | Tailwind | 用在哪 |
| --- | --- | --- |
| 正常 / 心跳 | `emerald-500` + `status-pulse-green` | 自动刷新脉冲点 |
| 数值正常 | `lime-600` | QC 卡大数字 |
| 失败 / 异常 | `rose-400` / `rose-500` | 状态竖条、图标底色、失败文案；心跳点变红时**不脉冲** |
| 未加载 / 未知 | `slate-300` | 数值为 `—` 时 |
| 常规信息 | `blue-500` / `blue-600` | 状态竖条（正常）、图标底色、链接 |

> `emerald`（心跳）与 `lime`（数字）**是两个不同的绿**，各司其职，不要顺手统一。

## 三、卡片规范（以 QC 卡为准）

最终形态（2026-09-19 / 09-22 两次改版确定）：

```
相对容器 relative overflow-hidden
├── 左侧 3px 状态竖条   absolute left-0 top-0 h-full w-[3px]
│                        正常 bg-blue-500    失败 bg-rose-400
├── 内边距              pl-3.5 pr-3 py-3
├── 标题行              flex items-center justify-between，text-[13px] font-semibold text-slate-600
│                        名称 truncate；图标容器 p-1 rounded-md shrink-0
│                        正常 bg-blue-50 text-blue-600   失败 bg-rose-50 text-rose-500
├── 大数字              text-center text-[30px] lg:text-[36px] font-extrabold font-mono
│                        tracking-tight leading-none mt-2
│                        有值 text-lime-600   无值 text-slate-300
└── 副行（口径/报错）    text-[11px] mt-2 truncate text-center leading-tight
                         正常 text-slate-400   失败 text-rose-500，完整内容放 title
```

基础样式：`bg-white rounded-xl border shadow-[0_1px_2px_rgba(15,23,42,0.04)]`；选中态 `border-blue-400 ring-1 ring-blue-200 shadow-sm`；未选中 `border-slate-200/80 hover:border-blue-300`；hover `hover:shadow-lg hover:-translate-y-0.5`（**上浮，不用缩放**）；`transition-all duration-200`。

### 两条不可踩的线

1. **只有数字居中，标题行与副行保持左对齐。** 需求原话是"卡片上的数字要居中"；把整卡设为 `text-center` 会连标题和口径一起挪走，属超范围改动。
2. **不要整卡渐变。** 纯白 + 细边框 + 柔和阴影；渐变只用于头部/标题条。

## 四、弹窗规范

所有弹窗统一骨架（照抄 `DesignGuideModal.tsx`）：

```
遮罩  fixed inset-0 z-50 flex items-center justify-center p-4
      bg-black/60 backdrop-blur-sm animate-fadeIn
面板  spatial-modal-surface bg-white dark:bg-slate-900 border rounded-2xl
      shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden
头部  px-6 py-4 border-b，左侧 = 带色图标容器 + 标题/副标题，右侧 = 关闭按钮
关闭  p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200
      hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors
```

- Props 固定为 `{ isOpen: boolean; onClose: () => void }`，`isOpen` 为假时 `return null`。
- 必须支持点击遮罩关闭 + 明确的关闭按钮。
- 标题与副标题走 i18n（`zh` / `en` 两处）。

## 五、排版

| 层级 | 字号/字重 |
| --- | --- |
| 弹窗标题 | `text-lg font-bold` |
| 弹窗副标题 | `text-xs text-slate-500 dark:text-slate-400` |
| 卡片标题 | `text-[13px] font-semibold` |
| 卡片副行 | `text-[11px]` |
| 大数字 | `text-[30px] lg:text-[36px] font-extrabold font-mono` |

- 数字一律 `font-mono` + `tracking-tight` + `leading-none`。
- **时钟与倒计时必须定宽**（补零到 `HH:MM:SS` / `MM:SS`）。实时区块精确到秒，且解析失败时退回原字符串截取，**不显示 `Invalid Date`**。
- 时间戳按**浏览器本地时区**重算，与页面时钟同一把尺子（后端返回的时间可能是 UTC，直接显示会差 8 小时，是"QC 好像没在自动更新"这类误判的来源之一）。

### 手写静态壳的字号体系（`/v1/olbrportal/`）

上面的 Tailwind 表针对 `src/` 内的 React 应用。两个手写静态壳（`olbrportal/`）
**不用 Tailwind**，字号走各自 `assets/olbr.css` 里的令牌，口径如下（2026-10-01 更新）：

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--fs-2xs` | 11.5px | 角标 / 时间戳 / 口径脚注 |
| `--fs-xs` | 11.5px | 次要标签 / chip 计数 / **表格表头** |
| `--fs-sm` | 12.5px | 卡名 / 说明 / **表格正文** |
| `--fs-md` | 14px | 正文 / 控件默认 |
| `--fs-lg` | 16px | 卡片标题 / 面板标题 |
| `--fs-xl` | 18px | L0 决策带标题 |
| `--fs-num` | 24px | 指标大数字 |

> ⚠️ `--fs-2xs` 与 `--fs-xs` **同为 11.5px**（2026-10-01 起）—— 两条相邻档只差
> 0.5px 时人眼分不出，反而制造不一致，故合并为同值。**两个令牌名保留**：语义上
> 仍是两类（角标/脚注 vs 标签/表头），将来若要分开仍可各调各的。

**行高令牌**（标题一律走 `--lh-tight`，是"标题只有一种行高口径"的落点）：

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `--lh-solid` | 1 | 仅单行徽章 / 大数字 |
| `--lh-tight` | 1.25 | **所有标题 / 卡名** |
| `--lh-base` | 1.5 | 正文 / 表格单元格 |

**字距令牌**：`--ls-tight`(-.01em，大字标题) / `--ls-base`(0，正文) / `--ls-wide`(.02em，小标签、表头、卡名)。

**字体栈**（2026-10-01 定稿）：

- `--sans`：系统 UI 字体优先 —— `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "WenQuanYi Micro Hei", sans-serif`。
  **刻意不用 Web 字体**：门户要求零 CDN、断网可用，且中文 Web 字体动辄数 MB。
- `--mono`：`ui-monospace, SFMono-Regular, "Cascadia Mono", Menlo, Consolas, "Microsoft YaHei", monospace`。
  ⚠️ **末尾的 `"Microsoft YaHei"` 不能删** —— 本页 37 处用 `--mono`，其中 6+ 处会渲染
  **中文**（`.esc-note` 数据源说明、`.gf-note` 模板提示、`.canvas-note` 中文地图标题、
  `.meta` 中文名…）。栈里没有中文字体时，汉字会落到 `monospace` 兜底
  （Windows 上多为 Courier New / 宋体），与 Consolas 的拉丁等宽**字形/字宽/基线都不同**，
  中英混排处会明显"跳"。`tabular-nums` 只作用于数字/拉丁，中文回退不影响对齐。
  同一栈也用在顶栏时钟与用户名（`masthead.css` 两处硬编码）。
- 下钻弹窗的 `--qc-mono`（`MsPortal/assets/qcDrill.css`，**两门户共用**）与 `--mono` 对齐
  （含 `"Cascadia Mono"` 与中文回退；仅少了 macOS 专属的 `SFMono-Regular`）。

- **图标字号单独一套** `--icon-xs/sm/md/lg`（12/13/15/18px），**不进** `--fs-*`
  —— 图标大小跟的是视觉重量、不是文字层级，混在一起会让人误以为同层。
- 三张表格（升级机制 / 用户管理 / 下钻弹窗）表头统一 `--fs-xs`、正文统一 `--fs-sm`。
  下钻弹窗的 `MsPortal/assets/qcDrill.css` 是**两门户共用**文件，改它会同时影响
  `/MsPortal/`（有意为之，两门户弹窗要求逐类一致）。
- 层级方向（不可倒挂）：**分区标题(18) > 卡片标题(16) > 正文(14) > 辅助文字(11.5)**。
  `.aux-h` 辅助区标题**不小于**其下的链接（同 14px，靠 700 字重 + 灰 + 下边框分层）。
- 六个入口卡按 `--v6-k: 1.5` 整块放大，其字号是 1.5 倍后的整数档（15/17/19/21），
  仍在 `--fs-*` 名下、但在 `.v6-grid` 作用域内重定义；**卡标题 `.v6-t` 例外**
  —— 它取 `--fs-lg`(16px)、**不随这块卡放大**（它属于全页"卡片标题"层级，
  随放大就会盖过 18px 的分区标题，即层级倒挂）。
- 顶栏 `masthead.css` 是**独立字阶**（`rem`，标题 22px 等），因为它是 MsPortal
  顶栏的同步副本；不并入 `--fs-*`。
- 完整变更记录见 `architecture.md` 九之四（首轮）与九之六（复查整改）。

## 六、动效

| 动效 | 语义 | 实现 |
| --- | --- | --- |
| 绿色脉冲 | 这个面板正在自动刷新 | `bg-emerald-500 status-pulse-green` |
| 红色静止 | 取不到数据 | `bg-rose-500`（**不脉冲**） |
| hover 上浮 | 卡片可点击 | `hover:-translate-y-0.5 hover:shadow-lg` |
| 淡入 | 弹窗出现 | `animate-fadeIn` |

**动效只表达状态，不做装饰。**

## 七、深浅双模

- 默认深色。切换状态持久化在 localStorage。
- 所有组件必须带 `dark:` 变体，包括 `TaskSyncWidget`、`AnnouncementBanner` 等辅助部件。
- **验收必须两套都看**——只验一套等于漏测一半。

## 八、无障碍

- 仅图标按钮必须有 `title` 或 `aria-label`。
- 深色下正文不低于 `text-slate-500`（再暗对比度不足）。
- 颜色不能是唯一载体：失败态除变红还要有文案（如"取数失败: xxx"）。

## 九、改样式的纪律

1. **先找既定需求再动手**——"数字居中""不要整卡渐变""标题左对齐"都是需求原话，重构时不能顺手改掉。
2. **只改样式，不搭车改数据口径。**
3. **改大文件前建 `_bak_<日期>_<说明>` 快照**（本项目既有习惯）。
4. **对照 `MsPortal\` 下三份专项记录**（QC 优化建议、三列对齐、配色对齐）确认没有回退已定的结论。

## 十、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 全域视觉总则 | `D:\01_RPA\DESIGN.md` |
| 站内设计指南 | 「设计指南」弹窗（`DesignGuideModal.tsx`，i18n `guide.*`） |
| QC 面板优化建议 | `MsPortal\QC面板展示优化建议_20260922.md` |
| 三列对齐实测 | `MsPortal\三列对齐_可行性方案与实测_20260918.md` |
| 配色对齐记录 | `MsPortal\配色对齐VMAX90天看板_可行性结论与实施记录_20260918.md` |
| 手写静态壳字号令牌化（olbrportal） | `architecture.md` 九之四、九之六 |
| 组件 API | `component-api.md` |

> **工具负责整理，人与 AI 负责协作执行。**
