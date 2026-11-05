---
trigger: always_on
---

<!-- 本文件是 AI 编码工具规则的真源（_agents\rules\）。.qoder\rules\ 是指向本目录的 junction。 -->

my_app项目下的引用不要放到外面。 避免给别人传递遗漏文件导致无法运行

**口径说明一律默认收起、点击才展开**：界面里解释「这个数字怎么算的」的文字（数据源 / 粒度 / 分子分母 / 筛选范围 / 空卡原因 / 口径备注）必须用 `frontend\src\components\CalcChainNote`（默认收起，点标题展开），**禁止**常驻展开的说明条占首屏；真正的异常（口径缺陷、数据错误、截断）仍要常驻可见。细则见 `Task\my_app\AGENTS.md` 三.3b 与 `docs\manual\16-new-page-guide.md` 3.4b。

**页面上的数字必须能悬浮看到「这个数怎么算」**（2026-11-03 如意定，与上一条**并存不互替**）：收起的 `CalcChainNote` 只回答「这页整体怎么算」，用户鼠标停在一个具体数字上时还要能问「你这个数是怎么算出来的」。两层载体：标题/列头用 `frontend\src\components\MetricExplain.tsx::ExplainIcon`（ⓘ 气泡，讲**这一列/这一张卡**的算法），数字本身用同文件的 `ExplainPopover`（气泡里列出**这一格**的构成：参与平均的样本数、其中几个未达标、区间、上一期与环比）。参考实现 `pages\AvailCounty.tsx` + `pages\availCounty\availCountyHelpers.tsx::cellExplainText`。**禁止**把口径塞成 `title=` 原生提示（不可复制、主题不一致），也**禁止**在前端重算后端已算出的数字 —— 气泡内容一律取接口既有字段。iframe 页（`LegacyToolFrame`）不适用。细则见 `Task\my_app\AGENTS.md` 三.3c。

**每个页面都要有自己的「按页刷新设置」**（2026-11-04 如意定）：顶栏的「停止/开启刷新」按钮 + 间隔下拉对**每一个页面**都必须可用，选择按页持久化在 `localStorage['myapp_auto_refresh_pages']`（`{page: 秒}`，**默认关闭**）。**禁止**按页把控件禁用或维护「只有某类页面参与刷新」的白名单 —— 2026-11-03 的 `AR_BOARD_PAGES` 白名单就是因此被否掉的（配置/操作页想刷刷不了，且新增页面得回来改名单）。新增页面两件事：① 在 `frontend\src\App.tsx` 的 `AR_PAGE_DEFAULTS` 登记建议间隔（档位取 `AR_OPTIONS`，按数据更新频率 60/300/900/1800）；② 重挂载代价大的页进 `AR_INPLACE_REFRESH_PAGES`（React 页监听 `myapp-refresh` 原地重取数）或 `AR_SOFT_REFRESH_PAGES` + `frontend\public\myapp-refresh-protocol.js`（iframe/legacy 页）。有机器守卫 `tests\test_doc_consistency.py::test_every_page_has_refresh_setting`，漏登记会被本地钩子与 CI 拦下。细则见 `Task\my_app\AGENTS.md` 三.3d 与 `docs\manual\16-new-page-guide.md` 3.4d。
