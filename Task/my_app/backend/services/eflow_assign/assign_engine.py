# -*- coding: utf-8 -*-
"""eFlow 自动派单的**共用引擎**（Fiber Break / 5G 站点告警共用）。

## 为什么要共用（2026-10-28 立项 5G 派单）

Fiber 与 5G 派单的**判定口径必须完全一致**：

* 「存续满 15 分钟才派」（下界）—— 业务口径，改一处就得改两处；
* 「触发窗口 180 分钟」（上界）；
* 关联判定三态（hit / none / undetermined）；
* 同一次故障合并派单；
* eFlow 派单「时灵时不灵」→ 重试 + 回查 ttid 才算成功；
* 演练模式（dry_run）；演练记录 D 在关掉 dry_run 后必须重新处理；
* WhatsApp 通报正文**一律英文**（2026-10-27 如意要求）。

这些规则每一条都是踩坑换来的（实测教训见各处注释）。写成两份必然漂移，
故抽到本模块，业务线只提供**差异**：

| 差异点 | Fiber | 5G |
| --- | --- | --- |
| 告警码 | 4758 | 200201001/18/41/43/60（**多个**，可配） |
| 站点字段 | `site` 是 ME 名 → 需 cmdb 解析 | `site` 已是数字站号、`sitename` 已是站名 |
| 合并判据 | 按**时间窗**（同一次断纤） | 按**站点 + 时间窗**（同一 gNB 多小区） |
| restype | 不限 | `zte.ran.gnodeb` 等（服务端过滤用） |

## `AssignContext` —— 判定口径的唯一载体

所有判定函数都从 `ctx` 取口径参数，**不读模块级全局**。这样：
* 业务线模块只装配一次 ctx（从自己的配置读），口径改动只改底座一处；
* 单测可用不同 ctx 造不同边界，不必 importlib.reload 模块；
* 5G 与 Fiber 的口径**必然一致**（同一个 ctx 字段、同一个判定函数）。

## 设计约束

* **纯函数优先**：判定、渲染、分组全是纯函数（只读入参）→ 可单测、不触网；
* **不吞错**：失败必须落状态表 + 留痕，不能静默漏派；
* **宁可不派，不可错派**：站点解析不确定 → 不派 + 通报人工。
"""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from backend.services.eflow_assign import eflow_assign_client as client
from backend.services.eflow_assign.assign_config import norm_code

logger = logging.getLogger("eflow_assign_engine")

SAMPLE_LIMIT = 5

# due_verdict 的几种结论（主循环据此分桶计数，便于排障区分「等一等」与「真有问题」）
DUE_YES = "due"           # 命中且在 [下界, 上界] 区间内 → 派单
DUE_TOO_NEW = "too_new"   # 存续时长 < min_age_minutes → 还没到派单时机，等下轮
DUE_TOO_OLD = "too_old"   # 存续时长 > window_minutes → 太老，不派
DUE_NO_CODE = "no_code"   # 告警码不命中白名单
DUE_NO_TIME = "no_time"   # 取不到告警升起时间

# 关联判定三态
CORRELATION_HIT = "hit"
CORRELATION_NONE = "none"
CORRELATION_UNDETERMINED = "undetermined"

_SITE_PLACEHOLDERS = ("--", "-", "empty", "none", "null")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                      re.IGNORECASE)


