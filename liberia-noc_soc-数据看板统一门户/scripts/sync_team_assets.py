#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sync_team_assets.py —— 把上游 v3/olbrportal/ 的共享资产同步到 v3/team_portal/
================================================================================
为什么需要这个脚本
------------------
`v3/team_portal/` 是五个团队门户共用的静态根，它的大多数资产与上游
`v3/olbrportal/` **本该完全相同**（同一套 olbr.js / olbr.css / i18n 字典 / logo）。
但它们此前是**手工复制**的 —— 于是必然漂移：

    实测（2026-10-30）上游加了「团队门户」功能（um.team* 的 16 个 i18n 键、
    olbr.js 里的 UM_TEAMS 与团队选择器），团队门户那份 olbr-data.js / olbr.js
    却是改动前的副本 —— 团队门户里的「用户管理」面板**没有团队归属下拉框**，
    管理员在团队门户上无法给账号指派团队。

这类漂移很难靠眼睛发现（两份文件都"看起来对"），但症状是真实的功能缺失。
故把「同步」变成脚本：共享资产从上游**生成**出来，漂移不可能再发生。

同步规则（逐文件）
------------------
  · **纯共享**（同一份字节）：直接复制。
      olbr-data.js / masthead.css / qa-assistant.css / logo-*.png

  · **需要打补丁**：以上游为基线 + 固定的一组补丁。
      olbr.js         —— 由 patch_team_portal.py 负责（它另有 --check）
      olbr.css        —— 追加团队门户专有样式（本脚本）
      qa-assistant.js —— 追加 Quick Q&A 的作用域判据（本脚本）

  · **纯团队专有**（上游没有，不动）：team-matrix.js / team-scope-map.js /
    team-scope.js / team-panels.js

  · **index.html**：结构上游与团队门户**有意不同**（团队门户多一块
    Customer Complaint、多引三个作用域脚本），故**不自动同步**——
    它由 scripts/check_scope_coverage.py 的「检查 6」盯着：上游新增容器时，
    团队门户的 index.html 必须同步补上。

幂等：每次都从上游重新生成，天然幂等。

用法
----
    python scripts/sync_team_assets.py            # 同步
    python scripts/sync_team_assets.py --check    # 只比对，不写盘（CI 用）

⚠️ 本脚本**只写** v3/team_portal/assets/，**绝不碰** v3/olbrportal/。
"""
from __future__ import annotations

import argparse
import io
import os
import sys
# 钩子（.git/hooks/pre-commit -> check-team-scope.mjs）与 CI 里 stdout 是管道，
# Windows 下 Python 默认按 cp1252 编码，打印中文/✓ 会抛 UnicodeEncodeError 让
# 校验误判失败（校验本身是通过的）。见 .qoder/rules/shell_safe.md 第 2 条。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UP = os.path.join(ROOT, "v3", "olbrportal", "assets")
TP = os.path.join(ROOT, "v3", "team_portal", "assets")


def read(path: str) -> str:
    with io.open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(path: str, s: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)


# --------------------------------------------------------------------------
# 纯共享资产：逐字节复制
# --------------------------------------------------------------------------
PLAIN_SHARED = [
    "olbr-data.js",
    "masthead.css",
    "qa-assistant.css",
    # _local-credentials.js 刻意不在列：它被门户 .gitignore 的 `_*` 规则覆盖、从未入库，
    # 列进来等于要求「干净检出必须有一个 git 里没有的文件」，CI 因此永远红（2026-11-06）。
    # 它本身也已在 2026-10-14 停用，olbr.js 里加载它的 qaCredHtml()/loadQaCred() 整条删除。
    "logo-olr-ms-116.png",
    "logo-olr-ms-174.png",
    "logo-qa-badge-112.png",
    "logo-qa-badge-168.png",
    "logo-qa-badge.png",
    "logo-zte-word-40.png",
    "logo-zte-word-60.png",
]


# --------------------------------------------------------------------------
# olbr.css：上游 + 团队门户专有样式（追加在末尾）
# --------------------------------------------------------------------------
# ⚠️ 为什么用「追加」而不是「插入到某个位置」：追加的样式是**纯新增**
#   （.tr-table / .complaint-slot / .oss-grid.is-single），不改写任何既有规则，
#   故放在文件末尾也不会被上游的规则盖掉（CSS 同特异性下后写的赢，
#   而这些类名上游根本没有，不存在竞争）。
#   这也是「同一份 olbr.css 在两处都能用」的原因。
CSS_TEAM_SUFFIX = """

