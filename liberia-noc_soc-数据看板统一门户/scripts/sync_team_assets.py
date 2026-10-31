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
      olbr-data.js / masthead.css / qa-assistant.css / _local-credentials.js / logo-*.png

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
    "_local-credentials.js",
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
     高度与右列的「OSS + 反馈」合计等高（--qarow-h），行数多时表体内滚动，
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
.complaint-slot { margin-top: var(--s4); }
.complaint-slot .oss-grid { margin-top: 0; }
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