@dataclass
class AssignContext:
    """派单判定的**全部口径参数**（业务线从自己的配置装配一次）。

    ⚠ 这里的字段是**判定口径的唯一定义处**：时间边界、关联码、目标组、演练开关、
    重试预算。改口径只改这里 + 对应业务线的配置解析，不在别处再写一遍。
    """

    # 触发派单的告警码白名单（**支持多个**，归一化后的文本集合）
    alarm_codes: Set[str] = field(default_factory=set)
    # 关联告警码：同站同窗口已有这些码时不再派单（避免重复派单）
    correlation_codes: Set[str] = field(default_factory=set)
    # 关联判定时间窗（分钟）
    correlation_window_minutes: int = 60
    # 触发窗口（分钟）—— **上界**：太老的告警不派
    window_minutes: int = 180
    # 派单等待时长（分钟）—— **下界**：存续满 N 分钟才派
    min_age_minutes: int = 15
    # 合并派单时间窗（分钟）。0 = 关闭合并（每条告警各派一单）
    group_window_minutes: int = 10
    # 派单目标用户组名（从 eFlow 用户组列表按名解析 groupId）
    assign_group: str = "ZTE_NOC_FO"
    # 演练模式：true = 只匹配+记录，不调派单接口
    dry_run: bool = True
    # WhatsApp 目标群组
    groups: List[str] = field(default_factory=list)
    # 站点名近似匹配（cmdb 与网管命名不一致时的兜底，带歧义保护）
    site_fuzzy_enabled: bool = True
    site_fuzzy_threshold: float = 0.9
    # 派单重试预算（eFlow 派单时灵时不灵，必须重试到 TT 真建出）
    assign_max_attempts: int = 3
    assign_retry_delay: float = 3.0
    # 通报抬头（群里每条通报都带）与日志前缀
    push_title: str = "TT Assign Notification"
    tag: str = "Assign"
    # 合并派单时正文里对「同一故障」的称呼（业务线各叫各的：
    # Fiber 是「同一次断纤」，5G 是「同一次站点故障」）
    outage_label: str = "the same outage"

    @property
    def group_window_ms(self) -> int:
        """合并派单时间窗（毫秒）。"""
        return max(0, int(self.group_window_minutes)) * 60 * 1000


def val(v: Any) -> Any:
    """eFlow 告警字段是 {value, displayname, ...} 对象；统一取 value。"""
    if isinstance(v, dict):
        return v.get("value")
    return v


def s(val_: Any) -> str:
    """转字符串并去空白；None → ''。"""
    return "" if val_ is None else str(val_).strip()


