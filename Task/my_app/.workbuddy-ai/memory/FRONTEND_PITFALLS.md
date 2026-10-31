# 前端 / Playwright / i18n 硬规则（从 MEMORY.md 拆出，主文件已超注入上限）

> 用法：做前端页面、写 Playwright 验证、改国际化文案前，先读本文件。

## A. 前端通用坑（实测）
1. **antd v6 `<Tag color="var(--wh-x)">` 会渲染成「看不见」**——antd 解析不了 CSS 变量 → 回落默认灰底 `rgb(242,242,242)`，叠加 `color:'#fff'` 就是白字白底。**传 CSS 变量给组件 color 属性一律不可靠**，改用内联样式徽标（淡底+同色字，按深浅主题两套）。
2. **Playwright `wait_for_function` 默认 rAF 轮询在无头下被节流**（把 11s 请求测成 178s）；测耗时用 `page.on("requestfinished")` 读 `timing`。
3. 帮助页「页面指南」是 **Tabs + Collapse 双层**，先点 `.ant-tabs-tab` 再展开分类 Collapse，否则 textContent 搜不到 → 易误判「文档没生成」。
4. **antd v6 DOM 类名与 v5 不同**（只影响 Playwright 断言）：没有 `.ant-collapse-content-active`（用 `.ant-collapse-item-active` 或 header 的 `aria-expanded`）、没有 `.ant-tabs-tabpane-active`（用 `.ant-tabs-content-active`，**且切换中旧面板会短暂共存 → 行数统计必须限定作用域**）、没有 `.ant-alert-message`（v6 是 `.ant-alert-section > .ant-alert-title/.ant-alert-description`）。**写断言前先 dump 一次 DOM 类名。**

## B. 下钻/明细类弹窗的既有组件（直接用，别自建 `Modal` + 裸 `Table`）
- `components/DraggableClickModal.tsx`：锚点=鼠标点击坐标、可拖动、Esc/× 关闭、点遮罩不关、自动跟随深浅主题。
- ⚠️ **必须用 `createPortal` 挂到 `document.body`**（2026-10-31 修，别再删）。全站卡片样式给
  `.ant-card/.wh-card` 挂了 `backdrop-filter`（玻璃态，`index.css:420` 那一组），而
  **`backdrop-filter`（同 `filter`/`transform`/`will-change`/`contain`）会让该元素成为
  `position:fixed` 子元素的包含块**。弹窗本来渲染在诊断卡内部时，fixed 变成「相对卡片固定」，
  JS 写的 `top` 再叠加卡片的文档偏移 —— 实测 `top:522px` 渲染成 `rect.top=882.5`，
  `bottom=1328 > vh=1100`，弹窗整体被推出视口。**判据：`el.style.top` 与
  `getBoundingClientRect().top` 不等时，先查祖先链上的 backdrop-filter。**
- 同理，`.dcm-body` 必须有 `flex:1 1 auto; min-height:0; overflow:auto`（三件套缺一不可）：
  否则 flex 子项默认 `min-height:auto` 会撑破 `.dcm-modal` 的 `max-height:88vh`，
  高度超过视口后 clamp 公式算出负数，弹窗上下同时被裁。
- 另外 `.dcm-overlay` **不要用 `display:flex` 居中**：modal 是 flex item 时会被
  `align-items:center` 预置偏移，JS 写的 `top` 叠加其上。
- `components/SearchableExportTable.tsx`：搜索框 + 导出按钮 + 分页表格，注释写明「供下钻/明细类抽屉复用」；已支持透传 `onRow`，整行可点即用它做下钻。
- 参考实现：`pages/UmeInKpi.tsx`（全页下钻，最完整）、`pages/gismap/SiteDrilldownDrawer.tsx`、`pages/RanCellsKpi.tsx`。

