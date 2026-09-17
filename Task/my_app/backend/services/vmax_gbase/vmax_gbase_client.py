"""VMAX 数仓 GBase 8a 直连客户端（只读）。

实测环境（2026-09-16 由用户提供的 notebook + 本机验证得到）
----------------------------------------------------------
* 连接串（notebook 里 `VmaxTool.GetDBConn("GBASE")` 打印出来的）:
      ['GBASE', '10.123.255.12', '5258', 'gbase', 'ZXvmax_2017', 'zxvmax']
      ['SPARK', '10.123.255.10', '18000', 'zxvmax', 'ZXvmax_2017', 'zxvmax']  # Spark ThriftServer，本包不用
* 协议指纹（本机读首包，未登录）: MySQL 协议 v10，服务端版本串
      `8.6.2.43-R35.5_patch.1674d63d6`
  → 用 `pymysql` 即可（纯 Python，无编译依赖）；GBase 8a 不是 PostgreSQL，`psycopg2` 用不上。
* 授权: `CURRENT_USER() = gbase@%`（通配，无网段限制）；本机经 NAT 连入显示为
      `gbase@10.16.151.254`，所以 192.168.100.20 也能直连。
* 分区保留期（`SHOW TABLES LIKE ...` 实测）:
      `_day_YYYYMMDD`   ≈ 90 天   ← 门户页面「最多 90 天」就是这个保留期
      `_hour_YYYYMMDD`  ≈ 94 天
      `_15min_YYYYMMDD` = 11 天
      `_month_YYYYMM`   少量（如 spservice 的 202509/202510）
  注意会有**缺表**（如 aggr_5gsa_flow_ciservice_day_20260907）和**未来空分区**
  （0917~0919 有表但没数据），所以取数一律先探测分区再查。
* 与门户对账（口径验证，逐字节一致）:
      2026-09-15 本客户端 SUM(ppb400401001+ppb400401002) = 299326487733949
      门户天粒度接口同日 ppc400401001 合计     = 299326487733949
      且 9 个维度成员逐个数值精确匹配（50331658→SGW_HQ_122 等）。

安全约定
--------
本模块**只允许 SELECT/SHOW/DESC/DESCRIBE/EXPLAIN/WITH**，其它语句直接拒绝（见 `query()`），
避免误写到生产数仓。凭据走 `credential_store`（分组 `vmax_gbase`），不在代码里写死。
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:                                                                     # 可选依赖：报错更友好
    import pymysql
except Exception:                                                        # noqa: BLE001
    pymysql = None                                                       # type: ignore[assignment]

logger = logging.getLogger("vmax_gbase")

# 默认连接参数（凭据/环境变量可覆盖；密码不写死在这里）
DEFAULT_DSN: Dict[str, Any] = {
    "host": "10.123.255.12",
    "port": 5258,
    "user": "gbase",
    "database": "zxvmax",
    "charset": "utf8mb4",
    "connect_timeout": 8,
    "read_timeout": 300,
}
CREDENTIAL_KEY = "vmax_gbase"
DEFAULT_USER = "gbase"
# 传给 pymysql 的白名单（配置里多写的说明性字段不会导致连接报错）
_PYMYSQL_KEYS = ("host", "port", "user", "password", "database", "charset", "connect_timeout",
                 "read_timeout", "write_timeout", "cursorclass", "autocommit", "ssl")
# 允许的只读语句前缀：本模块是取数客户端，不该也不能写库
_READONLY_PREFIXES = ("select", "show", "desc", "describe", "explain", "with")
_PARTITION_RE = re.compile(r"^\d{8}$")

# 常用表族（基名，不含粒度与日期后缀）
FAMILY_FLOW_CISERVICE = "aggr_5gsa_flow_ciservice"          # 总流量 / TCP / 核心网元
FAMILY_FLOW_SPSERVICE = "aggr_5gsa_flow_spservice"          # 按业务/APP / 缓存服务器
FAMILY_VIDEO_SPSERVICE = "aggr_5gsa_video_spservice"        # 视频业务
FAMILY_GAME_SPSERVICE = "aggr_5gsa_game_spservice"          # 游戏业务
FAMILY_DS_250024 = "aggr_ds_250024"                         # 活跃用户（msisdn）


class VmaxGbaseError(RuntimeError):
    """GBase 取数错误（SQL/协议/数据问题）。"""


class VmaxGbaseUnavailable(VmaxGbaseError):
    """连不上 GBase（网络/授权/驱动缺失），调用方通常降级处理而不是抛给用户。"""


# ==========================================================================
# 连接参数
# ==========================================================================
def resolve_dsn(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """合并「默认值 < 配置文件 < 环境变量 < credential_store 凭据」得到连接参数。

    环境变量：VMAX_GBASE_HOST / VMAX_GBASE_PORT / VMAX_GBASE_DB /
              VMAX_GBASE_USER / VMAX_GBASE_PASS
    凭据分组：`vmax_gbase`（设置页可改，改完最迟 30s 生效）
    """
    dsn = dict(DEFAULT_DSN)
    conf = dict(cfg or {})
    cred_key = str(conf.pop("credential_key", None) or CREDENTIAL_KEY)
    user_default = str(conf.get("user") or DEFAULT_USER)
    sec_default = str(conf.pop("password", "") or "")
    # 凭据分组里声明的默认值（与「设置 → 凭据管理」显示的一致），避免两处各写一份密码
    try:
        from backend.services.credential_store import CREDENTIAL_GROUPS
        group = next((g for g in CREDENTIAL_GROUPS if g.get("key") == cred_key), None) or {}
        user_default = user_default or str(group.get("default_user") or "")
        sec_default = sec_default or str(group.get("default_secret") or "")
    except Exception:                                                    # noqa: BLE001
        pass
    dsn.update({k: v for k, v in conf.items() if v not in (None, "")})

    env_map = {"host": "VMAX_GBASE_HOST", "port": "VMAX_GBASE_PORT",
               "database": "VMAX_GBASE_DB"}
    for field, env in env_map.items():
        val = os.environ.get(env)
        if val:
            dsn[field] = val
    try:
        dsn["port"] = int(dsn.get("port") or DEFAULT_DSN["port"])
    except (TypeError, ValueError):
        dsn["port"] = DEFAULT_DSN["port"]

    try:
        from backend.services.credential_store import get_credential
    except Exception:                                                    # noqa: BLE001
        try:
            from credential_store import get_credential                  # 直接跑本文件时
        except Exception:                                                # noqa: BLE001
            get_credential = None                                        # type: ignore[assignment]
    if get_credential is not None:
        try:
            user, secret = get_credential(cred_key, user_default, sec_default,
                                          "VMAX_GBASE_USER", "VMAX_GBASE_PASS")
            dsn["user"] = user or user_default
            dsn["password"] = secret or sec_default
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[vmax_gbase] 凭据读取失败，使用配置/默认值: %s", exc)
    dsn.setdefault("password", sec_default)
    return dsn


def dsn_summary(dsn: Dict[str, Any]) -> str:
    """脱敏的连接描述（日志/--check 用）。"""
    return "%s@%s:%s/%s" % (dsn.get("user"), dsn.get("host"), dsn.get("port"),
                            dsn.get("database"))


# ==========================================================================
# 日期/分区工具
# ==========================================================================
def norm_day(value: Any) -> str:
    """把 date/datetime/'YYYY-MM-DD'/'YYYYMMDD' 归一成 'YYYYMMDD'。"""
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if re.match(r"^\d{8}$", text):
        return text
    text = text.replace("/", "-").replace(".", "-")
    if " " in text or "T" in text:
        text = text.replace("T", " ").split(" ")[0]
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise VmaxGbaseError("无法识别的日期: %r" % (value,)) from exc


def iso_day(value: Any) -> str:
    """把任意日期写法归一成 'YYYY-MM-DD'（入库/接口用；与 norm_day 的分区后缀格式区分）。"""
    text = norm_day(value)
    return "%s-%s-%s" % (text[:4], text[4:6], text[6:])


def day_range(begin: Any, end: Any) -> List[str]:
    """[begin, end] 闭区间内每天的 'YYYYMMDD' 列表（含首尾）。"""
    b, e = norm_day(begin), norm_day(end)
    if b > e:
        b, e = e, b
    d0 = datetime.strptime(b, "%Y%m%d")
    d1 = datetime.strptime(e, "%Y%m%d")
    return [(d0 + timedelta(days=i)).strftime("%Y%m%d") for i in range((d1 - d0).days + 1)]


def day_table(family: str, day: Any, granularity: str = "day") -> str:
    """拼分区表名：('aggr_5gsa_flow_ciservice', '2026-09-15', 'day') → ..._day_20260915。"""
    gran = str(granularity or "day").strip().lower()
    if gran not in ("day", "hour", "15min", "month"):
        raise VmaxGbaseError("不支持的粒度: %r" % (granularity,))
    if gran == "month":
        return "%s_month_%s" % (family, norm_day(day)[:6])
    return "%s_%s_%s" % (family, gran, norm_day(day))


def partition_days(names: Iterable[str], family: str, granularity: str = "day") -> List[str]:
    """从 `SHOW TABLES` 结果里挑出该表族的日分区（升序，忽略非日期后缀）。"""
    prefix = "%s_%s_" % (family, str(granularity or "day").strip().lower())
    days = [str(n)[len(prefix):] for n in names
            if str(n).startswith(prefix) and _PARTITION_RE.match(str(n)[len(prefix):])]
    return sorted(set(days))


def available_days(present: Sequence[str], begin: Any, end: Any) -> Tuple[List[str], List[str]]:
    """(窗口内有表的天, 缺表的天) —— 数仓会出现缺表/未来空分区，调用方按此跳过。"""
    wanted = day_range(begin, end)
    have = set(present)
    return [d for d in wanted if d in have], [d for d in wanted if d not in have]


# ==========================================================================
# 客户端
# ==========================================================================
class VmaxGbaseClient:
    """GBase 只读客户端：连接复用 + 只读校验 + 断线重试 + 分区探测。"""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None,
                 dsn: Optional[Dict[str, Any]] = None, **overrides: Any):
        base = dict(cfg or {})
        if dsn:
            base.update(dsn)
        base.update({k: v for k, v in overrides.items() if v is not None})
        self.dsn = resolve_dsn(base)
        self._conn = None
        self.queries = 0
        self.seconds = 0.0
        self._verified_readonly = True

    # ---------------- 连接 ----------------
    @property
    def connected(self) -> bool:
        return self._conn is not None

    def connect(self):
        if pymysql is None:
            raise VmaxGbaseUnavailable(
                "未安装 pymysql（GBase 走 MySQL 协议）。请执行: python -m pip install pymysql")
        if self._conn is not None:
            return self._conn
        params = {k: v for k, v in self.dsn.items() if k in _PYMYSQL_KEYS}
        if not params.get("password"):
            raise VmaxGbaseUnavailable(
                "缺少 GBase 密码：请配置凭据分组 %s（或设 VMAX_GBASE_PASS）" % CREDENTIAL_KEY)
        params.setdefault("cursorclass", pymysql.cursors.Cursor)
        params.setdefault("autocommit", True)
        try:
            self._conn = pymysql.connect(**params)
        except Exception as exc:                                         # noqa: BLE001
            raise VmaxGbaseUnavailable("连接 GBase 失败（%s）: %s" % (dsn_summary(self.dsn), exc)) from exc
        logger.info("[vmax_gbase] 已连接 %s", dsn_summary(self.dsn))
        return self._conn

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:                                            # noqa: BLE001
                pass

    def __enter__(self) -> "VmaxGbaseClient":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ---------------- 查询 ----------------
    @staticmethod
    def _assert_readonly(sql: str) -> None:
        head = str(sql or "").lstrip().lstrip("(").lower()
        if not head.startswith(_READONLY_PREFIXES):
            raise VmaxGbaseError("只允许只读取数语句（SELECT/SHOW/DESC/EXPLAIN/WITH），拒绝执行: %s"
                                 % str(sql)[:120])

    def _execute(self, sql: str, params: Optional[Sequence[Any]] = None,
                 retries: int = 2) -> Tuple[List[str], List[tuple]]:
        """执行只读 SQL 一次，返回 (列名, 行)；断线（2006/2013 等）自动重连重试。"""
        self._assert_readonly(sql)
        attempt = 0
        while True:
            conn = self.connect()
            t0 = time.time()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    cols = [d[0] for d in (cur.description or [])]
                    rows = cur.fetchall()
                self.queries += 1
                self.seconds += time.time() - t0
                return cols, list(rows)
            except Exception as exc:                                     # noqa: BLE001
                attempt += 1
                code = getattr(exc, "args", [None])[0]
                transient = code in (2006, 2013, 2014, 2055) or "Lost connection" in str(exc)
                if attempt > retries or not transient:
                    raise VmaxGbaseError("SQL 执行失败（%s）: %s" % (type(exc).__name__, exc)) from exc
                logger.warning("[vmax_gbase] 查询失败将重试(%d/%d): %s", attempt, retries, exc)
                self.close()
                time.sleep(1.0 * attempt)

    def query(self, sql: str, params: Optional[Sequence[Any]] = None,
              retries: int = 2) -> List[tuple]:
        """执行只读 SQL，返回 tuple 列表。"""
        return self._execute(sql, params, retries)[1]

    def query_dicts(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
        cols, rows = self._execute(sql, params)
        return [dict(zip(cols, row)) for row in rows]

    def query_df(self, sql: str, params: Optional[Sequence[Any]] = None):
        """执行查询并返回 pandas.DataFrame（列名取 SQL 别名）。"""
        import pandas as pd

        cols, rows = self._execute(sql, params)
        return pd.DataFrame([list(r) for r in rows], columns=cols)

    def scalar(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        rows = self.query(sql, params)
        return rows[0][0] if rows and rows[0] else None

    # ---------------- 元数据 / 健康 ----------------
    def healthy(self) -> Tuple[bool, str]:
        """(是否可用, 说明)。不抛异常，便于 --check 与降级。"""
        try:
            ver = self.scalar("SELECT VERSION()")
            user = self.scalar("SELECT CURRENT_USER()")
            db = self.scalar("SELECT DATABASE()")
            return True, "GBase %s | %s | db=%s | %s" % (ver, user, db, dsn_summary(self.dsn))
        except Exception as exc:                                         # noqa: BLE001
            return False, "%s: %s" % (type(exc).__name__, exc)

    def tables_like(self, pattern: str) -> List[str]:
        rows = self.query("SHOW TABLES LIKE %s", (pattern,))
        return [str(r[0]) for r in rows]

    def table_exists(self, table: str) -> bool:
        return bool(self.tables_like(table))

    def describe(self, table: str) -> List[Tuple[Any, ...]]:
        return self.query("SHOW COLUMNS FROM %s" % table)

    def partition_days(self, family: str, granularity: str = "day") -> List[str]:
        """该表族现有分区日（升序）。一次 SHOW TABLES 即可，开销很小。"""
        return partition_days(self.tables_like("%s_%s_%%" % (family, granularity)),
                              family, granularity)

    def available_days(self, family: str, begin: Any, end: Any,
                       granularity: str = "day") -> Tuple[List[str], List[str]]:
        """(可查的天, 缺表的天)。"""
        present = self.partition_days(family, granularity)
        return available_days(present, begin, end)

    def latest_day(self, family: str, granularity: str = "day") -> Optional[str]:
        days = self.partition_days(family, granularity)
        return days[-1] if days else None
