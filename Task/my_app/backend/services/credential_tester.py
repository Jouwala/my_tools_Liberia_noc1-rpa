"""
credential_tester.py - 凭据「连接测试」的按系统分发实现
=======================================================
背景：设置页（`/myapp/?page=settings` → 凭据）原先只有 ZTE UME 系 / eFlow /
RAIS 几组带「连接测试」按钮，其余组（VMAX CXO、GBase 数仓、Greenplum、
UME 服务器网管、UMC、SFTP、126 邮箱、OWA 邮箱、微信推送）只能"保存后等任务跑
才知道对不对"。本模块把**每一组都接上各自系统的真实登录/连通性检查**。

设计约定
--------
1. **一个组一个 `_test_*` 函数**，签名统一：`(group, user, pwd, en) -> (ok, msg)`。
   `group` 是 `credential_store.CREDENTIAL_GROUPS` 里的那一条（可拿 test_host /
   test_port），`user` / `pwd` 是**当前生效**的凭据（由调用方从
   `get_credential()` 取好后传入，本模块不再读库，便于测"刚保存的值"）。
2. **不做依赖兜底**：缺 `paramiko` / `pymysql` / `exchangelib` / `cryptography`
   就明确报"缺少依赖"，不静默降级成"看起来通过"的假测试 —— 假成功比不测更糟。
3. **每个测试都自带超时**（默认 20s），避免设置页把后端线程挂死。
4. **不写敏感值**到日志/消息：只回账号名、主机端口、服务端版本这类非敏感信息；
   口令只用于当次连接，绝不出现在返回值里。
5. 有**会话配额**的系统（VMAX CXO 门户按用户限并发）测试完主动登出/关闭连接。

分发方式：`credential_store` 每条记录带 `test_kind`，本模块用 `TESTERS` 字典
按 kind 找函数；`test_kind` 为 `zte_oauth2` / `rais` 的仍走
`routers/credentials.py` 里既有的 auth_manager 路径（那两条带本地熔断与
终态错误判定，逻辑不适合搬到这里）。
"""
from __future__ import annotations

import base64
import json
import logging
import smtplib
import socket
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

# 测试地址解析（配置 > env > 内置默认）。credential_store 不反向依赖本模块，
# 无循环导入风险。
from backend.services.credential_store import resolve_endpoint

logger = logging.getLogger(__name__)

# 单组测试默认超时（秒）。所有 _test_* 都必须显式设超时，不许裸等。
DEFAULT_TIMEOUT = 20

# kind -> 测试函数
TESTERS: Dict[str, Callable[[dict, str, str, bool], Tuple[bool, str]]] = {}


def _disp(en: bool, zh: str, en_txt: str) -> str:
    """按语言挑文案（本模块消息量小，直接内联中英，不再走前端字典）。"""
    return en_txt if en else zh


def _register(kind: str):
    """装饰器：把一个 _test_* 函数登记到 TESTERS。"""
    def deco(fn):
        TESTERS[kind] = fn
        return fn
    return deco


def _safe_close(obj: Any) -> None:
    """关连接，失败也不许影响测试结果。"""
    try:
        if obj is None:
            return
        close = getattr(obj, "close", None)
        if callable(close):
            close()
    except Exception:  # noqa: BLE001
        pass


