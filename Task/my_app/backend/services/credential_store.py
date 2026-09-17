"""
credential_store.py - 集中凭据存储模块（数据库管理 + 运行时动态读取）
====================================================================
背景：各服务（ZTE UME / eFlow / FW / SFTP / 邮箱 / 微信通知）的用户名密码
原先硬编码在代码中，密码定期更改时不得不改代码。本模块将凭据集中存入
db/app.db 的 credentials 表，通过前端"设置"页面维护，服务运行时动态读取。

读取优先级：环境变量 > 数据库 > 代码默认值
缓存策略：进程内缓存 30 秒，改完密码最迟 30 秒生效，无需重启服务。

用法:
    from backend.services.credential_store import get_credential
    user, pwd = get_credential("zte_ume", "NOC", "Zte@2025!")
"""

import os
import time
import sqlite3
import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# db/app.db：backend/services -> backend -> my_app
DB_PATH = Path(__file__).resolve().parents[2] / "db" / "app.db"

# 进程内缓存 TTL（秒）
CACHE_TTL = float(os.environ.get("CREDENTIAL_CACHE_TTL", "30"))

_cache: dict = {}
_cache_lock = threading.Lock()

# ============================================================
# 凭据组注册表（key、显示名、代码默认值、是否可自动测试）
# ============================================================
CREDENTIAL_GROUPS = [
    {
        "key": "zte_ume",
        "name": "ZTE UME 网管 (RAN KPI / MS SLA)",
        "name_en": "ZTE UME NMS (RAN KPI / MS SLA)",
        "usage": "RAN KPI / MS SLA 报表抓取任务使用此账号登录 ZTE UME 网管拉取性能数据。",
        "usage_en": "Used by the RAN KPI / MS SLA report tasks to log into ZTE UME NMS and pull performance data.",
        "default_user": "NOC",
        "default_secret": "Zte@2025!",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "10.100.28.27",
        "test_port": 28001,
        "env_user": "RAN_UME_USER",
        "env_secret": "RAN_UME_PASS",
    },
    {
        "key": "vmax_cxo",
        "name": "VMAX CXO 经营看板门户 (10.123.255.12:26180)",
        "name_en": "VMAX CXO Dashboard Portal (10.123.255.12:26180)",
        "usage": "CXO 经营看板（my_app 内嵌页面）的实时数据代理 realtime_proxy_vmax.py 使用此账号登录 VMAX 门户拉取经营数据。",
        "usage_en": "Used by the CXO Dashboard's realtime proxy (realtime_proxy_vmax.py) to log into the VMAX portal and pull business data.",
        "default_user": "ZeeshanM",
        "default_secret": "Zte@1a2b3c",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": False,
        "env_user": "VMAX_CXO_USER",
        "env_secret": "VMAX_CXO_PASS",
    },
    {
        "key": "vmax_gbase",
        "name": "VMAX 数仓 GBase 8a (10.123.255.12:5258)",
        "name_en": "VMAX Data Warehouse GBase 8a (10.123.255.12:5258)",
        "usage": "OLIB SOC VMAX 例行报表任务（backend/services/olib_soc_report）直连数仓 GBase 取数"
                 "（MySQL 协议，库 zxvmax）时使用；仅执行 SELECT/SHOW 只读语句。",
        "usage_en": "Used by the OLIB SOC VMAX routine report task (backend/services/olib_soc_report) "
                    "to query the GBase data warehouse directly (MySQL protocol, database zxvmax); "
                    "read-only SELECT/SHOW statements only.",
        "default_user": "gbase",
        "default_secret": "ZXvmax_2017",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": False,
        "env_user": "VMAX_GBASE_USER",
        "env_secret": "VMAX_GBASE_PASS",
    },
    {
        "key": "ipran_ume",
        "name": "iPRAN UME 网管",
        "name_en": "iPRAN UME NMS",
        "usage": "iPRAN UME KPI 抓取任务使用此账号登录 iPRAN UME 网管拉取数据。",
        "usage_en": "Used by iPRAN UME KPI tasks to log into the iPRAN UME NMS.",
        "default_user": "noc1",
        "default_secret": "Zte@lbr202607",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "10.100.2.99",
        "test_port": 28001,
        "env_user": None,
        "env_secret": None,
    },
    {
        "key": "ccn_ume",
        "name": "CCN UME 网管",
        "name_en": "CCN UME NMS",
        "usage": "CCN UME KPI 抓取任务使用此账号登录 CCN UME 网管拉取数据。",
        "usage_en": "Used by CCN UME KPI tasks to log into the CCN UME NMS.",
        "default_user": "oss",
        "default_secret": "Mwebazeaaron@25",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "10.121.1.2",
        "test_port": 28808,
        "env_user": None,
        "env_secret": None,
    },
    {
        "key": "eflow",
        "name": "eFlow 告警系统",
        "name_en": "eFlow Alarm System",
        "usage": "eFlow 告警系统数据同步任务使用此账号获取告警 / 工单数据。",
        "usage_en": "Used by eFlow alarm-system sync tasks to fetch alarm/ticket data.",
        "default_user": "admin",
        "default_secret": "Brysj*8*",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "10.100.20.8",
        "test_port": 28001,
        "env_user": "EFLOW_USER",
        "env_secret": "EFLOW_PASS",
    },
    {
        "key": "rais",
        "name": "RAIS 统一权限平台 (10.100.20.9:8766)",
        "name_en": "RAIS Unified Permission Platform (10.100.20.9:8766)",
        "usage": "一键门户登录（RAIS 统一认证中心 / uacliteweb）使用此账号做直接鉴权登录；"
                 "该站点与 eFlow 同网段，同为 ZTE UAC 系账号。",
        "usage_en": "Used by the one-click portal login for RAIS (Unified Permission Platform / "
                    "uacliteweb) direct authentication.",
        "default_user": "admin",
        "default_secret": "ZXUniPOS_rais",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "10.100.20.9",
        "test_port": 8766,
        "env_user": "RAIS_USER",
        "env_secret": "RAIS_PASS",
    },
    {
        "key": "fms_portal",
        "name": "FMS 实时代理门户 (10.100.20.8:28001)",
        "name_en": "FMS Realtime Proxy Portal (10.100.20.8:28001)",
        "usage": "FMS 实时数据代理 realtime_proxy.py（支撑 Alarm Management / 站点宕机看板）使用此账号登录 FMS 门户拉取实时数据。",
        "usage_en": "Used by the FMS realtime proxy (realtime_proxy.py, backing Alarm Management / site-outage dashboard) to log into the FMS portal.",
        "default_user": "admin",
        "default_secret": "Brysj*8*",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "10.100.20.8",
        "test_port": 28001,
        "env_user": "FMS_PORTAL_USER",
        "env_secret": "FMS_PORTAL_PASS",
    },
    {
        "key": "fw_kpi",
        "name": "FW 整机吞吐 KPI (UMC)",
        "name_en": "FW Throughput KPI (UMC)",
        "usage": "FW 整机吞吐 KPI 抓取任务使用此账号登录 UMC 拉取吞吐数据。",
        "usage_en": "Used by the FW throughput KPI task to log into UMC and pull throughput data.",
        "default_user": "admin",
        "default_secret": "Zte@orange123!",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": False,
        "env_user": None,
        "env_secret": None,
    },
    {
        "key": "mw_ume",
        "name": "MW UME 微波网管 (192.168.169.247:28001)",
        "name_en": "MW UME Microwave NMS (192.168.169.247:28001)",
        "usage": "MW UME KPI 同步任务使用此账号登录 ZXMW 微波网管拉取带宽利用率等指标；一键门户登录也复用此凭据。",
        "usage_en": "Used by the MW UME KPI sync task to log into the ZXMW microwave NMS and pull bandwidth-utilization KPIs; also reused by the one-click portal login.",
        "default_user": "NOC_MW",
        "default_secret": "Zte@202608",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "192.168.169.247",
        "test_port": 28001,
        "env_user": "MW_UME_USER",
        "env_secret": "MW_UME_PASSWORD",
    },
    {
        "key": "ume_in",
        "name": "UME 客户业务 KPI 门户 (172.17.208.1:28808)",
        "name_en": "UME Customer Service KPI Portal (172.17.208.1:28808)",
        "usage": "客户业务 KPI 看板（IVR / P4M / VC / USSD / PPS / CPU / Memory）的同步任务使用此账号登录 UME em-portal 拉取周度业务指标。",
        "usage_en": "Used by the Customer Service KPI dashboard sync task (IVR / P4M / VC / USSD / PPS / CPU / Memory) to log into the UME em-portal and pull weekly service KPIs.",
        "default_user": "10172755",
        "default_secret": "Zte@liberia202609",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": True,
        "test_host": "172.17.208.1",
        "test_port": 28808,
        "env_user": "UME_IN_USER",
        "env_secret": "UME_IN_PASSWORD",
    },
    {
        "key": "sftp_sp",
        "name": "SFTP 备件报表服务器 (10.100.20.11)",
        "name_en": "SFTP Spare-parts Report Server (10.100.20.11)",
        "usage": "备件报表上传 / 下载任务使用此 SFTP 账号推送备件报表文件。",
        "usage_en": "Used by spare-parts report upload/download tasks over SFTP.",
        "default_user": "ubuntu",
        "default_secret": "UbuntU1!2@3#4$",
        "username_label": "用户名",
        "username_label_en": "Username",
        "secret_label": "密码",
        "secret_label_en": "Password",
        "has_username": True,
        "testable": False,
        "env_user": None,
        "env_secret": None,
    },
    {
        "key": "mail_126",
        "name": "126 邮箱（邮件报告）",
        "name_en": "126 Mailbox (Email Reports)",
        "usage": "邮件报告任务使用此 126 邮箱账号发送运营报告。",
        "usage_en": "Used by the email-report task to send ops reports via 126 mailbox.",
        "default_user": "xin83min@126.com",
        "default_secret": "LQcTaMMuWmhvAfRB",
        "username_label": "邮箱账号",
        "username_label_en": "Email Account",
        "secret_label": "SMTP 授权码",
        "secret_label_en": "SMTP Auth Code",
        "has_username": True,
        "testable": False,
        "env_user": None,
        "env_secret": None,
    },
    {
        "key": "owa_mail",
        "name": "Exchange/OWA 邮箱（运维报告 + 邮箱清理）",
        "name_en": "Exchange/OWA Mailbox (Ops Reports + Mailbox Cleanup)",
        "usage": "运维报告与邮箱清理任务使用此 Exchange/OWA 域账号。",
        "usage_en": "Used by ops-report and mailbox-cleanup tasks via Exchange/OWA.",
        "default_user": "ZTENOC_OLR",
        "default_secret": "Postcode@202608",
        "username_label": "登录账号 (域账号)",
        "username_label_en": "Login Account (Domain)",
        "secret_label": "邮箱密码",
        "secret_label_en": "Mailbox Password",
        "has_username": True,
        "testable": False,
        "env_user": None,
        "env_secret": None,
    },
    {
        "key": "weixin",
        "name": "微信/即时消息通知",
        "name_en": "WeChat/IM Notification",
        "usage": "Server酱 / PushPlus 推送任务使用此 Token 发送微信 / IM 通知。",
        "usage_en": "Used by ServerChan/PushPlus push tasks to send WeChat/IM notifications.",
        "default_user": "SCT389311TrwFJS9k0ZxfX5Plb9g0gozix",
        "default_secret": "f9cf7778112f486ab618d153456e2553",
        "username_label": "Server酱 SendKey",
        "username_label_en": "ServerChan SendKey",
        "secret_label": "PushPlus Token",
        "secret_label_en": "PushPlus Token",
        "has_username": True,
        "testable": False,
        "env_user": None,
        "env_secret": None,
    },
]

