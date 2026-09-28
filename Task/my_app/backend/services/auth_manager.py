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
# 鉴权缓存目录（与本文件同级）
AUTH_CACHE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "auth_cache"
AUTH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 默认token有效期（秒），ZTE网管session一般30分钟~1小时
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
                 username: str, ttl: int = DEFAULT_TTL):
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
    """手动使缓存失效（当API返回401等鉴权失败时调用）。"""
    cache_file = _cache_file_path(host, port)
    if cache_file.exists():
        try:
            cache_file.unlink()
            logger.info(f"[AUTH] 缓存已清除 ({host}:{port})")
        except OSError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] invalidate_cache: exception swallowed", exc_info=True)
            pass


# ========== ZTE OAuth2 登录流程 ==========
def _do_login(host: str, port: int, username: str, password: str) -> dict:
    """
    执行 ZTE 网管 OAuth2 RSA 登录流程。
    返回 {"cookie": str, "forgery_token": str}
    """
    logger.info(f"[AUTH] 开始登录 {host}:{port} (用户: {username})")
    session_cookie = ""
    forgery_token = ""
    last_error = None

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

            # 提取 loginParameters
            html = body.decode('utf-8', errors='replace')
            lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
            login_parameters = lp_match.group(1) if lp_match else ""

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
            return {"cookie": session_cookie, "forgery_token": forgery_token}

        except Exception as e:
            last_error = e
            logger.warning(f"[AUTH] 登录尝试 {attempt} 失败: {e}")

    raise Exception(f"[AUTH] 登录最终失败 ({host}:{port}): {last_error}")


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
        ttl: token 有效期（秒），默认 1800
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
    _write_cache(host, port, result["cookie"], result["forgery_token"], username, ttl)

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
    args = parser.parse_args()

    t0 = time.time()
    auth = get_auth(args.host, args.port, args.user, args.password,
                    force_refresh=args.force)
    print(f"\n{'='*50}")
    print(f"来源: {'缓存' if auth['from_cache'] else '重新登录'}")
    print(f"Cookie: {auth['cookie'][:80]}...")
    print(f"Forgery: {auth['forgery_token'][:40]}...")
    print(f"总耗时: {time.time() - t0:.2f}s")
