# -*- coding: utf-8 -*-
"""Fiber Break 告警自动派单 + WhatsApp 通报（每 5 分钟一轮，cron `3-59/5 * * * *`）。

## 业务口径（2026-10-26 立项）

**触发源**：实时告警（`eflow_assign_client.fetch_active_alarms`，直接查 eFlow，
不读本地镜像 —— 上游就是实时的，没有同步时延）。

**派单条件（全部满足）**：
  1. 告警码命中白名单（默认 `4758` Fiber Break，页面可配多个）；
  2. 告警未清除（实时告警接口本身只返回未清除的）；
  3. 告警**存续时长**落在 `[min_age_minutes, window_minutes]` 区间内
     （默认 **下界 15 分钟**、上界 180 分钟）：
       * **下界 15 分钟**（2026-10-27 业务口径「告警发生到选择超过 15 分钟，
         才要指派单子和发送 WhatsApp 消息」）—— **不是一升起就派**，
         要等满 15 分钟才派。留这段时间给短时闪断自然清除，避免建出无效 TT。
         配 0 = 恢复「一升起就派」。
       * 上界 180 分钟 —— 兼防上线瞬间把积压的历史未清除 fiber 告警一次性全派出去；
  4. 该告警**尚未派过单**（状态表 `eflow_fiber_assign_log` 无 Y/D 记录），
     且上游没有自带 TT（`ttid` 为空）；
  5. **同站点在同时间窗口内没有关联告警**（默认 `99933`，窗口默认 60 分钟）。
     这是需求的核心：站点已经因 99933 派过单时，fiber 告警不再重复派单。
     ⚠ 只有**确认命中**才跳过；站名写法对不上（无法判定）时按「无关联」
     **继续派单**（2026-10-27 业务要求：不能因为站名匹配不到就卡住派单），
     结果里写 `correlation_undetermined` 留痕可复核。

**不构成阻断的两个坑（都吃过）**：
  * 99933 站名对不上 → 见上，按「无关联」继续；
  * eFlow 侧 `ttstatus` 非 0（ME 未关联站点）→ **仍然尝试派单**，只是收缩重试预算，
    失败后通报人工（2026-10-27 业务要求：不能被 eFlow 侧数据问题挡住）。

**站点解析（关键，实测教训）**：Fiber（TRM/IPRAN）告警的 `site` 是 ME 名
（如 `6120HA_zardun_UPE128`）、`sitename` 为 `--`，eFlow 的 TT 引擎无法据此
建 TT。必须解析出**数字站点 ID + 站点名**再放进派单 payload，TT 才真正生成。
解析顺序见 `eflow_assign_client.resolve_site`：告警自带 `site_id`（纯数字）→
`site_name` 查 cmdb → 从 ME 名解析站点名查 cmdb。解析不出站点则跳过（不派无站点的单）。

**派单后**：回查告警的 `ttid`，确认 TT 真的建出来才记 'Y'（接口返回 `status:true`
不代表建成功，见 `eflow_assign_client` docstring）。确认后 WhatsApp 通报。

**演练模式**（`dry_run`，默认开）：只查+匹配+记录将要派的单（状态 'D'），
**不调用派单接口**。首次上线先看日志/结果确认无误，再在页面关掉 dry_run。

## 状态表

`eflow_fiber_assign_log`（见 `fiber_store.py`）：`assign_status`
（Y 成功 / N 失败 / S 跳过 / D 演练）、`tt_no`、`skip_reason`、`send_status`。

## 发送通道

WhatsApp 走 Baileys 推送进程（`wa_notify_service`），投递前查心跳，只有服务端
回执确认后才置 `send_status='Y'`。
"""
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection
from backend.services import wa_notify_service as wa_notify
from backend.services.eflow_fiber import eflow_assign_client as client
from backend.services.eflow_fiber import fiber_config as config_mod
from backend.services.eflow_fiber import fiber_store as store
from backend.services.eflow_fiber.fiber_config import norm_code
from backend.services.wa_notify_service import dispatch, wait_for_job_result

logger = logging.getLogger("eflow_fiber_assign")

# ========== 配置（导入期一次算好；改页面后需 worker 重启） ==========
_CFG = config_mod.load_config()
ALARM_CODES = _CFG["alarm_codes"]
CORRELATION_CODES = _CFG["correlation_codes"]
CORRELATION_WINDOW_MINUTES = _CFG["correlation_window_minutes"]
WINDOW_MINUTES = _CFG["window_minutes"]
MIN_AGE_MINUTES = _CFG["min_age_minutes"]
ASSIGN_GROUP = _CFG["assign_group"]
DRY_RUN = _CFG["dry_run"]
GROUPS = _CFG["groups"]
GROUPS_FALLBACK = _CFG["groups_fallback"]
# 站点名近似匹配（cmdb 与网管命名不一致时兜底，带歧义保护）
SITE_FUZZY_ENABLED = _CFG["site_fuzzy_enabled"]
SITE_FUZZY_THRESHOLD = _CFG["site_fuzzy_threshold"]
# 同一次光纤中断的合并派单时间窗（分钟）。0 = 关闭合并。
GROUP_WINDOW_MINUTES = _CFG["group_window_minutes"]
SAMPLE_LIMIT = 5

# 派单重试（Fiber 派单时灵时不灵，必须重试到 TT 真建出为止）：
# 单轮最多尝试 ASSIGN_MAX_ATTEMPTS 次，每次之间等 ASSIGN_RETRY_DELAY 秒。
# 环境变量可调，默认 3 次 × 3s。
ASSIGN_MAX_ATTEMPTS = max(1, int(os.environ.get("FIBER_ASSIGN_MAX_ATTEMPTS", "3")))
ASSIGN_RETRY_DELAY = float(os.environ.get("FIBER_ASSIGN_RETRY_DELAY", "3"))

# 消息抬头（群里每条通报都带）
PUSH_TITLE = "Fiber Break Alarm TT Assign Notification"


def _val(v: Any) -> Any:
    if isinstance(v, dict):
        return v.get("value")
    return v


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _epoch_ms(val: Any) -> Optional[int]:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


# ==========================================================
# 匹配与关联判定（纯函数，便于单测）
# ==========================================================
_SITE_PLACEHOLDERS = ("--", "-", "empty", "none", "null")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                      re.IGNORECASE)


def _is_uuid(value: str) -> bool:
    """UUID 不是站点名：`mename` 常是 UUID（实测 6784c258-…），别拿它当站名键。"""
    return bool(_UUID_RE.match(str(value or "").strip()))


