#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_multi_data —— VMAX vReport（RDK pluto 报表）多指标采集
=========================================================

来源：用户提供的抓包（backend/services/vmax_multi_data/url.txt）里两个 CIService 报表的
`server/report_query` / `server/export_data` 请求。本包按 RAN_UME 的方法（登录 → 拉取 →
解析 → 落库/落盘）把这两个报表的指标取回本地。

协议（从 VMAX 前端 RDK 框架复刻，见 vmax_report_client 头注释）：
    POST /rdk/service/app/vreport/web/rpt_home/<reportPart>/server/report_query
    Header: X-Content-Type: application/x-vmax-s-rsa-encrypted
    Body  : {"param": {"encryptedStr": RSA_encryptLong(JSON(condition))}}

子模块：
    vmax_report_client.py      传输/RSA/会话/报表配置/查询/导出
    vmax_multi_data_service.py 编排、解析、落盘（JSON + SQLite）、CLI
    vmax_multi_data_config.json 报表与指标配置（可由设置页维护）
"""

__all__ = ["vmax_report_client", "vmax_multi_data_service"]