/* ============================================================================
   团队门户专有面板（2026-10-29 加）：Auto Report 过滤表 + 客户投诉入口
   ----------------------------------------------------------------------------
   这两组样式**只服务** v3/team_portal/ 的两块新面板：
     · .tr-table    —— Auto Report 的报告附件表（team-panels.js 渲染）
     · .complaint-slot / .oss-grid.is-single —— 客户投诉入口卡片
   上游 /v3/olbrportal/ 那份 olbr.css **没有**这几条（那边没有对应元素），
   两边互不影响；同一份 olbr.css 在两处都能用，是因为这段是纯新增、
   没有改写任何既有规则。

   ⚠️ 表体用 .canvas 的滚动语义：Auto Report 这块在 .qarow 左列，
     高度与右列的「CCH + OSS」合计等高（--qarow-h），行数多时表体内滚动，
     不把整页撑长。 */
.tr-table {
  width: 100%; border-collapse: collapse; font-size: var(--fs-sm);
  table-layout: fixed;
}
.tr-table th {
  text-align: left; font-weight: 600; color: var(--t3); font-size: var(--fs-xs);
  padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.tr-table td {
  padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* 文件名列宽一点（它是这一栏最有用的信息：具体哪份报告） */
.tr-table th:nth-child(2), .tr-table td:nth-child(2) { width: 34%; }
.tr-table th:nth-child(3), .tr-table td:nth-child(3) { width: 10%; }
.tr-table th:nth-child(4), .tr-table td:nth-child(4) { width: 18%; }
.tr-table th:nth-child(5), .tr-table td:nth-child(5) { width: 12%; }
.tr-table tbody tr:hover td { background: var(--surface-2); }
.tr-file { font-family: var(--mono, ui-monospace, Consolas, monospace); font-size: var(--fs-xs); }
.tr-num { color: var(--t2); }
.tr-sub { color: var(--t3); font-size: var(--fs-xs); }
.tr-empty { text-align: center; color: var(--t3); padding: 22px 10px; }
.tr-dl { color: var(--b); text-decoration: none; font-weight: 600; }
.tr-dl:hover { text-decoration: underline; }
/* 客户投诉：只有一张卡片时铺满整行，不必占 6 列里的一格 */
.oss-grid.is-single { grid-template-columns: minmax(0, 1fr); }
/* ⚠️ 2026-11-05：原 `.complaint-slot { margin-top: var(--s4) }` 已删除。
   根因与上游 .qarow 的 margin-top 是**同一个**：#complaintSlot 是 #main 的直接子项，
   而 #main 已经是 flex 列容器且有 gap: var(--s4)=16px —— 两者叠加成 32px，
   这一处会比其它区块间距宽一倍。
   上游那份 /v3/olbrportal/ 没有 .complaint-slot（那边没有这块元素），
   所以这条 margin-top 纯属多余，删掉即两处口径一致。
   间距**只由 #main 的 gap 说了算**，别在子项上再补 margin-top。 */

/* ============================================================================
   团队门户弹性列数（P0-2）+ 对侧铺满（P0-3）+ 投诉下线（P0-1）
   ----------------------------------------------------------------------------
   背景：团队门户按矩阵过滤后，卡片数 < 上游满配 ——
     · Daily Operation（#band）：FO 只剩 4 张卡，仍用 repeat(6) 会空两格；
     · Domain Dashboard（#views6）：FO 只剩 FO View 1 列，仍用 repeat(3) 只占 1/3；
     · .maprow / .qarow：对侧整块 hidden 时，剩下一侧仍只占半行。
   修法：渲染侧给 data-n（见 patch_team_portal.py 的 qc-cards-n / views6-grid-n
     钩子），CSS 侧按 data-n 展开；行级用 :has() 探对侧 hidden / :empty。
   上游 olbr.css 没有 data-n / :has(hidden) 规则，故两边互不影响。 */

/* Daily Operation：按实际卡数铺满整行（1~6）。特异性 (0,2,0) 高于基类 (0,1,0)。 */
#band .qc-grid[data-n="1"] { grid-template-columns: minmax(0, 1fr); }
#band .qc-grid[data-n="2"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
#band .qc-grid[data-n="3"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
#band .qc-grid[data-n="4"] { grid-template-columns: repeat(4, minmax(0, 1fr)); }
#band .qc-grid[data-n="5"] { grid-template-columns: repeat(5, minmax(0, 1fr)); }
#band .qc-grid[data-n="6"] { grid-template-columns: repeat(6, minmax(0, 1fr)); }
/* 窄屏不断裂：列数取 min(实际卡数, 断点列数)。 */
@media (max-width: 1200px) {
  #band .qc-grid[data-n="4"], #band .qc-grid[data-n="5"], #band .qc-grid[data-n="6"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  #band .qc-grid[data-n="3"], #band .qc-grid[data-n="4"], #band .qc-grid[data-n="5"], #band .qc-grid[data-n="6"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
/* 卡内同步拉满（2026-11-03 加）：外层按 data-n 铺满后，卡内趋势图也要跟上。
   根因：.qc-card 是纵向 flex + align-items:center，.qc-spark-wrap 作为 flex 子项
   按内容收缩（svg 百分比宽按 viewBox 内在 300px 定，卡变宽图不变），两侧留白。
   修法：wrap 拉伸到整卡宽，svg 的 width:100% 才真正吃满。只作用于带 data-n 的
   团队门户网格，上游无 data-n 不受影响。 */
#band .qc-grid[data-n] .qc-card > .qc-spark-wrap { align-self: stretch; width: 100%; }
#band .qc-grid[data-n] .qc-card > .qc-spark-wrap .qc-spark,
#band .qc-grid[data-n] .qc-card > .qc-spark-wrap .qc-spark svg { width: 100%; }
/* 1~2 张独占整行时图太扁：加高，避免宽卡配细条（3 张以上维持 26px 不动）。 */
#band .qc-grid[data-n="2"] .qc-spark,
#band .qc-grid[data-n="2"] .qc-spark svg { height: 34px; }
#band .qc-grid[data-n="1"] .qc-spark,
#band .qc-grid[data-n="1"] .qc-spark svg { height: 40px; }

/* Network Status 单组铺满（2026-11-03 加）：FLM 只勾了 avail 一组（3 张卡），
   按基类 repeat(6) + 组 span 3 只占半行，右侧留白。单组时整组跨满整行，
   组内 3 张卡自动拉伸吃满（.qc-group-b[data-n="3"] 本来就是 3 列）。
   :has/:only-child 上游已在用（.maprow 那组），不引入新兼容风险。
   骨架与真卡同构，自动生效。 */
#kpi .qc-grid:has(> .qc-group:only-child) { grid-template-columns: minmax(0, 1fr); }
#kpi .qc-grid > .qc-group:only-child { grid-column: 1 / -1; }

/* Domain Dashboard：按实际视图列数铺满整行（1~6）。 */
#views6 .v6-grid[data-n="1"] { grid-template-columns: minmax(0, 1fr); }
#views6 .v6-grid[data-n="2"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
#views6 .v6-grid[data-n="3"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
#views6 .v6-grid[data-n="4"] { grid-template-columns: repeat(4, minmax(0, 1fr)); }
#views6 .v6-grid[data-n="5"] { grid-template-columns: repeat(5, minmax(0, 1fr)); }
#views6 .v6-grid[data-n="6"] { grid-template-columns: repeat(6, minmax(0, 1fr)); }
/* 卡内条目：**固定 5 列轨道，逐行对齐**（2026-11-06 改，用户要「5 个一行 + 不同组列对齐」）。
   演变与根因（这段改过三次，别退回前两版）：
     · 2026-11-03 版：只在 data-n="1" 时把 .v6-list 改 auto-fit 网格。
       轨道数由整张列表宽度一次性决定，与「某个专业域有几条」无关 ——
       5 条的 RAN 铺满 5 条轨道后，MW 只有 2 条仍只占 1~2 号轨道，
       右侧留下三条空轨道（约 870px 空白）。
     · 2026-11-05 版：改 flex 行流 + flex:1 1 280px + flex-grow 拉伸。
       消掉了右侧空白，但**代价是列宽不再固定** —— 段内条数少的那一行
       （MW 2 条 → 各 736px）与条数多的那一行（RAN 5 条 → 各 288px）
       宽度不同，跨段看过去左右边界一格都不齐。用户 2026-11-06 报的
       「按照 5 个一行，不同的组要列对齐」就是这一版的问题。
     · 本版（grid）：整张列表共用一个 5 列轨道模板，所有段的条目都落在
       同一套列边界上 —— 第 N 条恒在第 N 格，跨段垂直对齐；段头跨满整行。
       某段最后一行不足 5 条时**保留空格**（不再拉伸），这是列对齐的必然代价。
   为什么单列（data-n="1"）才是 5 列：
     · BO 视图列宽约 1520px（1600 视口），5 列每列 ~296px，与原先 280px 基准相当；
     · 半宽列（flm 双列，单列约 740px）放 5 列会挤成 ~140px，
       标题全被 ellipsis 截掉 —— 故多列布局退到 2 列，语义不变（组内仍逐行对齐）。
   为什么**不再按 data-n 分档**：5 列是「单列卡独占整行」这一种情形的解，
     data-n 只用来区分单列/多列两种宽度档，不再是 1~6 的等比数组。
   默认的 .v6-list 是 flex column（上游三列窄卡），本组规则只作用于带 data-n 的团队门户网格。
   段头（.v6-seg-h）/ 空态 / 展开按钮：grid-column 1/-1 → 跨满整行，不占轨道。
   ⚠️ DOM 结构不变（段头与条目仍是 .v6-list 的直接子元素）——
       team-layout.js 的拖拽排序按「.v6-list > .v6-row」取键与重排，
       一旦加包装层就会取不到键、排序失效。 */
#views6 .v6-grid[data-n] .v6-list {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: calc(4px * var(--v6-k));
  align-content: start;
}
/* 多列布局（flm 双列等）：半宽列放 5 列太挤，退到 2 列。 */
#views6 .v6-grid[data-n]:not([data-n="1"]) .v6-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
#views6 .v6-grid[data-n] .v6-seg-h,
#views6 .v6-grid[data-n] .v6-empty,
#views6 .v6-grid[data-n] .v6-more { grid-column: 1 / -1; }
/* 段头与上一段末行之间：grid gap 已给 4px，段头自带的 margin-top 归零，
   避免间距变成 7px 又和别处不一致（段间靠 .v6-seg-h 的上边框 + gap 区分即可）。 */
#views6 .v6-grid[data-n] .v6-seg-h { margin-top: 0; }
#views6 .v6-grid[data-n] .v6-row { min-width: 0; }
#views6 .v6-grid[data-n] .v6-more { justify-self: start; }
/* 编辑态：条目里有标题/链接两个输入框，296px 太窄，退回单列；编辑结束自动恢复。 */
#views6 .v6-grid[data-n] .v6-list:has(> .v6-row.is-ed) { grid-template-columns: minmax(0, 1fr); }
@media (max-width: 1200px) {
  #views6 .v6-grid[data-n] .v6-list { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 780px) {
  #views6 .v6-grid[data-n] .v6-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 1400px) {
  #views6 .v6-grid[data-n="4"], #views6 .v6-grid[data-n="5"], #views6 .v6-grid[data-n="6"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  #views6 .v6-grid[data-n="1"] { grid-template-columns: minmax(0, 1fr); }
}

/* 对侧铺满：.maprow / .qarow 任一侧 hidden 或空时，另一侧占满整行。
   :has() 在本项目已在用（见上游 .maprow:has(.map-slot:empty)），不引入新兼容风险。
   [hidden] 走属性选择器 —— olbr.js 按矩阵收放时设的是 el.hidden = true。
   [data-tl-off] 是布局隐藏的同语义标记（见 team-layout.js applyLayout），
   用户藏掉一侧后另一侧同样拉满。 */
.maprow:has(> .map-slot[hidden]) { grid-template-columns: minmax(0, 1fr); }
.maprow:has(> .map-slot[data-tl-off]) { grid-template-columns: minmax(0, 1fr); }
.maprow:has(> .qa-slot[hidden]) { grid-template-columns: minmax(0, 1fr); }
.maprow:has(> .qa-slot[data-tl-off]) { grid-template-columns: minmax(0, 1fr); }
.maprow:has(> .qa-slot:empty) { grid-template-columns: minmax(0, 1fr); }
.qarow:has(> .email-slot[hidden]) { grid-template-columns: minmax(0, 1fr); }
.qarow:has(> .email-slot[data-tl-off]) { grid-template-columns: minmax(0, 1fr); }
.qarow:has(> .email-slot:empty) { grid-template-columns: minmax(0, 1fr); }
.qarow:has(> .qarow-col[hidden]) { grid-template-columns: minmax(0, 1fr); }
.qarow:has(> .qarow-col[data-tl-off]) { grid-template-columns: minmax(0, 1fr); }
/* qarow 右列内部（2026-11-04 改）：CCH 与 OSS 任一 hidden 时，另一块吃掉整列高度。
   ⚠️ 选择器从 .fb-slot 改为 .cch-slot —— User Feedback 面板已移进头像下拉，
     右列上半现在是 CCH（独立面板），下半是 OSS Portal Login。 */
.qarow-col:has(> .oss-slot[hidden]) > .cch-slot { flex: 1 1 auto; }
.qarow-col:has(> .oss-slot[data-tl-off]) > .cch-slot { flex: 1 1 auto; }
.qarow-col:has(> .cch-slot[hidden]) > .oss-slot { flex: 1 1 auto; height: auto; min-height: var(--qarow-h); }
.qarow-col:has(> .cch-slot[data-tl-off]) > .oss-slot { flex: 1 1 auto; height: auto; min-height: var(--qarow-h); }

/* ----------------------------------------------------------------------------
   右列全空：Auto Report 独占整行 + 高度随内容（2026-11-06 加，用户要求）
   ----------------------------------------------------------------------------
   现象（/v3/flm_portal/ 实测）：团队矩阵把 cch 与 oss 两域对这个团队都关了，
   #cchSlot / #ossSlot 双双 hidden，但 .qarow 仍按 2 列栅格排版 ——
   Auto Report 被挤在左半栏（759px / 行宽 1534px），右半栏一片空；
   同时 .canvas 还锁着 min-height: var(--qarow-h)=860px，表体只有几行，
   下面拖出几百像素的白。用户要求：「右边没有组件就直接占一行，
   并且高度根据内容自适应」。

   判据与上面「对侧铺满」同族、同口径：右列里**没有任何一个未被矩阵/布局隐藏的
   section** 就算全空，[hidden]（矩阵）与 [data-tl-off]（布局编辑器隐藏）都认；
   再加上「.qarow-col 整个不存在」的兜底 —— 那种页面同样只有左列。
   ⚠️ 只看 section：右列将来若加非 section 的装饰元素（分隔线之类），
     不该因为它被判成「有右列」；真要参与判断再单独补，别放宽这里。

   ① 空列本身 display:none —— 只改栅格列数不够：它仍是第 2 个 grid item，
      会白占一整行高度并再吃一个 gap（与 2026-11-05 修「空行双 gap」同一个坑）。
   ② 栅格收成 1 列，Auto Report 满宽。
   ③ canvas 的 860px 下限归零、flex 不放大，高度回到表格本身。
      只在这一种形态下放开：有右列时仍要靠 --qarow-h 与右列合计等高（正常态）。
      上游 /v3/olbrportal/ 框里永远有 OSS，且它那份 olbr.css 没有本段，行为不变。
      ⚠️ 团队门户的 Auto Report 是 team-panels.js 渲染的 DOM 表（可自动量高）；
        上游那份是内嵌 iframe（height:100% 需要确定高度），所以这条不能上移到上游。
   ④ 加载态：骨架 .embed-boot 是 absolute inset:0、自身不贡献高度，数据没到时
      内容高度为 0 —— 给一个温和下限，避免面板从 0 起跳、数据到位再突然长高。 */
.qarow > .qarow-col:not(:has(> section:not([hidden]):not([data-tl-off]))) { display: none; }
.qarow:not(:has(> .qarow-col > section:not([hidden]):not([data-tl-off]))) {
  grid-template-columns: minmax(0, 1fr);
}
.qarow:not(:has(> .qarow-col > section:not([hidden]):not([data-tl-off]))) > .email-slot .canvas {
  min-height: 0;
  /* 父高度是 auto，flex:1 本来就等于自然高度；写成 0 0 auto 表明「别放大」 */
  flex: 0 0 auto;
}
.qarow:not(:has(> .qarow-col > section:not([hidden]):not([data-tl-off])))
  > .email-slot .canvas:has(> .embed-boot:not([hidden])) { min-height: 180px; }

/* Customer Complaint 下线（P0-1）：CCH（VMAX 用户查询，2026-11-04 起为独立面板）已覆盖，团队门户不再显示。
   矩阵侧已置空（scope-map.json matrix.complaint.vmax = []），这里再加一道硬隐藏 ——
   即使某份旧矩阵仍勾选，页面上也不会露出来（fail-closed 朝隐藏方向）。 */
.complaint-slot { display: none !important; }

/* ============================================================================
   CCH 与 OSS Portal Login 并排一行 + CCH「加载不出来」修复（2026-11-05）
   ----------------------------------------------------------------------------
   适用范围：本行左列 Auto Report 整块被隐藏的团队门户（当前就是 smc —— 它在
   report 域一行都没勾，renderEmailSection() 直接 el.hidden = true）。
   fo / bo / flm 左列还在，仍保持上游那份「上 CCH / 下 OSS」的上下叠放。

   ① 为什么原来「CCH 加载不出来」：
      .qarow 只剩 .qarow-col 一个 grid item 时，这一行**没有确定高度**：
        · .oss-slot 是 flex:0 0 var(--oss-h)（430px）；
        · .cch-slot 是 flex:1 1 auto，可分配的剩余高度为 0；
        · .qarow .canvas { min-height:0 } 又把 .canvas 的 460px 下限压掉，
          而 iframe 是 position:absolute（不参与流式高度）→ .canvas 归零。
      无头浏览器实测（1600px 宽）：cchSlot 91px / cchCanvas 2px / iframe 0px，
      但 nginx 访问日志里 /myapp/?page=vmax_user_query&embed=1&lang=en 是 304 ——
      iframe 其实已经加载，只是**容器 0 高**看不见，看起来像「没加载出来」。
      所以修法不是改 iframe 地址或重试，而是给这一行一个确定高度。

   ② 用户要求「放一行，CCH 在左边」：右列改横向 flex，两块各占一半。
      .qarow-col 显式 height: var(--qarow-h)（沿用本行唯一高度真相源，
      宽屏 860px / 窄屏 420px 自动跟 .qarow 的断点走），
      flex 子项被 align-items:stretch 拉满后 .canvas 才有真实高度。
      ⚠️ 必须同时把 .oss-slot 的 flex-basis / height 从 --oss-h 改回 auto：
        纵向布局里它是「固定高度」，横向布局里 430px 会变成「固定宽度」。

   ③ 隐藏态：三种隐藏写法都要认（矩阵 hidden / 布局编辑器 data-tl-off /
      渲染后 :empty），与上面「对侧铺满」那组保持同一口径。
      只剩一块时让它独占整行，否则并排规则会留下半行空白。 */
/* ⚠️ 末尾那个 :has() 不能省：cxo 团队的 cch / oss 两域都没勾，两块同时 hidden。
   若照样给它 860px 固定高度，页面上会多出一整行空白（改版前是 0 高、自动消失）。
   故只有「两块里至少还有一块可见」时才撑起这一行。 */
.qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty))
  > .qarow-col:has(> :is(.cch-slot, .oss-slot):not([hidden]):not([data-tl-off])) {
  flex-direction: row;
  align-items: stretch;
  height: var(--qarow-h);
}
.qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty)) > .qarow-col > .cch-slot {
  flex: 1 1 0; min-width: 0;
}
.qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty)) > .qarow-col > .oss-slot {
  flex: 1 1 0; width: auto; height: auto; min-height: 0;
}
/* 并排后右栏只有半行宽，原来 6 列每格不足 110px，卡片名会被挤成一行一个字。
   降到 3 列；行数多时仍沿用 .oss-grid 自带的 overflow:auto，不把面板撑长。 */
.qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty)) .oss-slot .oss-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
/* 只剩一块时独占整行（覆盖上面的 flex:1 1 0 与「对侧铺满」旧规则）。 */
.qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty))
  > .qarow-col:has(> .oss-slot:is([hidden], [data-tl-off])) > .cch-slot,
.qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty))
  > .qarow-col:has(> .cch-slot:is([hidden], [data-tl-off])) > .oss-slot {
  flex: 1 1 auto;
  min-height: var(--qarow-h);
}
/* 窄屏：并排会把两块同时压到 400px 以下，退回上下叠放。
   这里仍要留确定高度（min-height + .cch-slot 的 min-height），
   否则窄屏又会重现 ① 的「iframe 0 高」。 */
@media (max-width: 900px) {
  .qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty))
    > .qarow-col:has(> :is(.cch-slot, .oss-slot):not([hidden]):not([data-tl-off])) {
    flex-direction: column;
    height: auto;
    min-height: var(--qarow-h);
  }
  .qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty)) > .qarow-col > .cch-slot {
    flex: 1 1 auto; min-height: 320px;
  }
  .qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty)) > .qarow-col > .oss-slot {
    flex: 0 0 var(--oss-h); height: var(--oss-h);
  }
  .qarow:has(> .email-slot:is([hidden], [data-tl-off], :empty)) .oss-slot .oss-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
