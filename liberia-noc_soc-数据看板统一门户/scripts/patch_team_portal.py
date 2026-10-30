#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
patch_team_portal.py —— 生成 v3/team_portal/ 的作用域版 olbr.js
================================================================================
用途
----
`v3/team_portal/` 是五个团队门户（/v3/fo_portal/、/v3/bo_portal/、/v3/flm_portal/、
/v3/smc_portal/、/v3/cxo_portal/）共用的静态根。每个门户只显示《新看板设计.xlsx》
里该团队打勾（√）的那几行内容。

本脚本做两件事：
  ① 以 v3/olbrportal/assets/olbr.js 为**基线**，生成 team_portal 的副本；
  ② 在副本里插入若干「按矩阵过滤」的钩子。

为什么是「基线 + 钩子」而不是直接维护两份
------------------------------------------
olbr.js 有 8000 多行、37 万字符。fork 一份就是两份真相源，此后每次上游改动
都要手工合并一遍，必然漂移。这里让上游仍然是**唯一真相源**：脚本每次都从
上游重新生成副本，再打上固定的一组钩子。上游改了跑一遍脚本即可，钩子的位置
由本脚本里的「原文片段 → 新片段」一一对应表固定，片段找不到就报错退出，
不会静默漏改。

⚠️ 本脚本**只写** v3/team_portal/assets/olbr.js，**绝不碰** v3/olbrportal/。
   上游那份是别人的页面，一行都不动。

幂等：脚本每次都从上游重新生成，天然幂等；同一份输入必得同一份输出。

用法
----
    python scripts/patch_team_portal.py             # 生成 + 打钩子
    python scripts/patch_team_portal.py --check     # 只比对，不写盘（CI 用）
"""
from __future__ import annotations

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "v3", "olbrportal", "assets", "olbr.js")
OUT = os.path.join(ROOT, "v3", "team_portal", "assets", "olbr.js")


def read(path: str) -> str:
    with io.open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(path: str, s: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)


# --------------------------------------------------------------------------
# 钩子表：(标签, 原文, 新文)
# 原文里的换行用 \n 书写，脚本按文件实际换行风格归一化后再匹配。
# --------------------------------------------------------------------------
HOOKS: list[tuple[str, str, str]] = []


def H(label: str, old: str, new: str) -> None:
    HOOKS.append((label, old, new))


# ==========================================================================
# 1) 声明 SCOPE
# ==========================================================================
H(
    "scope-decl",
    """  var DATA = window.OLBR_DATA || {};
  var S = DATA.S || {};
""",
    """  var DATA = window.OLBR_DATA || {};
  var S = DATA.S || {};

  /* 团队门户作用域（2026-10-29 加）。
     ⚠️ **只在团队门户下非 null**：SCOPE 由 assets/team-scope.js 注入，
     那个脚本按 URL 前缀判断当前是不是 /v3/<team>_portal/。
     本文件是 v3/team_portal/ 的副本，与上游 /v3/olbrportal/ 并列共存 ——
     **上游那份一行未改**（改它等于改别人的页面）。

     为什么要有这一层：五个团队门户每个只显示《新看板设计.xlsx》里该团队勾了的
     几行内容。勾选矩阵是**需求文档的机器可读形式**（assets/team-matrix.js，
     由 scripts/gen_team_matrix.py 从 Excel 生成），本文件在各渲染点按矩阵过滤。

     为什么用「薄适配层」而不是 fork 这份 37 万字符的脚本：fork 一次就是两份
     真相源，此后每次上游改动都要手工合并一遍，必然漂移。改成在渲染点查
     SCOPE 之后，上游的修复能直接被五个团队门户继承。

     SCOPE 为 null 时下面每个 `if (SCOPE && ...)` 都短路 —— 行为与改动前完全一致。 */
  var SCOPE = window.OLBR_SCOPE || null;