# ==================================================================
# VMAX CXO 经营看板门户（RSA 加密口令 + JSESSIONID）
# ==================================================================
@_register("vmax_portal")
def _test_vmax_cxo(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """复刻 tools/realtime_proxy_vmax.py 的登录：取公钥 → PKCS#1 v1.5 加密 →
    POST /web/res/web-common/login，判 `result == 1`。

    注意：门户**网页**登录有图形验证码，但这条**接口**链路不需要，
    所以可以做全自动测试。测完调 logout 释放会话（门户按用户限并发）。
    """
    host, port = group.get("test_host"), group.get("test_port")
    base = f"https://{host}:{port}"
    try:
        import requests  # noqa: WPS433
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"缺少依赖: {e}", f"Missing dependency: {e}")

    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:  # noqa: BLE001
        pass

    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    try:
        r = sess.get(
            base + "/rdk/service/app/portal/server/loginAuthenticate",
            headers={"Referer": base + "/rdk/app/portal/web/"},
            timeout=DEFAULT_TIMEOUT, verify=False,
        )
        cfg = r.json()
        pem = (cfg or {}).get("publicKey") or ""
        if not pem:
            return False, _disp(en, "未取到登录公钥（门户返回异常）",
                                "Login public key missing (unexpected portal response)")
        pub = serialization.load_pem_public_key(
            ("-----BEGIN PUBLIC KEY-----\n" + pem + "\n-----END PUBLIC KEY-----\n").encode()
        )
        enc = base64.b64encode(pub.encrypt(pwd.encode("utf-8"), padding.PKCS1v15())).decode()
        resp = sess.post(
            base + "/web/res/web-common/login",
            data={"username": user, "password": enc, "isEncypted": "true"},
            timeout=DEFAULT_TIMEOUT, verify=False,
        )
        j = resp.json()
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"连接/登录失败: {type(e).__name__}: {e}",
                            f"Connect/login failed: {type(e).__name__}: {e}")
    finally:
        try:
            sess.get(base + "/rdk/service/app/portal/server/logout", timeout=8, verify=False)
        except Exception:  # noqa: BLE001
            pass

    if j.get("result") == 1:
        return True, _disp(en, f"登录成功（账号 {user} @ {host}:{port}）",
                           f"Login succeeded (account {user} @ {host}:{port})")
    return False, _disp(
        en,
        f"登录被拒绝（result={j.get('result')}）：{str(j)[:200]}",
        f"Login rejected (result={j.get('result')}): {str(j)[:200]}",
    )


# ==================================================================
# VMAX 数仓 GBase 8a（MySQL 协议，只读）
# ==================================================================
@_register("gbase")
def _test_vmax_gbase(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """复用 vmax_gbase_client：连上后跑 `SELECT VERSION()/CURRENT_USER()` 即算通过。

    走客户端自身的 `healthy()` —— 它内部会 connect，且只发只读语句，
    不会在数仓上留下任何写入。
    """
    try:
        from backend.services.vmax_gbase.vmax_gbase_client import VmaxGbaseClient
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"客户端导入失败: {e}", f"Client import failed: {e}")
    cli = None
    try:
        cli = VmaxGbaseClient()
        ok, info = cli.healthy()
        return bool(ok), str(info)
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"连接失败: {type(e).__name__}: {e}",
                            f"Connection failed: {type(e).__name__}: {e}")
    finally:
        _safe_close(cli)


# ==================================================================
# RAN Greenplum：control1 跳板（SSH）
# ==================================================================
@_register("ssh")
def _test_gp_ran_control(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """paramiko 口令登录 control1。

    ⚠ 这一组**不能**走 auth_manager 的 OAuth2 登录（那是 ZTE 网管 HTTP 登录，
    打 22 端口必然失败）—— 2026-10-21 修正：此前它 `testable=True` 却走
    `_do_login(host, 22, ...)`，按钮一直是"登录失败"的假阴性。
    """
    try:
        import paramiko  # noqa: WPS433
        from backend.services.gp_ran.gp_ran_client import resolve_endpoints
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"缺少依赖/导入失败: {e}", f"Missing dependency/import failed: {e}")
    try:
        ep = resolve_endpoints()
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"连接参数解析失败: {e}", f"Endpoint resolution failed: {e}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=ep["control_host"], port=int(ep["control_port"]),
            username=ep["control_user"], password=ep["control_password"],
            timeout=DEFAULT_TIMEOUT, banner_timeout=DEFAULT_TIMEOUT,
            auth_timeout=DEFAULT_TIMEOUT, allow_agent=False, look_for_keys=False,
        )
        return True, _disp(
            en,
            f"SSH 登录成功（{ep['control_user']}@{ep['control_host']}:{ep['control_port']}）",
            f"SSH login succeeded ({ep['control_user']}@{ep['control_host']}:{ep['control_port']})",
        )
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"SSH 登录失败: {type(e).__name__}: {e}",
                            f"SSH login failed: {type(e).__name__}: {e}")
    finally:
        _safe_close(client)