"""


# --------------------------------------------------------------------------
# qa-assistant.js：上游 + Quick Q&A 的作用域判据
# --------------------------------------------------------------------------
QA_OLD = """  /* 登录门打开时隐藏挂件：未登录的访客不该能问内部工单/站点数据 */
  function syncVisibility() {
    var gate = document.getElementById('gate');
    var gateOpen = !!(gate && !gate.hasAttribute('hidden'));
    fab.hidden = gateOpen;
    if (gateOpen) closePanel();
  }"""

QA_NEW = """  /* 登录门打开时隐藏挂件：未登录的访客不该能问内部工单/站点数据 */
  function syncVisibility() {
    var gate = document.getElementById('gate');
    var gateOpen = !!(gate && !gate.hasAttribute('hidden'));
    /* 团队门户作用域（2026-10-29 加）：Excel 的 Knowledge Q&A 域里「Quick Q&A」
       这一行决定右下角这个挂件要不要出现。
       ⚠️ SCOPE 为 null 时（上游 /v3/olbrportal/ 那份共用文件）行为与改动前完全一致。 */
    var scope = window.OLBR_SCOPE || null;
    var allowed = !scope || scope.ok('qa', 'assistant');
    fab.hidden = gateOpen || !allowed;
    if (gateOpen || !allowed) closePanel();
  }"""

# --------------------------------------------------------------------------
# qa-assistant.js：会话自愈（2026-10-30 加）
# --------------------------------------------------------------------------
# 为什么要给这个文件单独打补丁：
#   问答助手走同源 /api/portal-qa/*（my_app 后端转发到本机问答服务），
#   那些接口在远端**同样要求 myapp_session Cookie**（实测无会话时回 401）。
#   而本文件自带一个裸 fetch（api()），**不走** olbr.js 的 api()，
#   故拿不到「401 → 换会话 → 重试」的自愈 —— 症状是问答面板一直显示登录。
#
# ⚠️ 本文件的 api() **不抛异常**：它把结果收成 { status, body } 交给调用方
#   （describeError() 靠 res.status 判 401 并提示登录）。
#   故不能用 team-session.js 的 retryOn401（那个靠 catch 抛错来识别 401），
#   这里另写一个「按状态码判断」的变体。
#
# ⚠️ 只对 GET/POST 都重试一次；ask 是 POST —— 重复提问会问两遍吗？
#   不会：401 意味着请求**根本没进业务逻辑**（鉴权中间件在路由之前就拦了），
#   问答服务压根没收到这个请求。
QA_OLD_SESSION = """  function api(path, payload) {
    return fetch(API + path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        return { status: r.status, body: j };
      });
    });
  }"""

QA_NEW_SESSION = """  function api(path, payload) {
    /* 团队门户（2026-10-30 加）：401 时换一次 my_app 会话再重试一次。
       背景见 scripts/sync_team_assets.py 里本补丁的说明。
       ⚠️ SCOPE/OLBR_SESSION 为 null 时（上游 /v3/olbrportal/）行为与改动前完全一致。 */
    var SESSION = window.OLBR_SESSION || null;
    var raw = function () {
      return fetch(API + path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload || {})
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          return { status: r.status, body: j };
        });
      });
    };
    if (!SESSION) return raw();
    return raw().then(function (res) {
      /* 只在 401 时自愈；重试**仅一次**，避免把 401 变成死循环。 */
      if (!res || res.status !== 401) return res;
      return SESSION.ensure(true).then(function (r) {
        if (!r.ok) return res;          /* 换不到会话 → 把 401 如实交回调用方 */
        return raw();
      });
    });
  }"""


QA_OLD_HEALTH = """  function probeHealth() {
    if (healthDone) return;
    healthDone = true;
    foot.textContent = t('booting');
    fetch(API + '/health', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })"""

QA_NEW_HEALTH = """  function probeHealth() {
    if (healthDone) return;
    healthDone = true;
    foot.textContent = t('booting');
    /* 团队门户（2026-10-30 加）：探活也要带会话，否则远端用户看到的是
       「服务未就绪」而不是真实状态。401 时换一次会话再试一次。
       ⚠️ 这是 GET，幂等，重试安全。 */
    var SESSION = window.OLBR_SESSION || null;
    var healthRaw = function () {
      return fetch(API + '/health', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    };
    var healthFetch = SESSION
      ? healthRaw().then(function (r) {
          if (r.status !== 401) return r;
          return SESSION.ensure(true).then(function (res) {
            return res.ok ? healthRaw() : r;
          });
        })
      : healthRaw();
    healthFetch
      .then(function (r) { return r.json(); })"""


def build_qa_assistant(src: str) -> str:
    norm = src.replace("\r\n", "\n")
    # ① 作用域判据（Quick Q&A 该不该出现）
    if QA_OLD not in norm:
        if QA_NEW not in norm:
            sys.exit(
                "qa-assistant.js 未命中补丁片段 —— 上游已变，请核对 sync_team_assets.py 的 QA_OLD。"
            )
    else:
        norm = norm.replace(QA_OLD, QA_NEW, 1)
    # ② 会话自愈（401 → 换会话 → 重试一次）
    if QA_OLD_SESSION in norm:
        norm = norm.replace(QA_OLD_SESSION, QA_NEW_SESSION, 1)
    elif QA_NEW_SESSION not in norm:
        sys.exit(
            "qa-assistant.js 未命中会话补丁片段 —— 上游已变，"
            "请核对 sync_team_assets.py 的 QA_OLD_SESSION。"
        )
    # ③ 探活也要带会话
    if QA_OLD_HEALTH in norm:
        norm = norm.replace(QA_OLD_HEALTH, QA_NEW_HEALTH, 1)
    elif QA_NEW_HEALTH not in norm:
        sys.exit(
            "qa-assistant.js 未命中探活补丁片段 —— 上游已变，"
            "请核对 sync_team_assets.py 的 QA_OLD_HEALTH。"
        )
    # 恢复上游的换行风格
    return norm.replace("\n", "\r\n") if "\r\n" in src else norm


def build_olbr_css(src: str) -> str:
    """上游 CSS + 团队专有样式（幂等：已追加过就不重复追加）。"""
    norm = src.replace("\r\n", "\n")
    marker = "团队门户专有面板（2026-10-29 加）"
    if marker in norm:
        return src
    # 保持与上游一致的换行风格
    if src.endswith("\n"):
        norm = norm + CSS_TEAM_SUFFIX.lstrip("\n")
    else:
        norm = norm + CSS_TEAM_SUFFIX
    return norm.replace("\n", "\r\n") if "\r\n" in src else norm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对现有文件，不写入")
    args = ap.parse_args()

    if not os.path.isdir(UP):
        sys.exit("找不到上游资产目录：%s" % UP)
    os.makedirs(TP, exist_ok=True)

    # 生成物 → 期望内容
    expected: dict[str, bytes] = {}
    text_expected: dict[str, str] = {}

    # ① 纯共享：逐字节复制
    for name in PLAIN_SHARED:
        src = os.path.join(UP, name)
        if not os.path.exists(src):
            print("上游缺少资产：%s" % name, file=sys.stderr)
            return 1
        with open(src, "rb") as f:
            expected[name] = f.read()

    # ② olbr.css：上游 + 团队专有样式
    css_src = read(os.path.join(UP, "olbr.css"))
    text_expected["olbr.css"] = build_olbr_css(css_src)

    # ③ qa-assistant.js：上游 + Quick Q&A 判据
    qa_src = read(os.path.join(UP, "qa-assistant.js"))
    text_expected["qa-assistant.js"] = build_qa_assistant(qa_src)

    # —— 比对 / 写入 ——
    drift: list[str] = []
    for name in PLAIN_SHARED:
        dst = os.path.join(TP, name)
        if not os.path.exists(dst):
            drift.append("%s（缺失）" % name)
            continue
        with open(dst, "rb") as f:
            if f.read() != expected[name]:
                drift.append(name)
    for name, content in text_expected.items():
        dst = os.path.join(TP, name)
        if not os.path.exists(dst):
            drift.append("%s（缺失）" % name)
            continue
        if read(dst) != content:
            drift.append(name)

    if args.check:
        if drift:
            print("团队门户的共享资产与上游已漂移：%s" % ", ".join(drift), file=sys.stderr)
            print("请重跑 python scripts/sync_team_assets.py", file=sys.stderr)
            return 1
        print("✓ 团队门户的共享资产与上游一致")
        return 0

    for name in PLAIN_SHARED:
        dst = os.path.join(TP, name)
        with open(dst, "wb") as f:
            f.write(expected[name])
    for name, content in text_expected.items():
        write(os.path.join(TP, name), content)

    print("✓ 已同步 %d 个共享资产到 v3/team_portal/assets/" % (len(PLAIN_SHARED) + len(text_expected)))
    if drift:
        print("  （此前已漂移并被修正：%s）" % ", ".join(drift))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