## C. 验证 ECharts 点击下钻的正确姿势（2026-09-15 踩了 3 轮）
1. **图表在视口外时 `page.mouse.click` 点在视口外、什么都不会发生** → 先 `scroll_into_view_if_needed()` 再取 `bounding_box()`。
2. 别用「最粗列」猜柱体（折线/横条图上最粗的往往是坐标轴/网格线），要**读 canvas 像素找系列色**：`getImageData` → 排除灰/黑/白（`max-min<45` = 文字/轴/网格）→ 按色聚类 → 组内按 **7×7 同色邻域密度**取点。
3. ⚠️ **必须排除图例区（y < 14%h）——点图例 = 切换系列显隐**，会把后续验证全带偏。
4. canvas 尺寸 == CSS 尺寸（dsf=1），换算 `box.x + px*box.width/canvas.width`。
5. 先 `wait_for_selector(".echarts-for-react canvas")`，否则 `querySelectorAll(...)[idx]` 为 undefined。

## D. 另外几个 Playwright 选择器坑
1. `:text-is()` 匹配不到「文本在子元素里」的节点（`.ant-statistic-title` 内是 `<span>`，`:text-is("KPI 项数")` 命中 0）→ 用 `filter(has_text=...)`。
2. 点 antd 表格里自绘的可点击单元格时，**要点 `td:has-text("X") span` 的第一个**——td 宽而可点 span 只占左侧一小段，点 td 中心会落在 span 外、不触发。
3. `.ant-card` + `has_text` 会串（`has_text="Alerts"` 命中的是**告警卡片**而不是「Alerts 概览卡」，点它会展开 Collapse 污染后续断言）→ 先 `filter(has=page.locator(".ant-statistic-title"))` 限定统计卡。
4. 弹窗内导出要限定 `.ant-tabs-content-active`，否则会点到隐藏页签的按钮（element is not visible）。

## E. 国际化（i18n）约定与检查方法（2026-09-15/16 实测）
- **后端只下发结构化字段，前端按 locale 组装文案**。反面教材：`_build_alerts` 曾把中文句子（`"XX / YY 系统侧失败率 37.5%（阈值 1%）"`）直接拼好下发 → EN 环境全是中文。现在下发 `metric_code` / `message_code` / `basis` / `*_en` / 原始数值，前端用 i18n 模板拼。
- 后端静态标签的英文放**映射表**（`FAIL_LABEL_EN` / `EXTRA_LABEL_EN`，中文标签→英文），不必把 `fail_cols` 元组改成 4 元组（改动面小、不破坏既有解包）。
- 前端统一用 `pick(en, zh, enVal)` / `kpiTitleOf(k, en)` / `failReasonOf(f, en)` / `alertKpiLabel(a, en)` / `alertTexts(a, en, t)`；**缺失英文时退回中性值（KPI 编码）而不是中文**。
- ⚠️ **中文未必在前端**：`ran_cells_kpi` 的「小区可用率 = …」来自 API 的 `desc` 字段（后端硬编码），grep 前端找不到 —— 先判断字符串来源再动手。
- ⚠️ **后端改完必须重启 7038**（uvicorn 无 `--reload`，不重启接口返回的还是旧结构）。
- **英文环境回归方法**（可复用）：`createTreeWalker(body, SHOW_TEXT)` 扫文本节点里带 `[\u4e00-\u9fff]` 的**可见**文本（过滤 `getBoundingClientRect()` 宽高为 0），去重打印。整站逐页 `TMP/t_i18n_allpages.py`、单页全下钻 `TMP/t_i18n_sweep2.py`。**导出 xlsx 也要逐单元格 grep CJK**（「失败分解」sheet 是独立代码路径，最易漏）。
- ⚠️ **先分清「请求时生成」还是「已落库」**：只有**请求时生成、不落库**的文案才值得本地化（如 `sp_material` 的 12 条 warnings → 后端加 `lang` 参数 + `_w(lang, zh, en)`）。**落库的中文不要翻译**：`tables` 页是 `task_queue.result_json` 的**值**、`sync` 页是任务 `error`/`message` 字段、`archive` 页的「分析 - xxx」是中文环境存进去的分析名称 —— 这些是**数据**，翻它们要么改源语言，要么上结构化 code + 渲染时本地化，都是独立工程。
- 现状：`ume_in_kpi` / `ran_cells_kpi` / `sp_material` 已 0 残留；整站 32 页 UI 文案全干净，剩余「中文」全属上面那类**存库数据**。

