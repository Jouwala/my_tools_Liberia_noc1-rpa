# -*- coding: utf-8 -*-
"""ZTE 系上游登录共用的 RSA 加密工具（PKCS#1 v1.5）。

## 为什么有这个模块（2026-10-06）

同一段「公钥 Base64 → PEM → PKCS1v15 加密 → Base64 密文」曾在 **9 个文件**里
各写一遍：`auth_manager` / `eflow_api_client` / `ms_sla_sync` / `ran_ume_service` /
`ran_ume_main_kpi` / `ran_ume_network_kpi` / `cm_data_export` / `mw_ume_kpi` /
`battary_kpi_fetch_socket`。它们**经 AST 比对确认语义完全一致**（差异只在
docstring、类型注解与换行），属于纯复制。

之所以迟迟没合并，是"看起来像但不确认"—— 本文件落地前先用 AST 比对证明
了 9 处同构（脚本见 `TMP/_diff_rsa_ast.py`），才敢动。

**放这里的理由**：原实现散落在业务服务里，任何一处要改（比如上游换成
OAEP 填充）就得改 9 遍，漏一处就是"某个任务单独登录失败"这类极难定位的故障。
收敛后只改一处。没有放进 `auth_manager`，是因为其中一半调用方（如
`cm_data_export`、`mw_ume_kpi`）与鉴权模块没有依赖关系，不该为了一个
8 行的纯函数去 import 整个鉴权体系。

## 协议背景

ZTE UME / eFlow 的 OAuth2 登录是：`GET /api/oauth2/v1/login/publickey` 拿
RSA 公钥（Base64，**不含 PEM 头尾**）→ 用它加密口令 → `POST login_rsa`。
填充方式固定为 PKCS#1 v1.5（非 OAEP），改动会直接导致上游解密失败。
"""
from __future__ import annotations

import base64

__all__ = ["rsa_encrypt_pem"]


def rsa_encrypt_pem(plaintext: str, public_key_b64: str) -> str:
    """用上游给的 Base64 公钥做 RSA(PKCS#1 v1.5) 加密，返回 Base64 密文。

    Args:
        plaintext: 待加密明文（本项目里是口令）。
        public_key_b64: `login/publickey` 返回的裸 Base64 公钥（无 PEM 头尾）。

    Returns:
        Base64 编码的密文（ASCII）。

    Note:
        `cryptography` 在此处**延迟导入**：本模块被多个服务在模块顶层引用，
        而部分服务（如电池抓取的独立脚本模式）允许在没装 cryptography 的环境
        下只用到非加密功能。延迟导入让"没用到的环境"不受影响 —— 与原先
        9 处实现的写法保持一致。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode("utf-8"), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode("ascii")
