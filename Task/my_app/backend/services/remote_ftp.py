# -*- coding: utf-8 -*-
"""
remote_ftp.py
=============
从远程报表服务器 (192.168.100.19) 通过 FTP 读取文件。

凭据按路径前缀区分（由用户规定）：
  - 路径以 /01_RPA   开头 -> 账号 ZTEEMS / DX
  - 路径以 /Python   开头 -> 账号 FINEBI / DX

典型用途：
  - 读取各报告的远程收件人名单 ss_email.txt / cc_email.txt
  - 把远程生成的 Excel / 图片下载到本地临时目录，供邮件脚本使用
"""
from __future__ import annotations

import ftplib
import os
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("remote_ftp")

FTP_HOST = "192.168.100.19"


def creds_for(remote_path: str) -> Tuple[str, str]:
    """根据远程路径前缀返回 (用户名, 密码)。"""
    p = remote_path.replace("\\", "/")
    if p.startswith("/01_RPA"):
        return ("ZTEEMS", "DX")
    if p.startswith("/Python"):
        return ("FINEBI", "DX")
    # 默认兜底
    return ("ZTEEMS", "DX")


def _connect(remote_path: str) -> ftplib.FTP:
    user, pw = creds_for(remote_path)
    ftp = ftplib.FTP(FTP_HOST, timeout=30)
    ftp.login(user, pw)
    return ftp


def read_text(remote_path: str) -> str:
    """读取远程文本文件内容（UTF-8，解码失败用 replace）。"""
    with _connect(remote_path) as ftp:
        try:
            buf = bytearray()
            ftp.retrbinary(f"RETR {remote_path}", lambda b: buf.extend(b))
            return bytes(buf).decode("utf-8", "replace")
        finally:
            try:
                ftp.quit()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] read_text: exception swallowed", exc_info=True)
                pass


def list_names(remote_dir: str) -> List[str]:
    """列出 remote_dir 下的文件名（basename）。"""
    base = remote_dir.rstrip("/")
    with _connect(base) as ftp:
        try:
            return [n.split("/")[-1] for n in ftp.nlst(base)]
        finally:
            try:
                ftp.quit()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] list_names: exception swallowed", exc_info=True)
                pass


def _prune_stale_siblings(local, keep=None):
    """下载成功后尽力删除同图表旧版本(时间戳/随机名兄弟文件)，避免目录堆积与邮件重复内嵌。

    只删 ``{stem}_*`` 兄弟文件，不碰固定名 ``local`` 本身（可能被锁）；``keep`` 指定的
    当前交付文件也跳过。失败全部忽略，不引入新锁。
    """
    try:
        local = Path(local)
        parent = local.parent
        keep = Path(keep) if keep else None
        for f in parent.glob(f"{local.stem}_*"):
            try:
                if f.is_file() and f != keep:
                    f.unlink()
            except OSError:
                pass
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _prune_stale_siblings: exception swallowed", exc_info=True)
        pass


def download_filtered(
    remote_dir: str,
    local_dir,
    name_filter: Optional[str] = None,
) -> List[Path]:
    """
    把 remote_dir 下文件名包含 name_filter 的**文件**下载到 local_dir。
    子目录会被跳过。返回下载后的本地路径列表。
    """
    base = remote_dir.rstrip("/")
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    # 原子替换依赖 atomic_write（含 pandas，按需懒加载一次）。必须在下方 try 之前绑定
    # AtomicReplaceFallback，否则当 retrbinary 等更早抛错时，except 子句求值该名会触发
    # UnboundLocalError 遮蔽真实错误。
    try:
        from .atomic_write import atomic_replace_file, AtomicReplaceFallback
    except ImportError:
        from atomic_write import atomic_replace_file, AtomicReplaceFallback

    with _connect(base) as ftp:
        try:
            try:
                names = ftp.nlst(base)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_filtered: exception swallowed", exc_info=True)
                return []
            out: List[Path] = []
            for full in names:
                nm = full.split("/")[-1]
                if nm in (".", ".."):
                    continue
                item = f"{base}/{nm}"
                # 目录检测：能 cwd 进去的就是目录，跳过
                try:
                    ftp.cwd(item)
                    ftp.cwd(base)
                    continue
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_filtered: exception swallowed", exc_info=True)
                    pass
                if name_filter and name_filter not in nm:
                    continue
                local = local_dir / nm
                # 先下载到临时文件，再原子替换到最终路径，扛目标被锁(Permission denied)。
                # 直接 open(local,'wb') 会在目标被其他进程独占时立刻报 [Errno 13]。
                tmp = local.with_suffix(local.suffix + f".{os.getpid()}.tmp")
                try:
                    with open(tmp, "wb") as f:
                        ftp.retrbinary(f"RETR {item}", f.write)
                    atomic_replace_file(str(tmp), str(local))
                except AtomicReplaceFallback as e:
                    # 目标被持久锁(看板热读/索引/杀软)时，atomic_replace_file 重试耗尽后
                    # 已把数据存到唯一名备用文件(_fallback_save)并抛此异常。数据已保全，
                    # 应视为下载成功、交付该备用文件，而非跳过——避免邮件因锁漏发。
                    fb = getattr(e, "fallback_path", None)
                    if fb and os.path.exists(fb):
                        logger.warning(
                            "下载目标被锁，已用备用文件交付(邮件将内嵌该图): %s -> %s",
                            local, fb,
                        )
                        out.append(Path(fb))
                        _prune_stale_siblings(local, keep=fb)
                    else:
                        logger.error("下载失败(备用文件缺失): %s -> %s: %s", item, local, e)
                    continue
                except Exception as e:
                    try:
                        if os.path.exists(str(tmp)):
                            os.remove(str(tmp))
                    except OSError:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_filtered: exception swallowed", exc_info=True)
                        pass
                    logger.error("下载失败(已跳过): %s -> %s: %s", item, local, e)
                    continue
                _prune_stale_siblings(local)
                out.append(local)
            return out
        finally:
            try:
                ftp.quit()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_filtered: exception swallowed", exc_info=True)
                pass


def parse_addresses(text: str) -> List[str]:
    """从名单文本解析邮箱地址（支持 ; , 空白 分隔；忽略空行与 # 注释；去重）。"""
    out: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for raw in re.split(r"[;,\s]+", line):
            a = raw.strip()
            if a and a not in out:
                out.append(a)
    return out