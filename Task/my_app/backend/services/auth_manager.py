"""
auth_manager.py - 多任务共享鉴权管理模块
==========================================
多个RPA任务使用相同URL获取数据时，通过本地JSON文件缓存鉴权信息：
1. 第一个任务完成鉴权后，将 cookie/token 存储到本地 auth_cache 目录
2. 其他任务启动时，优先从缓存中获取已有的鉴权信息
3. 如果缓存不存在或已过期，再使用用户名密码重新鉴权
4. 避免同一账户同时登录导致互踢或登录冲突

用法:
    from auth_manager import get_auth
    from backend.services.credential_store import get_credential

    _user, _pass = get_credential("zte_ume")   # 口令不写在代码/文档里
    auth = get_auth(host="10.100.28.27", port=28001,
                    username=_user, password=_pass)
    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]
"""

import ssl
import socket
import sys
import json
import time
import re
import base64
import gzip
import os
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 跨平台文件锁
if sys.platform == 'win32':
    import msvcrt

    def _lock_shared(f):
        """Windows 共享锁（读）"""
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        except (IOError, OSError):
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _lock_shared: exception swallowed", exc_info=True)
            pass

    def _lock_exclusive(f):
        """Windows 排他锁（写）"""
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        except (IOError, OSError):
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _lock_exclusive: exception swallowed", exc_info=True)
            pass

    def _unlock(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except (IOError, OSError):
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _unlock: exception swallowed", exc_info=True)
            pass
else:
    import fcntl

    def _lock_shared(f):
        fcntl.flock(f, fcntl.LOCK_SH)

    def _lock_exclusive(f):
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:auth_manager>: exception swallowed", exc_info=True)
    pass

logger = logging.getLogger("auth_manager")

# ========== 配置 ==========
# ⚠ 本模块必须自己加载 .env，**不能**依赖 backend.database 的导入副作用。
#
# 原因（2026-10-04 实测）：`DEFAULT_TTL` 在**模块导入时求值**，而此前
# `auth_manager` 自己不调 load_dotenv，只在 `backend.database` 被先导入时
# 才"顺带"读到 `.env`。于是同一个环境变量会出现两种结果：
#     先 import backend.database → DEFAULT_TTL = 86400（读到了 .env）
#     直接 import auth_manager    → DEFAULT_TTL = 1800 （没读到）
# worker 是多进程（u/n/v/m/c），各进程导入顺序不受控 —— 一旦某个 worker
# 先碰 auth_manager，它的 TTL 就静默退回 30 分钟，于是"配了 1440 分钟却
# 仍然频繁登录"。这类"看起来配了、实际没生效"的问题极难现场定位。
# 自己加载后，无论谁先导入结果都一致。
try:
    from dotenv import load_dotenv as _load_dotenv

    # override=False：不覆盖已存在的环境变量（避免抢走 systemd/父进程显式传入的值，
    # 也避免多进程互相覆盖）；.env 不存在时静默跳过。
    _load_dotenv(Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / ".env",
                 override=False)
except ImportError:  # python-dotenv 未安装时退回纯环境变量，不中断导入
    logging.getLogger(__name__).warning(
        "[SILENT-EXCEPT] auth_manager: python-dotenv 不可用，AUTH_TOKEN_TTL 仅从环境变量读取"
    )

# 鉴权缓存目录（与本文件同级）
AUTH_CACHE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "auth_cache"
AUTH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 默认token有效期（秒）。由 .env 的 AUTH_TOKEN_TTL 配置（生产 86400 = 24 小时，
# 与 eFlow 自身的 Max Idle Time 1440 分钟一致，见 docs/manual/13-operations.md）。
DEFAULT_TTL = int(os.environ.get("AUTH_TOKEN_TTL", "1800"))

# 登录重试次数
MAX_RETRIES = 2


# ========== SSL / HTTP 底层 ==========
def _create_ssl_socket(host: str, port: int):
    """创建绕过证书校验的 TLS socket。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    ssock = ctx.wrap_socket(sock)
    ssock.connect((host, port))
    return ssock


def _decode_chunked(data: bytes) -> bytes:
    """解码 HTTP chunked 响应体。"""
    result = b""
    pos = 0
    while pos < len(data):
        line_end = data.find(b"\r\n", pos)
        if line_end == -1:
            break
        chunk_size_str = data[pos:line_end].decode('utf-8', errors='replace').strip()
        try:
            chunk_size = int(chunk_size_str, 16)
        except ValueError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _decode_chunked: exception swallowed", exc_info=True)
            break
        if chunk_size == 0:
            break
        pos = line_end + 2
        result += data[pos:pos + chunk_size]
        pos += chunk_size + 2
    return result


def _http_request(host: str, port: int, method: str, path: str,
                  headers_extra: str = None, body=None):
    """发送原始 HTTPS 请求，返回 (status_line, resp_headers, raw_header_text, resp_body)。"""
    ssock = _create_ssl_socket(host, port)

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: close\r\n"
        f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36\r\n"
    )
    if headers_extra:
        headers += headers_extra
    if body:
        headers += f"Content-Length: {len(body)}\r\n"
    headers += "\r\n"

    request_bytes = headers.encode('utf-8')
    if body:
        request_bytes += body if isinstance(body, bytes) else body.encode('utf-8')

    ssock.sendall(request_bytes)

    response_data = b""
    while True:
        try:
            chunk = ssock.recv(65536)
            if not chunk:
                break
            response_data += chunk
        except socket.timeout:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request: exception swallowed", exc_info=True)
            break
    ssock.close()

    header_end = response_data.find(b"\r\n\r\n")
    if header_end == -1:
        raise Exception("Cannot parse HTTP response")

    header_part = response_data[:header_end].decode('utf-8', errors='replace')
    resp_body = response_data[header_end + 4:]

    status_line = header_part.split("\r\n")[0]

    resp_headers = {}
    for line in header_part.split("\r\n")[1:]:
        if ": " in line:
            k, v = line.split(": ", 1)
            resp_headers[k.lower()] = v

    if "chunked" in resp_headers.get("transfer-encoding", ""):
        resp_body = _decode_chunked(resp_body)
    if "gzip" in resp_headers.get("content-encoding", ""):
        try:
            resp_body = gzip.decompress(resp_body)
        except Exception as exc:
            raise Exception(f"Failed to decompress gzip: {exc}")

    return status_line, resp_headers, header_part, resp_body


def _rsa_encrypt_pem(plaintext: str, public_key_b64: str) -> str:
    """使用 RSA 公钥加密（PKCS#1 v1.5），返回 base64 字符串。"""
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


# ========== 缓存读写（带文件锁） ==========
def _cache_file_path(host: str, port: int) -> Path:
    """根据 host:port 生成缓存文件路径。"""
    safe_name = f"{host}_{port}.json"
    return AUTH_CACHE_DIR / safe_name


def _read_cache(host: str, port: int) -> dict | None:
    """读取缓存的鉴权信息，如果不存在或已过期返回 None。"""
    cache_file = _cache_file_path(host, port)
    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            _lock_shared(f)
            data = json.load(f)
            _unlock(f)
    except (json.JSONDecodeError, IOError, OSError):
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _read_cache: exception swallowed", exc_info=True)
        return None

    # 检查过期
    created_at = data.get("created_at", "")
    expires_in = data.get("expires_in", DEFAULT_TTL)
    try:
        created_time = datetime.fromisoformat(created_at)
        if datetime.now(timezone.utc) - created_time > timedelta(seconds=expires_in):
            logger.info(f"[AUTH] 缓存已过期 ({host}:{port})")
            return None
    except (ValueError, TypeError):
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _read_cache: exception swallowed", exc_info=True)
        return None

    # 验证必要字段
    if not data.get("cookie") or not data.get("forgery_token"):
        return None

    return data


def _write_cache(host: str, port: int, cookie: str, forgery_token: str,
                 username: str, ttl: int = DEFAULT_TTL, auth_code: str = ""):
    """将鉴权信息写入缓存文件。

    用「临时文件 + os.replace」并带重试，扛 WPS云同步/Defender/索引服务瞬时锁：
    之前直接 open(..., 'w') 在目标被占用时抛 Permission denied，缓存写不进去，
    后续任务就会拿到过期 cookie → 401。
    """
    cache_file = _cache_file_path(host, port)
    data = {
        "host": host,
        "port": port,
        "username": username,
        "cookie": cookie,
        "forgery_token": forgery_token,
        # auth_code：登出接口 `POST /api/oauth2/v1/delete/login/remove` 的 payload
        # 需要它（`{"authCode":[<此值>]}`）。**它来自在线用户列表的行字段**
        # （由 _record_own_auth_code 在登录后取回，形如 `<长hex>$10`，len≈121），
        # **不是** authorize 页面的 loginParameters（len=225，实测登出无效），
        # 也**不是** Z-AUTH-CODE cookie（len=43 无后缀）。见文件顶部登出小节。
        "auth_code": auth_code or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_in": ttl,
    }
    tmp = cache_file.with_name(cache_file.name + f".{os.getpid()}.tmp")
    last_err = None
    for _attempt in range(46):
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(str(tmp), str(cache_file))
            logger.info(f"[AUTH] 鉴权信息已缓存 → {cache_file}")
            return
        except (IOError, OSError) as e:
            last_err = e
            time.sleep(2.0)
    if last_err is not None:
        logger.warning(f"[AUTH] 写入缓存失败(重试耗尽): {last_err}")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def invalidate_cache(host: str, port: int):
    """手动使缓存失效（当API返回401等鉴权失败时调用）。

    ⚠ 本函数**只删本地缓存文件，不发任何网络请求**——服务端会话依然存活。
    要真正释放服务端会话，用 logout()。
    """
    cache_file = _cache_file_path(host, port)
    if cache_file.exists():
        try:
            cache_file.unlink()
            logger.info(f"[AUTH] 缓存已清除 ({host}:{port})")
        except OSError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] invalidate_cache: exception swallowed", exc_info=True)
            pass


