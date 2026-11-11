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
# 钩子（.git/hooks/pre-commit -> check-team-scope.mjs）与 CI 里 stdout 是管道，
# Windows 下 Python 默认按 cp1252 编码，打印中文/✓ 会抛 UnicodeEncodeError 让
# 校验误判失败（校验本身是通过的）。见 .qoder/rules/shell_safe.md 第 2 条。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
# 1b) 运行时矩阵到达后重画（2026-10-30 加）
# ==========================================================================
# 为什么需要：矩阵是**异步**从服务端取回来的（/uniplam/api/auth/team-scope），
# 而 boot() 在 DOMContentLoaded 时同步跑完。若不重画，页面会停在
# 「矩阵未就绪 → 什么都不显示」的状态 —— 团队门户整页空白。
#
# 为什么用自定义事件而不是直接调 render()：render() 是这个 IIFE 里的私有函数，
# team-scope.js（另一个文件）拿不到。故由 team-scope.js 派发事件，
# 这里监听后自己重画 —— 两侧通过**事件名**这个契约对接。
H(
    "scope-refresh",
    """  function boot() {
    applyI18n();""",
    """  /* 团队门户作用域（2026-10-30 加）：运行时矩阵是**异步**取回来的
     （/uniplam/api/auth/team-scope），而 boot() 同步跑完 —— 故矩阵到位后
     必须重画一次，否则页面停在「矩阵未就绪 → 什么都不显示」的状态。
     ⚠️ 事件名带 'olbr' 前缀，避免与页面上的其它事件撞名。
     ⚠️ SCOPE 为 null（上游页面）时这个监听器**不注册** ——
       上游那份 index.html 不引 team-scope.js，永远不会有这个事件。
     ⚠️ 2026-11-04 加 loadCxort()：矩阵未就绪时 loadKpi 的第 4 路
       （CXO RealTime Dashboard）被 wantCxortGroup() fail-closed 跳过，
       bo 门户首屏这一路要等矩阵到位才补发；只 render() 不取数的话，
       卡片会一直是「—」直到下一个 5 分钟刻度。 */
  if (SCOPE) {
    document.addEventListener('olbr:scope-ready', function () { render(); loadCxort(); });
  }
  function boot() {
    applyI18n();""",
)