# ==================================================================
# RAN Greenplum 主节点（经 control1 转发，本机不可直连）
# ==================================================================
@_register("ssh_via_control")
def _test_gp_ran_master(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """两跳 SSH：本机 → control1 → GP 主节点。

    主节点从本机直连是超时的（193.168.0.6 只在内网），所以必须借 control1 转发。
    这也意味着测这一组时 control1 的凭据必须同时有效 —— 报的是**第二跳**的结果。
    """
    try:
        from backend.services.gp_ran.gp_ran_client import GpRanClient
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"客户端导入失败: {e}", f"Client import failed: {e}")
    cli = None
    try:
        cli = GpRanClient()
        cli.connect()
        ep = cli.ep
        return True, _disp(
            en,
            f"经 control1 转发登录主节点成功（{ep['master_user']}@{ep['master_host']}）",
            f"Master login via control1 succeeded ({ep['master_user']}@{ep['master_host']})",
        )
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"登录主节点失败: {type(e).__name__}: {e}",
                            f"Master login failed: {type(e).__name__}: {e}")
    finally:
        _safe_close(cli)


# ==================================================================
# ZTE UME 服务器网管（Keystone v3 → 项目 token）
# ==================================================================
@_register("ume_keystone")
def _test_ume_alarm(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """走 ume_alarm_client.login(force_refresh=True)：RSA 加密 → Keystone v3
    换未 scoped token → 换项目 token。拿到项目 token 才算通过。

    `force_refresh=True` 是故意的：本函数要验的是**当前输入框里的凭据**，
    走缓存会拿一份旧会话说"通过"，把问题掩盖到任务跑起来才暴露。
    """
    try:
        from backend.services.ume_alarm_client import login as ume_login
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"客户端导入失败: {e}", f"Client import failed: {e}")
    host, port = group.get("test_host"), group.get("test_port")
    try:
        sess = ume_login(force_refresh=True)
        tok = (sess or {}).get("project_token") or ""
        if not tok:
            return False, _disp(en, "登录未返回项目 token", "Login returned no project token")
        return True, _disp(
            en,
            f"Keystone v3 登录成功（{user} @ {host}:{port}，项目 token {len(tok)} 字符）",
            f"Keystone v3 login succeeded ({user} @ {host}:{port}, project token {len(tok)} chars)",
        )
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"登录失败: {type(e).__name__}: {e}",
                            f"Login failed: {type(e).__name__}: {e}")


# ==================================================================
# FW 整机吞吐（DPtech 经典 UMC）
# ==================================================================
@_register("umc_portal")
def _test_fw_kpi(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """复用 fw_kpi_services 的 `Session + login()`：code.jsp → 登录页取 cn/cp/c_form
    → Node 跑服务器原版 e.js 算 strEnc/SM3 → POST Login.action。

    依赖本机 Node（与 fw_kpi_sync 任务同一依赖）；缺 Node 会明确报错。
    """
    try:
        from backend.services.fw_kpi.fw_kpi_services import Session, login as umc_login
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"客户端导入失败: {e}", f"Client import failed: {e}")
    try:
        sess = Session()
        umc_login(sess)
        return True, _disp(
            en,
            f"UMC 登录成功（账号 {user} @ {group.get('test_host')}:{group.get('test_port')}）",
            f"UMC login succeeded ({user} @ {group.get('test_host')}:{group.get('test_port')})",
        )
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"UMC 登录失败: {type(e).__name__}: {e}",
                            f"UMC login failed: {type(e).__name__}: {e}")


# ==================================================================
# SFTP 备件报表服务器
# ==================================================================
def _sftp_host_port() -> Tuple[str, int]:
    """主机/端口从 sp_sftp_config.json 读（与 get_sp_table 同源），读不到用内置默认。

    不 `import get_sp_table` —— 它模块级就拉 pandas 与 database，
    为了两个常量把重量级依赖拖进 Web 进程不划算。
    """
    host, port = "10.100.20.11", 22
    try:
        from backend.services.task_config_files import load_json_config
        conf = load_json_config(
            Path(__file__).resolve().parent / "sp_sftp_config.json") or {}
        host = conf.get("sftp_host") or host
        port = int(conf.get("sftp_port") or port)
    except Exception:  # noqa: BLE001
        pass
    return host, port