def epoch_ms(value: Any) -> Optional[int]:
    """毫秒时间戳 → int；解析不了返回 None。"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def is_uuid(value: str) -> bool:
    """UUID 不是站点名：`mename` 常是 UUID（实测 6784c258-…），别拿它当站名键。"""
    return bool(_UUID_RE.match(str(value or "").strip()))


def alarm_site_keys(alarm: Dict[str, Any]) -> Set[str]:
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
    keys: Set[str] = set()

    for cand in (s(val(alarm.get("site_id"))), s(val(alarm.get("site")))):
        if cand.isdigit():
            keys.add("id:" + cand)

    for cand in (s(val(alarm.get("site_name"))), s(val(alarm.get("sitename")))):
        if cand and cand.lower() not in _SITE_PLACEHOLDERS and not is_uuid(cand):
            keys.add("name:" + cand.lower())

    me = s(val(alarm.get("mename")) or val(alarm.get("site")))
    if me:
        if me.isdigit():
            keys.add("id:" + me)
        else:
            derived = client.site_name_from_me(me)
            if (derived and derived.lower() not in _SITE_PLACEHOLDERS
                    and not is_uuid(derived)):
                keys.add("name:" + derived.lower())

    return keys


def occur_ms(alarm: Dict[str, Any]) -> Optional[int]:
    """告警升起时间（毫秒）：优先 `alarmraisedtime`，回退 `servertime`。"""
    return epoch_ms(val(alarm.get("alarmraisedtime")) or val(alarm.get("servertime")))


def alarm_key_of(alarm: Dict[str, Any]) -> str:
    """告警唯一键：优先 `alarmkey`，回退 `id`（与主流程取键口径一致）。"""
    return s(val(alarm.get("alarmkey"))) or s(val(alarm.get("id")))


def age_minutes(alarm: Dict[str, Any], now_ms: int) -> Optional[float]:
    """告警升起至今的分钟数；取不到升起时间返回 None。

    用 `alarmraisedtime`（无则 `servertime`）。负值（上游时间跑在将来）钳到 0，
    避免时钟漂移把「刚升起的告警」判成「已存续很久」。
    """
    occ = occur_ms(alarm)
    if occ is None:
        return None
    return max(0.0, (now_ms - occ) / 60000.0)


def due_verdict(ctx: AssignContext, alarm: Dict[str, Any],
                now_ms: int) -> Tuple[str, Optional[float]]:
    """判定该告警本轮是否该派单 → (结论, 存续分钟数)。

    ## 两条边界（2026-10-27 业务口径）

    * **下界** `min_age_minutes`（默认 15）：告警升起后必须先存在满 N 分钟才派单。
      业务原话「告警发生到选择超过 15 分钟，才要指派单子和发送 WhatsApp 消息」——
      即**不是一升起就派**，而是等满 15 分钟再派。留这段时间给短时闪断自然清除，
      避免建出一堆瞬时告警的无效 TT。配 0 = 恢复「一升起就派」。
    * **上界** `window_minutes`（默认 180）：太老的告警不再派（防上线瞬间把积压的
      历史未清除告警一次性全派出去）。

    ⚠ 下界只挡「太新」，不挡「太老」；两条独立生效。

    ⚠ **这是派单判定的唯一真相源** —— 任何改动只改这里，别在别处再写一遍边界判断。
    """
    if norm_code(val(alarm.get("alarmcode"))) not in ctx.alarm_codes:
        return DUE_NO_CODE, None
    age = age_minutes(alarm, now_ms)
    if age is None:
        return DUE_NO_TIME, None
    if age < ctx.min_age_minutes:
        return DUE_TOO_NEW, age
    if age > ctx.window_minutes:
        return DUE_TOO_OLD, age
    return DUE_YES, age


def upstream_tt(alarm: Dict[str, Any]) -> str:
    """告警上游（eFlow 自身派单规则）已带的 TT 编号；没有则返回空串。

    生产上 eFlow 的 `assign_rule` 会给部分告警先建 TT，这些告警在我方
    状态表里没有记录，只看状态表就会重复派单。判定为纯函数便于单测。
    """
    tt = s(val(alarm.get("ttid")))
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

    实测教训（2026-10-27 切生产首轮就撞上）：全库 6669 条告警里 `ttstatus=2`
    只有 5 条，共同特征是 **`site` 是 ME 名、`sitename` 为 `--`/None** ——
    ME 未在 eFlow 侧正确关联站点。对这类告警派单，接口回
    `200 manual assign succeed.`，但 `ttid` 永远为空、`ttstatus` 不变，
    重试 3 次 + 人工单次调用全部失败（实测白跑 ~70 秒）。

    `0` = UnAssigned；`1` = Assigned（已派，前面按 ttid 已跳过）；`2`/`4`/`5`/`6`
    视为可疑（仍会尝试，但只用最小预算）。
    """
    txt = s(val(ttstatus))
    return not txt or txt == "0"


def assign_attempt_budget(ctx: AssignContext, status_suspect: bool) -> Tuple[int, int]:
    """本轮派单预算 → (接口尝试次数, 每次回查次数)。

    * 正常告警：`ctx.assign_max_attempts`(默认 3) × 3 次回查 —— eFlow 派单
      「时灵时不灵」，必须重试到 TT 真建出为止；
    * `ttstatus` 可疑（ME 未关联站点）：1 次尝试 × 2 次回查 —— 仍要试（业务要求不可
      被挡住），但实测这类多半回 succeed 不建 TT，按 3 次重试白烧 70s 不划算。
    """
    if status_suspect:
        return 1, 2
    return max(1, ctx.assign_max_attempts), 3


