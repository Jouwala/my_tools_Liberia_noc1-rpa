"""P1 TT 通报**邮件通道**（Orange EWS）。
## 为什么是 EWS 而不是 126

用户 2026-10-06 明确要求：P1 通报邮件走**项目的 Orange 邮箱**，不要用 126。
发件人 `ztenoc.olr@orange.com`（凭据组 `owa_mail`，与 `mailbox_cleanup` 同一套），
收件人由「Settings → 邮件收件人」页维护（见 `email_recipient_store`）。

## 两个实测踩到的坑（都已在本模块内解决，勿重犯）

1. **`EXCHANGE_2016` 是 `Build` 不是 `Version`**。直接
   `Configuration(version=EXCHANGE_2016)` 会抛
   `InvalidTypeError: must be of type <class 'exchangelib.version.Version'>`，
   必须包一层 `Version(build=EXCHANGE_2016, api_version="Exchange2016")`
   —— 与 `mailbox_cleanup.py:71` 同一写法。
2. **内网 EWS 是自签证书**，默认校验必然失败：
   `SSLCertVerificationError: unable to get local issuer certificate`。
   故与 `mailbox_cleanup.py:77-78` 一致地把 `Protocol.HTTP_ADAPTER_CLS`
   换成 `NoVerifyHTTPAdapter`（可用 `MAILBOX_VERIFY_SSL=true` 关掉该行为）。

## 依赖来源（2026-10-06 实测更正）

`liberia_email_report.py:7-9` 写着「后端系统 Python 未安装 exchangelib，必须用
托管 venv 子进程」。**该注释已过时**：实测后端 Python 3.12 直接
`import exchangelib` 得到 5.6.0（装在其 `Lib\\site-packages` 下），
故本模块**进程内直发**，不起子进程 —— 少一层进程开销，也不会吞掉异常栈。

## 失败语义

本模块**只返回 bool，不抛异常**：邮件是 WhatsApp 之外的附加通道，
它失败绝不能影响推送结果与 `send_status`（调用方把 False 记进 `warnings`）。
"""
import logging
import os
from typing import List, Optional

logger = logging.getLogger("tt_alarm_mailer")

# EWS 服务器与发件地址（与 mailbox_cleanup / owa_mail_report 保持一致）
DEFAULT_EWS_SERVER = "exchmail.orange-cit.ci"
DEFAULT_SMTP_ADDRESS = "ztenoc.olr@orange.com"
# SOAP 超时（秒）。与邮件脚本一致压到 60s，避免卡住的 EWS 拖住整轮推送。
SOAP_TIMEOUT = max(10, int(os.getenv("TT_ALARM_MAIL_TIMEOUT", "60")))

_ACCOUNT_CACHE: Optional[object] = None


def _split_addrs(text: Optional[str]) -> List[str]:
    """收件人文本 → 地址列表（支持 `;` `,` 与空白分隔，去重保序）。

    `email_recipient_store` 的保存值是 `;` 分隔；但页面上用户可能手打逗号或
    换行，故这里三种分隔符都认，行为与 `_parse_addrs` 一致。
    """
    out: List[str] = []
    for raw in str(text or "").replace(",", ";").replace("\n", ";").split(";"):
        a = raw.strip()
        if a and a not in out:
            out.append(a)
    return out


def _build_account():
    """登录 EWS 并返回 Account（失败抛异常，由 `send_mail` 收敛为 False）。"""
    from exchangelib import Account, Configuration, Credentials, DELEGATE, NTLM
    from exchangelib.protocol import FaultTolerance, NoVerifyHTTPAdapter, Protocol
    from exchangelib.version import EXCHANGE_2016, Version

    # 自签证书：与 mailbox_cleanup.py:77-78 同款处理（见模块 docstring 坑 2）
    if os.getenv("MAILBOX_VERIFY_SSL", "false").lower() not in ("1", "true", "yes", "on"):
        Protocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
    Protocol.TIMEOUT = SOAP_TIMEOUT

    from backend.services.credential_store import get_credential

    username, password = get_credential(
        "owa_mail", env_user="MAILBOX_USERNAME", env_secret="MAILBOX_PASSWORD")
    return Account(
        primary_smtp_address=os.getenv("MAILBOX_SMTP", DEFAULT_SMTP_ADDRESS),
        config=Configuration(
            server=os.getenv("MAILBOX_SERVER", DEFAULT_EWS_SERVER),
            credentials=Credentials(username=username, password=password),
            auth_type=NTLM,
            # 必须包 Version（见模块 docstring 坑 1）
            version=Version(build=EXCHANGE_2016, api_version="Exchange2016"),
            max_connections=2,
            retry_policy=FaultTolerance(max_wait=60),
        ),
        access_type=DELEGATE,
        autodiscover=False,
    )


def _get_account():
    """缓存的 Account（每次发信重建会话代价高；EWS 会话可长期复用）。"""
    global _ACCOUNT_CACHE
    if _ACCOUNT_CACHE is None:
        _ACCOUNT_CACHE = _build_account()
    return _ACCOUNT_CACHE


def reset_account_cache() -> None:
    """丢弃缓存的会话（改密/换服务器后调用；测试也用它隔离状态）。"""
    global _ACCOUNT_CACHE
    _ACCOUNT_CACHE = None


def send_mail(subject: str, body: str, to: Optional[str], cc: Optional[str] = None,
              source: str = "tt_alarm") -> bool:
    """发送一封纯文本邮件。**不抛异常**，成功返回 True，任何失败返回 False。

    Args:
        subject: 邮件主题（调用方负责语言，本模块不做翻译）
        body:    纯文本正文
        to:      主送（`;`/`,`/换行分隔）；**解析后为空则直接返回 False 不发信**
        cc:      抄送（同上；为空表示不抄送）
        source:  日志前缀，便于区分是通报还是汇总

    Returns:
        bool：是否已被 EWS 接受（`send_and_save` 无异常返回即视为成功）。
    """
    to_list = _split_addrs(to)
    if not to_list:
        # 无主送地址 = 配置为空 = 明确不发（不猜、不兜底到某个人）
        logger.info("[%s] 主送为空，跳过发信: %s", source, subject)
        return False

    try:
        from exchangelib import Mailbox, Message

        acct = _get_account()
        msg = Message(
            account=acct,
            folder=acct.sent,
            subject=subject,
            body=body,
            to_recipients=[Mailbox(email_address=a) for a in to_list],
            cc_recipients=[Mailbox(email_address=a) for a in _split_addrs(cc)],
        )
        msg.send_and_save()
        logger.info("[%s] 邮件已发送 to=%s cc=%s subject=%s",
                    source, ",".join(to_list), cc or "-", subject)
        return True
    except Exception as e:  # noqa: BLE001
        # 缓存坏会话会让后续每一次都失败（如改密后），故失败即丢弃重建
        reset_account_cache()
        logger.warning("[%s] 邮件发送失败（不影响推送）subject=%s: %s: %s",
                       source, subject, type(e).__name__, e)
        return False