### E.1 规则层（纯函数）怎么写可翻译文案（2026-10-31，`vmaxDiagnosisRules.ts`）
- **规则层是纯函数、拿不到 `t()`**（不能 import React/context，否则不可单测）。
  所以描述一律返回 `I18nText = { key, params? }`，由组件用 `renderI18n(t, v)` 渲染。
  `params` 允许嵌套 `I18nText`（「无线侧不可判：{{why}}」），`renderI18n` 递归展开。
- `frontend/src/renderI18n.ts` **故意不 import `I18nText` 类型**，改用结构判断
  `isTranslatable` —— 否则形成 `rules ↔ render` 双向依赖。
- ⚠️ **`check:i18n` 扫不到这类漏翻**：它只扫 JSX 文本与 `t()` 的**字面量**入参，
  扫不到规则层拼好的中文串，也扫不到 `render: (v) => \`${v} 次\`` 这类回调里的内容。
  **真正的验收只有一条：切 EN 跑一遍，扫页面上的 `[\u4e00-\u9fa5]`。**
- ⚠️ **`t()` 占位符必须两种括号都替换**：字典主流写法是 `{{name}}`，早期有 `{name}`。
  只写 `replace('{name}')` 时 `'{{n}}'.replace('{n}','5')` = `'{5}'`（内层被吃、外层残留），
  **不报错也不缺键**，只有肉眼能发现。正确顺序：**先 `replaceAll('{{k}}')` 再 `replaceAll('{k}}')`**，
  且必须 `replaceAll`（同一参数在句中可能重复）。
- **标点 / 单位 / 分隔符都是文案**，不能硬编码：
  中文全角「：」「（）」「、」「；」↔ 英文半角「: 」「 (n)」「, 」「; 」。
  解决法：把「带标点的标签」整条做成键（`vmaxq.voice.estLabel` / `vmaxq.diag.suggestionLabel` /
  `vmaxq.diag.srcTag` / `vmaxq.game.keywordsCount`），值单独渲染以便染色。
- **量纲不同的单位词不能共用数值模板**：中文「万」=10^4、英文「K」=10^3，
  一个 `{{v}} 万 / {{v}}K` 模板吃同一个 `v` 会差 10 倍（1.42万==14200，1.42K==1420）。
  正确做法：**除数跟着语言走**（JS 里按 locale 选），字典只出单位词。
- **后端中文文案的正确修法**：后端**同时给 key 和中文兜底**
  （`label_key` + `label`、`key` + `name`、`service_key` + `category_label`、`raw` + `value`），
  前端按 key 翻译、缺键回退中文。不要只给 key（老版本后端/缓存会缺）也不要只给中文。
  两张映射表用 `assert set(A) == set(B)` 防漂移。
- **同一字段多处渲染时抽一个函数**（`sourceLabel(t, s)`）：三处各写一遍，
  改 i18n 只改一处就会出现「1300 是英文、空态那行还是中文」的割裂。

### E.2 英文界面回归脚本写法（`TMP/t_vmax_diag_i18n.py`，可复用）
- 切换语言**用 URL 参数 `?lang=en`**：`i18n.tsx::detectLocale` 判定链是
  `?lang= > app-locale > olbr.lang > 浏览器语言`，优先级最高，比点按钮稳。
  同时把 `locale` 也设成 `en-US` 兜底，避免「语言没切过去」被误判成漏翻。
- 白名单只放行**数据**：应用名（`EGAME_FREEFIRE`）/ 小区名 / 厂商名，
  以及**语言切换按钮**（显示目标语言本名，是通行做法）。其余一律算漏翻。
- 断言里的英文文案**必须查字典真实取值**，别凭印象写（曾写 "All Complaints"，实际是 "All"，白等 30s 超时）。
- ⚠️ **点下一个页签前必须先关 `.dcm-modal`**：它 Portal 挂 body，
  `.dcm-overlay` 会拦截后续所有点击（30s 超时 + "intercepts pointer events"）。
- ⚠️ **脚本内联的 mock 要跟着后端契约更新**，否则验证的是旧结构、漏翻会假通过。
- 反向也要跑：中文回归脚本确认没改坏（`TMP/t_vmax_diag_shot.py`）。

