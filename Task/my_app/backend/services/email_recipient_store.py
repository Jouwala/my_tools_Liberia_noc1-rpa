"""
email_recipient_store.py - 邮件收件人名单集中存储模块
====================================================

背景：各邮件任务原先在各自代码里直接读取收件人名单
（远程 FTP / UNC 共享 / 本地 email_reports 下的 ss_email.txt + cc_email.txt）。
本模块把名单来源统一收口到「Settings → 邮件收件人」页签维护，与
credential_store.py 的凭据管理一致：

- 用户在 Settings 页签保存的收件人写入 db/app.db 的 email_recipients 表；
- 任务发送时优先用 DB 保存值；未保存（DB 无记录）时，实时回退读取原
  默认名单文件（远程 FTP / UNC / 本地），满足"默认值仍从原地方读取"。

读取优先级：显式传入 to/cc（测试覆盖） > 数据库保存值 > 原默认名单文件。
缓存策略：进程内缓存 30 秒（与凭据一致），改完最迟 30 秒生效，无需重启。

用法:
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("packet_loss_email", to, cc)
"""

import os
import re
import time
import sqlite3
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# db/app.db：backend/services -> backend -> my_app
DB_PATH = Path(__file__).resolve().parents[2] / "db" / "app.db"

# 进程内缓存 TTL（秒）
CACHE_TTL = float(os.environ.get("EMAIL_RECIPIENT_CACHE_TTL", "30"))

_cache: dict = {}
_cache_lock = threading.Lock()


# ============================================================
# 默认名单读取（轻量，仅读文件，不加载 exchangelib/playwright 等重型依赖）
# 每个 default_loader 在调用时才懒 import 对应模块，避免本模块被导入时
# 连带触发重型模块的副作用。
# ============================================================
def _parse_addrs(text: str) -> List[str]:
    """从名单文本解析邮箱地址（支持 ; , 空白 分隔；忽略空行与 # 注释；去重）。"""
    out: List[str] = []
    if not text:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for raw in re.split(r"[;,\s]+", line):
            a = raw.strip()
            if a and a not in out:
                out.append(a)
    return out