# ========== 登出（释放服务端会话） ==========
# 为什么需要它：本仓库此前**只登录、从不登出**，每次 401/TTL 过期后的"重新登录"
# 都会在上游网管侧新增一个**永不释放**的会话，旧会话只能等自己超时。
# 高频任务（如 sp_online_sync 每小时一轮）叠加短 TTL 后，会在上游堆积大量僵尸
# 会话 —— 这正是 2026-10-04「eFlow 用户数持续增长」的直接原因。
#
# ============ ✅ 2026-10-04 已解决：authCode 取值确定，登出真正生效 ============
# 结论（受控实验，务必先读，避免重复踩坑）：
#
#   1) 接口与必需请求头**已确认**：
#      POST /api/oauth2/v1/delete/login/remove
#      Body: {"authCode":["<值>"]}
#      请求头必须含 `forgerydefense: <会话 forgerydefense cookie 的值>`
#        —— 缺它一律 403 {"code":3329008,"message":"...prohibited for cross-site access"}。
#        实测 Referer/Origin 怎么组合都过不了，只有加这个头才返回 204。
#        注意**头名是不带端口后缀的裸 `forgerydefense`**（带 `-28001` 同样 403）。
#
#   2) ✅ **authCode 的正确取值已确定**：来自「在线用户列表」
#      POST /api/oauth2/v1/login/users 的**行字段** `authCode`（len≈121）。
#      `_record_own_auth_code` 在登录刚成功时取它并落盘。
#
#   3) ⚠ **不能用 authorize 页面的 `loginParameters`**（len=225）：
#      它同样以 `$10` 结尾、形状极像，但受控实验证明——
#        - 用 loginParameters 调 remove → 204，**该会话随后仍能 200**（没生效）
#        - 用列表行 authCode   调 remove → 204，**会话随即 401、并从列表消失**
#      2026-10-04 之前缓存里存的就是前者，所以「204 不代表成功」这个现象出现过。
#      **204 不是判据**：上游对无效 authCode 也无条件返回 204。
#      真正的判据是「登出后该会话再请求变 401」。
#
#   4) **"取最新一行"有竞态，必须用差集**：
#      admin 名下实测有 8 条会话，登录时刻彼此只差 18s / 81s / 116s
#      —— 多个 worker 的登录是交错的。等到登出时再"取最新一行"，
#      那一刻的最新行可能是**别的 worker 刚建的会话**，登出就会误杀别人。
#      所以：登录**前**拍该账户 authCode 快照，登录后取差集定位自己的行。
#
#   5) 上游对**连续批量**登出有短暂抖动：实测批量删到第 139 条时，
#      调用方会话瞬时 401（hasLogged:true），几秒后自愈 200。
#      程序化清理时建议**每 100 条暂停几秒**。
#
# `AUTH_LOGOUT_ENABLED` 默认仍为 False —— 不是"不可用"，而是"不默认开启"：
# 开启后每次登录会多两次上游请求（列表快照 + 定位），且登出会**主动销毁**会话，
# 影响面需要按部署场景评估。置 1 即为真正可用的登出：登录即释放、不再堆僵尸。
LOGOUT_PATH = os.environ.get(
    "AUTH_LOGOUT_PATH",
    "/api/oauth2/v1/delete/login/remove",
)
# 「在线用户列表」只读接口 —— 登出 authCode 的唯一正确来源（见 _record_own_auth_code）
LOGIN_USERS_PATH = os.environ.get(
    "AUTH_LOGIN_USERS_PATH",
    "/api/oauth2/v1/login/users",
)
LOGOUT_ENABLED = os.environ.get("AUTH_LOGOUT_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def _read_cached_auth_code(host: str, port: int) -> str:
    """从缓存文件读取登录时落盘的 authCode（登出 payload 用）。

    该值由 `_record_own_auth_code` 在登录后从「在线用户列表」取回并落盘，
    是**真正可用的**登出 authCode（len≈121）。

    注意：**不要**从 Z-AUTH-CODE cookie 推导 —— 实测两者不是同一个值
    （cookie len=43 无后缀；authCode len≈121 以 `$10` 结尾）。
    也**不要**回退去用 loginParameters（len=225）—— 见文件顶部第 3 条。
    """
    import json as _json
    p = _cache_file_path(host, port)
    if not p.exists():
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            return (_json.load(f).get("auth_code") or "").strip()
    except (IOError, OSError, ValueError):
        return ""


def logout(host: str, port: int, cookie: str = None, forgery_token: str = None,
           auth_code: str = None, clear_cache: bool = True) -> bool:
    """登出上游网管，释放服务端会话（可选同时清本地缓存）。

    默认**不启用**（`AUTH_LOGOUT_ENABLED` 未置位时直接返回 False 并记一条日志）。
    接口契约与 authCode 取值均已实测确认，置位 `AUTH_LOGOUT_ENABLED=1` 即为
    真正可用的登出（登录即释放、不再堆僵尸）—— 见文件顶部登出小节。

    Args:
        host/port: 上游网管地址。
        cookie: 要登出的会话；不传则读本地缓存里的 cookie。
        forgery_token: 上游跨站防护要求，缺它必 403（本接口**需要**它）。
        auth_code: 登出 payload 的 authCode；不传则读缓存里登录时落盘的值。
            **它必须来自在线用户列表，不是 loginParameters**，见 _record_own_auth_code。
        clear_cache: 登出成功后是否删掉本地缓存文件（默认 True —— 登出后缓存即失效）。

    Returns:
        True 表示上游返回 2xx **且**本地已清缓存；False 表示未启用/无会话/失败。
        任何异常都吞掉并记 warning：**登出失败不应阻断任务主流程**。

    ⚠ 成功判据：本函数以 2xx 为「已发出且被受理」。上游对**无效** authCode 也
      返回 204，所以 2xx **不等于**会话真被销毁。真正的端到端判据是
      「登出后该会话再请求变 401」，那需要调用方自测，本函数不做（会多打上游）。
    """
    if not LOGOUT_ENABLED:
        logger.debug(
            "[AUTH] 登出未启用（AUTH_LOGOUT_ENABLED 未置位），跳过 %s:%s", host, port,
        )
        return False

    # 取会话：优先用调用方传入的，否则回读缓存
    if not cookie or not auth_code:
        cached = _read_cache(host, port)
        if cached:
            cookie = cookie or cached.get("cookie", "")
            forgery_token = forgery_token or cached.get("forgery_token", "")
            auth_code = auth_code or (cached.get("auth_code") or "")
        # 登出通常发生在缓存刚失效时，_read_cache 会因过期返回 None；
        # 此时**绕过 TTL** 直接读文件，只为拿到 authCode/cookie 去释放服务端会话。
        if not auth_code:
            auth_code = _read_cached_auth_code(host, port)

    if not cookie:
        logger.info(f"[AUTH] 无会话可登出 ({host}:{port})")
        return False

    if not auth_code:
        # 没有 authCode 就无法让上游定位要销毁的会话 —— 宁可不发请求，
        # 也不要发一个必然 4xx 的假请求（那只会污染上游日志）。
        logger.info(
            f"[AUTH] 缓存中无 auth_code，跳过登出 ({host}:{port})；"
            "该会话将依赖上游自身超时回收"
        )
        return False

    body = json.dumps({"authCode": [auth_code]}, ensure_ascii=False).encode("utf-8")
    headers_extra = (
        f"Content-Type: application/json; charset=utf-8\r\n"
        f"Cookie: {cookie}\r\n"
        f"Accept: */*\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Origin: https://{host}:{port}\r\n"
        f"Referer: https://{host}:{port}/uportal/framework/default.html\r\n"
    )
    # ⚠ 必需：`forgerydefense` 头（值为会话里的 forgerydefense cookie）。
    # 缺它会被上游的跨站防护拒绝：
    #   403 {"message":"This request is prohibited for cross-site access","code":3329008}
    # 2026-10-04 实测：Referer/Origin 怎么组合都是 403，只有带上本头才返回 204。
    # **注意头名必须是不带端口后缀的裸 `forgerydefense`** —— 用
    # `forgerydefense-28001` 同样 403（cookie 名带后缀，但头名不带）。
    if forgery_token:
        headers_extra += f"forgerydefense: {forgery_token}\r\n"
    else:
        logger.info(
            f"[AUTH] 缺 forgerydefense，跳过登出 ({host}:{port})："
            "上游跨站防护会拒绝，发了也是 403"
        )
        return False

    try:
        status, _hdrs, _raw, _body = _http_request(
            host, port, "POST", LOGOUT_PATH, headers_extra=headers_extra, body=body,
        )
        # 实测成功为 **204 No Content**。
        # ⚠ 判据必须是「2xx 才算成功」：先前只排 5xx，于是 403 被误判为成功，
        #   让"登出没生效"看起来像"已登出"（2026-10-04 踩过，靠受控对照才发现）。
        code = status.split()[1] if len(status.split()) > 1 else "?"
        ok = code.startswith("2")
        if ok:
            logger.info(f"[AUTH] 已登出 {host}:{port}（{status.strip()}）")
            if clear_cache:
                invalidate_cache(host, port)
        else:
            logger.warning(
                f"[AUTH] 登出未生效 {status.strip()} ({host}:{port}) "
                f"—— 会话仍在上游存活"
            )
        return ok
    except Exception as e:
        # 登出失败绝不能阻断任务：会话交给上游超时回收即可
        logger.warning(f"[AUTH] 登出失败（忽略）{host}:{port}: {e}")
        return False


# ========== ZTE OAuth2 登录流程 ==========
def _do_login(host: str, port: int, username: str, password: str) -> dict:
    """
    执行 ZTE 网管 OAuth2 RSA 登录流程。
    返回 {"cookie": str, "forgery_token": str, "auth_code": str}

    `auth_code` 是**登出接口 payload 需要的值**，它在登录成功之后由
    `_record_own_auth_code` 从「在线用户列表」取回（形如 `<长hex>$10`，len≈121）。

    ⚠ 不要误用第 1 步 authorize 页面的 `loginParameters`：它形状极像
    （同样以 `$10` 结尾）但 len=225，实测登出**无效**（返回 204 但会话不死）。
    ⚠ 也**不是** Z-AUTH-CODE cookie（cookie 值 len=43 且无 `$` 后缀）。
    """
    logger.info(f"[AUTH] 开始登录 {host}:{port} (用户: {username})")
    session_cookie = ""
    forgery_token = ""
    auth_code = ""
    last_error = None

    # 登录前拍快照：该账户当前已有的会话 authCode。
    # 登录后取差集就能**确定**找出自己刚建的那一行（见 _record_own_auth_code）。
    # 只在已有可用会话时拍（列表接口需要鉴权）；拍不到就拿空集，
    # 退化为"登录后该账户的新增行"，仍然比"取最新一行"可靠。
    _pre_codes = set()
    if LOGOUT_ENABLED:
        try:
            _c = _read_cache(host, port)
            if _c:
                _pre_codes = _snapshot_auth_codes(
                    host, port, username, _c.get("cookie", ""), _c.get("forgery_token", ""))
        except Exception as e:
            logger.debug(f"[AUTH] 登录前会话快照失败（不影响登录）: {e}")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                wait = 2 ** (attempt - 1)
                logger.info(f"[AUTH] 第 {attempt}/{MAX_RETRIES} 次尝试，等待 {wait}s...")
                time.sleep(wait)

            # Step 1: 获取授权页 Cookie + loginParameters
            status, hdrs, raw_hdrs, body = _http_request(
                host, port, "GET",
                "/api/oauth2/v1/authorize?scope=user.login&response_type=code"
                "&redirect_uri=/uportal/framework/default.html"
            )

            init_cookies = []
            for line in raw_hdrs.split("\r\n"):
                if line.lower().startswith("set-cookie:"):
                    cookie_val = line.split(": ", 1)[1].split(";")[0]
                    if cookie_val.split("=")[1]:
                        init_cookies.append(cookie_val)
                        if "forgerydefense" in cookie_val:
                            forgery_token = cookie_val.split("=", 1)[1]

            init_cookie_str = "; ".join(init_cookies)

            # 提取 loginParameters（登出**不能**用它 —— 见下方 _record_own_auth_code）
            html = body.decode('utf-8', errors='replace')
            lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
            login_parameters = lp_match.group(1) if lp_match else ""
            if login_parameters:
                auth_code = login_parameters

            # Step 2: 获取 RSA 公钥
            rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
            status, hdrs, raw_hdrs, body = _http_request(
                host, port, "GET", "/api/oauth2/v1/login/publickey",
                headers_extra=rsa_headers,
            )

            public_key_b64 = ""
            if "200" in status:
                pk_data = json.loads(body.decode('utf-8'))
                public_key_b64 = pk_data.get("rsaPublicKey", "")

            if not public_key_b64:
                # 回退：从 HTML 中提取
                pk_match = re.search(r'var\s+publicKey\s*=\s*["\']([^"\']+)["\']', html)
                if pk_match:
                    public_key_b64 = pk_match.group(1)

            if not public_key_b64:
                raise Exception("无法获取 RSA 公钥")

            # Step 3: RSA 加密密码
            encrypted_pwd = _rsa_encrypt_pem(password, public_key_b64)

            # Step 4: 提交登录
            login_payload = json.dumps({
                "username": username,
                "password": encrypted_pwd,
                "parameters": login_parameters,
            })

            login_headers = (
                f"Content-Type: application/json\r\n"
                f"Cookie: {init_cookie_str}\r\n"
                f"Referer: https://{host}:{port}/api/oauth2/v1/authorize?"
                f"scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html\r\n"
                f"X-Requested-With: XMLHttpRequest\r\n"
            )
            if forgery_token:
                login_headers += f"forgerydefense: {forgery_token}\r\n"

            status, hdrs, raw_hdrs, body = _http_request(
                host, port, "POST", "/api/oauth2/v1/login_rsa",
                headers_extra=login_headers, body=login_payload,
            )

            # 收集登录后的 Cookie
            cookies = list(init_cookies)
            for line in raw_hdrs.split("\r\n"):
                if line.lower().startswith("set-cookie:"):
                    cookie_val = line.split(": ", 1)[1].split(";")[0]
                    if cookie_val.split("=")[1]:
                        cookie_name = cookie_val.split("=")[0]
                        cookies = [c for c in cookies if not c.startswith(cookie_name + "=")]
                        cookies.append(cookie_val)
                        if "forgerydefense" in cookie_val:
                            forgery_token = cookie_val.split("=", 1)[1]

            session_cookie = "; ".join(cookies)

            # 验证登录成功
            if not any("Z-AUTH-CODE" in c for c in cookies):
                raise Exception("登录失败 - 未获取到 Z-AUTH-CODE cookie")

            logger.info(f"[AUTH] 登录成功 ({len(cookies)} cookies)")

            # 取**真正可用的**登出 authCode（在线列表行的值，len≈121）。
            # 失败不影响登录：宁可登出时跳过，也不拿一个必然 204-but-无效 的值。
            if LOGOUT_ENABLED:
                real_ac = _record_own_auth_code(
                    host, port, username, session_cookie, forgery_token, _pre_codes)
                if real_ac:
                    auth_code = real_ac
                    logger.info(f"[AUTH] 已记录本会话登出 authCode (len={len(real_ac)})")
                else:
                    auth_code = ""  # 明确置空：登出时据此跳过，不拿旧值去猜

            return {
                "cookie": session_cookie,
                "forgery_token": forgery_token,
                "auth_code": auth_code,
            }

        except Exception as e:
            last_error = e
            logger.warning(f"[AUTH] 登录尝试 {attempt} 失败: {e}")

    raise Exception(f"[AUTH] 登录最终失败 ({host}:{port}): {last_error}")


def _list_login_users(host: str, port: int, cookie: str, forgery_token: str) -> list:
    """读取上游「在线用户列表」（只读，无副作用）。

    这是**唯一**能拿到有效登出 authCode 的地方 —— 见本文件顶部登出小节。

    Returns:
        行列表（每行含 username / loginIp / loginTime / authCode）；失败返回 []。
    """
    body = json.dumps({
        "pageNo": 1, "pageSize": 500, "searchName": "", "searchIp": "",
        "sort": {"key": "", "type": ""},
    }, ensure_ascii=False).encode("utf-8")
    headers_extra = (
        f"Content-Type: application/json; charset=utf-8\r\n"
        f"Cookie: {cookie}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"language-option: en-US\r\n"
        f"Origin: https://{host}:{port}\r\n"
        f"Referer: https://{host}:{port}/iui/sm/page/index.html\r\n"
    )
    if forgery_token:
        headers_extra += f"forgerydefense: {forgery_token}\r\n"
    try:
        _status, _hdrs, _raw, raw = _http_request(
            host, port, "POST", LOGIN_USERS_PATH, headers_extra=headers_extra, body=body,
        )
        data = json.loads(raw.decode("utf-8", "ignore"))
    except Exception as e:
        logger.warning(f"[AUTH] 读取在线用户列表失败（忽略）{host}:{port}: {e}")
        return []
    rows = data.get("data") if isinstance(data, dict) else data
    return rows if isinstance(rows, list) else []


def _snapshot_auth_codes(host: str, port: int, username: str,
                         cookie: str, forgery_token: str) -> set:
    """登录前拍一张"该账户已有会话的 authCode"快照，供登录后取差集。"""
    rows = _list_login_users(host, port, cookie, forgery_token)
    return {r.get("authCode") for r in rows if r.get("username") == username}


def _record_own_auth_code(host: str, port: int, username: str,
                          cookie: str, forgery_token: str, before: set) -> str:
    """登录**刚成功**时调用：查在线列表，找出「刚建的那一行」的 authCode。

    为什么要在登录后立刻查、而不是登出时再查：
        admin 名下实测有 8 条会话，登录时刻彼此只差 18s / 81s / 116s
        —— 多个 worker 的登录是交错的。若等到**登出时**才"取最新一行"，
        那一刻的最新行很可能是别的 worker 刚建的会话，登出就会**误杀别人**。
        刚登录完这个瞬间，"自己是最新的"这件事竞态窗口最小。

    为什么不能直接用缓存里的 auth_code：
        那是 authorize 页面的 `loginParameters`（len=225）。2026-10-04 受控实验：
        用它调 remove → 上游返回 204，但**该会话随后仍能 200**（登出没生效）；
        而用列表行的 authCode（len=121）→ 会话随即 401 且从列表消失。
        两者形状相似（都以 `$10` 结尾）但**长度差近一倍、语义不同**。

    Args:
        before: 登录前该账户名下已有的 authCode 集合（见 _snapshot_auth_codes），
            登录后取差集即自己的行 —— 比"取最新一行"可靠，不易误伤并发登录。

    Returns:
        自己的 authCode；定位不到时返回 ""（调用方据此跳过登出，**不猜**）。
    """
    try:
        rows = _list_login_users(host, port, cookie, forgery_token)
        mine = [r for r in rows
                if r.get("username") == username and r.get("authCode") not in before]
        if not mine:
            logger.info(
                f"[AUTH] 在线列表中未找到本次登录的会话 ({username}@{host}:{port})，"
                "登出将跳过（宁可不登出，也不误删别人的会话）"
            )
            return ""
        mine.sort(key=lambda r: r.get("loginTime") or 0, reverse=True)
        return mine[0].get("authCode") or ""
    except Exception as e:
        logger.warning(f"[AUTH] 定位本次登录会话失败（忽略）{host}:{port}: {e}")
        return ""


# ========== 对外主接口 ==========
def get_auth(host: str, port: int, username: str, password: str,
             ttl: int = DEFAULT_TTL, force_refresh: bool = False) -> dict:
    """
    获取鉴权信息（优先从缓存读取，缓存无效则重新登录）。

    Args:
        host: 网管系统 IP
        port: 端口
        username: 用户名
        password: 密码
        ttl: token 有效期（秒），默认取 DEFAULT_TTL（即 AUTH_TOKEN_TTL，
            默认 1800；2026-10-04 起生产环境设为 86400 = 24 小时，见 backend/.env）
        force_refresh: 强制重新登录（忽略缓存）

    Returns:
        {"cookie": str, "forgery_token": str, "from_cache": bool}
    """
    start_time = time.time()

    # 1. 尝试从缓存获取
    if not force_refresh:
        cached = _read_cache(host, port)
        if cached:
            elapsed = time.time() - start_time
            logger.info(f"[AUTH] 使用缓存鉴权 ({host}:{port})，耗时 {elapsed:.2f}s")
            return {
                "cookie": cached["cookie"],
                "forgery_token": cached["forgery_token"],
                "from_cache": True,
            }

    # 2. 缓存无效，执行登录
    result = _do_login(host, port, username, password)

    # 3. 写入缓存
    _write_cache(host, port, result["cookie"], result["forgery_token"], username, ttl,
                 auth_code=result.get("auth_code", ""))

    elapsed = time.time() - start_time
    logger.info(f"[AUTH] 重新登录完成 ({host}:{port})，耗时 {elapsed:.2f}s")
    return {
        "cookie": result["cookie"],
        "forgery_token": result["forgery_token"],
        "from_cache": False,
    }


# ========== 便捷入口（独立运行测试） ==========
if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="ZTE 网管鉴权管理")
    parser.add_argument("--host", default="10.100.28.27")
    parser.add_argument("--port", type=int, default=28001)
    # 命令行未指定时，从凭据存储读取（环境变量 > 数据库 > 默认值）
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        try:
            from credential_store import get_credential
        except ImportError:
            get_credential = None
    if get_credential:
        _def_user, _def_pass = get_credential("zte_ume")
    else:
        # credential_store 不可用时只回退用户名，口令留空由 --pass 显式传入。
        # 2026-09-27：原先这里回退硬编码口令字面量（已入库），已删除。
        _def_user, _def_pass = "NOC", ""
    parser.add_argument("--user", default=_def_user)
    parser.add_argument("--pass", dest="password", default=_def_pass)
    parser.add_argument("--force", action="store_true", help="强制重新登录")
    parser.add_argument("--logout", action="store_true",
                        help="登出（释放服务端会话）；需 AUTH_LOGOUT_ENABLED=1 才真正发请求")
    parser.add_argument("--logout-path", default=None,
                        help=f"覆盖登出路径（默认 {LOGOUT_PATH}）")
    args = parser.parse_args()

    if args.logout:
        # 本块是 `if __name__ == "__main__"` 的模块级代码，直接赋值即改模块全局，
        # 因此**不需要** global 声明（且此处加 global 会与上面 f-string 里的
        # LOGOUT_PATH 引用冲突，触发 "used prior to global declaration"）。
        if args.logout_path:
            LOGOUT_PATH = args.logout_path
        print(f"登出 {args.host}:{args.port}")
        print(f"  路径      : {LOGOUT_PATH}")
        print(f"  已启用    : {LOGOUT_ENABLED}"
              f"{'' if LOGOUT_ENABLED else '  ← 未启用，请置 AUTH_LOGOUT_ENABLED=1'}")
        ok = logout(args.host, args.port)
        print(f"  结果      : {'已登出' if ok else '未执行/失败（详见日志）'}")
        # 模块级代码不能用 return，直接退出（0 = 已尝试登出，细节见日志）
        raise SystemExit(0)

    t0 = time.time()
    auth = get_auth(args.host, args.port, args.user, args.password,
                    force_refresh=args.force)
    print(f"\n{'='*50}")
    print(f"来源: {'缓存' if auth['from_cache'] else '重新登录'}")
    print(f"Cookie: {auth['cookie'][:80]}...")
    print(f"Forgery: {auth['forgery_token'][:40]}...")
    print(f"总耗时: {time.time() - t0:.2f}s")
