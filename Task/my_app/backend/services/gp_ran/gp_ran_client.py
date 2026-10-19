"""RAN Greenplum 只读取数客户端（control1 两跳 SSH + psql）。

链路（2026-10-19 现场人工流程，本模块把它自动化）
--------------------------------------------------
    本机 --SSH:22--> control1 (10.100.29.12, ubuntu)
                   --SSH:22--> GP 主节点 (193.168.0.6, ubuntu)   [direct-tcpip 转发]
                                --sudo -S--> root
                                --su - gpadmin--> psql

实测连通性（2026-10-19 本机发起）：
* `10.100.29.12:22` OPEN（OpenSSH_8.5）；`:5432` refused → control1 上没有可直接连的库。
* `193.168.0.6:22 / :5432` 从本机**超时**，必须经 control1 转发，不能直连。
* 本机 `~/.ssh/id_ed25519` 在 control1 上**未被信任**（publickey 被拒），可用认证方式为
  `password`（`publickey,gssapi-keyex,gssapi-with-mic,password`）。凭据走 credential_store。

与 `vmax_gbase` 的区别（别混用）
-------------------------------
`vmax_gbase` 连的是 GBase 8a（MySQL 协议，10.123.255.12:5258，pymysql 直连）。
本模块连的是 Greenplum（PostgreSQL 语法），且 SQL 里的 `L_T216` 只存在于这套集群。

安全约定
--------
* 只放行 `SELECT / WITH / SHOW / EXPLAIN / COPY (... ) TO STDOUT`，其余语句拒绝；
  `COPY ... TO '文件'` 显式拒绝 —— 那会在数仓上留下落盘文件（内容为用户号码清单）。
* 改用车上流程的 `COPY ... TO STDOUT`：CSV 经 SSH 标准输出直接回到本机，
  不再需要 `chmod 777` + `scp` 到 /home/ubuntu 这两步，服务器零残留。
* 口令只进 credentials 表 / 环境变量，不进代码、不进日志、不进 git。
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

try:
    import paramiko
except Exception:  # noqa: BLE001
    paramiko = None  # type: ignore[assignment]

logger = logging.getLogger("gp_ran")

# ---------------------------------------------------------------- 连接参数
DEFAULT_ENDPOINTS: Dict[str, Any] = {
    "control_host": "10.100.29.12",   # control1 跳板
    "control_port": 22,
    "control_user": "ubuntu",
    "master_host": "193.168.0.6",     # GP 主节点（利比里亚现场）
    "master_port": 22,
    "master_user": "ubuntu",
    "db_user": "gpadmin",             # psql 实际执行身份
    "database": "netmaxdb",           # 2026-10-19 实测：gpadmin 默认库，L_T216 就在这里
    "connect_timeout": 15,
    "query_timeout": 1800,            # 全天信令表扫描可能很久，默认给 30min
}
CREDENTIAL_KEY_CONTROL = "gp_ran_control"
CREDENTIAL_KEY_MASTER = "gp_ran_master"

# 只读语句白名单 / 危险写法黑名单
_READONLY_PREFIXES = ("select", "with", "show", "explain", "copy")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|vacuum|"
    r"lock|call|do|set|reset)\b", re.IGNORECASE)
# `COPY ... TO '文件'` 会在数盘上留文件（内容还是用户号码清单）；
# `COPY ... TO PROGRAM '命令'` 更严重 —— 它以 gpadmin 身份**执行操作系统命令**。
_COPY_TO_FILE = re.compile(r"\bto\s*'", re.IGNORECASE)
_COPY_TO_PROGRAM = re.compile(r"\bto\s+program\b", re.IGNORECASE)
# SQL 是经 `psql -f -` 喂进去的，psql 元命令同样会被执行：`\! rm` 等于远端 shell。
_PSQL_METACOMMAND = re.compile(r"^\s*\\", re.MULTILINE)
# 会被拼进远端 shell 命令的字段必须限死为合法标识符：这些值来自配置/凭据表/环境变量，
# 一旦混入 `;` 或反引号，就会在 gpadmin 的 shell 里执行任意命令。
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$\-]{0,62}$")


class GpRanError(RuntimeError):
    """Greenplum 取数错误（SQL / 认证 / 命令失败）。"""


class GpRanUnavailable(GpRanError):
    """链路不可达或依赖缺失，调用方应降级而不是把异常抛给使用者。"""


# ---------------------------------------------------------------- 凭据与端点
def _cred(key: str, default_user: str, env_user: str, env_pass: str) -> Tuple[str, str]:
    try:
        from backend.services.credential_store import get_credential
    except Exception:  # noqa: BLE001
        try:
            from credential_store import get_credential  # 直接跑本文件时
        except Exception:  # noqa: BLE001
            return (os.environ.get(env_user, default_user),
                    os.environ.get(env_pass, ""))
    return get_credential(key, default_user, "", env_user, env_pass)


def resolve_endpoints(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """合并「默认 < 传入配置 < 环境变量 < 凭据库」得到两跳的连接参数。

    环境变量：GP_RAN_CONTROL_HOST / GP_RAN_CONTROL_PORT / GP_RAN_CONTROL_USER /
              GP_RAN_CONTROL_PASS / GP_RAN_MASTER_HOST / GP_RAN_MASTER_PORT /
              GP_RAN_MASTER_USER / GP_RAN_MASTER_PASS / GP_RAN_DB
    凭据分组：`gp_ran_control`（control1 ubuntu）、`gp_ran_master`（主节点 ubuntu）；
              主节点分组留空时自动复用 control 的口令（现场两台通常是同一口令）。
    """
    ep = dict(DEFAULT_ENDPOINTS)
    conf = dict(cfg or {})
    ep.update({k: v for k, v in conf.items()
               if v not in (None, "") and k in ep})

    env_map = {"control_host": "GP_RAN_CONTROL_HOST", "control_port": "GP_RAN_CONTROL_PORT",
               "master_host": "GP_RAN_MASTER_HOST", "master_port": "GP_RAN_MASTER_PORT",
               "database": "GP_RAN_DB"}
    for field, env in env_map.items():
        val = os.environ.get(env)
        if val:
            ep[field] = val
    for int_field in ("control_port", "master_port"):
        try:
            ep[int_field] = int(ep[int_field])
        except (TypeError, ValueError):
            ep[int_field] = DEFAULT_ENDPOINTS[int_field]

    c_user, c_pass = _cred(CREDENTIAL_KEY_CONTROL, str(ep["control_user"]),
                           "GP_RAN_CONTROL_USER", "GP_RAN_CONTROL_PASS")
    m_user, m_pass = _cred(CREDENTIAL_KEY_MASTER, str(ep["master_user"]),
                           "GP_RAN_MASTER_USER", "GP_RAN_MASTER_PASS")
    ep["control_user"], ep["control_password"] = c_user, c_pass
    ep["master_user"] = m_user or ep["master_user"]
    # 主节点未单独配凭据时复用跳板口令，避免两处维护同一份密码
    ep["master_password"] = m_pass or c_pass
    if not c_pass and not m_pass:
        raise GpRanUnavailable(
            f"未配置 SSH 口令：请在「设置 → 凭据管理」填写 {CREDENTIAL_KEY_CONTROL}"
            f"（或设环境变量 GP_RAN_CONTROL_PASS）")
    _looks_placeholder(c_pass, "GP_RAN_CONTROL_PASS")
    _looks_placeholder(m_pass, "GP_RAN_MASTER_PASS")
    _validate_shell_idents(ep)
    return ep


def _looks_placeholder(password: str, env_name: str) -> None:
    """拦住「把示例里的占位符原样贴进来」这类误用。

    生产 SSH 口令不会含中文，一旦检出非 ASCII 基本就是占位符没替换。
    提前报错而不是拿去登录，是因为对着生产账号连试错口令有**触发锁定**的风险，
    那种情况下真正在跑的任务会一起挂掉。
    """
    if password and not password.isascii():
        raise GpRanError(
            f"{env_name} 含非 ASCII 字符（{password[:12]!r}…），疑似命令示例里的占位符没换成"
            f"真实口令；已阻止登录，避免反复试错触发账号锁定。")


def _validate_shell_idents(ep: Dict[str, Any]) -> None:
    """校验会被拼进远端 shell 的字段（库名、gpadmin 账号名）。"""
    for field in ("db_user", "database"):
        val = str(ep.get(field) or "")
        if val and not _IDENT_RE.match(val):
            raise GpRanError(f"{field} 含非法字符（只允许字母/数字/_ $ -）：{val!r}")


def endpoints_summary(ep: Dict[str, Any]) -> str:
    """脱敏的连接描述（日志 / --check 用），绝不含口令。"""
    return (f"control1={ep['control_user']}@{ep['control_host']}:{ep['control_port']} "
            f"-> gp_master={ep['master_user']}@{ep['master_host']}:{ep['master_port']} "
            f"as {ep['db_user']}"
            + (f" db={ep['database']}" if ep.get("database") else " (默认库)"))


# ---------------------------------------------------------------- 只读守卫
def assert_readonly(sql: str) -> None:
    """只允许只读取数语句；拒绝写语句、服务器落盘、以及任何能起 shell 的写法。

    这层守卫是本模块唯一的执行身份是 **gpadmin（数仓超级用户）**，
    一次误判的代价是生产库被改或被植入文件，所以宁可拒了再解释。
    """
    stripped = re.sub(r"^(--[^\n]*\n\s*)+", "", sql.lstrip()).lower()
    if not any(stripped.startswith(p) for p in _READONLY_PREFIXES):
        raise GpRanError(f"拒绝执行非只读语句：{stripped[:40]!r}")
    if _PSQL_METACOMMAND.search(sql):
        raise GpRanError("拒绝执行：SQL 里含 psql 元命令（以 \\ 开头），那会绕过只读限制起 shell")
    if _COPY_TO_PROGRAM.search(sql):
        raise GpRanError("拒绝执行：COPY ... TO PROGRAM 会以 gpadmin 身份执行操作系统命令")
    # `TO STDOUT` 是合法出口（数据经 SSH 直接回本机），排除掉之后再查有没有 `TO '文件'`
    body = re.sub(r"\bto\s+stdout\b", "", sql, flags=re.IGNORECASE)
    if _COPY_TO_FILE.search(body):
        raise GpRanError("拒绝执行：COPY ... TO '文件' 会在数仓上留下用户号码清单；请改用 TO STDOUT")
    if _FORBIDDEN.search(sql):
        raise GpRanError(f"拒绝执行：语句含写操作关键字 "
                         f"{_FORBIDDEN.search(sql).group(0)!r}")


# ---------------------------------------------------------------- SQL 模板
EPOCH_BASE = "TIMESTAMP '2000-01-01 00:00:00'"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def epoch_of(date_str: str) -> str:
    """把 YYYY-MM-DD 转成 L_T216.D027 的口径（自 2000-01-01 起的秒）。

    供 `sql_*` 模板与用户宽表（gp_ran_profile）共用，不要各处再拼一遍 EXTRACT。
    """
    if not _DATE_RE.match(date_str or ""):
        raise GpRanError(f"日期格式应为 YYYY-MM-DD，收到 {date_str!r}")
    return (f"EXTRACT(EPOCH FROM ('{date_str}'::TIMESTAMP - {EPOCH_BASE}))")


def _day_window(start: str, end: str) -> str:
    """左闭右开的时间窗：[start 00:00, end 00:00)。"""
    return f"A.D027 >= {epoch_of(start)} AND A.D027 < {epoch_of(end)}"


# D023 实测有大量空值（2026-10-19 单个 12h 分区：1985 万行里只有 297 万行非空），
# 不加这个条件，空串会被 DISTINCT 当成一个合法身份带进结果文件。
_HAS_ID = "A.D023 IS NOT NULL AND A.D023 <> ''"


def sql_volte_users(start: str, end: str) -> str:
    """VoLTE 用户身份清单（D023）。

    ⚠ D023 是 **IMSI**（618=利比里亚 MCC，样本长度均为 15 位），不是 MSISDN；
    要号码得另找 IMSI↔MSISDN 关联表，别把这份清单当电话列表用。

    ⚠ 与现场人工语句的两处差异（必须知道）：
    1. 人工版写 `WHERE C031=1 OR C032=1 OR C033=1 AND D027>x AND D027<y`，
       SQL 里 AND 优先级高于 OR，时间窗**只作用在 C033 那一支**，C031/C032 等于全历史
       —— 结果是「历史上出现过的所有身份」且要扫全表。这里补上括号。
    2. 人工版没排空值，这里排掉。
    """
    return ("SELECT DISTINCT A.D023 FROM L_T216 A "
            f"WHERE (A.C031 = 1 OR A.C032 = 1 OR A.C033 = 1) "
            f"AND {_day_window(start, end)} AND {_HAS_ID}")


def sql_n78_users(start: str, end: str) -> str:
    """N78 频段用户身份清单（D023，同样是 IMSI）。

    C043 实测是 `$` 分隔的频段列表（如 `1$3$7$8$20$28$38$40$41$78`），
    所以用 `$` 包裹做整词匹配是对的 —— 直接 `LIKE '%78%'` 会误命中 780、178 之类。
    """
    return ("SELECT DISTINCT A.D023 FROM L_T216 A "
            f"WHERE POSITION('$78$' IN '$'||A.C043||'$') > 0 "
            f"AND {_day_window(start, end)} AND {_HAS_ID}")


def _as_copy(sql: str) -> str:
    """把 SELECT 包成 COPY ... TO STDOUT WITH CSV HEADER（结果经 SSH 直接回本机）。"""
    return f"COPY ({sql.rstrip(';')}) TO STDOUT WITH (FORMAT csv, HEADER true)"


# ---------------------------------------------------------------- 客户端
class GpRanClient:
    """control1 -> GP 主节点 -> sudo -> su - gpadmin -> psql 的只读执行器。"""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, **overrides: Any) -> None:
        self.ep = resolve_endpoints({**(cfg or {}), **overrides})
        self._hop1: Optional[paramiko.SSHClient] = None
        self._hop2: Optional[paramiko.SSHClient] = None
        self.queries = 0
        self.seconds = 0.0

    # ---- 连接 ----
    def connect(self) -> "GpRanClient":
        if paramiko is None:
            raise GpRanUnavailable("缺少依赖 paramiko（requirements.txt 已声明，请 pip install）")
        ep = self.ep
        self._hop1 = self._ssh(ep["control_host"], ep["control_port"],
                               ep["control_user"], ep["control_password"], label="control1")
        try:
            sock = self._hop1.get_transport().open_channel(
                "direct-tcpip", (ep["master_host"], ep["master_port"]),
                ("127.0.0.1", 0), timeout=ep["connect_timeout"])
        except Exception as exc:  # noqa: BLE001
            raise GpRanUnavailable(
                f"经 control1 转发到 {ep['master_host']}:{ep['master_port']} 失败：{exc}") from exc
        self._hop2 = self._ssh(ep["master_host"], ep["master_port"], ep["master_user"],
                               ep["master_password"], sock=sock, label="gp_master")
        return self

    def _ssh(self, host: str, port: int, user: str, password: str,
             sock: Any = None, label: str = "") -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        # 第二跳的 host key 无法预先固化（主节点 IP 由 control1 上的 PaaS 决定），
        # 这里自动收录并把指纹打进日志：日后 key 变化会在日志里留下对比痕迹。
        client.set_missing_host_key_policy(_LogPolicy(label))
        try:
            client.connect(hostname=host, port=port, username=user, password=password,
                           sock=sock, timeout=ep_timeout(self.ep),
                           banner_timeout=ep_timeout(self.ep),
                           auth_timeout=ep_timeout(self.ep),
                           allow_agent=False, look_for_keys=False)
        except Exception as exc:  # noqa: BLE001
            raise GpRanUnavailable(
                f"{label} SSH 登录失败（{user}@{host}:{port}）：{type(exc).__name__}: {exc}") from exc
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
        return client

    def close(self) -> None:
        for attr in ("_hop2", "_hop1"):
            cli = getattr(self, attr, None)
            if cli is not None:
                try:
                    cli.close()
                except Exception:  # noqa: BLE001
                    logger.debug("[gp_ran] 关闭 %s 连接时异常", attr, exc_info=True)
            setattr(self, attr, None)

    def __enter__(self) -> "GpRanClient":
        return self.connect()

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False

    @property
    def connected(self) -> bool:
        return bool(self._hop2 and self._hop2.get_transport()
                    and self._hop2.get_transport().is_active())

    # ---- 执行 ----
    def _remote_psql(self, sql: str) -> str:
        """把 SQL base64 后在远端还原，喂给 psql 的标准输入。

        用 base64 是为了绕开三层 shell（sudo/su/psql）的引号嵌套 —— 这些 SQL 里
        全是单引号，直接拼进命令行会在某一层被截断，且报错点很难定位。

        刻意**不带 `--csv`**：现场这套 psql 不认该选项（实测 `psql: unrecognized option
        '--csv'`，`--csv` 是 PG 12 才加的，这里是 psql 9.4 / Greenplum 6），而 CSV 本来
        就该由 `COPY ... TO STDOUT` 自己产出，`-A -t -F,` 只是把 psql 的命令标签与对齐
        装饰去掉，让输出就是纯数据。
        """
        b64 = base64.b64encode(sql.encode("utf-8")).decode("ascii")
        db_flag = f'-d "{self.ep["database"]}" ' if self.ep.get("database") else ""
        psql = f'psql -X -A -t -F, -v ON_ERROR_STOP=1 {db_flag}-f -'
        inner = f"echo {b64} | base64 -d | {psql}"
        su_cmd = f'su - {self.ep["db_user"]} -c {chr(39)}{inner}{chr(39)}'
        return f'sudo -S -p "" {su_cmd}'

    def exec_sql(self, sql: str, timeout: Optional[int] = None) -> str:
        """执行只读 SQL，返回 stdout（CSV 文本）。失败抛 GpRanError。"""
        assert_readonly(sql)
        if not self.connected:
            raise GpRanUnavailable("未连接（先 connect() 或用 with 语句）")
        limit = int(timeout or self.ep["query_timeout"])
        t0 = time.time()
        out, err, rc = self._exec(self._remote_psql(sql), password=self.ep["master_password"],
                                  timeout=limit)
        self.queries += 1
        self.seconds += time.time() - t0
        if rc != 0:
            raise GpRanError(
                f"psql 退出码 {rc}（{time.time() - t0:.1f}s）：{(err or out).strip()[:800]}")
        return out

    def query_csv(self, sql: str, timeout: Optional[int] = None) -> str:
        """SELECT 自动包成 COPY TO STDOUT，返回带表头的 CSV 文本。"""
        return self.exec_sql(_as_copy(sql), timeout=timeout)

    def query_df(self, sql: str, timeout: Optional[int] = None):
        import pandas as pd
        text = self.query_csv(sql, timeout=timeout)
        return pd.read_csv(io.StringIO(text)) if text.strip() else pd.DataFrame()

    def raw(self, command: str, timeout: Optional[int] = None,
            sudo: bool = False) -> Tuple[str, str, int]:
        """在 GP 主节点上执行 shell（诊断用）。

        sudo=True 时命令包成 `sudo -S -p '' <command>` 并把口令喂进标准输入 —— 现场流程
        的 `cat /home/gpadmin/paas_hosts_master.cc` 这类步骤需要 root。
        默认走 ubuntu 身份，不升权。
        """
        if not self.connected:
            raise GpRanUnavailable("未连接")
        cmd = f'sudo -S -p "" {command}' if sudo else command
        return self._exec(cmd, password=self.ep["master_password"] if sudo else None,
                          timeout=int(timeout or 60))

    def _exec(self, command: str, password: Optional[str], timeout: int) -> Tuple[str, str, int]:
        import socket
        transport = self._hop2.get_transport()  # type: ignore[union-attr]
        chan = transport.open_channel("session")
        chan.settimeout(1.0)
        chan.exec_command(command)
        if password:
            # sudo -S 从标准输入读口令；psql 的 SQL 来自管道（base64 -d），两者不冲突
            chan.sendall((password + "\n").encode("utf-8"))
        try:
            chan.shutdown_write()
        except Exception:  # noqa: BLE001
            logger.debug("[gp_ran] shutdown_write 失败", exc_info=True)

        out, err = bytearray(), bytearray()
        deadline = time.time() + timeout
        while True:
            try:
                if chan.recv_ready():
                    out.extend(chan.recv(65536))
                    continue
                if chan.recv_stderr_ready():
                    err.extend(chan.recv_stderr(65536))
                    continue
            except socket.timeout:
                pass
            # 退出码就绪 **且** 两个缓冲都排空了才算完 —— 只看退出码会截掉尾部输出
            if chan.exit_status_ready() and not chan.recv_ready() \
                    and not chan.recv_stderr_ready():
                break
            if time.time() > deadline:
                chan.close()
                raise GpRanError(
                    f"远端命令超过 {timeout}s 未返回，已放弃等待"
                    f"（可加 --timeout 放宽；全天信令表扫描本来就慢）")
            time.sleep(0.05)
        rc = chan.recv_exit_status()
        chan.close()
        return (out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), rc)


class _LogPolicy(paramiko.MissingHostKeyPolicy):
    """自动收录未知 host key，并把指纹写进日志（不做静默信任）。"""

    def __init__(self, label: str = "") -> None:
        self.label = label

    def missing_host_key(self, client, hostname, key) -> None:  # noqa: D102
        import hashlib
        fp = hashlib.md5(key.asbytes()).hexdigest()
        logger.warning("[gp_ran] %s 首次连接 %s，收录 host key %s 指纹=%s",
                       self.label or "?", hostname, key.get_name(),
                       ":".join(fp[i:i + 2] for i in range(0, len(fp), 2)))
        client.get_host_keys().add(hostname, key.get_name(), key)


def ep_timeout(ep: Dict[str, Any]) -> float:
    try:
        return float(ep.get("connect_timeout") or DEFAULT_ENDPOINTS["connect_timeout"])
    except (TypeError, ValueError):
        return float(DEFAULT_ENDPOINTS["connect_timeout"])