""",
)

# ==========================================================================
# 2) Daily Operation（#band）：按矩阵过滤六张 QC 卡
# ==========================================================================
H(
    "qc-skeleton",
    """        '<div class="qc-grid">' + (D.qc || []).map(function () {
          return '<div class="qc-card"><span class="sk" style="width:56%"></span>' +
            '<span class="sk v"></span><span class="sk s"></span></div>';
        }).join('') + '</div>';""",
    """        '<div class="qc-grid">' + (D.qc || []).filter(function (d) {
          /* 团队门户作用域：骨架也要按矩阵过滤，否则会出现「骨架摆六张、
             数据到位只剩两张」的整块跳动（骨架与真卡必须 1:1 同构）。 */
          return !SCOPE || SCOPE.ok('qc', d.id);
        }).map(function () {
          return '<div class="qc-card"><span class="sk" style="width:56%"></span>' +
            '<span class="sk v"></span><span class="sk s"></span></div>';
        }).join('') + '</div>';""",
)

H(
    "qc-cards",
    """    var cards = DATA.QC_PRIMARY_ORDER.concat(DATA.QC_SECONDARY_ORDER).map(function (id) {
      return byId[id] ? qcCardHtml(byId[id]) : '';
    }).join('');""",
    """    var cards = DATA.QC_PRIMARY_ORDER.concat(DATA.QC_SECONDARY_ORDER).map(function (id) {
      /* 团队门户作用域（2026-10-29 加）：只渲染本团队在《新看板设计.xlsx》里
         勾了的指标。判据来自 assets/team-matrix.js（由 scripts/gen_team_matrix.py
         从 Excel 生成），引擎见 assets/team-scope.js。
         SCOPE 为 null 时（上游 /v3/olbrportal/ 那种非团队门户）行为与改动前
         完全一致 —— 一行都没少、一行都没多。 */
      if (SCOPE && !SCOPE.ok('qc', id)) return '';
      return byId[id] ? qcCardHtml(byId[id]) : '';
    }).join('');
    /* 整个 Daily Operation 域都没勾时，这一带应当**整块消失**（连标题行都不留）——
       留一个空标题 + 空卡区比不显示更难懂（用户会以为数据没加载出来）。
       判据放在这里而不是更上层，是因为 renderBand 是这一带的唯一渲染入口。
       ⚠️ hidden 由本函数显式管理：mainLocked(false) 会把清单里所有区块的 hidden
       设成 false，而团队门户需要在渲染时按矩阵重新收放，故这里成对地写 true/false。
       SCOPE 为 null 时**不碰 hidden**，保持上游行为不变。 */
    if (SCOPE) {
      if (!SCOPE.ok('qc')) { box.innerHTML = ''; box.hidden = true; return; }
      box.hidden = false;
    }""",
)

# ==========================================================================
# 3) Network Status / Network Benchmark（#kpi）：按组过滤
# ==========================================================================
H(
    "kpi-scope-vars",
    """  function renderKpi() {
    var box = $('#kpi');
    if (!box) return;
    var k = state.kpi;""",
    """  function renderKpi() {
    var box = $('#kpi');
    if (!box) return;
    var k = state.kpi;
    /* 团队门户作用域（2026-10-29 加）：
       · KPI_GROUPS 有两组（rich = 总流量/活跃用户/视频速率，avail = 2G/3G/4G 可用率），
         对应 Excel 的 Network Status 域两行，按组 id 过滤。
       · BF_GROUPS 有两组（speed = Ookla，meta = Meta），对应 Network Benchmark 域两行。
       判据见 assets/team-scope.js（矩阵来自《新看板设计.xlsx》）。
       ⚠️ 过滤的是**组**，不是组内的卡：Excel 的勾选粒度就是「这一类要不要」，
         组内几张卡是这个数据源不可分割的一部分（少一张就与组头说的口径不符）。
       ⚠️ 这两个变量必须算在**骨架分支之前** —— 骨架与真卡用的是同一份清单，
         否则会出现「骨架摆两组、真卡只出一组」的错位。 */
    var kpiGroups = SCOPE ? DATA.KPI_GROUPS.filter(function (g) {
      return SCOPE.ok('kpi', g.id);
    }) : DATA.KPI_GROUPS;
    var bfGroups = SCOPE ? DATA.BF_GROUPS.filter(function (g) {
      return SCOPE.ok('bf', g.id);
    }) : DATA.BF_GROUPS;""",
)

H(
    "kpi-skeleton-groups",
    """      var skTop = DATA.KPI_GROUPS.map(function (g) {""",
    """      var skTop = kpiGroups.map(function (g) {""",
)

H(
    "kpi-skeleton-bf-groups",
    """      var skBfRow = DATA.BF_GROUPS.map(function (g) {""",
    """      var skBfRow = bfGroups.map(function (g) {""",
)

H(
    "kpi-skeleton-html",
    """      box.innerHTML = '<div class="band-h"><div class="band-txt"><div class="band-k" title="' +
        esc(t('kpi.sub')) + '">' + esc(t('kpi.title')) + '</div></div></div>' +
        '<div class="qc-grid">' + skTop + '</div>' +
        '<div class="band-h"><div class="band-txt"><div class="band-k" title="' +
          esc(tf('kpi.bf.subBoth', { n: (k.speed && k.speed.days) || '—' })) + '">' +
          esc(t('kpi.bf.title')) + '</div></div></div>' +
        '<div class="qc-grid">' + skBfRow + '</div>';
      return;
    }""",
    """      /* 团队门户作用域：一组都没勾时，那一段（连它的标题行）整段不输出。
         留一个空标题 + 空卡区比不显示更难懂（用户会以为数据没加载出来）。 */
      box.innerHTML = (kpiGroups.length
          ? '<div class="band-h"><div class="band-txt"><div class="band-k" title="' +
            esc(t('kpi.sub')) + '">' + esc(t('kpi.title')) + '</div></div></div>' +
            '<div class="qc-grid">' + skTop + '</div>'
          : '') +
        (bfGroups.length
          ? '<div class="band-h"><div class="band-txt"><div class="band-k" title="' +
            esc(tf('kpi.bf.subBoth', { n: (k.speed && k.speed.days) || '—' })) + '">' +
            esc(t('kpi.bf.title')) + '</div></div></div>' +
            '<div class="qc-grid">' + skBfRow + '</div>'
          : '');
      if (SCOPE) {
        if (!kpiGroups.length && !bfGroups.length) { box.innerHTML = ''; box.hidden = true; }
        else { box.hidden = false; }
      }
      return;
    }""",
)

H(
    "kpi-real-groups",
    """    var top = DATA.KPI_GROUPS.map(function (g) {""",
    """    var top = kpiGroups.map(function (g) {""",
)

H(
    "kpi-real-bf-groups",
    """          DATA.BF_GROUPS.map(function (g) {
            return qcGroupHtml(g, qcGroupCards(g, function (sp) {
              return srcKind[sp.src](sp);
            }));
          }).join('') +""",
    """          bfGroups.map(function (g) {
            return qcGroupHtml(g, qcGroupCards(g, function (sp) {
              return srcKind[sp.src](sp);
            }));
          }).join('') +""",
)

H(
    "kpi-real-tail",
    """          }).join('') +
        '</div>';
    }
    box.innerHTML =
      '<div class="band-h">' +""",
    """          }).join('') +
        '</div>';
    }
    /* 团队门户作用域：Benchmark 一组都没勾时，那一段（连标题行）整段不输出。 */
    if (!bfGroups.length) bf = '';
    /* 团队门户作用域：Network Status 与 Network Benchmark **都没勾**时，
       整个 #kpi 区块消失（连标题行都不留）。
       ⚠️ hidden 成对管理：mainLocked(false) 会把区块的 hidden 设成 false，
         团队门户需要在渲染时按矩阵重新收放。 */
    if (SCOPE && !kpiGroups.length && !bf) { box.innerHTML = ''; box.hidden = true; return; }
    if (SCOPE) { box.hidden = false; }
    box.innerHTML =
      (kpiGroups.length ? '<div class="band-h">' +""",
)

H(
    "kpi-real-tail-end",
    """      '</div><div class="qc-grid">' + top + '</div>' + bf;
  }""",
    """      '</div><div class="qc-grid">' + top + '</div>' : '') + bf;
  }""",
)

# ==========================================================================
# 4) Domain Dashboard（#views6）：按矩阵过滤视图列
# ==========================================================================
H(
    "views6-filter",
    """    var gids = v6Gids();
    gids.forEach(function (gid) {""",
    """    var gids = v6Gids();
    /* 团队门户作用域（2026-10-29 加）：只渲染本团队在《新看板设计.xlsx》的
       Domain Dashboard 域勾了的视图列。
       ⚠️ 过滤的是**列**，不是列里的行：Excel 的勾选粒度是「这个专业域的看板要不要看」，
         列内那几条是这一域的完整报告清单，不该被裁。
       ⚠️ 一列都没勾时整块消失（连标题行都不留）—— 留个空标题比不显示更难懂。 */
    if (SCOPE) {
      var allow = SCOPE.viewGroups();
      gids = gids.filter(function (gid) { return allow.indexOf(gid) !== -1; });
      if (!gids.length) { box.innerHTML = ''; box.hidden = true; return; }
      box.hidden = false;
    }
    gids.forEach(function (gid) {""",
)

# ==========================================================================
# 5) GIS MAP（#l0Map）：按矩阵过滤地图页签
# ==========================================================================
H(
    "map-filter",
    """  function mapItems() {
    var all = allowed();
    return DATA.MAP_TABS.map(function (m) {""",
    """  function mapItems() {
    var all = allowed();
    /* 团队门户作用域（2026-10-29 加）：只渲染本团队在《新看板设计.xlsx》的
       GIS MAP 域勾了的地图页签（gis / person / mwRealTime）。
       ⚠️ 页签由矩阵决定，不是「目录里有没有对应看板」—— 与本页既有的口径一致
         （见 mapItems 上方那段说明：目录是业务数据，不能决定页签存不存在）。 */
    var tabs = DATA.MAP_TABS;
    if (SCOPE) {
      var allow = SCOPE.mapPages();
      tabs = tabs.filter(function (m) { return allow.indexOf(m.page) !== -1; });
    }
    return tabs.map(function (m) {""",
)

H(
    "map-empty-hide",
    """  function renderL0(keepMap) {
    var mapBox = $('#l0Map');
    if (!mapBox) return;""",
    """  function renderL0(keepMap) {
    var mapBox = $('#l0Map');
    if (!mapBox) return;
    /* 团队门户作用域（2026-10-29 加）：GIS MAP 域一个都没勾时整块消失。
       ⚠️ 判据放在 keepMap 快速路径**之前** —— 否则首次渲染隐藏后，
         后续走「快速路径」时又会画回来（mapBox 里已经有 .map 了）。 */
    if (SCOPE && !SCOPE.ok('map')) { mapBox.innerHTML = ''; mapBox.hidden = true; return; }
    mapBox.hidden = false;""",
)

# ==========================================================================
# 6) Knowledge Q&A（#qaSlot）：按矩阵过滤页签
# ==========================================================================
H(
    "qa-filter",
    """    var eflow = pick('page=eflow_qa');""",
    """    var eflow = pick('page=eflow_qa');
    /* 团队门户作用域（2026-10-29 加）：Excel 的 Knowledge Q&A 域有三行 ——
       · TT/Alarm Analysis → eFlow 知识库（页签 eflow）
       · Knowledge O&A     → 本地知识问答（页签 rag）
       · Quick Q&A         → 右下角悬浮问答助手（不是页签，由 qa-assistant.js 判断）
       这里只管前两个页签。 */
    if (SCOPE) {
      var qaAllow = SCOPE.qaTabs();
      if (qaAllow.indexOf('eflow') === -1) eflow = null;
      if (qaAllow.indexOf('rag') === -1) rag = null;
    }""",
)

H(
    "qa-empty-hide",
    """  function renderQaSection() {
    var el = $('#qaSlot'); if (!el) return;""",
    """  function renderQaSection() {
    var el = $('#qaSlot'); if (!el) return;
    /* 团队门户作用域（2026-10-29 加）：一个页签都没勾时整块消失。
       ⚠️ hidden 成对管理：mainLocked(false) 会把区块的 hidden 设成 false。 */
    if (SCOPE && !SCOPE.ok('qa')) { el.innerHTML = ''; el.hidden = true; return; }
    if (SCOPE) { el.hidden = false; }""",
)

# ==========================================================================
# 7) OSS Portal Login（#ossSlot）：按矩阵过滤入口
# ==========================================================================
H(
    "oss-filter",
    """  function ossSectionHtml() {
    var list = groupItems('Friends Link');""",
    """  function ossSectionHtml() {
    var list = groupItems('Friends Link');
    /* 团队门户作用域（2026-10-29 加）：只保留本团队在《新看板设计.xlsx》的
       OSS Portal Login 域勾了的入口。
       ⚠️ 槽位 → 目录条目的对应表见 assets/team-scope.js 的 OSS_SLOTS。
         用 url 片段匹配而不是标题匹配 —— 目录标题可编辑，url 稳定。
       ⚠️ 一条都没勾时整块消失。 */
    if (SCOPE) {
      var allow = SCOPE.ossSlots();
      list = list.filter(function (it) {
        var slot = SCOPE.ossSlotOf(it);
        return !!slot && allow.indexOf(slot) !== -1;
      });
    }""",
)

H(
    "oss-empty-hide",
    """  function renderOssSection() {
    var el = $('#ossSlot'); if (!el) return;
    /* 标题/计数随语言与筛选变，总是重画（这块没有 iframe，重画代价可忽略）。 */
    el.innerHTML = ossSectionHtml();
  }""",
    """  function renderOssSection() {
    var el = $('#ossSlot'); if (!el) return;
    /* 标题/计数随语言与筛选变，总是重画（这块没有 iframe，重画代价可忽略）。 */
    /* 团队门户作用域（2026-10-29 加）：一个入口都没勾时整块消失。 */
    if (SCOPE && !SCOPE.ok('oss')) { el.innerHTML = ''; el.hidden = true; return; }
    if (SCOPE) { el.hidden = false; }
    el.innerHTML = ossSectionHtml();
  }""",
)

# ==========================================================================
# 8) Escalation Matrix（#esc）
# ==========================================================================
H(
    "esc-scope",
    """  function renderEsc() {
    var box = $('#esc'), E = D.escalation || {}, rows = E.rows || [], lv = E.levels || [];
    if (!rows.length) { box.hidden = true; return; }""",
    """  function renderEsc() {
    var box = $('#esc'), E = D.escalation || {}, rows = E.rows || [], lv = E.levels || [];
    /* 团队门户作用域（2026-10-29 加）：Excel 的 Escalation Matrix 域未勾时整块消失。 */
    if (SCOPE && !SCOPE.hasEscalation()) { box.innerHTML = ''; box.hidden = true; return; }
    if (SCOPE) { box.hidden = false; }
    if (!rows.length) { box.hidden = true; return; }""",
)

# ==========================================================================
# 9) User Feedback（#fbSlot）
# ==========================================================================
H(
    "fb-scope",
    """  function renderFeedbackSection() {
    var el = $('#fbSlot'); if (!el) return;
    if (fbLang !== state.lang || !el.querySelector('#fbHost')) {""",
    """  function renderFeedbackSection() {
    var el = $('#fbSlot'); if (!el) return;
    /* 团队门户作用域（2026-10-29 加）：Excel 的 User Feedback 域未勾时整块消失。 */
    if (SCOPE && !SCOPE.hasFeedback()) { el.innerHTML = ''; el.hidden = true; return; }
    if (SCOPE) { el.hidden = false; }
    if (fbLang !== state.lang || !el.querySelector('#fbHost')) {""",
)

# ==========================================================================
# 10) Auto Report（#emailSlot）：交给团队门户自己的渲染器
# ==========================================================================
H(
    "email-team",
    """  function renderEmailSection() {
    var el = $('#emailSlot'); if (!el) return;
    if (emailLang !== state.lang || !el.querySelector('#emailHost')) {""",
    """  function renderEmailSection() {
    var el = $('#emailSlot'); if (!el) return;
    /* 团队门户作用域（2026-10-29 加）：Auto Report 这一块**不内嵌** my_app 的
       email_reports 页，改为由 assets/team-reports.js 自己渲染一张按矩阵过滤的表。
       理由：Excel 的 Auto-report 域逐条勾选了要哪几种报告，而 my_app 那个页面
       渲染的是**全部**报告源（14 个），没法按 source_id 过滤；在这里另做一张表，
       既能精确按矩阵过滤，也不用改 my_app 那一侧。
       ⚠️ 只有团队门户走这条支路；上游 /v3/olbrportal/ 的行为完全不变。 */
    if (SCOPE && window.OLBR_TEAM_REPORTS) {
      /* 一份报告都没勾时整块消失（连标题行都不留）——
         与 QC / KPI / View / QA / OSS 各域的处置口径一致：
         「这一域对这个团队完全无关」就不该留一个空标题，让用户以为数据没加载出来。
         ⚠️ 矩阵缺项 = 不勾 = 不显示，这是本门户的唯一语义，没有「默认全显」兜底。 */
      if (!SCOPE.ok('report')) { el.innerHTML = ''; el.hidden = true; return; }
      el.hidden = false;
      window.OLBR_TEAM_REPORTS.render(el);
      return;
    }
    if (emailLang !== state.lang || !el.querySelector('#emailHost')) {""",
)


H(
    "complaint-scope",
    """  function renderAux() {
    var box = $('#aux'), html = '';""",
    """  function renderComplaintSection() {
    var el = $('#complaintSlot'); if (!el) return;
    /* 团队门户作用域（2026-10-29 加）：Excel 的 Customer complaint 域未勾时整块消失。 */
    if (SCOPE && !SCOPE.hasComplaint()) { el.innerHTML = ''; el.hidden = true; return; }
    if (SCOPE) { el.hidden = false; }
    if (SCOPE && window.OLBR_TEAM_REPORTS) {
      window.OLBR_TEAM_REPORTS.renderComplaint(el);
      return;
    }
    /* 非团队门户（本函数只在有 #complaintSlot 时才走到这里）—— 留空即可。 */
    el.innerHTML = '';
  }

  function renderAux() {
    var box = $('#aux'), html = '';""",
)

H(
    "render-complaint",
    """  function render() { renderBand(); renderKpi(); renderViews6(); renderL0(); renderEsc(); renderEmailSection(); renderQaSection(); renderOssSection(); renderFeedbackSection(); renderAux(); renderArchive(); applyI18n(); }""",
    """  /* ⚠️ renderComplaintSection() 是**团队门户专有**的（上游页面没有 #complaintSlot，
     那个函数找不到节点就直接返回）。放在 renderAux 之前，与 DOM 顺序一致。 */
  function render() { renderBand(); renderKpi(); renderViews6(); renderL0(); renderEsc(); renderEmailSection(); renderQaSection(); renderOssSection(); renderFeedbackSection(); renderComplaintSection(); renderAux(); renderArchive(); applyI18n(); }""",
)


def build(src_text: str) -> str:
    use_crlf = "\r\n" in src_text
    norm = src_text.replace("\r\n", "\n")
    for label, old, new in HOOKS:
        old_n = old.replace("\r\n", "\n")
        new_n = new.replace("\r\n", "\n")
        if old_n not in norm:
            sys.exit("钩子未命中：%s\n上游 olbr.js 已变，请核对原文片段。" % label)
        norm = norm.replace(old_n, new_n, 1)
        print("  + %s" % label)
    return norm.replace("\n", "\r\n") if use_crlf else norm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对现有文件，不写入")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        sys.exit("找不到上游基线：%s" % SRC)
    out = build(read(SRC))

    if args.check:
        cur = read(OUT) if os.path.exists(OUT) else ""
        if cur.replace("\r\n", "\n") != out.replace("\r\n", "\n"):
            print("team_portal/assets/olbr.js 与上游基线不一致，请重跑 patch_team_portal.py")
            return 1
        print("team_portal/assets/olbr.js 与上游基线一致")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    write(OUT, out)
    print("已写入 %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
