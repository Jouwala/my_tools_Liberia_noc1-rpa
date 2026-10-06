"""P1 推送的**单据来源层**：实时查单、本地镜像兜底、三层合并。

从 `tt_alarm_whatsapp_service` 拆出（2026-10-05，该文件重写后越过 500 行上限，
且「去哪拿这张单的最新数据」与「拿到了之后怎么决策/发送」本就是两个职责）。

## 一张单的三层来源（越靠前越新鲜、越可信）

| 层 | 来源 | 新鲜度 | 局限 |
| --- | --- | --- | --- |
| 实时 | eFlow `base/list` 分页遍历（`fetch_tt_live_batch`） | 秒级 | 按最近修改倒序最多扫 4000 行，**停滞多日的老单扫不到** |
| 镜像 | 本地 `eflow_tt`（`eflow_sync` 每小时 :22 刷新） | ≤1 小时 | 对「一直没更新的停滞单」反而**准确**（它没变过） |
| 触发行 | `realtime_alarm` 行（`tt_alarm_trigger.fetch_triggered_tts`） | ≤30 分钟 | 只有告警侧字段（站点/告警码/升起时间），无工单详情 |

使用规则：
  * 决策用的 `last_modified_time`：实时 > 镜像 > 日志记录 —— 实时查得到就用最新的；
  * 实时查不到（老单超出扫描窗口）→ 镜像兜底，停滞判断无损；
  * 渲染行 = 触发行打底 ← 镜像 ← 实时逐层覆盖（触发行补齐站点/告警码身份字段，
    实时行提供最新状态）；发生时间缺省时退回触发行的 `alarm_raised_time`。

实时查单**失败**（网络/登录/接口异常）时返回空 dict，调用方整批回退镜像 ——
宁可降级也不能因为查单失败漏推告警。
"""
import logging
from typing import Any, Dict, List, Optional

from backend.services.tt_alarm_message import s as _s

logger = logging.getLogger("tt_alarm_whatsapp")

# 本地 eflow_tt 镜像要读的列（与表实际列求交集，兼容不同同步版本的列差异）。
_TT_COLUMNS = (
    "tt_no", "site_id", "site_name", "title", "alarm_code", "alarm_severity",
    "alarm_type", "alarm_category", "alarm_description", "ticket_severity", "status",
    "alarm_occur_time", "alarm_clear_time", "created_time", "last_modified_time",
    "region_level1", "site_type", "site_information", "asset_id", "impacted_service",
    "down_site_count", "site_outage", "vip_site",
    "ne_name", "ne_id", "specific_problem",
    "sub_alarm_ne_name", "sub_alarm_ne_ip",
    "sub_alarm_name", "alarm_reason_type", "domain",
)


def _is_sqlite(conn) -> bool:
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _existing_columns(conn, table: str) -> set:
    if _is_sqlite(conn):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
        "AND table_schema = ANY(current_schemas(false))",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def mirror_rows(conn, tt_nos: List[str]) -> Dict[str, Dict[str, Any]]:
    """从本地 eflow_tt 镜像批量取单（实时查单未命中时的兜底数据源）。

    返回 {tt_no: 行}；表/列缺失时返回 {}（镜像不可用不是致命错误，
    实时层通常已覆盖绝大多数场景）。
    """
    nos = [n for n in tt_nos if n]
    if not nos:
        return {}
    try:
        from backend.dialect_helpers import list_table_names
        if "eflow_tt" not in {str(t).lower() for t in list_table_names(conn)}:
            return {}
        cols = [c for c in _TT_COLUMNS if c in _existing_columns(conn, "eflow_tt")]
        if not cols:
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(nos), 200):
            chunk = nos[i:i + 200]
            marks = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"SELECT {', '.join(cols)} FROM eflow_tt WHERE UPPER(tt_no) IN ({marks})",
                tuple(chunk),
            )
            names = [d[0] for d in cur.description]
            for r in cur.fetchall():
                row = dict(zip(names, r))
                no = _s(row.get("tt_no")).upper()
                if no:
                    out[no] = row
        return out
    except Exception:  # noqa: BLE001
        # 镜像兜底自身出任何问题都不能弄坏主流程（实时层/日志记录还在）
        logger.warning("[TTAlert] 镜像兜底查询失败（按无镜像处理）", exc_info=True)
        return {}


def live_tt_rows(tt_nos: List[str]) -> Dict[str, Dict[str, Any]]:
    """实时回 eFlow 批量查单（失败返回 {}，调用方回退镜像 —— 宁可降级不漏推）。

    延迟导入：`eflow_data_mapper` → `eflow_api_client` 的 import 链有配置读盘
    等副作用，不宜在每个 worker 进程 import 本模块时都背上来。
    """
    try:
        from backend.services.eflow_data_mapper import fetch_tt_live_batch
        return fetch_tt_live_batch(tt_nos) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("[TTAlert] 实时查单失败，全部回退本地镜像: %s", e, exc_info=True)
        return {}


def merged_render_row(trig: Dict[str, Any], mirror: Optional[Dict[str, Any]],
                      live: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """合并三层来源为渲染行：触发行打底 → 镜像 → 实时（越右越新鲜越优先）。"""
    merged = dict(trig)
    if mirror:
        merged.update(mirror)
    if live:
        merged.update(live)
    merged.setdefault("tt_no", trig.get("tt_no"))
    # 渲染与横幅要用的发生时间：实时/镜像的 alarm_occur_time 优先，
    # 缺失时退回触发行的告警升起时间（alarmraisedtime 的可读形式）。
    if not _s(merged.get("alarm_occur_time")):
        merged["alarm_occur_time"] = trig.get("alarm_raised_time")
    return merged


def cleared_rows(conn, tt_nos) -> Dict[str, Dict[str, Any]]:
    """从 `eflow_tt` 取**已清除**的单（`alarm_clear_time` 非空）→ {tt_no: 行}。

    为什么单独一个查询（2026-10-06）：结束汇总邮件要判断"这单结束了没"，而
    **告警一清除就会从 `realtime_alarm` 消失**（实测 4 个已清除单在实时表里
    0 命中），所以主循环那份活跃告警候选永远看不到它们。这里直接回 `eflow_tt`
    查 —— 那是清除状态的权威来源，与告警是否还活跃无关。

    取多列而非 COUNT：汇总正文要用 alarm_occur_time / alarm_clear_time /
    created_time / last_modified_time 算时间轴与总历时。
    查询失败返回空 dict（调用方本轮不发汇总，下轮再试，不影响推送）。
    """
    out: Dict[str, Dict[str, Any]] = {}
    ids = [str(t) for t in (tt_nos or []) if t]
    if not ids:
        return out
    cols = ("tt_no, ticket_severity, site_id, site_name, title, alarm_code, "
            "alarm_occur_time, alarm_clear_time, created_time, last_modified_time")
    try:
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            marks = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"SELECT {cols} FROM eflow_tt "
                f"WHERE tt_no IN ({marks}) "
                f"AND alarm_clear_time IS NOT NULL AND alarm_clear_time != ''",
                tuple(chunk),
            )
            names = [d[0] for d in cur.description]
            for r in cur.fetchall():
                row = dict(zip(names, r))
                out[str(row["tt_no"])] = row
    except Exception as e:  # noqa: BLE001
        logger.warning("[TTAlert] 查已清除单失败（汇总邮件本轮跳过）: %s", e)
        return {}
    return out
