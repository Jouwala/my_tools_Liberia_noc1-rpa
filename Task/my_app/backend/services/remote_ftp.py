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
import re
from pathlib import Path
from typing import List, Optional, Tuple

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
    ftp = _connect(remote_path)
    try:
        buf = bytearray()
        ftp.retrbinary(f"RETR {remote_path}", lambda b: buf.extend(b))
        return bytes(buf).decode("utf-8", "replace")
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def list_names(remote_dir: str) -> List[str]:
    """列出 remote_dir 下的文件名（basename）。"""
    base = remote_dir.rstrip("/")
    ftp = _connect(base)
    try:
        return [n.split("/")[-1] for n in ftp.nlst(base)]
    finally:
        try:
            ftp.quit()
        except Exception:
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

    ftp = _connect(base)
    try:
        try:
            names = ftp.nlst(base)
        except Exception:
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
                pass
            if name_filter and name_filter not in nm:
                continue
            local = local_dir / nm
            with open(local, "wb") as f:
                ftp.retrbinary(f"RETR {item}", f.write)
            out.append(local)
        return out
    finally:
        try:
            ftp.quit()
        except Exception:
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