@_register("sftp")
def _test_sftp_sp(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """paramiko Transport 口令认证 + 开 SFTP 通道 + normalize('.') 取主目录。

    只列目录、不下载任何文件，对上游只读。
    """
    try:
        import paramiko  # noqa: WPS433
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"缺少依赖 paramiko: {e}", f"Missing dependency paramiko: {e}")
    host, port = _sftp_host_port()
    sock = None
    trans = None
    try:
        sock = socket.create_connection((host, port), timeout=DEFAULT_TIMEOUT)
        trans = paramiko.Transport(sock)
        trans.banner_timeout = DEFAULT_TIMEOUT
        trans.start_client(timeout=DEFAULT_TIMEOUT)
        trans.auth_password(user, pwd)
        if not trans.is_authenticated():
            return False, _disp(en, "SFTP 认证未通过", "SFTP authentication failed")
        sftp = paramiko.SFTPClient.from_transport(trans)
        if sftp is None:
            return False, _disp(en, "SFTP 通道建立失败", "SFTP channel could not be opened")
        home = sftp.normalize(".")
        return True, _disp(
            en,
            f"SFTP 登录成功（{user}@{host}:{port}，主目录 {home}）",
            f"SFTP login succeeded ({user}@{host}:{port}, home {home})",
        )
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"SFTP 登录失败: {type(e).__name__}: {e}",
                            f"SFTP login failed: {type(e).__name__}: {e}")
    finally:
        _safe_close(trans)
        _safe_close(sock)


# ==================================================================
# 126 邮箱（SMTP 授权码）
# ==================================================================
@_register("smtp")
def _test_mail_126(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """SMTP_SSL + login，不发信。

    只做 AUTH 握手 —— 发一封测试信会污染收件箱，而我们要验的只是"授权码对不对"。
    """
    try:
        from backend.services.email_notifier import SMTP_SERVER, SMTP_PORT
    except Exception:  # noqa: BLE001
        SMTP_SERVER, SMTP_PORT = "smtp.126.com", 465
    srv = None
    try:
        srv = smtplib.SMTP_SSL(SMTP_SERVER, int(SMTP_PORT), timeout=DEFAULT_TIMEOUT)
        srv.login(user, pwd)
        return True, _disp(
            en,
            f"SMTP 登录成功（{user} @ {SMTP_SERVER}:{SMTP_PORT}）",
            f"SMTP login succeeded ({user} @ {SMTP_SERVER}:{SMTP_PORT})",
        )
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"SMTP 登录失败: {type(e).__name__}: {e}",
                            f"SMTP login failed: {type(e).__name__}: {e}")
    finally:
        try:
            if srv is not None:
                srv.quit()
        except Exception:  # noqa: BLE001
            _safe_close(srv)


# ==================================================================
# Exchange / OWA 邮箱（EWS）
# ==================================================================
@_register("ews")
def _test_owa_mail(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """exchangelib 登 EWS，取收件箱总数当探活（GetFolder 会真正走一次鉴权）。

    复用 mailbox_cleanup.get_account()：它已按凭据库优先级取账号口令，
    与 owa_mail_report / 邮箱清理任务完全同源，不会出现"测的和跑的不是一个配置"。
    """
    import os
    try:
        from backend.services.mailbox_cleanup import get_account
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"客户端导入失败（可能缺 exchangelib）: {e}",
                            f"Client import failed (exchangelib missing?): {e}")
    try:
        acct = get_account()
        total = acct.inbox.total_count
        server = os.getenv("MAILBOX_SERVER", "exchmail.orange-cit.ci")
        return True, _disp(
            en,
            f"EWS 登录成功（{user} @ {server}，收件箱 {total} 封）",
            f"EWS login succeeded ({user} @ {server}, inbox {total} items)",
        )
    except Exception as e:  # noqa: BLE001
        return False, _disp(en, f"EWS 登录失败: {type(e).__name__}: {e}",
                            f"EWS login failed: {type(e).__name__}: {e}")


