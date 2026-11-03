---
trigger: always_on
---

<!-- 本文件是 AI 编码工具规则的真源（_agents\rules\）。.qoder\rules\ 是指向本目录的 junction。 -->

my_app项目下的引用不要放到外面。 避免给别人传递遗漏文件导致无法运行

**口径说明一律默认收起、点击才展开**：界面里解释「这个数字怎么算的」的文字（数据源 / 粒度 / 分子分母 / 筛选范围 / 空卡原因 / 口径备注）必须用 `frontend\src\components\CalcChainNote`（默认收起，点标题展开），**禁止**常驻展开的说明条占首屏；真正的异常（口径缺陷、数据错误、截断）仍要常驻可见。细则见 `Task\my_app\AGENTS.md` 三.3b 与 `docs\manual\16-new-page-guide.md` 3.4b。

**页面上的数字必须能悬浮看到「这个数怎么算」**（2026-11-03 如意定，与上一条**并存不互替**）：收起的 `CalcChainNote` 只回答「这页整体怎么算」，用户鼠标停在一个具体数字上时还要能问「你这个数是怎么算出来的」。两层载体：标题/列头用 `frontend\src\components\MetricExplain.tsx::ExplainIcon`（ⓘ 气泡，讲**这一列/这一张卡**的算法），数字本身用同文件的 `ExplainPopover`（气泡里列出**这一格**的构成：参与平均的样本数、其中几个未达标、区间、上一期与环比）。参考实现 `pages\AvailCounty.tsx` + `pages\availCounty\availCountyHelpers.tsx::cellExplainText`。**禁止**把口径塞成 `title=` 原生提示（不可复制、主题不一致），也**禁止**在前端重算后端已算出的数字 —— 气泡内容一律取接口既有字段。iframe 页（`LegacyToolFrame`）不适用。细则见 `Task\my_app\AGENTS.md` 三.3c。