def _alarm_site_keys(alarm: Dict[str, Any]) -> set:
    """关联判定用的站点键**集合**（数字站号 / 站点名两类，任一相交即同站）。

    ⚠ 为什么是集合而不是单个键（2026-10-26 生产实测，原实现会漏判）：
    两类告警的站点字段形态**都不一样**，且同一类也不稳定：

    | 字段 | 4758（Fiber） | 99933（小区退服） |
    | --- | --- | --- |
    | `site` | 有时数字（`4030`）、有时 ME 名（`6120HS_Peter_..._UPE80`） | 数字站号（`4523`） |
    | `sitename` | 有时真名（`Old Road`）、有时 `--` | 站点名（`Tokpah Camp`） |
    | `mename` | ME 名或 **UUID**（`6784c258-...`） | 站点名 |

    原实现「优先 site_id → 再 site_name → 最后 mename」只认数据库列名
    （`site_id`/`site_name`），对原始 API 行（`site`/`sitename`）取不到值，最后
    落到 `mename` 的 UUID 上 —— 于是 4758 的键是 UUID、99933 的键是站点名，
    **永远不相交，「同站已有 99933 就不派单」这条核心需求会静默失效**（会重复派单）。
    改成把「所有能代表站点的标识」都收进集合，跨形态比对：
      * `id:<数字站号>` —— 来自 `site_id` / `site` / `mename` 中的纯数字；
      * `name:<站点名小写>` —— 来自 `site_name` / `sitename` / 从 ME 名解析出的站点名。
    """
    keys = set()

    for cand in (_s(_val(alarm.get("site_id"))), _s(_val(alarm.get("site")))):
        if cand.isdigit():
            keys.add("id:" + cand)

    for cand in (_s(_val(alarm.get("site_name"))), _s(_val(alarm.get("sitename")))):
        if cand and cand.lower() not in _SITE_PLACEHOLDERS and not _is_uuid(cand):
            keys.add("name:" + cand.lower())

    me = _s(_val(alarm.get("mename")) or _val(alarm.get("site")))
    if me:
        if me.isdigit():
            keys.add("id:" + me)
        else:
            derived = client.site_name_from_me(me)
            if (derived and derived.lower() not in _SITE_PLACEHOLDERS
                    and not _is_uuid(derived)):
                keys.add("name:" + derived.lower())

    return keys


def _occur_ms(alarm: Dict[str, Any]) -> Optional[int]:
    return _epoch_ms(_val(alarm.get("alarmraisedtime")) or _val(alarm.get("servertime")))


CORRELATION_HIT = "hit"
CORRELATION_NONE = "none"
CORRELATION_UNDETERMINED = "undetermined"


def correlation_verdict(alarm: Dict[str, Any], all_alarms: List[Dict[str, Any]]
                        ) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """判定「同站同窗口是否已有关联告警（默认 99933）」，返回 (结论, 命中告警, 说明)。

    结论三态（2026-10-27 按如意要求明确化）：
      * `hit`          —— 确实命中，调用方跳过派单；
      * `none`         —— 站点信息齐全、确实查过没有；
      * `undetermined` —— 站点名对不上，**无法判定**。业务要求「匹配不到就当作没有」，
                         所以**继续派单**，但必须留痕（warnings/samples），事后能复核。

    为什么会出现 undetermined：fiber 的站点名来自 ME 名（`x_<站名>_UPEyy`），与 99933
    的 cmdb 站名写法可能不同（实测 `Peter_luogan_town` vs `Peter Luogon Town`）——
    两边站点键不相交。原实现对此静默返回 None（等于当作没有但无从追溯），现在显式区分。
    """
    if not CORRELATION_CODES:
        return CORRELATION_NONE, None, "未启用关联告警码"

    keys = _alarm_site_keys(alarm)
    if not keys:
        return (CORRELATION_UNDETERMINED, None,
                "fiber 侧站点信息不足（site/sitename/mename 均解析不出站点键）")

    occ = _occur_ms(alarm)
    win_ms = CORRELATION_WINDOW_MINUTES * 60 * 1000
    blind = 0
    for other in all_alarms:
        if norm_code(_val(other.get("alarmcode"))) not in CORRELATION_CODES:
            continue
        o_keys = _alarm_site_keys(other)
        if not o_keys:
            blind += 1
            continue
        if not (keys & o_keys):
            continue
        o_occ = _occur_ms(other)
        if occ is not None and o_occ is not None and abs(o_occ - occ) > win_ms:
            continue
        return CORRELATION_HIT, other, ""

    if blind:
        return (CORRELATION_UNDETERMINED, None,
                f"{blind} 条关联告警站点信息不足无法比对")
    # 只有站名键、没有数字站号：站名是从 ME 名推导的，与 99933 的 cmdb 站名写法
    # 可能不同（实测 `Peter_luogan_town` vs `Peter Luogon Town`）→ 不相交不足为凭。
    if not any(k.startswith("id:") for k in keys):
        return (CORRELATION_UNDETERMINED, None,
                f"仅有站名键（{', '.join(sorted(keys))}）无数字站号，站名写法差异可能漏判")
    return CORRELATION_NONE, None, ""


def find_correlated_alarm(alarm: Dict[str, Any], all_alarms: List[Dict[str, Any]],
                          now_ms: int = 0) -> Optional[Dict[str, Any]]:
    """兼容包装：只返回命中的关联告警（`none` / `undetermined` 都返回 None）。

    保留旧签名供单测与既有调用点使用；需要区分三态请直接用 `correlation_verdict`。
    """
    verdict, hit, _ = correlation_verdict(alarm, all_alarms)
    return hit if verdict == CORRELATION_HIT else None


def alarm_key_of(alarm: Dict[str, Any]) -> str:
    """告警唯一键：优先 `alarmkey`，回退 `id`（与主流程取键口径一致）。"""
    return _s(_val(alarm.get("alarmkey"))) or _s(_val(alarm.get("id")))