# ==================================================================
# 微信 / IM 推送（Server酱 SendKey + PushPlus Token）
# ==================================================================
def _post_json(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


@_register("weixin_push")
def _test_weixin(group: dict, user: str, pwd: str, en: bool) -> Tuple[bool, str]:
    """本组两个字段是两个平台的凭据：`user` = Server酱 SendKey，`pwd` = PushPlus Token。

    ⚠ 这两个平台都没有"只验 token 不发消息"的接口，所以测试**会真的推送一条**。
    这是本组唯一能证明 token 有效的手段，界面提示里必须说清楚。
    哪一项填了就测哪一项，没填的不测（不算失败）。
    """
    sendkey = (user or "").strip()
    token = (pwd or "").strip()
    if not sendkey and not token:
        return False, _disp(en, "Server酱 SendKey 与 PushPlus Token 均为空，无可测试项",
                            "Both ServerChan SendKey and PushPlus Token are empty")

    title = _disp(en, "【my_app】凭据连接测试", "[my_app] Credential test")
    parts: list = []
    ok_all = True

    if token:
        try:
            body = _post_json(
                "http://www.pushplus.plus/send",
                {"token": token, "title": title,
                 "content": _disp(en, "这是一条来自「设置 → 凭据」的连接测试消息，收到即表示 Token 有效。",
                                  "Connectivity test from Settings > Credentials."),
                 "template": "txt"},
                DEFAULT_TIMEOUT,
            )
            ok = body.get("code") == 200
            ok_all = ok_all and ok
            parts.append(_disp(en, f"PushPlus：{'成功' if ok else str(body)[:200]}",
                               f"PushPlus: {'ok' if ok else str(body)[:200]}"))
        except Exception as e:  # noqa: BLE001
            ok_all = False
            parts.append(f"PushPlus：{type(e).__name__}: {e}")

    if sendkey:
        try:
            body = _post_json(
                f"https://sctapi.ftqq.com/{sendkey}.send",
                {"title": title, "desp": _disp(en, "来自「设置 → 凭据」的连接测试。",
                                               "From Settings > Credentials.")},
                DEFAULT_TIMEOUT,
            )
            ok = body.get("code") == 0
            ok_all = ok_all and ok
            parts.append(_disp(en, f"Server酱：{'成功' if ok else str(body)[:200]}",
                               f"ServerChan: {'ok' if ok else str(body)[:200]}"))
        except Exception as e:  # noqa: BLE001
            ok_all = False
            parts.append(f"Server酱：{type(e).__name__}: {e}")

    detail = "；".join(parts)
    if ok_all:
        return True, _disp(en, f"推送成功（已发出测试消息）：{detail}",
                           f"Push succeeded (a test message was sent): {detail}")
    return False, _disp(en, f"推送失败：{detail}", f"Push failed: {detail}")


# ==================================================================
# 对外入口
# ==================================================================
def run_test(key: str, group: dict, user: str, pwd: str, en: bool = False) -> dict:
    """按 test_kind 分发执行连接测试。

    Returns:
        {"status": "ok"|"fail"|"unsupported", "key":..., "message":...}
    """
    kind = (group or {}).get("test_kind") or ""
    fn = TESTERS.get(kind)
    if fn is None:
        return {
            "status": "unsupported",
            "key": key,
            "message": _disp(en, "该系统暂不支持自动连接测试，请保存后观察下次任务执行结果",
                             "Automatic connection test is not supported for this system. "
                             "Save and check the next task run."),
        }

    # 2026-10-22：测试地址统一由 credential_store.resolve_endpoint 解析
    # （优先级：环境变量 > 任务配置文件 > 内置默认），覆盖到 group 的**副本**上，
    # 于是所有 _test_* 里的 test_host / test_port 自动跟随配置，不必逐个改。
    # 未登记配置的组解析结果仍等于内置默认，行为与改动前一致。
    # 为什么不能继续用 group 里的硬编码值：任务实际连的地址来自页面可编辑的
    # <task>_config.json，两边各写一份就会出现「改了配置、测试还在测旧机」，
    # 更糟的是消息里报的主机跟真正连上的主机不是同一台。
    group = dict(group or {})
    ep = resolve_endpoint(key)
    if ep.get("host"):
        group["test_host"] = ep["host"]
    if ep.get("port"):
        group["test_port"] = ep["port"]
    group["_endpoint"] = ep

    try:
        ok, msg = fn(group, user, pwd, en)
    except Exception as e:  # noqa: BLE001
        # 兜底：任何一个测试函数抛出未捕获异常，都不能让设置页 500。
        logger.warning(f"[CRED-TEST] {key} 测试异常: {e}", exc_info=True)
        return {"status": "fail", "key": key, "endpoint": ep,
                "message": _disp(en, f"测试异常: {type(e).__name__}: {e}",
                                 f"Test error: {type(e).__name__}: {e}")}
    return {"status": "ok" if ok else "fail", "key": key, "endpoint": ep, "message": msg}


def supported_kinds() -> list:
    """返回本模块支持的 test_kind 列表（自检 / 文档用）。"""
    return sorted(TESTERS.keys())