## F. 页面高度别自己减「外壳留白」（2026-09-17 实测，修掉 108px 底部空白）
- **外壳 embed/bare 模式**：URL 首屏带 `?page=`（直链/门户深链）或 `?embed=1` 时，
  `App.tsx` 的 `shellHidden` 会**不渲染 Header**、并把 Content 自己的 margin/padding 置 0。
- 此时若页面还写 `height: calc(100vh - var(--wh-header-height) - var(--wh-content-margin)*2 - var(--wh-content-padding)*2)`，
  就会**在底部多出 108px 空白**（2544×1297 视口下 iframe 只有 1189 高，实测像素色 (7,19,31) = 外壳底色，
  而页面 bg 是 `#02050c`=(2,5,12)——**用像素色就能判定空白属于页内还是外壳**）。
- 108 的来历：`index.css` 的 `html{font-size:clamp(14px,.55vw + 12.2px,18px)}` 在宽屏下 = **18px**，
  `3.5rem+1rem*2+.25rem*2 = 63+36+9 = 108`（注释里「56px」是 16px 根字号的旧值，别照抄）。
- **正确写法 = 铺满父级，不要自己算**：`LegacyToolFrame` 用 `height:'100%'`；普通页面同理用 `height:'100%'`
  或 `flex:1`。正常模式下 Content 已经把 Header/margin/padding 扣掉了，两种模式都对
  （实测正常模式 1189、bare 模式 1297）。
- 已修：`components/LegacyToolFrame.tsx`、`pages/EflowQa.tsx`（桌面分支）。
  ⚠️ `index.css` 的 `--wh-page-min-height` 是同类写法，只在「页面内容比视口矮」时才露出症状，属潜在项。

## G. ⚠️ 验证前端**必须走 nginx（`http://localhost/myapp/`），不能走 7038**（2026-09-17 实测）
- 7038 是后端 uvicorn，`/myapp/*` 是 **SPA catch-all**：请求 `/myapp/xxx.html` 返回的是 **index.html（1745 B）**，
  不是 `_fe_dist` 里的静态文件（对比：nginx :80 返回 34588 B 的真文件）。
- 症状：Playwright 打开 `http://127.0.0.1:7038/myapp/?page=xxx` 时，iframe 的 `src` 是
  `/myapp/xxx.html`，但 `contentDocument.title` 变成 **"任务管理 - 数据洞察 MVP"**、`#appTitle` 为 null、
  iframe 高度 = 整个视口 —— 其实是 **SPA 套 SPA**（iframe 里又渲染了一个外壳，默认停在任务管理页）。
  只看 `topbar` / `menu` / `iframe[title]` 会以为「改好了」，**实际页内文案根本没验到**。
- 正确姿势：`BASE = "http://localhost/myapp/"`（nginx :80）。静态资源 build 后由 nginx 直出。
- 快速判据：`curl -s --noproxy '*' -o out.html -w "%{size_download}" <url>` —— 1~2 KB 级 = 拿到 index.html，30 KB 级 = 真静态页。

## H. legacy 单文件页改显示名的「N 处清单」（漏一处就在某个入口露旧名）
`frontend/public/*.html` 是**自带内联 I18N 的单文件页**，和 `frontend/src/i18n.tsx` 是**两套 i18n**，必须都改：
1. `public/xxx.html` 的 `<title>`（静态兜底；**有的页不写 `document.title`，标签页名字就靠它**）
2. `public/xxx.html` 的 `<h1 id="appTitle">`（静态兜底，`paintStatic()` 会用 4 覆盖）
3. `public/xxx.html` 内联 `I18N.zh` 的标题键（90days 是 `title`，daily 是 `app.title`）
4. `public/xxx.html` 内联 `I18N.en` 的标题键
5. `src/i18n.tsx` zh 的 `nav.<pageKey>`（侧栏菜单 + 外壳顶栏 + 浏览器标签都吃它）
6. `src/i18n.tsx` en 的同一键
- 若页内副标题带「天粒度 / 日粒度」这类词，标题改了要**同一条 mast 行统一用词**，别一行两个词。
- 改完 `vite build`（`public/` 由构建拷进 `_fe_dist`），**静态资源不用重启 7038**。
- 核对产物：以 `_fe_dist/index.html` **实际引用的那个 `i18n-*.js`** 为准（`assets` 里堆着历史 chunk，grep 旧名会误命中）。