def group_by_occurrence(alarms: List[Dict[str, Any]], window_ms: int
                        ) -> Dict[str, Dict[str, Any]]:
    """按升起时间把告警聚类成「同一次故障」组（合并派单的判据）。

    背景（2026-10-27 生产实况）：一次光缆中断会让链路上多个站点**同时**告警，
    实测 14:21 一次故障派出 5 个 TT（R.I.A×3 + Tower Hill + HQ_Site，9 秒内），
    现场反馈是同一个故障 → 应合并成**一个** TT，正文说明涵盖哪些站点。

    **为什么用时间窗**：项目现有数据判不出「同一条光纤」——
    `probeid` 全库同一个 UUID、`impact_site_list`/`link_path` 全空、
    `flm_database.fdn` 被 96 个站点共用（太粗）、`victim_topology` 里
    R.I.A 与 Tower Hill 互不包含且各是独立网关、eFlow `relatedAlarms` 返回 0 条。
    时间聚集是唯一立即可用的强信号。

    **分组规则**：按升起时间升序，与组内**第一条**的时间差 ≤ `window_ms` 则并入，
    否则开新组。用「与第一条比」而非「与上一条比」是刻意的 —— 链式比较会让组
    无限膨胀（A→B 差 9 分钟、B→C 差 9 分钟，结果跨度 18 分钟却同组），
    与第一条比则保证**组跨度不超过窗口**。

    **取不到升起时间的告警不参与合并**，各自成一组：无法判断时序时宁可多派一单，
    也不把来路不明的告警并进别人的 TT（宁可漏派不可错派）。

    返回 `{alarm_key: {"root": 组长告警的 key, "members": [告警, ...]}}`，
    组长 = 组内升起最早的那条（最可能是根因站点）。
    `window_ms <= 0` 时每条告警自成一组（= 关闭合并）。
    """
    groups: Dict[str, Dict[str, Any]] = {}

    def _alone(a: Dict[str, Any]) -> None:
        k = alarm_key_of(a)
        groups[k] = {"root": k, "members": [a]}

    if window_ms <= 0:
        for a in alarms:
            _alone(a)
        return groups

    ordered = sorted(alarms, key=lambda x: (_occur_ms(x) is None, _occur_ms(x) or 0,
                                            alarm_key_of(x)))
    bucket: List[Dict[str, Any]] = []
    base_ms: Optional[int] = None

    def _flush() -> None:
        nonlocal bucket, base_ms
        if not bucket:
            return
        root_key = alarm_key_of(bucket[0])
        for m in bucket:
            groups[alarm_key_of(m)] = {"root": root_key, "members": list(bucket)}
        bucket, base_ms = [], None

    for a in ordered:
        occ = _occur_ms(a)
        if occ is None:
            _flush()
            _alone(a)
            continue
        if base_ms is None or not bucket:
            bucket, base_ms = [a], occ
            continue
        if occ - base_ms <= window_ms:
            bucket.append(a)
            continue
        _flush()
        bucket, base_ms = [a], occ
    _flush()
    return groups


def age_minutes(alarm: Dict[str, Any], now_ms: int) -> Optional[float]:
    """告警升起至今的分钟数；取不到升起时间返回 None。

    用 `alarmraisedtime`（无则 `servertime`）。负值（上游时间跑在将来）钳到 0，
    避免时钟漂移把「刚升起的告警」判成「已存续很久」。
    """
    occ = _occur_ms(alarm)
    if occ is None:
        return None
    return max(0.0, (now_ms - occ) / 60000.0)


# due_verdict 的几种结论（主循环据此分桶计数，便于排障区分「等一等」与「真有问题」）
DUE_YES = "due"           # 命中且在 [下界, 上界] 区间内 → 派单
DUE_TOO_NEW = "too_new"   # 存续时长 < min_age_minutes → 还没到派单时机，等下轮
DUE_TOO_OLD = "too_old"   # 存续时长 > window_minutes → 太老，不派
DUE_NO_CODE = "no_code"   # 告警码不命中白名单
DUE_NO_TIME = "no_time"   # 取不到告警升起时间


def due_verdict(alarm: Dict[str, Any], now_ms: int) -> Tuple[str, Optional[float]]:
    """判定该告警本轮是否该派单 → (结论, 存续分钟数)。

    ## 两条边界（2026-10-27 业务口径）

    * **下界** `MIN_AGE_MINUTES`（默认 15）：告警升起后必须先存在满 N 分钟才派单。
      业务原话「告警发生到选择超过 15 分钟，才要指派单子和发送 WhatsApp 消息」——
      即**不是一升起就派**，而是等满 15 分钟再派。留这段时间给短时闪断自然清除，
      避免建出一堆瞬时告警的无效 TT。配 0 = 恢复「一升起就派」。
    * **上界** `WINDOW_MINUTES`（默认 180）：太老的告警不再派（防上线瞬间把积压的
      历史未清除 fiber 告警一次性全派出去）。

    ⚠ 下界只挡「太新」，不挡「太老」；两条独立生效。

    ⚠ **这是派单判定的唯一真相源** —— `is_due` 是它的薄封装，主循环也直接调它
    （主循环要按结论分桶计数）。任何改动只改这里，别在别处再写一遍边界判断。
    """
    if norm_code(_val(alarm.get("alarmcode"))) not in ALARM_CODES:
        return DUE_NO_CODE, None
    age = age_minutes(alarm, now_ms)
    if age is None:
        return DUE_NO_TIME, None
    if age < MIN_AGE_MINUTES:
        return DUE_TOO_NEW, age
    if age > WINDOW_MINUTES:
        return DUE_TOO_OLD, age
    return DUE_YES, age


def is_due(alarm: Dict[str, Any], now_ms: int) -> bool:
    """告警码命中 + 存续时长落在 [最小存续时长, 触发窗口] 区间内。

    ⚠ 薄封装：判定口径只有 `due_verdict` 一处，主循环与单测都走它，
    避免两处各写一遍边界判断而悄悄跑偏。
    """
    return due_verdict(alarm, now_ms)[0] == DUE_YES


def upstream_tt(alarm: Dict[str, Any]) -> str:
    """告警上游（eFlow 自身派单规则）已带的 TT 编号；没有则返回空串。

    生产上 eFlow 的 `assign_rule` 会给部分 fiber 告警先建 TT，这些告警在我方
    状态表里没有记录，只看状态表就会重复派单。判定为纯函数便于单测。
    """
    tt = _s(_val(alarm.get("ttid")))
    if not tt or tt.lower() in ("empty", "none", "null", "-"):
        return ""
    return tt


def is_already_handled(prev_status: str, dry_run: bool) -> bool:
    """状态表命中「已处理」的判定。

    * `Y`（已确认派单成功）→ 永远跳过，避免对同一告警重复建 TT；
    * `D`（演练记录）→ **只在演练模式下**算已处理。一旦关掉 dry_run，演练过的
      告警必须重新走完整流程真派单，否则会被永久跳过（2026-10-26 自查发现）。
    """
    return prev_status == "Y" or (prev_status == "D" and bool(dry_run))