def correlation_verdict(ctx: AssignContext, alarm: Dict[str, Any],
                         all_alarms: List[Dict[str, Any]]
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
    if not ctx.correlation_codes:
        return CORRELATION_NONE, None, "未启用关联告警码"

    keys = alarm_site_keys(alarm)
    if not keys:
        return (CORRELATION_UNDETERMINED, None,
                "告警侧站点信息不足（site/sitename/mename 均解析不出站点键）")

    occ = occur_ms(alarm)
    win_ms = ctx.correlation_window_minutes * 60 * 1000
    blind = 0
    for other in all_alarms:
        if norm_code(val(other.get("alarmcode"))) not in ctx.correlation_codes:
            continue
        o_keys = alarm_site_keys(other)
        if not o_keys:
            blind += 1
            continue
        if not (keys & o_keys):
            continue
        o_occ = occur_ms(other)
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

    ordered = sorted(alarms, key=lambda x: (occur_ms(x) is None, occur_ms(x) or 0,
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
        occ = occur_ms(a)
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


def verify_tt(alarm_key: str, alarm: Dict[str, Any], max_tries: int = 3,
              sleep_fn: Callable[[float], None] = time.sleep) -> str:
    """派单后回查该告警的 ttid，确认 TT 真的建出来。

    ## 为什么用「按 id 单查」而不是全量重拉（2026-10-28 实测）

    Fiber 原实现每轮回查都**全量重拉**实时告警（实测 6752 条 / 4.4s），
    单条告警最多重查 3 次 ≈ 白烧 13 秒。实测 `secondarycondition={"id": ...}`
    单查可用：**1 条 / 0.06s**（同一告警按 `alarmkey` 查则 HTTP 400，只能用 `id`）。

    ⚠ **回查逻辑必须在「全量拉取」下同样正确** —— 若 eFlow 侧哪天不再支持
    `secondarycondition`（会退化成返回全量），按 id 过滤仍能找回目标告警，
    只是慢。故两条路径都实现，按 id 单查为快路径、全量为兜底。

    `max_tries` 次（每次间隔 2s）给 eFlow 处理时间；`ttstatus` 可疑时调用方传 2，
    避免每次回查都全量拉 6000+ 告警（实测约 2~3s/次）白烧时间。
    """
    target_id = s(val(alarm.get("id")))
    for attempt in range(max(1, int(max_tries))):
        if attempt:
            sleep_fn(2)
        try:
            rows = client.fetch_alarm_by_id(target_id) if target_id else []
            if not rows:
                # 单查拿不到 → 兜底全量拉取后按 id/alarmkey 过滤
                rows = client.fetch_active_alarms()
        except Exception:  # noqa: BLE001
            continue
        for a in rows:
            if (s(val(a.get("alarmkey"))) == alarm_key
                    or s(val(a.get("id"))) == target_id):
                tt = s(val(a.get("ttid")))
                if tt and tt.lower() not in ("empty", "none", "null", "-"):
                    return tt
        # 告警可能已从实时列表消失（清除），此时无法回查 → 再试一次再放弃
    return ""


def render_message(ctx: AssignContext, alarm: Dict[str, Any],
                   site_id: str, site_name: str,
                   tt_no: str, dry_run: bool,
                   site_note: str = "",
                   notes: Optional[List[str]] = None,
                   impacted: Optional[List[Tuple[str, str]]] = None,
                   extra_lines: Optional[List[Tuple[str, str]]] = None,
                   ) -> str:
    """按需求格式渲染通报：TT Title = SITE ID_Site name_Alarm Code。

    TT 的真正标题由 eFlow 自动生成（`<site>.[<site name>]<告警名>`），接口不接受
    自定义标题；故群里按需求格式通报，并附上真实 TT 编号。

    ⚠ **群通报正文一律英文**（2026-10-27 如意要求「通报默认使用英文」）。
    故调用方传入的 `site_note` / `notes` / `extra_lines` 必须已是英文；
    中文只留在日志与状态表里。

    `site_note` 非空时在末尾追加提示（站点名近似匹配时用，提醒核对 cmdb 命名）；
    `notes` 是其它需要让人看见的留痕（如「99933 关联无法判定，已按无关联派单」）。

    `impacted` 是**同一次故障里被本 TT 一并覆盖的其它站点**：`[(site_id, site_name), ...]`，
    已去重，**不含**本条自己的站点。非空时在正文追加一段，说明「这一单实际涵盖 N 个站点」，
    避免群里误以为只坏了这一个站。

    `extra_lines` 是业务线自有的附加行（如 5G 的小区列表），格式 `[(标签, 值), ...]`。
    """
    code = norm_code(val(alarm.get("alarmcode")))
    code_name = s(val(alarm.get("codename")) or val(alarm.get("alarm_title")))
    occ = occur_ms(alarm)
    occ_txt = datetime.fromtimestamp(occ / 1000).strftime("%Y-%m-%d %H:%M:%S") if occ else "-"
    title = f"{site_id}_{site_name}_{code}"
    lines = [ctx.push_title, ""]
    lines.append(f"TT Title : {title}")
    lines.append(f"Site ID  : {site_id}")
    lines.append(f"Site Name: {site_name}")
    lines.append(f"Alarm    : {code} {code_name}".rstrip())
    lines.append(f"Occurred : {occ_txt}")
    me_name = s(val(alarm.get("mename")) or val(alarm.get("site")))
    if me_name:
        lines.append(f"ME       : {me_name}")
    for label, value in (extra_lines or []):
        if value:
            lines.append(f"{label:<8}: {value}")
    if tt_no:
        lines.append(f"TT No.   : {tt_no}")
    lines.append(f"Assigned : {ctx.assign_group}")
    if impacted:
        # 合并派单：说清「这一单实际涵盖多个站点」，否则群里会以为只坏了一个站
        lines.append("")
        lines.append(f"This TT covers {len(impacted) + 1} sites from {ctx.outage_label}:")
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


def render_manual_message(ctx: AssignContext, alarm: Dict[str, Any], reason: str,
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
    code = norm_code(val(alarm.get("alarmcode")))
    code_name = s(val(alarm.get("codename")) or val(alarm.get("alarm_title")))
    occ = occur_ms(alarm)
    occ_txt = datetime.fromtimestamp(occ / 1000).strftime("%Y-%m-%d %H:%M:%S") if occ else "-"
    me_name = s(val(alarm.get("mename")) or val(alarm.get("site")))

    lines = [ctx.push_title, ""]
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


def assign_with_retry(ctx: AssignContext, alarm: Dict[str, Any],
                      group: Dict[str, Any],
                      site_id: str, site_name: str,
                      alarm_key: str,
                      max_attempts: int, verify_tries: int,
                      sleep_fn: Callable[[float], None] = time.sleep,
                      ) -> Tuple[str, str]:
    """派单 + 重试 + 回查 → (tt_no, last_error)。

    ⚠ eFlow 的派单**时灵时不灵**（2026-10-26 实测：同一告警、同一 payload，
    有时建出 TT、有时接口回 success 却不建）。故不能「调一次算一次」，
    必须「调一次 → 回查 ttid → 没建出就重试」，最多 `max_attempts` 次。

    这是本任务能稳定出单的关键。
    """
    tt_no = ""
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        res = client.assign_alarm(alarm, group, site_id, site_name)
        if not res.get("ok"):
            last_err = res.get("error") or f"HTTP {res.get('status')} {res.get('message')}"
            logger.warning("[%s] 派单接口失败 %s（第 %d/%d 次）：%s",
                           ctx.tag, alarm_key, attempt, max_attempts, last_err)
            if attempt < max_attempts:
                sleep_fn(ctx.assign_retry_delay)
            continue
        tt_no = verify_tt(alarm_key, alarm, max_tries=verify_tries, sleep_fn=sleep_fn)
        if tt_no:
            return tt_no, ""
        last_err = "assign API returned success but no TT was created (ttid still empty)"
        logger.info("[%s] 第 %d/%d 次派单未建出 TT（%s），稍后重试",
                    ctx.tag, attempt, max_attempts, alarm_key)
        if attempt < max_attempts:
            sleep_fn(ctx.assign_retry_delay)
    return "", last_err


def group_members(groups: Dict[str, Dict[str, Any]], root_key: str,
                  fallback: Sequence[Dict[str, Any]] = (),
                  ) -> List[Dict[str, Any]]:
    """取组长所在组的全部成员（不含组长自身）。

    用于「派单成功后才知道该组涵盖哪些站点」的场景 —— 组长先建单，
    成员随后合并进来。
    """
    grp = groups.get(root_key) or {"root": root_key, "members": list(fallback)}
    return [m for m in grp["members"] if alarm_key_of(m) != root_key]