_GROUP_INDEX = {g["key"]: g for g in CREDENTIAL_GROUPS}


# ============================================================
# 数据库访问（独立 sqlite3，避免与 SQLAlchemy 会话互相干扰）
# ============================================================
def _get_conn() -> sqlite3.Connection:
    """获取连接并确保 credentials 表存在。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credentials (
                key TEXT PRIMARY KEY,
                username TEXT,
                secret TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
    except Exception:
        logger.warning("[CRED] 建表失败", exc_info=True)
    return conn


def _read_db(key: str):
    """从数据库读取凭据，返回 (username, secret) 或 None。"""
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT username, secret FROM credentials WHERE key = ?", (key,)
            ).fetchone()
            if row and (row["secret"] or row["username"]):
                return row["username"], row["secret"]
            return None
        finally:
            conn.close()
    except Exception:
        logger.warning(f"[CRED] 读取凭据失败: {key}", exc_info=True)
        return None


# ============================================================
# 对外接口
# ============================================================
def get_credential(key: str, default_user: str = "", default_secret: str = "",
                   env_user: str | None = None, env_secret: str | None = None):
    """获取凭据 (username, secret)。

    优先级：环境变量 > 数据库(credentials 表) > 代码默认值。
    结果缓存 CACHE_TTL 秒（数据库部分），改密码后最迟 30 秒生效。

    Args:
        key: 凭据组 key（如 zte_ume / eflow）
        default_user: 代码默认用户名（回退值）
        default_secret: 代码默认密码（回退值）
        env_user: 可选的环境变量名（覆盖用户名的 env）
        env_secret: 可选的环境变量名（覆盖密码的 env）
    """
    group = _GROUP_INDEX.get(key)
    # 环境变量优先
    if env_user is None and group:
        env_user = group.get("env_user")
    if env_secret is None and group:
        env_secret = group.get("env_secret")

    user_env = os.environ.get(env_user) if env_user else None
    secret_env = os.environ.get(env_secret) if env_secret else None

    # 数据库值（带缓存）
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached[0]) < CACHE_TTL:
        db_val = cached[1]
    else:
        db_val = _read_db(key)
        with _cache_lock:
            _cache[key] = (now, db_val)

    db_user, db_secret = db_val if db_val else (None, None)

    username = user_env or db_user or default_user
    secret = secret_env or db_secret or default_secret
    return username, secret


def set_credential(key: str, username: str | None, secret: str | None) -> None:
    """写入/更新凭据并清空对应缓存。传 None 表示恢复代码默认值（删除记录）。"""
    conn = _get_conn()
    try:
        if username is None and secret is None:
            conn.execute("DELETE FROM credentials WHERE key = ?", (key,))
        else:
            # 历史版本 credentials 表可能缺少 key 主键，ON CONFLICT(key) 会报
            # "does not match any PRIMARY KEY or UNIQUE constraint"。改用
            # 删除+插入的幂等 upsert，不依赖表结构约束。
            conn.execute("DELETE FROM credentials WHERE key = ?", (key,))
            conn.execute(
                """
                INSERT INTO credentials (key, username, secret, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, username, secret, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
        conn.commit()
    finally:
        conn.close()
    clear_cache(key)


def get_effective(key: str):
    """返回当前生效的 (username, secret)：数据库 > 代码默认值（不含环境变量）。

    供 PUT 部分更新时合并未修改字段使用。
    """
    g = _GROUP_INDEX.get(key)
    db_val = _read_db(key)
    if db_val:
        du = g["default_user"] if g else ""
        ds = g["default_secret"] if g else ""
        return (db_val[0] or du), (db_val[1] or ds)
    if g:
        return g["default_user"], g["default_secret"]
    return "", ""


def clear_cache(key: str | None = None) -> None:
    """清空缓存（key=None 清空全部）。"""
    with _cache_lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


def mask(secret: str | None) -> str:
    """密码掩码显示：保留前 4 位，其余用 * 代替。"""
    if not secret:
        return ""
    if len(secret) <= 4:
        return "*" * len(secret)
    return secret[:4] + "*" * (len(secret) - 4)


def list_credentials(lang: str = "zh") -> list:
    """列出全部凭据组（密码掩码 + 来源标记），供设置页面展示。

    返回: [{key, name, username, secret_masked, source, updated_at, ...}]
    `lang='en'` 时 name / username_label / secret_label 取 *_en 变体（缺失则回退中文）。
    """
    en = (lang or "zh").lower().startswith("en")
    updated_map = {}
    try:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT key, username, secret, updated_at FROM credentials"
            ).fetchall()
            for r in rows:
                updated_map[r["key"]] = {
                    "username": r["username"],
                    "secret": r["secret"],
                    "updated_at": r["updated_at"],
                }
        finally:
            conn.close()
    except Exception:
        logger.warning("[CRED] 列出凭据失败", exc_info=True)

    result = []
    for g in CREDENTIAL_GROUPS:
        db_val = updated_map.get(g["key"])
        if db_val and (db_val["secret"] or db_val["username"]):
            user = db_val["username"] or ""
            secret = db_val["secret"] or ""
            source = "db"
            updated_at = db_val["updated_at"]
        else:
            user = g["default_user"]
            secret = g["default_secret"]
            source = "default"
            updated_at = None
        # 环境变量覆盖标记
        env_u = os.environ.get(g["env_user"]) if g.get("env_user") else None
        env_s = os.environ.get(g["env_secret"]) if g.get("env_secret") else None
        if env_u:
            user = env_u
            source = "env"
        if env_s:
            secret = env_s
            source = "env"
        result.append({
            "key": g["key"],
            "name": g.get("name_en") if en and g.get("name_en") else g["name"],
            "username": user,
            "secret_masked": mask(secret),
            "source": source,
            "updated_at": updated_at,
            "usage": g.get("usage_en") if en and g.get("usage_en") else g.get("usage", ""),
            "username_label": (g.get("username_label_en") if en and g.get("username_label_en")
                              else g.get("username_label", "用户名")),
            "secret_label": (g.get("secret_label_en") if en and g.get("secret_label_en")
                             else g.get("secret_label", "密码")),
            "has_username": g.get("has_username", True),
            "testable": g.get("testable", False),
        })
    return result