def is_clean_ttstatus(ttstatus: Any) -> bool:
    """eFlow 侧 `ttstatus` 是否处于「正常可派」状态（`0` = UnAssigned；字段缺失按正常）。

    ⚠ **这是提示信号，不是阻断条件**（2026-10-27 业务要求：不能被 eFlow 侧
    「ME 未绑定站点」挡住，该试还得试）。它只用来：
      1. 把本轮派单尝试预算收窄（见 `assign_attempt_budget`），避免每轮白烧 70s；
      2. 失败时把原因写成「ME 未关联站点」，并通报人工去 eFlow 修绑定。

    ## 实测教训（2026-10-27 切生产首轮就撞上）

    全库 6669 条告警里 `ttstatus=2` 只有 5 条（1 条 fiber 4758 + 4 条环境温度
    761761），它们的共同特征是 **`site` 是 ME 名、`sitename` 为 `--`/None** ——
    ME 未在 eFlow 侧正确关联站点。对这类告警派单，接口回
    `200 manual assign succeed.`，但 `ttid` 永远为空、`ttstatus` 不变，
    重试 3 次 + 人工单次调用全部失败（实测白跑 ~70 秒）。

    这不是 payload 问题（站点 ID/名都对），是 eFlow 数据侧状态问题，只能人工处理。
    `0` = UnAssigned；`1` = Assigned（已派，前面按 ttid 已跳过）；`2`/`4`/`5`/`6`
    视为可疑（仍会尝试，但只用最小预算）。
    """
    txt = _s(_val(ttstatus))
    return not txt or txt == "0"


def assign_attempt_budget(status_suspect: bool) -> Tuple[int, int]:
    """本轮派单预算 → (接口尝试次数, 每次回查次数)。

    * 正常告警：`ASSIGN_MAX_ATTEMPTS`(默认 3) × 3 次回查 —— eFlow 派单「时灵时不灵」，
      必须重试到 TT 真建出为止；
    * `ttstatus` 可疑（ME 未关联站点）：1 次尝试 × 2 次回查 —— 仍要试（业务要求不可
      被挡住），但实测这类多半回 succeed 不建 TT，按 3 次重试白烧 70s 不划算。
    """
    if status_suspect:
        return 1, 2
    return ASSIGN_MAX_ATTEMPTS, 3


# ==========================================================
# 消息渲染
# ==========================================================
def build_message(alarm: Dict[str, Any], site_id: str, site_name: str,
                  group_name: str, tt_no: str, dry_run: bool,
                  site_note: str = "",
                  notes: Optional[List[str]] = None,
                  impacted: Optional[List[Tuple[str, str]]] = None) -> str:
    """按需求格式渲染通报：TT Title = SITE ID_Site name_Alarm Code。

    TT 的真正标题由 eFlow 自动生成（`<site>.[<site name>]<告警名>`），接口不接受
    自定义标题；故群里按需求格式通报，并附上真实 TT 编号。

    ⚠ **群通报正文一律英文**（2026-10-27 如意要求「通报默认使用英文」）。
    故调用方传入的 `site_note` / `notes` 必须已是英文；中文只留在日志与状态表里。

    `site_note` 非空时在末尾追加提示（站点名近似匹配时用，提醒核对 cmdb 命名）；
    `notes` 是其它需要让人看见的留痕（如「99933 关联无法判定，已按无关联派单」）。

    `impacted` 是**同一次光纤中断里被本 TT 一并覆盖的其它站点**（合并派单，
    2026-10-27）：`[(site_id, site_name), ...]`，已去重，**不含**本条自己的站点。
    非空时在正文追加一段，说明「这一单实际涵盖 N 个站点」，避免群里误以为
    只坏了这一个站。只有 1 个站点（没有合并）时调用方传空 → 正文保持原样。
    """
    code = norm_code(_val(alarm.get("alarmcode")))
    code_name = _s(_val(alarm.get("codename")) or _val(alarm.get("alarm_title")))
    occ = _occur_ms(alarm)
    occ_txt = datetime.fromtimestamp(occ / 1000).strftime("%Y-%m-%d %H:%M:%S") if occ else "-"
    title = f"{site_id}_{site_name}_{code}"
    lines = [PUSH_TITLE, ""]
    lines.append(f"TT Title : {title}")
    lines.append(f"Site ID  : {site_id}")
    lines.append(f"Site Name: {site_name}")
    lines.append(f"Alarm    : {code} {code_name}".rstrip())
    lines.append(f"Occurred : {occ_txt}")
    me_name = _s(_val(alarm.get("mename")) or _val(alarm.get("site")))
    if me_name:
        lines.append(f"ME       : {me_name}")
    if tt_no:
        lines.append(f"TT No.   : {tt_no}")
    lines.append(f"Assigned : {group_name}")
    if impacted:
        # 合并派单：说清「这一单实际涵盖多个站点」，否则群里会以为只坏了一个站
        lines.append("")
        lines.append(f"This TT covers {len(impacted) + 1} sites from the same fiber cut:")
        lines.append(f"  - {site_id}/{site_name}  (TT created on this site)")
        for _sid, _sname in impacted:
            # 站点解析失败的成员也要露出来（用站名/ME 名兜底），不能显示成空行 ——
            # 否则群里看到一行空白，反而不知道这一单还涵盖了谁。
            _label = f"{_sid}/{_sname}" if _sid else (_sname or "unknown site")
            lines.append(f"  - {_label}")
    if dry_run:
        lines.append("")
        lines.append("⚠ DRY-RUN: rehearsal only, no TT has been created")
    if site_note:
        lines.append("")
        lines.append(f"⚠ {site_note}")
    for note in notes or []:
        if note:
            lines.append(f"⚠ {note}")
    return "\n".join(lines)


def build_manual_message(alarm: Dict[str, Any], reason: str,
                         hint_lines: Optional[List[str]] = None) -> str:
    """自动派单失败时的「需人工处理」通报（2026-10-27 业务要求：不能静默漏派）。

    两类失败都会走它：
      1. **站点解析失败** —— 拿不到数字站号，eFlow 对只带 ME 名的 payload 会回
         `manual assign succeed.` 却不建 TT（实测）；
      2. **eFlow 侧 ttstatus 非 0**（ME 未关联站点）—— 仍会尝试派单，但接口回
         succeed 也不建 TT，必须让人去 eFlow 修站点绑定。

    共同点：自动派不了，**但必须让群里看到**，否则等于漏派且无人知晓。
    同一条告警只通知一次，由状态表 `send_status` 抑制（见主流程）。

    ⚠ **群通报正文一律英文**（2026-10-27 如意要求「通报默认使用英文」）：
    `reason` / `hint_lines` 必须由调用方传入英文；中文原因走 `last_error` 落状态表。
    """
    code = norm_code(_val(alarm.get("alarmcode")))
    code_name = _s(_val(alarm.get("codename")) or _val(alarm.get("alarm_title")))
    occ = _occur_ms(alarm)
    occ_txt = datetime.fromtimestamp(occ / 1000).strftime("%Y-%m-%d %H:%M:%S") if occ else "-"
    me_name = _s(_val(alarm.get("mename")) or _val(alarm.get("site")))

    lines = [PUSH_TITLE, ""]
    lines.append("⚠ Auto assign failed — manual action required in eFlow")
    lines.append(f"ME       : {me_name or '-'}")
    lines.append(f"Alarm    : {code} {code_name}".rstrip())
    lines.append(f"Occurred : {occ_txt}")
    lines.append(f"Reason   : {reason}")
    lines.append("")
    if hint_lines is None:
        hint_lines = ["Note: no numeric site ID could be resolved from cmdb for this site,",
                      "      so eFlow cannot create a TT automatically.",
                      "      Please fix the cmdb site or assign the TT manually in eFlow."]
    lines.extend(hint_lines)
    return "\n".join(lines)