# ==========================================================================
# 1c) my_app 会话预热 + 401 自愈（2026-10-30 加）
# ==========================================================================
# 背景（真实故障，2026-10-30）：
#   团队门户页的数据全部来自 **my_app 后端**（QC 汇总、KPI 指标、报告列表、
#   看板目录），这些接口在 my_app 侧要求 `myapp_session` Cookie
#   （Task\my_app\backend\main.py 的 require_session_middleware）。
#   但团队门户页自己**从不**建立这个会话 —— 全页唯一换会话的地方是登录闸门里的
#   login() → POST /api/auth/portal-login。真实故障链：
#     ① 用户在 /uniplam/ 登录 → 拿到**门户 token**（localStorage + HttpOnly Cookie）；
#     ② 打开 /v3/fo_portal/ → nginx auth_request 校验团队通过 → 页面打开；
#     ③ 页面 probe() 判「已登录」用的是**门户 token** → 直接 start() 拉数据；
#     ④ 但 myapp_session **根本不存在** → my_app 回 401
#        → 心跳点变红（qc-dot-bad）、卡片显示「—」、报告表显示「加载失败」；
#     ⑤ 页面里的 **my_app 内嵌 iframe**（地图/QA/反馈）自己会跑 bootstrapAuth()
#        （Task\my_app\frontend\src\api.ts），从**同一个 localStorage** 读到门户 token
#        再调一次 /api/auth/portal-login → 这才是真正种下 myapp_session 的那一步；
#     ⑥ 用户刷新 → Cookie 已在 → 全部 200 → 恢复正常。
#   第 ⑤ 步的 iframe 是**副作用**，且必然比父页的数据请求慢一拍 —— 踩空是结构性的。
#   本机管理员看不到，是因为 my_app 对本机回环直接放行（portal_auth.current_user
#   → client_is_local），只有局域网其他机器才是真实远端。
#
# 修法（两处，配合 assets/team-session.js）：
#   ① boot() 里**先 ensure() 换会话、再 start() 拉数据** —— 首屏就有会话；
#   ② api() 收到 401 时**换一次会话再重试一次** —— 兜住运行期失效
#      （会话过期、门户进程重启导致门户 token 失效）。
#
# 为什么用独立文件 assets/team-session.js 而不是把代码塞在这里：
#   本文件是**生成物**（从上游基线生成），直接改生成物会被下次重跑覆盖。
#   scripts/sync_team_assets.py 明确把 team-*.js 列为「纯团队专有、不动」。
#
# ⚠️ 上游 /v3/olbrportal/ 的 index.html **不引** team-session.js
#   → window.OLBR_SESSION 为 null → 下面两处 `if (SCOPE && ...)` 短路
#   → 上游行为一行未变。
H(
    "session-api-retry",
    """  function api(u) {
    return fetch(u, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      var ct = (r.headers.get('Content-Type') || '').toLowerCase();
      if (!r.ok) throw new Error('HTTP ' + r.status);
      /* my_app 的 catch-all 会把未注册的 /api/* 也回成 SPA 的 index.html（200 + text/html） */
      if (ct.indexOf('json') === -1) throw new Error('non-JSON');
      return r.json();
    });
  }""",
    """  function api(u) {
    /* 团队门户（2026-10-30 加）：原始取数逻辑抽成 apiRaw()，api() 在外面包一层
       401 自愈。**SCOPE 为 null（上游 /v3/olbrportal/）时行为与改动前完全一致** ——
       那一侧既不引 team-session.js，window.OLBR_SESSION 也是 null。
       ⚠️ 重试**只做一次**：再失败就抛出去，由调用方显示错误态。
         无限重试会把 401 变成死循环、把后端打爆。
       ⚠️ 只对 GET 生效：本文件里 api() 的调用点**全部是 GET**（QC 汇总/趋势/明细/
         KPI 概览/目录），幂等，重试安全。 */
    var apiRaw = function (u) {
      return fetch(u, { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
        var ct = (r.headers.get('Content-Type') || '').toLowerCase();
        if (!r.ok) throw new Error('HTTP ' + r.status);
        /* my_app 的 catch-all 会把未注册的 /api/* 也回成 SPA 的 index.html（200 + text/html） */
        if (ct.indexOf('json') === -1) throw new Error('non-JSON');
        return r.json();
      });
    };
    if (SCOPE && window.OLBR_SESSION) return window.OLBR_SESSION.retryOn401(apiRaw)(u);
    return apiRaw(u);
  }""",
)