def _read_local_file(path) -> List[str]:
    """读取本地名单文件（ss_email.txt / cc_email.txt）。文件缺失返回空列表。"""
    try:
        p = Path(path)
        if not p.is_file():
            return []
        return _parse_addrs(p.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception as e:
        logger.warning("[EMAIL-RCPT] 读取本地名单失败 %s: %s", path, e)
        return []


def _read_remote_dir(email_dir_remote: str) -> Tuple[List[str], List[str]]:
    """读取远程 FTP 名单目录下的 ss_email.txt / cc_email.txt。"""
    import backend.services.remote_ftp as rf
    try:
        ss = rf.read_text(f"{email_dir_remote}/ss_email.txt")
        cc = rf.read_text(f"{email_dir_remote}/cc_email.txt")
        return rf.parse_addresses(ss or ""), rf.parse_addresses(cc or "")
    except Exception as e:
        logger.warning("[EMAIL-RCPT] 读取远程名单失败 %s: %s", email_dir_remote, e)
        return [], []


def _read_unc_dir(email_dir_unc: str) -> Tuple[List[str], List[str]]:
    """读取 UNC 共享名单目录下的 ss_email.txt / cc_email.txt。"""
    try:
        ss = _read_local_file(Path(email_dir_unc) / "ss_email.txt")
        cc = _read_local_file(Path(email_dir_unc) / "cc_email.txt")
        return ss, cc
    except Exception as e:
        logger.warning("[EMAIL-RCPT] 读取 UNC 名单失败 %s: %s", email_dir_unc, e)
        return [], []


# ---- 各默认来源 loader（懒 import 对应模块常量）----
def _default_liberia() -> Tuple[List[str], List[str]]:
    from backend.services.liberia_email_report import SS_EMAIL_FILE, CC_EMAIL_FILE
    return _read_local_file(SS_EMAIL_FILE), _read_local_file(CC_EMAIL_FILE)


def _default_ms_sla() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import _MS_SLA_EMAIL
    return _read_remote_dir(_MS_SLA_EMAIL)


def _default_sp() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import _SP_EMAIL_UNC
    return _read_unc_dir(_SP_EMAIL_UNC)


def _default_sp_details() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import _SP_DETAILS_DEFAULT_TO, _SP_DETAILS_DEFAULT_CC
    return _parse_addrs(_SP_DETAILS_DEFAULT_TO), _parse_addrs(_SP_DETAILS_DEFAULT_CC)


def _default_sp_details_files() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import (
        _SP_DETAILS_FILES_DEFAULT_TO,
        _SP_DETAILS_FILES_DEFAULT_CC,
    )
    return _parse_addrs(_SP_DETAILS_FILES_DEFAULT_TO), _parse_addrs(_SP_DETAILS_FILES_DEFAULT_CC)


def _default_sp_material() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import (
        _SP_MATERIAL_DEFAULT_TO,
        _SP_MATERIAL_DEFAULT_CC,
    )
    return _parse_addrs(_SP_MATERIAL_DEFAULT_TO), _parse_addrs(_SP_MATERIAL_DEFAULT_CC)


def _default_ume_in_osg() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import (
        _UME_IN_OSG_DEFAULT_TO,
        _UME_IN_OSG_DEFAULT_CC,
    )
    return _parse_addrs(_UME_IN_OSG_DEFAULT_TO), _parse_addrs(_UME_IN_OSG_DEFAULT_CC)


def _default_ran() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import _RAN_EMAIL
    return _read_remote_dir(_RAN_EMAIL)


def _default_packet_loss() -> Tuple[List[str], List[str]]:
    from backend.services.kpi_email_report import _PL_EMAIL
    return _read_remote_dir(_PL_EMAIL)


def _default_ipran() -> Tuple[List[str], List[str]]:
    from backend.services.ipran_chart_service import SS_EMAIL_FILE, CC_EMAIL_FILE
    return _read_local_file(SS_EMAIL_FILE), _read_local_file(CC_EMAIL_FILE)


def _default_ccn() -> Tuple[List[str], List[str]]:
    from backend.services.ccn_free_rating_chart_service import SS_EMAIL_FILE, CC_EMAIL_FILE
    return _read_local_file(SS_EMAIL_FILE), _read_local_file(CC_EMAIL_FILE)


def _default_fw_kpi() -> Tuple[List[str], List[str]]:
    from backend.services.fw_kpi.fw_kpi_services import SS_EMAIL_FILE, CC_EMAIL_FILE
    return _read_local_file(SS_EMAIL_FILE), _read_local_file(CC_EMAIL_FILE)


def _default_battery() -> Tuple[List[str], List[str]]:
    from backend.services.battary_kpi_fetch.battery_kpi_service import BATT_EMAIL_REMOTE
    return _read_remote_dir(BATT_EMAIL_REMOTE)


def _default_tt_alarm() -> Tuple[List[str], List[str]]:
    """P1 TT 通报邮件默认收件人（用户 2026-10-06 指定）。

    固定默认，不读名单文件 —— 该任务本是 WhatsApp 推送，邮件是附加通道，
    没有既有的 ss/cc 名单来源。用户在「Settings → 邮件收件人」改过即以页面值优先。
    """
    return ["dong.xinmin@zte.com.cn"], []


# ============================================================
# 收件人组注册表（key、显示名、默认来源 loader）
# key 与 task_registry.py 中各邮件任务的 task_id 对齐（liberia 1h/8h 共用一组）。
# ============================================================
EMAIL_RECIPIENT_GROUPS = [
    {
        "key": "liberia_email",
        "name": "Liberia 宕站报告邮件 (1h/8h)",
        "name_en": "Liberia Site-Down Report Email (1h/8h)",
        "default_loader": _default_liberia,
    },
    {
        "key": "kpi_ms_contract",
        "name": "MS Contract KPIs 日报邮件",
        "name_en": "MS Contract KPIs Daily Report Email",
        "default_loader": _default_ms_sla,
    },
    {
        "key": "kpi_ms_wo_sla",
        "name": "MS WOs SLA 日报邮件",
        "name_en": "MS WOs SLA Daily Report Email",
        "default_loader": _default_ms_sla,
    },
    {
        "key": "kpi_sp_spareparts",
        "name": "SpareParts 备件报表邮件",
        "name_en": "SpareParts Report Email",
        "default_loader": _default_sp,
    },
    {
        "key": "kpi_sp_consumables",
        "name": "Comsumables 耗材报表邮件",
        "name_en": "Comsumables Report Email",
        "default_loader": _default_sp,
    },
    {
        "key": "sp_email_details",
        "name": "SP 备件明细报表邮件",
        "name_en": "SP Spare Parts Details Report Email",
        "default_loader": _default_sp_details,
    },
    {
        "key": "sp_details_files",
        "name": "SP 备件明细分文件邮件 (6 份 xlsx 逐个发送)",
        "name_en": "SP Spare Parts Details Files Email (6 xlsx, one per email)",
        "default_loader": _default_sp_details_files,
    },
    {
        "key": "sp_online_report",
        "name": "SP 在线未关闭单报表邮件",
        "name_en": "SP Online Open Tickets Report Email",
        "default_loader": _default_sp,
    },
    {
        "key": "sp_material_report",
        "name": "SP 物料库存与消耗报表邮件",
        "name_en": "SP Material Stock & Consumption Report Email",
        "default_loader": _default_sp_material,
    },
    {
        "key": "kpi_ran_availability",
        "name": "MS Network Availability 日报邮件",
        "name_en": "MS Network Availability Daily Report Email",
        "default_loader": _default_ran,
    },
    {
        "key": "ume_in_osg_report",
        "name": "客户业务 KPI + OSG 周报邮件",
        "name_en": "Customer Service KPI + OSG Weekly Report Email",
        "default_loader": _default_ume_in_osg,
    },
    {
        "key": "packet_loss_email",
        "name": "Packet Loss 丢包日报邮件",
        "name_en": "Packet Loss Daily Report Email",
        "default_loader": _default_packet_loss,
    },
    {
        "key": "ipran_m6k_chart_email",
        "name": "IP RAN M6K-FW 图表邮件",
        "name_en": "IP RAN M6K-FW Chart Email",
        "default_loader": _default_ipran,
    },
    {
        "key": "ccn_free_rating_chart_email",
        "name": "CNN Free Rating 图表邮件",
        "name_en": "CNN Free Rating Chart Email",
        "default_loader": _default_ccn,
    },
    {
        "key": "fw_kpi_sync",
        "name": "FW 吞吐 KPI 图表邮件",
        "name_en": "FW Throughput KPI Chart Email",
        "default_loader": _default_fw_kpi,
    },
    {
        "key": "battery_email",
        "name": "电池 KPI 邮件",
        "name_en": "Battery KPI Email",
        "default_loader": _default_battery,
    },
    {
        # P1 TT 通报邮件的收件人（2026-10-06 新增，原为 WhatsApp 推送的附加邮件通道）
        "key": "tt_alarm_p1_email",
        "name": "P1 TT 告警通报邮件",
        "name_en": "P1 TT Alarm Progress Email",
        "default_loader": _default_tt_alarm,
    },
]

_GROUP_INDEX = {g["key"]: g for g in EMAIL_RECIPIENT_GROUPS}


# ============================================================
# 数据库访问（独立 sqlite3，与 credentials 表同库）
# ============================================================
def _get_conn() -> sqlite3.Connection:
    """获取连接（与 credential_store 同库，故意不走 get_raw_connection）。

    ⚠️ 与 `credential_store._get_conn()` 同理：**故意**保留裸 sqlite3.connect。
    收件人表与凭据表同属 `db/app.db` 的"本地配置类"数据，按 R8 的原始意图
    应始终留在 SQLite。注意 R8 当前是空转的（`register_hard_excluded`
    从未被调用，见 credential_store.py 同位置的长注释），所以**这里是唯一
    的保证**，勿改成 get_raw_connection。
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_recipients (
                key TEXT PRIMARY KEY,
                to_text TEXT,
                cc_text TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
    except Exception:
        logger.warning("[EMAIL-RCPT] 建表失败", exc_info=True)
    return conn


def _read_db(key: str):
    """从数据库读取保存的收件人，返回 (to_text, cc_text) 或 None。

    ⚠️ 与 `_read_db_map`（:348）**刻意不同**：这里读失败仍返回 None，因为
    调用方 `get_recipients`(:396) / `get_effective_recipients`(:418) 在 None 时
    会回退到默认名单文件 —— 这是**发送主流程**，读配置库失败时「用默认名单把邮件
    发出去」明显优于「抛异常导致邮件发不出」。None 在此是**有明确含义的降级信号**，
    调用方能正确理解，不属静默吞错，故保留（2026-10-07 复核）。
    展示路径（`_read_db_map`）则相反：那里伪装成「未保存」会误导用户并诱发覆盖写。
    """
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT to_text, cc_text FROM email_recipients WHERE key = ?", (key,)
            ).fetchone()
            if row and (row["to_text"] or row["cc_text"]):
                return row["to_text"], row["cc_text"]
            return None
        finally:
            conn.close()
    except Exception:
        logger.warning(f"[EMAIL-RCPT] 读取收件人失败: {key}", exc_info=True)
        return None


def _read_db_map() -> dict:
    """读取全部已保存记录，key -> (to_text, cc_text, updated_at)。

    ⚠️ 2026-10-07：读库失败**必须上抛**，不得吞成空 dict。
    原先失败返回 `{}`，`list_email_recipients` 会把所有组判为「未保存」，
    设置页显示 `source: "default"` + 默认值 + `updated_at: None` —— 这是一个
    **完全合法的界面状态**，用户看不出读库已经坏了；更危险的是此时点保存，
    `set_email_recipients` 会无条件 upsert，把默认名单**覆盖掉真实配置**。
    实测本机有 10 个组确实保存过配置，一旦读失败这 10 个组全部伪装成未保存。
    属「数据完整性问题」，按项目约定不得静默（参照 ms_sla_dashboard 的容错声明）。
    """
    out = {}
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT key, to_text, cc_text, updated_at FROM email_recipients"
        ).fetchall()
        for r in rows:
            out[r["key"]] = (r["to_text"], r["cc_text"], r["updated_at"])
    finally:
        conn.close()
    return out


# ============================================================
# 对外接口
# ============================================================
def _join(addrs: List[str]) -> Optional[str]:
    """列表 -> ';' 分隔字符串；空列表返回 None（与原始行为一致）。"""
    return ";".join(addrs) if addrs else None


def get_email_recipients(key: str, to: Optional[str] = None, cc: Optional[str] = None):
    """获取指定邮件任务的收件人 (to_arg, cc_arg)（字符串，';' 分隔）。

    优先级：显式传入 to/cc（测试覆盖） > 数据库保存值 > 原默认名单文件。
    未保存且默认名单为空时，to_arg 返回 None、cc_arg 返回 ''（与原始行为一致）。
    """
    # 1) 测试覆盖优先
    if to is not None or cc is not None:
        return to, cc

    # 2) 数据库保存值（带缓存）
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached[0]) < CACHE_TTL:
        db_val = cached[1]
    else:
        db_val = _read_db(key)
        with _cache_lock:
            _cache[key] = (now, db_val)

    if db_val:
        db_to, db_cc = db_val
        return db_to or None, db_cc or ""

    # 3) 默认名单文件（仍从原路径实时读取）
    group = _GROUP_INDEX.get(key)
    if group:
        try:
            to_list, cc_list = group["default_loader"]()
            return _join(to_list), _join(cc_list) or ""
        except Exception as e:
            logger.warning("[EMAIL-RCPT] 默认名单读取异常: %s: %s", key, e)
            return None, ""
    return None, ""


def get_effective_recipients(key: str):
    """返回当前生效的 (to_text, cc_text)：数据库保存值优先，否则默认名单。"""
    db_val = _read_db(key)
    if db_val:
        return db_val[0] or "", db_val[1] or ""
    group = _GROUP_INDEX.get(key)
    if group:
        try:
            to_list, cc_list = group["default_loader"]()
            return _join(to_list) or "", _join(cc_list) or ""
        except Exception:
            return "", ""
    return "", ""


def set_email_recipients(key: str, to_text: Optional[str], cc_text: Optional[str]) -> None:
    """写入/更新收件人并清空对应缓存。to/cc 为 None 时视为空串。"""
    if key not in _GROUP_INDEX:
        raise KeyError(f"Unknown email recipient group: {key}")
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO email_recipients (key, to_text, cc_text, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                to_text = excluded.to_text,
                cc_text = excluded.cc_text,
                updated_at = excluded.updated_at
            """,
            (key, to_text or "", cc_text or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()
    clear_cache(key)


def reset_email_recipients(key: str) -> None:
    """恢复默认：删除数据库记录（下次发送回退读原名单文件）。"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM email_recipients WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()
    clear_cache(key)


def clear_cache(key: str | None = None) -> None:
    with _cache_lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


def list_email_recipients(lang: str = "zh") -> list:
    """列出全部收件人组（含当前生效 to/cc、来源标记 db/default、更新时间）。

    供 Settings 页签展示。未保存的组实时读取默认名单（读不到则空，不报错）。
    """
    en = (lang or "zh").lower().startswith("en")
    saved_map = _read_db_map()
    result = []
    for g in EMAIL_RECIPIENT_GROUPS:
        saved = saved_map.get(g["key"])
        if saved and (saved[0] or saved[1]):
            to_text = saved[0] or ""
            cc_text = saved[1] or ""
            source = "db"
            updated_at = saved[2]
        else:
            try:
                to_list, cc_list = g["default_loader"]()
            except Exception:
                to_list, cc_list = [], []
            to_text = _join(to_list) or ""
            cc_text = _join(cc_list) or ""
            source = "default"
            updated_at = None
        result.append({
            "key": g["key"],
            "name": g.get("name_en") if en and g.get("name_en") else g["name"],
            "to_text": to_text,
            "cc_text": cc_text,
            "source": source,
            "updated_at": updated_at,
        })
    return result