# ==========================================================
# 主流程
# ==========================================================
def run_fiber_assign() -> Dict[str, Any]:
    """每 5 分钟执行：拉实时告警 → 匹配 → 关联判定 → 派单（或演练）→ 通报 → 落库。"""
    started = time.time()
    now_ms = int(time.time() * 1000)
    out: Dict[str, Any] = {
        "success": False, "dry_run": DRY_RUN, "fetched": 0,
        "fiber_alarms": 0, "due": 0, "assigned": 0, "skipped": 0,
        "failed": 0, "notified": 0,
        # 还没到派单时机（存续时长 < min_age_minutes，默认 15 分钟）→ 本轮不派，
        # 等下一轮再看。分出来是为了让排障能区分「等一等」与「真有问题」。
        "waiting": 0, "waiting_samples": [],
        # 存续时长超过触发窗口（太老）→ 不派。
        "expired": 0, "expired_samples": [],
        # 关联判定「无法判定 → 按无关联继续派单」的计数与明细（可审计，2026-10-27）
        "correlation_undetermined": 0, "correlation_undetermined_samples": [],
        # eFlow 侧 ttstatus 非 0（ME 未关联站点）的条数 —— 不再阻断，只收缩重试预算
        "suspect_ttstatus": 0, "suspect_ttstatus_samples": [],
        # 自动派不了（站点解析失败 / ttstatus 异常）→ 群里通报「需人工处理」的计数
        "manual_notified": 0,
        # 同一次光纤中断合并派单：被组长的 TT 覆盖、未单独建单的告警条数
        "merged": 0,
        "group_window_minutes": GROUP_WINDOW_MINUTES,
        "assign_group": ASSIGN_GROUP, "alarm_codes": sorted(ALARM_CODES),
        "correlation_codes": sorted(CORRELATION_CODES),
        "groups": list(GROUPS), "group_fallback": GROUPS_FALLBACK,
        "samples": [], "errors": [], "warnings": [], "elapsed_seconds": 0,
    }

    def _finish() -> Dict[str, Any]:
        out["elapsed_seconds"] = round(time.time() - started, 2)
        logger.info("[Fiber] 完成 dry_run=%s fetched=%s fiber=%s due=%s waiting=%s expired=%s "
                    "assigned=%s skipped=%s failed=%s notified=%s "
                    "corr_undet=%s suspect_ttstatus=%s merged=%s 用时%.2fs",
                    DRY_RUN, out["fetched"], out["fiber_alarms"], out["due"],
                    out["waiting"], out["expired"],
                    out["assigned"], out["skipped"], out["failed"], out["notified"],
                    out["correlation_undetermined"], out["suspect_ttstatus"],
                    out.get("merged", 0),
                    out["elapsed_seconds"])
        return out

    # ---------- 1. 拉取实时告警 ----------
    try:
        all_alarms = client.fetch_active_alarms()
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"拉取实时告警失败: {type(e).__name__}: {e}")
        logger.exception("[Fiber] 拉取实时告警失败")
        return _finish()
    out["fetched"] = len(all_alarms)

    fiber_alarms = [a for a in all_alarms
                    if norm_code(_val(a.get("alarmcode"))) in ALARM_CODES]
    out["fiber_alarms"] = len(fiber_alarms)
    if not fiber_alarms:
        out["success"] = True
        out["message"] = "无 fiber 告警"
        return _finish()

    # ---------- 2. 解析目标派单组 ----------
    try:
        group = client.resolve_group(ASSIGN_GROUP)
    except Exception as e:  # noqa: BLE001
        group = None
        out["errors"].append(f"解析用户组失败: {type(e).__name__}: {e}")
    if group is None:
        out["errors"].append(f"找不到派单用户组 {ASSIGN_GROUP!r}，本轮不派单")
        return _finish()

    # ---------- 3. 读状态表 ----------
    conn = get_raw_connection()
    try:
        store.ensure_log_table(conn)
        keys = [_s(_val(a.get("alarmkey"))) or _s(_val(a.get("id"))) for a in fiber_alarms]
        records = store.load_records(conn, keys)

        index = client.SiteIndex(fuzzy_enabled=SITE_FUZZY_ENABLED,
                                 fuzzy_threshold=SITE_FUZZY_THRESHOLD)
        messages: List[Dict[str, Any]] = []
        pending_success: List[Dict[str, Any]] = []
        # 自动派不了（站点解析失败 / ttstatus 异常）→ 需人工处理，同一告警只发一次
        pending_manual: List[Dict[str, Any]] = []

        # ---------- 3.1 同一次光纤中断的合并分组（2026-10-27） ----------
        # 一次光缆中断会让链路上多个站点同时告警 → 合并成**一个** TT，
        # 正文列出实际涵盖的站点（判据与理由见 `group_by_occurrence`）。
        group_map = group_by_occurrence(fiber_alarms, GROUP_WINDOW_MINUTES * 60 * 1000)
        # 组长（组内升起最早）必须先处理，成员才能跟随它建出的 TT 号。
        fiber_alarms = sorted(
            fiber_alarms,
            key=lambda x: (_occur_ms(x) is None, _occur_ms(x) or 0, alarm_key_of(x)))
        # 组长 key → 该组建出的 TT 号（dry-run 时为空串，表示「演练已覆盖」）
        group_tt: Dict[str, str] = {}
        # 组长 key → 本组涵盖的站点 [(site_id, site_name), ...]（去重后）
        group_sites: Dict[str, List[Tuple[str, str]]] = {}
        # 合并掉的告警条数（被组长的 TT 覆盖、未单独派单）
        merged = 0

        for a in fiber_alarms:
            akey = _s(_val(a.get("alarmkey"))) or _s(_val(a.get("id")))
            rec = records.get(akey) or {}
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            base = {
                "alarm_key": akey,
                "alarm_id": _s(_val(a.get("id"))),
                "alarm_code": norm_code(_val(a.get("alarmcode"))),
                "me_name": _s(_val(a.get("mename")) or _val(a.get("site"))),
                "occur_time": (datetime.fromtimestamp(_occur_ms(a) / 1000).strftime("%Y-%m-%d %H:%M:%S")
                               if _occur_ms(a) else None),
                "last_seen_time": now_str,
                "first_seen_time": rec.get("first_seen_time") or now_str,
            }

            # 已确认派单成功（Y）→ 永久跳过，避免对同一告警重复建 TT。
            # ⚠ 演练记录（D）**只在演练模式下**算「已处理」：一旦关掉 dry_run，
            #   之前演练过的告警必须重新走完整流程去真派单，否则它们会被永久跳过
            #   （2026-10-26 生产切换自查发现）。所以 D 只在 DRY_RUN 为真时跳过。
            prev = _s(rec.get("assign_status"))
            # 首次见到这条告警（状态表无历史状态）。
            # ⚠ 为什么需要：`warnings` 非空会让 `task_runner` 判「任务降级完成」并推**一条
            #   微信通知**。而「站点名近似匹配」「关联判定不了」「ttstatus 异常」这些是
            #   **告警级**的长期状态 —— 每轮都写 warnings 就等于每 5 分钟推一条微信。
            #   故 warnings 只报首次（人知道一次就够），后续轮次只留在 samples / 状态表里。
            first_sight = not prev
            if is_already_handled(prev, DRY_RUN):
                out["skipped"] += 1
                store.upsert_record(conn, base)
                continue

            # ⚠ 告警**上游已经带 TT** 时绝不能重复派单（2026-10-26 生产切换自查发现）。
            # 生产上 eFlow 自己的派单规则（assign_rule）会给部分 fiber 告警先建 TT，
            # 这些告警在我方状态表里没有记录，若只看状态表就会再派一次、建出重复单。
            # ttid 非空且不是占位值 → 视为已派单，登记 Y 跳过。
            upstream_tt_no = upstream_tt(a)
            if upstream_tt_no:
                out["skipped"] += 1
                base.update({"assign_status": "Y", "tt_no": upstream_tt_no,
                             "skip_reason": "上游已存在 TT（eFlow 规则已派单），不重复派"})
                store.upsert_record(conn, base)
                out["samples"].append({"alarm_key": akey, "action": "skip_existing_tt",
                                       "tt_no": upstream_tt_no})
                logger.info("[Fiber] 跳过 %s：上游已有 TT %s", akey, upstream_tt_no)
                continue

            # 触发条件：告警码命中 + 存续时长落在 [最小存续时长, 触发窗口] 内。
            # ⚠ 分三种「不派」的原因分别计数，否则排障时分不清「还没到派单时机」
            #   和「太老已过期」—— 前者正常（等下轮），后者要查为何积压。
            #   判定口径见 `due_verdict`（唯一真相源），这里只做分桶。
            _verdict, _age = due_verdict(a, now_ms)
            if _verdict == DUE_TOO_NEW:
                # 还没到派单时机（默认等满 15 分钟）→ 本轮不派，下轮再看
                out["waiting"] += 1
                if len(out["waiting_samples"]) < SAMPLE_LIMIT:
                    out["waiting_samples"].append(
                        {"alarm_key": akey, "age_minutes": round(_age or 0, 1)})
                continue
            if _verdict in (DUE_TOO_OLD, DUE_NO_TIME):
                # 太老（超过触发窗口）或取不到升起时间 → 不派
                out["expired"] += 1
                if len(out["expired_samples"]) < SAMPLE_LIMIT:
                    out["expired_samples"].append(
                        {"alarm_key": akey, "age_minutes": round(_age or 0, 1),
                         "reason": _verdict})
                continue
            if _verdict != DUE_YES:
                # 告警码不命中白名单 → 不算本任务的告警，不计数
                continue

            # eFlow 侧 `ttstatus`：**提示信号，不是阻断条件**。
            # 2026-10-27 业务要求：不能被「ME 未关联站点」挡住 —— 该试还得试，
            # 试失败才通报人工。实测这类告警接口回 succeed 却不建 TT，故只用最小
            # 预算（见 `assign_attempt_budget`），避免每轮白烧 70 秒并反复刷群。
            tt_status = _s(_val(a.get("ttstatus")))
            status_suspect = not is_clean_ttstatus(tt_status)
            if status_suspect:
                out["suspect_ttstatus"] += 1
                out["suspect_ttstatus_samples"].append(
                    {"alarm_key": akey, "ttstatus": tt_status})
                if first_sight:
                    out["warnings"].append(
                        f"{akey} eFlow 侧 ttstatus={tt_status}（ME 可能未关联站点），仍尝试派单")
                logger.warning("[Fiber] %s ttstatus=%s（ME 未关联站点），不阻断、仍尝试派单",
                               akey, tt_status)

            # 关联判定：同站同窗口已有 99933 → 跳过。
            # ⚠ 站点名对不上（fiber 的 ME 站名 vs 99933 的 cmdb 站名写法不同）时
            #   `correlation_verdict` 返回 undetermined：**按「没有关联」继续派单**
            #   （2026-10-27 业务要求：不能因为站名匹配不到就卡住派单），
            #   但写进 warnings / correlation_undetermined 留痕，事后可复核是否重复派单。
            corr_note_for_msg = ""
            verdict, corr, corr_note = correlation_verdict(a, all_alarms)
            if verdict == CORRELATION_HIT and corr is not None:
                reason = (f"同站点已有 {norm_code(_val(corr.get('alarmcode')))} 告警"
                          f"（id={_s(_val(corr.get('id')))}），不重复派单")
                out["skipped"] += 1
                base.update({"assign_status": "S", "skip_reason": reason})
                store.upsert_record(conn, base)
                out["samples"].append({"alarm_key": akey, "action": "skip", "reason": reason})
                logger.info("[Fiber] 跳过 %s：%s", akey, reason)
                continue
            if verdict == CORRELATION_UNDETERMINED:
                out["correlation_undetermined"] += 1
                out["correlation_undetermined_samples"].append(
                    {"alarm_key": akey, "me_name": base.get("me_name"),
                     "site_keys": sorted(_alarm_site_keys(a)), "note": corr_note})
                if first_sight:
                    out["warnings"].append(
                        f"{akey} 关联判定无法完成（{corr_note}），按「无关联」继续派单")
                logger.warning("[Fiber] %s 关联判定无法完成：%s；按无关联继续派单",
                               akey, corr_note)
                # 通报里也写一句，群里能看到「这条是判定不了关联、按无关联派的」。
                # ⚠ 通报正文必须英文（corr_note 是中文，只留在 warnings/日志里），
                #   故这里用英文重述，并带上可核查的站点键。
                site_keys_txt = ", ".join(sorted(_alarm_site_keys(a))) or "-"
                corr_note_for_msg = ("99933 correlation could not be determined "
                                     f"(site keys: {site_keys_txt}) — "
                                     "assigned as no-correlation")

            out["due"] += 1

            # ---------- 合并派单：本条已被组长告警的 TT 覆盖 ----------
            # 组长（组内升起最早）在上一轮迭代里已经派单成功/演练覆盖，
            # 本条不再单独建单，只登记同一个 TT 号，让通报错开重复单。
            grp = group_map.get(akey) or {"root": akey, "members": [a]}
            root_key = grp["root"]
            if root_key != akey and root_key in group_tt:
                # 仍要解析站点：通报里要列出本组实际涵盖哪些站点
                _mtrace: Dict[str, Any] = {}
                m_site_id, m_site_name = client.resolve_site(a, index, trace=_mtrace)
                # 解析不出站点时用 ME 名兜底：通报里必须露出这条告警属于哪个站，
                # 否则群里只看到「涵盖 3 个站点」却数不出第三个是谁。
                if not m_site_name:
                    m_site_name = base.get("me_name") or akey
                label = f"{m_site_id}/{m_site_name}" if m_site_id else m_site_name
                bucket = group_sites.setdefault(root_key, [])
                if (m_site_id, m_site_name) not in bucket:
                    bucket.append((m_site_id, m_site_name))
                if m_site_id:
                    base["site_id"] = m_site_id
                    base["site_name"] = m_site_name
                base.update({
                    "assign_status": "D" if DRY_RUN else "Y",
                    "tt_no": group_tt.get(root_key) or None,
                    "skip_reason": (f"同一次光纤中断，已合并到组长告警 {root_key} 的 TT"
                                    f"（本组共 {len(grp['members'])} 条告警）"),
                })
                store.upsert_record(conn, base)
                merged += 1
                out["samples"].append({"alarm_key": akey, "action": "merged_into_group",
                                       "root": root_key, "site": label})
                logger.info("[Fiber] %s 合并到组长 %s 的 TT（本组 %d 条告警），不单独派单",
                            akey, root_key, len(grp["members"]))
                continue

            # 站点解析（trace 留痕：近似匹配必须让人能一眼看出来）
            trace: Dict[str, Any] = {}
            site_id, site_name = client.resolve_site(a, index, trace=trace)
            if not site_id:
                tried = trace.get("tried") or []
                hint = f"；已尝试站名 {tried}" if tried else ""
                # 中文：进状态表 last_error / warnings / 日志
                reason = f"站点解析失败（site_id/site_name/ME 均无法映射到 cmdb 站点{hint}）"
                # 英文：进群通报（通报默认英文）
                tried_txt = f" (tried site names: {', '.join(map(str, tried))})" if tried else ""
                reason_en = ("site resolution failed — no numeric site ID matched in cmdb"
                             f"{tried_txt}")
                out["failed"] += 1
                base.update({"assign_status": "N", "last_error": reason})
                store.upsert_record(conn, base)
                if first_sight:
                    out["warnings"].append(f"{akey} 站点解析失败，未派单：{reason}")
                # 自动派不了，但不能静默：同一条只往群里通报一次（send_status 抑制），
                # 否则每 5 分钟刷一条同样的失败消息（2026-10-27 如意要求）。
                if _s(rec.get("send_status")) != "Y":
                    pending_manual.append({"alarm_key": akey, "alarm": a,
                                           "reason": reason_en})
                continue
            base.update({"site_id": site_id, "site_name": site_name})

            fuzzy_note = ""      # 中文：进 warnings / 日志
            fuzzy_note_en = ""   # 英文：进群通报
            if trace.get("matched_by") == "fuzzy":
                fuzzy_note = (f"站点名近似匹配：{trace.get('query')!r} → {site_name!r}"
                              f"（相似度 {trace.get('score')}），请核对 cmdb 命名")
                fuzzy_note_en = (f"Site name fuzzy-matched: {trace.get('query')!r} -> "
                                 f"{site_name!r} (score {trace.get('score')}), "
                                 f"please verify the cmdb naming")
                if first_sight:
                    out["warnings"].append(f"{akey} {fuzzy_note}")
                logger.warning("[Fiber] %s %s", akey, fuzzy_note)

            # 演练模式：只记录
            if DRY_RUN:
                base.update({"assign_status": "D",
                             "skip_reason": "dry-run 演练模式，未真派单"
                                            + (f"（{fuzzy_note}）" if fuzzy_note else "")})
                store.upsert_record(conn, base)
                # 标记本组已覆盖：后续同组成员跟随本条，演练里也能看出会合并成几单
                group_tt.setdefault(root_key, "")
                if (site_id, site_name) not in group_sites.setdefault(root_key, []):
                    group_sites[root_key].append((site_id, site_name))
                out["samples"].append({"alarm_key": akey, "action": "dry_run",
                                       "site_id": site_id, "site_name": site_name,
                                       "site_matched_by": trace.get("matched_by"),
                                       "site_score": trace.get("score"),
                                       "group_size": len(grp["members"])})
                logger.info("[Fiber] DRY-RUN 将派单 %s site=%s/%s（匹配方式 %s，本组 %d 条告警）",
                            akey, site_id, site_name, trace.get("matched_by"),
                            len(grp["members"]))
                continue

            # 真派单。⚠ eFlow 的 Fiber 派单**时灵时不灵**（2026-10-26 实测：
            # 同一告警、同一 payload，有时建出 TT、有时接口回 success 却不建）。
            # 故不能「调一次算一次」，必须「调一次 → 回查 ttid → 没建出就重试」，
            # 正常状态最多 ASSIGN_MAX_ATTEMPTS 次。这是本任务能稳定出单的关键。
            # ttstatus 可疑时也照派（不阻断），只是预算收窄到 1 次 × 2 回查。
            max_attempts, verify_tries = assign_attempt_budget(status_suspect)
            res = None
            tt_no = ""
            last_err = ""
            for attempt in range(1, max_attempts + 1):
                res = client.assign_alarm(a, group, site_id, site_name)
                if not res.get("ok"):
                    last_err = res.get("error") or f"HTTP {res.get('status')} {res.get('message')}"
                    logger.warning("[Fiber] 派单接口失败 %s（第 %d/%d 次）：%s",
                                   akey, attempt, max_attempts, last_err)
                    if attempt < max_attempts:
                        time.sleep(ASSIGN_RETRY_DELAY)
                    continue
                tt_no = _verify_tt(akey, a, index, max_tries=verify_tries)
                if tt_no:
                    break
                last_err = "assign API returned success but no TT was created (ttid still empty)"
                logger.info("[Fiber] 第 %d/%d 次派单未建出 TT（%s），稍后重试",
                            attempt, max_attempts, akey)
                if attempt < max_attempts:
                    time.sleep(ASSIGN_RETRY_DELAY)

            if tt_no:
                base.update({"assign_status": "Y", "tt_no": tt_no,
                             "tt_proc_id": _s(_val(a.get("procid"))) or None})
                store.upsert_record(conn, base)
                out["assigned"] += 1
                # 本组组长已建出 TT → 同组其余告警跟随这个单号，不再单独建单
                group_tt[root_key] = tt_no
                if (site_id, site_name) not in group_sites.setdefault(root_key, []):
                    group_sites[root_key].append((site_id, site_name))
                pending_success.append({"alarm_key": akey, "alarm": a,
                                        "site_id": site_id, "site_name": site_name,
                                        "tt_no": tt_no,
                                        "group_key": root_key,
                                        "group_size": len(grp["members"]),
                                        "site_matched_by": trace.get("matched_by"),
                                        "site_note": fuzzy_note_en,
                                        "corr_note": corr_note_for_msg})
                logger.info("[Fiber] 派单成功 %s → TT %s（本组 %d 条告警）",
                            akey, tt_no, len(grp["members"]))
            else:
                # 重试预算用完仍未建出 TT：如实记失败（下一轮还会重试，因状态不是 Y）
                out["failed"] += 1
                reason = last_err
                reason_en = last_err
                if status_suspect:
                    # ttstatus 可疑 = eFlow 侧 ME 未关联站点（数据问题，不是 payload 问题）。
                    # 代码改不动它，只能让人去 eFlow 修 —— 故写清原因并通报一次。
                    reason = (f"eFlow 侧 ttstatus={tt_status}（ME 未关联站点），"
                              f"已尝试派单但未建出 TT：{last_err}")
                    reason_en = (f"eFlow ttstatus={tt_status} "
                                 f"(ME not bound to a site); assign was attempted "
                                 f"but no TT was created: {last_err}")
                base.update({"assign_status": "N", "last_error": reason})
                store.upsert_record(conn, base)
                if first_sight:
                    out["warnings"].append(
                        f"{akey} 派单失败（尝试 {max_attempts} 次）：{reason}")
                logger.warning("[Fiber] 派单失败 %s：%s", akey, reason)
                if status_suspect and _s(rec.get("send_status")) != "Y":
                    # 同一条只通报一次（send_status 抑制），否则每 5 分钟刷一条
                    pending_manual.append({
                        "alarm_key": akey, "alarm": a,
                        "reason": reason_en,
                        "hint": ["Note: this ME is not correctly bound to a site in eFlow",
                                 "      (site still holds the ME name, sitename is empty),",
                                 "      so eFlow will never create a TT for it.",
                                 "      Please bind the ME to a numeric site in eFlow,",
                                 "      or assign the TT manually. Once the binding is",
                                 "      fixed, this task retries automatically."],
                    })

        out["merged"] = merged

        # ---------- 4. WhatsApp 通报 ----------
        # ① 真派单成功的；② 自动派不了、需人工处理的（同一条只发一次）。
        for p in pending_success:
            # 合并派单：把本组涵盖的其它站点列进正文（排除本条自己的站点）
            gkey = p.get("group_key") or p["alarm_key"]
            others = [s for s in group_sites.get(gkey, [])
                      if s != (p["site_id"], p["site_name"])]
            messages.append({
                "tt_no": p["tt_no"] or p["alarm_key"],
                "text": build_message(p["alarm"], p["site_id"], p["site_name"],
                                      ASSIGN_GROUP, p["tt_no"], dry_run=False,
                                      site_note=p.get("site_note") or "",
                                      notes=[p.get("corr_note") or ""],
                                      impacted=others or None),
            })
        for p in pending_manual:
            messages.append({
                "tt_no": p["alarm_key"],
                "text": build_manual_message(p["alarm"], p["reason"],
                                             hint_lines=p.get("hint")),
            })

        if messages:
            out["samples"] = [{"alarm_key": m["tt_no"], "text": m["text"][:200]}
                              for m in messages[:SAMPLE_LIMIT]]
            wa_notify.check_channel_before_dispatch(out, len(messages), 30)
            disp = dispatch(messages, GROUPS)
            out["errors"].extend(disp.get("errors") or [])
            if not disp.get("ok"):
                out["warnings"].append(
                    f"WhatsApp 通报投递失败：{'; '.join(disp.get('errors') or [])}")
            else:
                rep = wait_for_job_result(disp.get("job_id"))
                out["errors"].extend(rep.get("errors") or [])
                confirmed_ok = rep.get("confirmed") and rep.get("ok")
                if confirmed_ok:
                    sent = {_s(x) for x in rep.get("sent") or []}
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for p in pending_success:
                        if p["tt_no"] in sent:
                            store.upsert_record(conn, {"alarm_key": p["alarm_key"],
                                                       "send_status": "Y", "send_time": now_str})
                            out["notified"] += 1
                    # 人工派单通报也标记已发，避免下一轮重复刷同一条
                    for p in pending_manual:
                        if p["alarm_key"] in sent:
                            store.upsert_record(conn, {"alarm_key": p["alarm_key"],
                                                       "send_status": "Y", "send_time": now_str})
                            out["manual_notified"] += 1
                elif rep.get("timed_out"):
                    out["warnings"].append("WhatsApp 通报未在超时内获确认（不判失败，请人工核对群消息）")

        out["success"] = not out["errors"]
        out["message"] = (f"演练" if DRY_RUN else f"派单 {out['assigned']} 单") + \
                         f"，跳过 {out['skipped']}，失败 {out['failed']}"
        return _finish()
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _verify_tt(alarm_key: str, alarm: Dict[str, Any], index: client.SiteIndex,
               max_tries: int = 3) -> str:
    """派单后回查该告警的 ttid，确认 TT 真的建出来。

    重新拉一次实时告警，按 alarmkey（或 id）找同一告警，取 `ttid`；
    非空且不是 'empty'/'None' 才算成功。失败返回空串。
    `max_tries` 次（每次间隔 2s）给 eFlow 处理时间；`ttstatus` 可疑时调用方传 2，
    避免每次回查都全量拉 6000+ 告警（实测约 2~3s/次）白烧时间。
    """
    target_id = _s(_val(alarm.get("id")))
    for attempt in range(max(1, int(max_tries))):
        if attempt:
            time.sleep(2)
        try:
            alarms = client.fetch_active_alarms()
        except Exception:  # noqa: BLE001
            continue
        for a in alarms:
            if (_s(_val(a.get("alarmkey"))) == alarm_key
                    or _s(_val(a.get("id"))) == target_id):
                tt = _s(_val(a.get("ttid")))
                if tt and tt.lower() not in ("empty", "none", "null", "-"):
                    return tt
        # 告警可能已从实时列表消失（清除），此时无法回查 → 再试一次再放弃
    return ""