H(
    "session-boot-prewarm",
    """    envBadge();
    probe().then(function () {
      if (!state.authOk) { renderGate(); return; }
      renderGate(); mainLocked(false); start();
    });""",
    """    /* 团队门户（2026-10-30 加）：**先换 my_app 会话，再做任何取数**。
       页面判「已登录」用的是**门户 token**，而 my_app 的数据接口认的是
       **myapp_session** Cookie —— 两者不是一回事。此前本页从不换这个会话，
       于是首屏必然 401（心跳点变红、卡片空、报告表「加载失败」）；
       真正种下会话的是页面里 my_app 内嵌 iframe 的 bootstrapAuth()，
       那是个**副作用**且必然慢一拍 —— 踩空是结构性的，不是偶发。

       ⚠️ probe() 与 ensure() **并行**发起，不串行：
         probe() 判「登没登录」，ensure() 换会话，两者互不依赖，
         串行会白白多一个来回（首屏延迟直接翻倍）。
       ⚠️ envBadge() 的位置**按门户类型分开**：
         · 团队门户：挪到会话建立**之后**再探活。
           它是顶栏那个红点（探活），原先在 probe() 之前就发第一个请求 ——
           那时 myapp_session 还不存在，远端用户必然收到 401，
           于是「后端明明正常」却被显示成「后端挂了」。
           会话就位之后再探，才是名副其实的探活。
         · 上游 /v3/olbrportal/：位置**保持原样**（仍在 boot() 开头），
           一行都没动 —— 那一侧不引 team-session.js，TEAM_SESSION 为 null。
       ⚠️ 换不到会话也不阻断：ensure() 自己吞掉失败，这里照样 start()，
         只是首屏可能空 —— 由 api() 的 401 自愈在下一轮兜住。 */
    var TEAM_SESSION = (SCOPE && window.OLBR_SESSION) ? window.OLBR_SESSION : null;
    if (!TEAM_SESSION) envBadge();
    var warm = TEAM_SESSION ? TEAM_SESSION.ensure() : Promise.resolve();
    Promise.all([probe(), warm]).then(function () {
      if (TEAM_SESSION) envBadge();
      if (!state.authOk) { renderGate(); return; }
      renderGate(); mainLocked(false); start();
    });""",
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
    """        '<div class="qc-grid" data-n="' + (D.qc || []).filter(function (d) {
          /* 团队门户作用域：骨架也要按矩阵过滤，否则会出现「骨架摆六张、
             数据到位只剩两张」的整块跳动（骨架与真卡必须 1:1 同构）。
             data-n 让 CSS 按实际卡数铺满整行（P0-2）。 */
          return !SCOPE || SCOPE.ok('qc', d.id);
        }).length + '">' + (D.qc || []).filter(function (d) {
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

H(
    "qc-cards-n",
    """      '</div><div class="qc-grid">' + cards + '</div>';""",
    """      '</div><div class="qc-grid" data-n="' + (SCOPE ? DATA.QC_PRIMARY_ORDER.concat(DATA.QC_SECONDARY_ORDER).filter(function (id) { return SCOPE.ok('qc', id); }).length : DATA.QC_PRIMARY_ORDER.length + DATA.QC_SECONDARY_ORDER.length) + '">' + cards + '</div>';""",
)

H(
    "views6-grid-n",
    """      '<div class="band-h"><div class="band-txt"><div class="band-k">' + esc(t('v6.title')) + '</div></div></div>' +
      '<div class="v6-grid">' + html + '</div>';""",
    """      '<div class="band-h"><div class="band-txt"><div class="band-k">' + esc(t('v6.title')) + '</div></div></div>' +
      '<div class="v6-grid" data-n="' + gids.length + '">' + html + '</div>';""",
)

# ==========================================================================
# 3) Network Status / Network Benchmark（#kpi）：按组过滤
# ==========================================================================
H(
    "kpi-scope-vars",
    """  function renderKpi() {
    var box = $('#kpi');
    if (!box) return;
    var k = state.kpi;
    /* teamOnly 卡组（2026-11-04 加）：DATA.KPI_GROUPS 里带 teamOnly 的组
       （当前只有 cxort = CXO RealTime Dashboard，bo 团队门户专用）不进
       上游主门户 —— 上游没有团队矩阵，无从判断哪个团队该看，直接不渲染。
       团队门户那份（v3/team_portal/，由 scripts/patch_team_portal.py 生成）
       会把这一行换成按矩阵 kpi.cxort 过滤的版本，见该脚本的 kpi-scope-vars 钩子。
       取数侧同样按它 gating（wantCxortGroup / loadKpi 第 4 路）。 */
    var kpiGroups = DATA.KPI_GROUPS.filter(function (g) { return !g.teamOnly; });""",
    """  function renderKpi() {
    var box = $('#kpi');
    if (!box) return;
    /* 登出后不再重画（2026-11-02 加）：KPI 是**异步**装载的（多路并行，见 loadKpi），
       登出那一刻还在飞的回调会把 #kpi 重新解隐 —— 与 #band 同一类漏点，
       详见 logout() 的注释。 */
    if (state.signedOut) { box.hidden = true; return; }
    var k = state.kpi;
    /* 团队门户作用域（2026-10-29 加）：
       · KPI_GROUPS 现在是**三组**：rich / avail / cxort（后者 teamOnly，
         2026-11-04 加，bo 专用 —— Daily Availability KPI 换成 CXO RealTime
         Dashboard，矩阵 kpi.cxort 只勾了 bo；avail 那行同步去掉了 bo）。
         一律按矩阵 kpi 域的子键过滤，缺键 = 不显示（无默认全显兜底）。
       · BF_GROUPS 有两组（speed = Ookla，meta = Meta），对应 Network Benchmark 域两行
         （2026-11-04 起矩阵把 bo 也勾上了）。
       ⚠️ 过滤的是**组**，不是组内的卡：勾选粒度就是「这一类要不要」，
         组内几张卡是这个数据源不可分割的一部分（少一张就与组头说的口径不符）。
       ⚠️ 这两个变量必须算在**骨架分支之前** —— 骨架与真卡用的是同一份清单，
         否则会出现「骨架摆两组、真卡只出一组」的错位。 */
    var kpiGroups = SCOPE ? DATA.KPI_GROUPS.filter(function (g) {
      return SCOPE.ok('kpi', g.id);
    }) : DATA.KPI_GROUPS.filter(function (g) { return !g.teamOnly; });
    var bfGroups = SCOPE ? DATA.BF_GROUPS.filter(function (g) {
      return SCOPE.ok('bf', g.id);
    }) : DATA.BF_GROUPS;""",
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

# ⚠️ 2026-11-05（用户要求「bo 门户的 BO View 不要跳过 RAN/IP/MW/CN/OCS 页签」）：
#   这里原先有一个 v6-bo-flat 钩子，对 SCOPE.teamId === 'bo' 直接跳过 v6SubBar()，
#   把 BO View 摊平成「每条报告一行」—— 页签与按专业域分段全丢了。
#   **该钩子已删除**（不保留兼容层，见 AGENTS.md 第三节第 10 条「删除优于兼容」）：
#   bo 门户回到与其它团队门户一致的行为 —— 有子分组页签、「全部」视图按专业域分段。
#   随之要一起修的是「分段默认折叠」：上游 v6SegHtml 的语义是
#   「state.v6SubFold[sid] === true 才展开」（默认折叠，2026-10-12 用户要求），
#   折叠态下用户只看得到 5 个段头（RAN/IP/MW/CN/OCS + 计数）、看不到任何报告，
#   「按组按行展示」等于没实现。故 bo 侧改为**默认展开**，见下面两个钩子。
#
#   bo 侧「RAN 放一行、不够就两行」由 CSS 侧现成的一条规则兜住：
#   sync_team_assets.py 追加的 `#views6 .v6-grid[data-n] .v6-list`
#   （**flex 行流**，段头 flex-basis:100% 独占整行，条目 flex:1 1 280px 自动横排折行）
#   —— 2026-11-05 之前那条是 auto-fit 网格且只挂在 data-n="1" 上，轨道数按整张列表宽度
#   一次算死，MW 只有 2 条也占着 5 条轨道的位置，右侧留下约 870px 空白
#   （2026-11-05 用户报「一行还排不满，右边有大量空白」）。现在改成 flex 行流后，
#   同一行内条数少的那一组也会被拉伸吃满整行（MW 两条各占半行），零右侧空白。
H(
    "v6-seg-open-bo",
    """    var open = state.v6SubFold[sid] === true;   // 默认折叠""",
    """    /* 团队门户 bo（2026-11-05 加）：BO View 的专业域分段**默认展开** ——
       用户要求「BO View 里的报告按组按行展示：RAN 放一行，不够就两行」。
       折叠态下用户只看得到 5 个段头（RAN/IP/MW/CN/OCS + 计数）、一条报告都看不到，
       等于没实现。
       ⚠️ 折叠状态键仍复用 state.v6SubFold，但 bo 侧语义与上游**相反**：
         上游 = 「=== true 才展开」（默认折叠）；
         bo  = 「=== false 才折叠」（默认展开）。
         两处必须成对改：这里的判定 + 点击时的翻转（v6-seg-toggle-bo 钩子），
         只改一处会出现「点一下没反应」。
       ⚠️ 判据 SCOPE.teamId === 'bo'：BO View 这一列本来就只有 bo 有
         （view 矩阵），上游主门户（/v3/olbrportal/，SCOPE 为 null）
         与其它团队门户一行未改。 */
    var open = (SCOPE && SCOPE.teamId === 'bo')
      ? state.v6SubFold[sid] !== false
      : state.v6SubFold[sid] === true;   // 默认折叠""",
)

H(
    "v6-seg-toggle-bo",
    """        state.v6SubFold[ssid] = state.v6SubFold[ssid] !== true;""",
    """        /* 团队门户 bo（2026-11-05 加）：与 v6SegHtml 的 bo 侧语义对齐 ——
           bo 侧「false = 折叠、其余 = 展开」，故翻转是「当前展开就置 false、
           当前折叠就置 true」。上游那套「!== true」在默认展开下第一次点击
           算出来还是 true（看着没反应），不能照抄。
           ⚠️ SCOPE 为 null（上游）或非 bo 团队时行为与改动前完全一致。 */
        state.v6SubFold[ssid] = (SCOPE && SCOPE.teamId === 'bo')
          ? (state.v6SubFold[ssid] === false ? true : false)
          : state.v6SubFold[ssid] !== true;""",
)

H(
    "views6-limit-show",
    """      var open = !!state.v6Open[gid];
      var show = open || ed ? list : list.slice(0, V6_LIMIT);""",
    """      var open = !!state.v6Open[gid];
      /* 团队门户单列自适应首屏条数（2026-11-03 加）：V6_LIMIT=2 是按三列窄卡定的，
         一行只摆一条；单列卡独占整行时一行可摆 4~6 条，仍只切 2 条会空出半行。
         按容器宽度估算首行可摆条数（320px/条，与 CSS 的 minmax(280px,1fr)+缝对应，
         至少 2 条），展开按钮计剩余数。窗口缩放后下次渲染重新估算。
         ⚠️ 2026-11-06（用户要求「flm 的 Domain Dashboard 内容格式参考 bo」）：
           多列团队（当前只有 flm = FLM View + SP View）的视图卡已由 CSS 改成
           上下堆叠、每张独占整行，与 bo 的 BO View 分段视图一样把整列条目
           全部平铺 —— 不再折叠成「Show N more」。故 gids.length > 1 时
           v6Lim 直接取全量；单列团队仍按宽度估算，一行未改。
           配套在 sync_team_assets.py 的 CSS_TEAM_SUFFIX（.v6-grid[data-n] 一律单列）。 */
      var v6Lim = V6_LIMIT;
      if (SCOPE && !ed && !open && !sub.grouped && list.length > V6_LIMIT) {
        var v6W = (box && box.clientWidth) || window.innerWidth || 1280;
        v6Lim = gids.length > 1
          ? list.length
          : Math.min(list.length, Math.max(V6_LIMIT, Math.floor(v6W / 320)));
      }
      var show = open || ed ? list : list.slice(0, v6Lim);""",
)

H(
    "views6-limit-more",
    """      if (!ed && !sub.grouped && list.length > V6_LIMIT) {
        body += '<button type="button" class="v6-more" data-act="v6-toggle" data-gid="' + esc(gid) +
          '" aria-expanded="' + (open ? 'true' : 'false') + '">' +
          '<i class="ph ph-' + (open ? 'caret-up' : 'caret-down') + '" aria-hidden="true"></i>' +
          '<span>' + esc(open ? t('v6.less') : tf('v6.more', { n: list.length - V6_LIMIT })) + '</span></button>';
      }""",
    """      if (!ed && !sub.grouped && list.length > v6Lim) {
        body += '<button type="button" class="v6-more" data-act="v6-toggle" data-gid="' + esc(gid) +
          '" aria-expanded="' + (open ? 'true' : 'false') + '">' +
          '<i class="ph ph-' + (open ? 'caret-up' : 'caret-down') + '" aria-hidden="true"></i>' +
          '<span>' + esc(open ? t('v6.less') : tf('v6.more', { n: list.length - v6Lim })) + '</span></button>';
      }""",
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
    /* 团队门户作用域（2026-10-29 加，2026-11-04 改）：Excel 的 Knowledge Q&A 域剩三行 ——
       · TT/Alarm Analysis → eFlow 知识库（页签 eflow）
       · Knowledge O&A     → 本地知识问答（页签 rag）
       · Quick Q&A         → 右下角悬浮问答助手（不是页签，由 qa-assistant.js 判断）
       ⚠️ 原第四行 VMAX 用户查询（页签 vmax，短名 CCH）已于 2026-11-04 拆成独立
         面板 #cchSlot，由 cch 域的 cch-scope 钩子控制，不再在这里过滤。
       ⚠️ 服务端库矩阵里可能仍残留 qa/vmax（合并逻辑只补不删），
         qaItems() 已不消费它，qaTabs() 多返回一项也无副作用。
       ⚠️ 2026-11-08：上游新增第三个页签 master_site（Master Site，站点主数据表）。
         用户最初只要求主门户 /v3/olbrportal/ 加，团队门户按矩阵走；
         2026-11-11 起矩阵 qa/master_site 勾了 fo / bo / flm，本判据自动放行，
         这三个团队门户也显示该页签，smc / cxo 未勾、置 null 保持两个页签。
         以后要增删团队只改 scope-map.json 的矩阵即可，无需再动代码。 */
    if (SCOPE) {
      var qaAllow = SCOPE.qaTabs();
      if (qaAllow.indexOf('eflow') === -1) eflow = null;
      if (qaAllow.indexOf('rag') === -1) rag = null;
      if (qaAllow.indexOf('master_site') === -1) masterSite = null;
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
# 9) CCH 独立面板（#cchSlot）
# ==========================================================================
H(
    "cch-scope",
    """  function renderCchSection() {
    var el = $('#cchSlot'); if (!el) return;""",
    """  function renderCchSection() {
    var el = $('#cchSlot'); if (!el) return;
    /* 团队门户作用域（2026-11-04 加）：CCH 独立面板受 cch 域控制 ——
       只有 fo / bo / smc 勾了（用户要求「CCH 在 olbr / smc / fo / bo 显示」里的
       后三个；olbr 是上游主门户，不引 team-scope.js、SCOPE 为 null，恒显示）。
       flm / cxo 未勾 → 整块消失，且它们也没有 Knowledge Q&A 里的 CCH 页签了。
       ⚠️ 兜底：服务端 teamScopeDb.getTemplate() 把 scope-map.json 缓存一次，
         新增的 cch 域要等 dev 重启才会由 load() 合并进库矩阵。重启之前矩阵里
         根本没有这个域，直接问 ok('cch','cch') 会对所有团队返回 false
         （fail-closed）= CCH 一个团队都看不到。故此时按静态白名单判，
         重启合并后自动切回矩阵（管理员仍可在界面里改）。
       ⚠️ hidden 成对管理：mainLocked(false) 会把区块的 hidden 设成 false。 */
    if (SCOPE) {
      var allow = SCOPE.hasDomain('cch')
        ? SCOPE.hasCch()
        : (['fo', 'bo', 'smc'].indexOf(SCOPE.teamId) !== -1);
      if (!allow) { el.innerHTML = ''; el.hidden = true; return; }
      el.hidden = false;
    }""",
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
    """  function render() { renderBand(); renderKpi(); renderViews6(); renderL0(); renderEsc(); renderEmailSection(); renderQaSection(); renderOssSection(); renderCchSection(); renderAux(); renderArchive(); applyI18n(); }""",
    """  /* ⚠️ renderComplaintSection() 是**团队门户专有**的（上游页面没有 #complaintSlot，
     那个函数找不到节点就直接返回）。放在 renderAux 之前，与 DOM 顺序一致。 */
  function render() {
    /* 登出后不再重画（2026-11-02 加）—— 完整理由见 logout() 的「登出后还能看到
       Daily Operation」那段注释。render() 有多个**异步**触发点（矩阵 scope-ready、
       目录装载完成、切换语言），它们都不看登录态，会把 mainLocked(true) 藏起来的
       区块重新解开。
       ⚠️ 判据用 state.signedOut，**不能**用 !state.authOk：boot() 里这一次 render()
         是同步跑的，那一刻 probe() 还没回来、authOk 天然是 false —— 用它会把首屏锁死。 */
    if (state.signedOut) { mainLocked(true); return; }
    renderBand(); renderKpi(); renderViews6(); renderL0(); renderEsc(); renderEmailSection(); renderQaSection(); renderOssSection(); renderCchSection(); renderComplaintSection(); renderAux(); renderArchive(); applyI18n(); }""",
)


# ==========================================================================
# 11) 辅助入口（#aux）：受 aux 域控制（2026-10-30 加）
# ==========================================================================
# 为什么此前没管它：Excel 的内容清单里没有「辅助入口」这一行 ——
# 它是门户页面的**结构性区块**（L2 辅助分组），不是需求清单里的一个条目。
# 于是它对五个团队全都显示，与「矩阵缺项 = 不显示」的既定语义相悖（fail-open）。
# 现在给它一个单独的域 aux（scope-map.json 的 extra_domains 里），
# 默认**一个团队都没勾** —— 即默认整块隐藏；要放出某一块得显式勾。
H(
    "aux-scope",
    """  function renderAux() {
    var box = $('#aux'), html = '';""",
    """  function renderAux() {
    var box = $('#aux'), html = '';
    /* 团队门户作用域（2026-10-30 加）：辅助入口受 aux 域控制。
       ⚠️ Excel 的内容清单里没有这一行（它是结构性区块，不是需求条目），
         所以默认**一个团队都没勾** = 整块隐藏。
         要放出某个辅助分组，得在 scope-map.json 的 matrix.aux 里显式勾上。
       ⚠️ hidden 成对管理：mainLocked(false) 会把区块的 hidden 设成 false。 */
    if (SCOPE && !SCOPE.ok('aux')) { box.innerHTML = ''; box.hidden = true; return; }
    if (SCOPE) { box.hidden = false; }""",
)

# ==========================================================================
# 12) 归档区（#arch）：受 archive 域控制（2026-10-30 加）
# ==========================================================================
# 同 aux：归档是「把看板收起来」的去处，是结构性区块，默认对所有团队隐藏。
H(
    "archive-scope",
    """  function renderArchive() {
    var box = $('#arch');
    if (!box) return;
    var list = archivedItems();""",
    """  function renderArchive() {
    var box = $('#arch');
    if (!box) return;
    /* 团队门户作用域（2026-10-30 加）：归档区受 archive 域控制，默认整块隐藏。
       ⚠️ 判据放在归档项判空**之前** —— 否则归档区为空时会走「隐藏」分支，
         但非空时又会画出来（那正是 fail-open 的口子）。 */
    if (SCOPE && !SCOPE.ok('archive')) { box.innerHTML = ''; box.hidden = true; return; }
    if (SCOPE) { box.hidden = false; }
    var list = archivedItems();""",
)



# ==========================================================================
# 24) 登录闸门藏正文的清单：补 #complaintSlot
# ==========================================================================
H(
    "mainlocked-complaint",
    """  function mainLocked(on) {
    ['#band', '#kpi', '#views6', '#l0Map', '#emailSlot', '#qaSlot', '#cchSlot', '#ossSlot', '#esc', '#aux']""",
    """  function mainLocked(on) {
    /* 团队门户专有补丁（2026-10-30）：清单里补 '#complaintSlot'。
       上游 /v3/olbrportal/ 没有 Customer Complaint 这一整块，基线那行不需要它；
       团队副本里 #complaintSlot 是 #main 的子区块（index.html 的 .complaint-slot），
       不写进这份清单，登出后 renderGate() → mainLocked(true) 就藏不掉它 —— 登录框下面
       照常挂着「Customer Complaint」。上面那段基线注释记的两次漏藏是同一个坑。 */
    ['#band', '#kpi', '#views6', '#l0Map', '#emailSlot', '#qaSlot', '#cchSlot', '#ossSlot', '#esc', '#complaintSlot', '#aux']""",
)

# ==========================================================================
# 25) 登出后不再重画：给所有「异步到达的渲染」加一道锁（2026-11-02 加）
# ==========================================================================
# 真实故障（用户报）：
#   「/v3/fo_portal/ 退出后有时候还能看到 Daily Operation」。
#
# 根因**不是**登出没清会话（它清了：localStorage token + HttpOnly Cookie 都清）。
# 漏点在**渲染**这一侧：本页的渲染全是异步、分散的 ——
#   · QC 两条轮询（全量一小时一档、alarm 五分钟一档）；
#   · KPI 三路并行装载、目录装载；
#   · 矩阵由 team-scope.js 异步取回后派发 olbr:scope-ready → render()；
#   · 切回标签页时 visibilitychange → loadQc()/loadKpi()/loadQcAlarm()。
# 这些回调里都写着 `box.hidden = false`（团队门户为了按矩阵收放，必须显式解隐，
# 见上文 qc-cards / kpi-real-tail 两个钩子）。于是 logout() 里那次
# mainLocked(true) 只把区块藏到「下一次渲染为止」—— 任何一次迟到的回调都会把它
# 重新解隐。登出与这些回调谁先谁后取决于网络与定时器，所以表现为**偶发**。
#
# 修法：一个**登出标记** state.signedOut，在四个渲染入口 + 三个装载入口上锁。
# 为什么不用 `!state.authOk`：boot() 里的 render() 是**同步**跑的，那一刻
# probe() 还没回来、authOk 天然是 false —— 用它当锁会把首屏直接锁死。
H(
    "state-signedout",
    """    user: null, authOk: false, booted: false, userMenuOpen: false, sysMenuOpen: false,""",
    """    user: null, authOk: false, booted: false, userMenuOpen: false, sysMenuOpen: false,
    /* 已登出（2026-11-02 加）：渲染/装载入口据此上锁，见 logout() 的注释。
       ⚠️ 与 authOk 不是一回事：authOk 在 boot() 的同步 render() 那一刻还没被
          probe 写回来，用它当锁会把首屏锁死；本标记**只由登出/会话失效置真**。 */
    signedOut: false,""",
)

H(
    "logout-lock",
    """  function logout() {
    fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(function () {});""",
    """  /* 登出（2026-11-02 补护栏）。
     ————————————————————————————————————————————————————————————————
     为什么这里要置 state.signedOut：本页的渲染是**异步、分散**的（QC 全量与 alarm
     两条轮询、KPI 三路装载、目录装载、矩阵 scope-ready、切回标签页的
     visibilitychange），每个回调都会把区块的 hidden 重新设成 false。所以
     mainLocked(true) 只保证「这一刻藏起来」，任意一次迟到的回调都会让它重新出现 ——
     用户看到的就是「退出后有时候还能看到 Daily Operation」。
     置上标记后，render / renderCatalog / renderBand / renderKpi 四个渲染入口与
     loadQc / loadQcAlarm / loadKpi 三个装载入口都会直接返回；标记在登录成功与
     probe 认到身份时清掉，所以重新登录后一切照旧。
     ⚠️ 别再往这里加「事后补一次 mainLocked(true)」之类的补丁 —— 那是与定时器赛跑。 */
  function logout() {
    state.signedOut = true;
    fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(function () {});""",
)

H(
    "render-catalog-guard",
    """  function renderCatalog() { renderViews6(); renderL0(true); renderEmailSection(); renderQaSection(); renderOssSection(); renderCchSection(); renderAux(); renderArchive(); }""",
    """  function renderCatalog() {
    /* 登出后不再重画（2026-11-02 加）：loadCatalog() 是异步的，登出后它照样会
       resolve 并走到这里，把 #views6 / #l0Map 等区块重新解隐。详见 logout() 的注释。 */
    if (state.signedOut) { mainLocked(true); return; }
    renderViews6(); renderL0(true); renderEmailSection(); renderQaSection(); renderOssSection(); renderCchSection(); renderAux(); renderArchive(); }""",
)

H(
    "render-band-guard",
    """  function renderBand() {
    var box = $('#band'), q = state.qc;""",
    """  function renderBand() {
    var box = $('#band'), q = state.qc;
    /* 登出后不再重画（2026-11-02 加）。**这是用户报的「退出后还能看到 Daily Operation」
       的直接漏点**：本函数末尾有一段 `box.hidden = false`（团队门户按矩阵收放必需），
       而它由两条轮询与 visibilitychange 触发 —— 登出时还在飞的那一次回调会在
       mainLocked(true) 之后把它重新解隐。
       ⚠️ 置 hidden 而不只是 return：万一调用发生在 login() 之前（首屏同步渲染被
          signedOut 挡住的情况不存在，但重登后残留的隐藏态要能自愈），这里成对处理。 */
    if (state.signedOut) { if (box) box.hidden = true; return; }""",
)

H(
    "loadqc-guard",
    """  function loadQc(force) {
    if (qcFullBusy) return;""",
    """  function loadQc(force) {
    /* 登出后不再取数（2026-11-02 加）：轮询没有停，但请求只会拿到 401、
       并在回调里重画 #band（见 renderBand 的护栏）。这里直接短路，省掉无意义的往返。 */
    if (state.signedOut) return;
    if (qcFullBusy) return;""",
)

H(
    "loadqcalarm-guard",
    """  function loadQcAlarm() {
    if (qcAlarmBusy) return;""",
    """  function loadQcAlarm() {
    /* 登出后不再取数（2026-11-02 加）：alarm 是五分钟一档的高频轮询，登出后
       它是最先「迟到」的那一个 —— 见 renderBand 的护栏与 logout() 的注释。 */
    if (state.signedOut) return;
    if (qcAlarmBusy) return;""",
)

H(
    "loadkpi-guard",
    """  function loadKpi() {
    if (kpiBusy) return;""",
    """  function loadKpi() {
    /* 登出后不再取数（2026-11-02 加）。 */
    if (state.signedOut) return;
    if (kpiBusy) return;""",
)

H(
    "login-clear-signedout",
    """        ss(TOKEN_KEY, d.token);
        state.user = d.user; state.authOk = true;""",
    """        ss(TOKEN_KEY, d.token);
        /* 重新登录要把登出标记清掉（2026-11-02 加）：否则 renderBand / renderKpi
           会一直短路，页面停在「登录成功但什么都不显示」的死状态。 */
        state.signedOut = false;
        state.user = d.user; state.authOk = true;""",
)

H(
    "probe-clear-signedout",
    """    return Promise.all([p1, p2]).then(function (a) {
      state.user = a[1] || a[0] || null;
      state.authOk = !!state.user;
      renderWho();
    });""",
    """    return Promise.all([p1, p2]).then(function (a) {
      state.user = a[1] || a[0] || null;
      state.authOk = !!state.user;
      /* 刷新页面后已有有效会话 → 清掉登出标记（2026-11-02 加）。
         ⚠️ 只在**认到身份**时清：token 已失效时 authOk 为 false，标记保持为假即可，
            由 renderGate() 兜住，不影响任何渲染。 */
      if (state.authOk) state.signedOut = false;
      renderWho();
    });""",
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
