# -*- coding: utf-8 -*-
"""
邮箱空间守卫 (Mailbox Storage Guard)
====================================

每小时检查 Exchange 邮箱（ztenoc.olr@orange.com / exchmail.orange-cit.ci）容量：
  - 邮件总数 > MAILBOX_COUNT_THRESHOLD (默认 500)
  - 且 已用空间 / 配额 > MAILBOX_SIZE_WARN_PCT (默认 50%)

两者**同时**满足时，循环删除收件箱(+子文件夹)、已发送、已删除项中**最旧**的
邮件（每轮 MAILBOX_DELETE_COUNT 默认 200 封，硬删除真正释放配额），
删除后重新扫描空间，直到 已用/配额 <= MAILBOX_SIZE_WARN_PCT 达标
或无可删邮件为止（单次运行最多 MAILBOX_MAX_ROUNDS 轮，默认 50），
从而避免 Outlook/Exchange 弹出 "You're about to exceed the storage limit
for your mailbox" 告警。

设计要点：
  - 仅在邮件数已超阈值时才做较重的「逐封统计大小」扫描；平时只发一次 GetFolder
    拿 total_count，开销极低；
  - 遍历用 folder.walk() + 文件夹自身 + FindFolder 深度遍历兜底：
    exchangelib 对 account.inbox 这类「distinguished folder」不填充 .children，
    walk() 会产出空集合（且不含文件夹自身），若只用 walk() 会扫出 0 字节、
    导致永不触发清理（历史 bug：邮箱将超配额却被判 space_under_threshold）；
  - EWS 不可达时降级为 skip（success=True），不触发每小时失败告警；
  - 配额无法从 EWS 取得，由 MAILBOX_QUOTA_BYTES 显式配置（默认 50 GiB），
    日志会打印真实已用字节与占比，便于校准；
  - 删除走 account.bulk_delete(delete_type=HARD_DELETE) 一次性批量移除，
    释放邮箱配额（软删只进已删除项、仍占配额，无效）。

环境变量（均可覆盖，默认值见下）：
  MAILBOX_SERVER           EWS 服务器          (默认 exchmail.orange-cit.ci)
  MAILBOX_USERNAME         登录账号            (默认 ZTENOC_OLR)
  MAILBOX_PASSWORD         密码                (默认 Postcode@231)
  MAILBOX_SMTP             邮箱地址            (默认 ztenoc.olr@orange.com)
  MAILBOX_AUTH_TYPE        认证方式 NTLM/BASIC (默认 NTLM)
  MAILBOX_VERIFY_SSL       是否校验证书链       (默认 false)
  MAILBOX_SOAP_TIMEOUT     SOAP 超时秒         (默认 60)
  MAILBOX_COUNT_THRESHOLD 触发删除的邮件数下限 (默认 500)
  MAILBOX_SIZE_WARN_PCT    触发删除/达标的空间占比%  (默认 50)
  MAILBOX_QUOTA_BYTES      邮箱配额字节数        (默认 5 GiB；实测已用约 4.4 GiB 时
                           Exchange 已弹 storage limit 告警，说明真实配额远小于 50 GiB，
                           请用环境变量按实际配额校准)
  MAILBOX_DELETE_COUNT     每轮删除的最旧邮件数 (默认 200)
  MAILBOX_MAX_ROUNDS       单次运行最大删除轮数   (默认 50)
  MAILBOX_DELETE_MODE      hard|soft           (默认 hard；soft=移入已删除项)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from exchangelib import (
    BASIC,
    NTLM,
    Account,
    Configuration,
    Credentials,
    DELEGATE,
    FaultTolerance,
    Version,
)
from exchangelib.folders.collections import FolderCollection
from exchangelib.items import HARD_DELETE, MOVE_TO_DELETED_ITEMS
from exchangelib.protocol import NoVerifyHTTPAdapter, Protocol
from exchangelib.version import EXCHANGE_2016

logger = logging.getLogger("mailbox_cleanup")

# 锁版本，跳过 exchangelib 的 Version.guess() 握手（偶发被 10054 断开）
EWS_VERSION = Version(build=EXCHANGE_2016, api_version="Exchange2016")

# SOAP 超时（秒）。与其他邮件脚本一致压到 60s，避免卡住的 GetFolder 拖住整点任务。
MAILBOX_SOAP_TIMEOUT = max(10, int(os.getenv("MAILBOX_SOAP_TIMEOUT", "60")))
Protocol.TIMEOUT = MAILBOX_SOAP_TIMEOUT

if os.getenv("MAILBOX_VERIFY_SSL", "false").lower() not in ("1", "true", "yes", "on"):
    Protocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

# 目标文件夹：收件箱(+子文件夹)、已发送、已删除项
_TARGET_FOLDER_GETTERS = ("inbox", "sent", "trash")


def get_account() -> Account:
    """登录 EWS 并返回 Account 对象（配置与 owa_mail_report 保持一致）。

    凭据优先级：环境变量(MAILBOX_USERNAME/MAILBOX_PASSWORD) > 数据库(设置页) > 代码默认值。
    这样在「设置」页改完 OWA 邮箱密码后，无需改代码、无需重启即可生效。
    """
    from backend.services.credential_store import get_credential
    server = os.getenv("MAILBOX_SERVER", "exchmail.orange-cit.ci")
    username, password = get_credential(
        "owa_mail", "ZTENOC_OLR", "Postcode@231",
        env_user="MAILBOX_USERNAME", env_secret="MAILBOX_PASSWORD",
    )
    smtp = os.getenv("MAILBOX_SMTP", "ztenoc.olr@orange.com")
    auth_type = os.getenv("MAILBOX_AUTH_TYPE", "NTLM").upper()
    auth_cls = NTLM if auth_type == "NTLM" else BASIC
    creds = Credentials(username=username, password=password)
    config = Configuration(
        server=server,
        credentials=creds,
        auth_type=auth_cls,
        version=EWS_VERSION,
        max_connections=2,
        retry_policy=FaultTolerance(max_wait=60),
    )
    return Account(
        primary_smtp_address=smtp,
        config=config,
        access_type=DELEGATE,
        autodiscover=False,
    )


def _target_folders(account):
    folders = []
    for name in _TARGET_FOLDER_GETTERS:
        try:
            folders.append(getattr(account, name))
        except Exception as e:  # noqa: BLE001
            logger.warning("获取文件夹 %s 失败: %s", name, e)
    return folders


def get_total_count(account: Account) -> int:
    """各目标文件夹 total_count 之和（含子文件夹，单次 GetFolder 即可）。"""
    total = 0
    for f in _target_folders(account):
        try:
            total += int(f.total_count or 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("统计 %s 邮件数失败: %s", getattr(f, "name", "?"), e)
    return total


def _all_folders(folder):
    """返回 folder 自身及其全部子孙文件夹。

    exchangelib 的 folder.walk() 只递归 .children 且不含自身；对
    account.inbox / account.sent / account.trash 这类 distinguished folder，
    .children 恒为空列表，walk() 直接产出空集合。因此优先走
    FindFolder(depth=Deep) 兜底，保证能扫到真实邮件。
    """
    subs = list(folder.children) if getattr(folder, "children", None) else []
    if not subs:
        try:
            fc = FolderCollection(account=folder.account, folders=[folder])
            subs = list(fc.find_folders(depth="Deep"))
        except Exception as e:  # noqa: BLE001
            logger.warning("深度遍历 %s 子文件夹失败: %s", getattr(folder, "name", "?"), e)
    return [folder] + subs


def scan_size_and_oldest(account: Account, delete_count: int):
    """扫描邮箱真实已用字节，并返回最旧的 delete_count 封邮件对象。

    返回 (total_bytes, scanned_count, oldest_items)。
    仅在邮件数已超阈值时调用，避免平时开销。
    """
    total_bytes = 0
    scanned_count = 0
    candidates = []
    for folder in _target_folders(account):
        try:
            for sub in _all_folders(folder):
                try:
                    for it in sub.all().only("id", "changekey", "datetime_received", "size"):
                        total_bytes += int(it.size or 0)
                        scanned_count += 1
                        candidates.append(it)
                except Exception as e:  # noqa: BLE001
                    logger.warning("扫描 %s 邮件失败: %s", getattr(sub, "name", "?"), e)
        except Exception as e:  # noqa: BLE001
            logger.warning("遍历 %s 失败: %s", getattr(folder, "name", "?"), e)
    logger.info("空间扫描完成: 扫描邮件 %d 封, 合计 %.2f MB", scanned_count, total_bytes / 1024 / 1024)
    # 全局最旧优先（收件时间早的排前面）；缺收件时间的排到最后
    candidates.sort(key=lambda x: x.datetime_received or datetime.min)
    return total_bytes, scanned_count, candidates[:delete_count]


def delete_items(account: Account, items, mode: str) -> int:
    """批量删除邮件。返回实际删除数量。"""
    if not items:
        return 0
    delete_type = HARD_DELETE if mode == "hard" else MOVE_TO_DELETED_ITEMS
    try:
        account.bulk_delete(items, delete_type=delete_type, chunk_size=100)
        return len(items)
    except Exception as e:  # noqa: BLE001
        # 批量失败则逐封兜底删除
        logger.warning("批量删除失败，转逐封删除: %s", e)
        ok = 0
        for it in items:
            try:
                it.delete(delete_type=delete_type)
                ok += 1
            except Exception as ex:  # noqa: BLE001
                logger.warning("单封删除失败: %s", ex)
        return ok


def run_mailbox_cleanup() -> dict:
    """Task Manager 入口：检查邮箱容量，超限则清理最旧邮件。"""
    count_threshold = int(os.getenv("MAILBOX_COUNT_THRESHOLD", "500"))
    size_pct = float(os.getenv("MAILBOX_SIZE_WARN_PCT", "50"))
    quota_bytes = int(os.getenv("MAILBOX_QUOTA_BYTES", str(5 * 1024 ** 3)))
    delete_count = int(os.getenv("MAILBOX_DELETE_COUNT", "200"))
    delete_mode = os.getenv("MAILBOX_DELETE_MODE", "hard").lower()

    logger.info(
        "邮箱空间守卫：开始检查（邮件数>%d 且 空间>%.0f%% 才删除）",
        count_threshold, size_pct,
    )
    try:
        account = get_account()
    except Exception as e:  # noqa: BLE001
        logger.error("EWS 登录失败: %s", e)
        # 软跳过：EWS 不可达不应触发每小时失败告警
        return {
            "success": True,
            "action": "skip",
            "reason": "ews_unreachable",
            "error": f"EWS login failed: {e}",
            "message": f"EWS 不可达（{e}），本次跳过清理，等待下次重试",
        }

    total_count = get_total_count(account)
    logger.info("邮箱总邮件数: %d (触发阈值 %d)", total_count, count_threshold)
    if total_count <= count_threshold:
        return {
            "success": True,
            "action": "skip",
            "reason": "count_under_threshold",
            "total_count": total_count,
            "count_threshold": count_threshold,
            "message": f"邮件数 {total_count} <= {count_threshold}，无需清理",
        }

    # 邮件数已超阈值 -> 进入循环清理
    used_pct_before = 0.0
    # 直到 used_pct <= MAILBOX_SIZE_WARN_PCT（达标）或无可删邮件为止
    max_rounds = max(1, int(os.getenv("MAILBOX_MAX_ROUNDS", "50")))
    deleted_total = 0
    used_pct = 0.0
    total_bytes = 0
    for round_no in range(1, max_rounds + 1):
        total_bytes, scanned_count, oldest = scan_size_and_oldest(account, delete_count)
        used_pct = (total_bytes / quota_bytes * 100.0) if quota_bytes else 0.0
        logger.info(
            "第 %d 轮：已用空间 %.2f MB (%.1f%% / 配额 %.0f MB), 本轮可删候选 %d 封",
            round_no, total_bytes / 1024 / 1024, used_pct,
            quota_bytes / 1024 / 1024, len(oldest),
        )

        # 兜底：大小统计为 0（扫描异常/字段缺失）时不能误判「空间充足」，
        # 按邮件数清理，防止配额真正告警
        if total_bytes <= 0 and scanned_count <= 0:
            logger.warning("空间统计为 0 但邮件数已超阈值，按数量触发清理")
            n = delete_items(account, oldest, delete_mode)
            if n <= 0:
                break
            deleted_total += n
            continue

        if used_pct <= size_pct:
            # 已达标
            if deleted_total <= 0:
                return {
                    "success": True,
                    "action": "skip",
                    "reason": "space_under_threshold",
                    "total_count": total_count,
                    "total_bytes": total_bytes,
                    "used_pct": round(used_pct, 2),
                    "size_pct": size_pct,
                    "message": f"邮件数超阈值但空间 {used_pct:.1f}% <= {size_pct:.0f}%，暂不清理",
                }
            return {
                "success": True,
                "action": "deleted",
                "deleted": deleted_total,
                "rounds": round_no,
                "total_count_before": total_count,
                "used_pct_before": "%.2f" % used_pct_before,
                "used_pct_after": round(used_pct, 2),
                "delete_mode": delete_mode,
                "message": (
                    f"已循环删除 {deleted_total} 封最旧邮件，空间 {used_pct_before:.1f}% -> "
                    f"{used_pct:.1f}%（达标线 {size_pct:.0f}%）"
                ),
            }

        # 未达标 -> 删除本批最旧邮件后进入下一轮
        if not oldest:
            logger.warning("无更多可删邮件，终止循环")
            break
        if round_no == 1:
            used_pct_before = used_pct
        n = delete_items(account, oldest, delete_mode)
        logger.info("第 %d 轮已删除 %d 封（累计 %d）", round_no, n, deleted_total + n)
        if n <= 0:
            break
        deleted_total += n

    # 循环结束仍未达标（达到轮数上限/无可删/删除失败）
    return {
        "success": True,
        "action": "deleted" if deleted_total > 0 else "skip",
        "reason": "loop_finished_not_below_target",
        "deleted": deleted_total,
        "total_count_before": total_count,
        "used_pct_last": round(used_pct, 2),
        "size_pct": size_pct,
        "delete_mode": delete_mode,
        "message": (
            f"累计删除 {deleted_total} 封，当前空间 {used_pct:.1f}% "
            f"（目标 <= {size_pct:.0f}%，未达标则等待下次整点继续）"
        ),
    }


if __name__ == "__main__":
    import pprint
    import time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _t0 = time.time()
    pprint.pprint(run_mailbox_cleanup())
    print(f"总耗时: {time.time() - _t0:.1f} 秒")
