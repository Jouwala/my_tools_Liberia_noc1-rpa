# -*- coding: utf-8 -*-
"""
iPRAN UME KPI 全内存高并发数据同步服务

架构流程：
requests.Session (扩容长连接池)
   ↓ create (并发创建历史查询任务)
   ↓ async poll (极速阶梯轮询)
   ↓ export(BytesIO) (内存流导出，零磁盘 I/O)
   ↓ pandas/calamine (内存并行解析 Excel)
   ↓ INSERT OR REPLACE / DbWriter (原生高效去重写入 SQLite/远程 API)
"""

import base64
import gc
import gzip
import io
import json
import logging
import os
import re
import sys
import threading
import time
import warnings
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from urllib3.exceptions import InsecureRequestWarning

# 禁用未安全校验 HTTPS 警告
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

logger = logging.getLogger("ipran_ume_kpi_service")

# 强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ============================================================
# 系统与路径配置
# ============================================================
HOST = "10.100.2.99"
PORT = 28001
USERNAME = "noc1"
PASSWORD = "Zte@lbr202607"
LOGIN_PORTAL = "/portal-athena/framework/default.html"

# 数据目录
IPRAN_DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\ipran_ume")
IPRAN_DATA_DIR.mkdir(parents=True, exist_ok=True)

MONTHS_BACK = int(os.environ.get("IPRAN_KPI_MONTHS_BACK", "1"))
# 并发线程数：匹配当前 6 个 KPI 查询任务
MAX_PARALLEL_WORKERS = int(os.environ.get("IPRAN_KPI_PARALLEL_WORKERS", "6"))
# 创建查询遇到 Repeated query（服务端旧查询未释放）时的退避重试上限与间隔。
# UMW 会自然释放卡住的查询（观察周期约 1h），因此用较长重试窗口等待其释放后再提交。
# 注意：UME 会话约 30 分钟过期，长耗时任务容易踩中，故 request_with_retry 内置自动重登录。
# 这里用「固定间隔 × 次数」覆盖约 60 分钟，足以等到 UME 释放窗口，且不至于无限拉长。
MAX_CREATE_RETRIES = int(os.environ.get("IPRAN_KPI_CREATE_RETRIES", "30"))
CREATE_RETRY_WAIT = int(os.environ.get("IPRAN_KPI_CREATE_WAIT", "120"))
# 会话主动刷新阈值（秒）。小于 UME 30 分钟过期时间，保证长耗时任务中途自动续期，避免 401。
SESSION_REFRESH_SEC = int(os.environ.get("IPRAN_KPI_SESSION_REFRESH", "1500"))

# PM 接口路径
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
HISTORY_REFERER = f"https://{HOST}:{PORT}{LOGIN_PORTAL}"

# 数据库配置
DB_NAME = "ipran_ume_kpi.sqlite3"
DB_PATH = str(IPRAN_DATA_DIR / DB_NAME)

# 远程写入 API 客户端配置 (若存在)
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    try:
        from db_writer_client import DbWriterClient
    except ImportError:
        DbWriterClient = None

try:
    _db_writer = DbWriterClient() if DbWriterClient else None
except Exception:
    _db_writer = None
    logger.warning("[iPRAN] db_writer_client 未初始化，将使用本地 SQLite3 写入")

IDENTITY_COL_CANDIDATES = ["NE", "ME", "Managed Element", "SERVICE", "Measurement Object"]

GR_RENAME = {
    "900": "15mins",
    "3600": "1hour",
    "86400": "1Day",
}

# ============================================================
# 全量嵌入的 KPI 查询配置
# ============================================================
_HQ_M6K_FW_CONFIG = {
    "favoriteconditionname": "HQ M6K-FW",
    "filterlayer": "bnctp",
    "grouplayer": "me,bnctp",
    "gr": "900",
    "motid": "BNCTN.PMP",
    "nfctid": (
        "bn.me.ZXR10.15K-M6000-16SE,bn.me.ZXR10.15K-M6000-18S,bn.me.ZXR10.15K-M6000-18S-Plus,"
        "bn.me.ZXR10.15K-M6000-2S10,bn.me.ZXR10.15K-M6000-2S16,bn.me.ZXR10.15K-M6000-2S4,"
        "bn.me.ZXR10.15K-M6000-2S4-Plus,bn.me.ZXR10.15K-M6000-2S6,bn.me.ZXR10.15K-M6000-3S,"
        "bn.me.ZXR10.15K-M6000-3S-Plus,bn.me.ZXR10.15K-M6000-4SE,bn.me.ZXR10.15K-M6000-5S,"
        "bn.me.ZXR10.15K-M6000-6F,bn.me.ZXR10.15K-M6000-8S,bn.me.ZXR10.15K-M6000-8SE,"
        "bn.me.ZXR10.15K-M6000-8S-Plus,bn.me.ZXR10.15K-M6000-S-VND,bn.me.ZXR10.15K-M6000-S-VRC"
    ),
    "items": ["C019901990", "C019911991"],
    "itemsposition": [0, 0],
    "itemsposition1": [0, 0],
    "containvcell": 0,
    "indexfillingtype": "zeroDenominator",
    # NOTE: uilocations / reslocation 必须存在，否则 UME 返回
    # 499 {"errorcode":"0001610001","message":"Parameter[uilocations,locations] is not valid."}
    "uilocations": [
        {
            "id": "f72f2173-766a-4ae2-9215-c33fd7fe2b07$ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
            "moc": "bnag",
            "model": "bnag",
        }
    ],
    "reslocation": [
        {
            "id": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
            "displayName": '{"en_US":"SmartGroup:3","zh_CN":"SmartGroup:3"}',
            "nbiId": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
            "labelDn": "HQ-M6K-8S_Plus_PS01#SmartGroup:3",
            "moc": "bnag",
            "path": [
                {
                    "id": "f72f2173-766a-4ae2-9215-c33fd7fe2b07",
                    "displayName": "HQ-M6K-8S_Plus_PS01",
                    "model": "wlme",
                    "nbiId": "BN:ME{431941261}",
                },
                {
                    "id": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
                    "displayName": "SmartGroup:3",
                    "model": "bnag",
                    "nbiId": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
                },
            ],
        }
    ],
    "chartsetting": (
        '{"showchart":true,"layout":1,"showMarkLineLabel":false,"showDataZoom":true,'
        '"charts":[{"id":"03059aec-6875-bca7-06bb9cd39805d826","legendmode":0,"displayMode":0,'
        '"mos":["f72f2173-766a-4ae2-9215-c33fd7fe2b07$ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}"],'
        '"mosNames":["\\"HQ-M6K-8S_Plus_PS01\\"-SmartGroup:3"],'
        '"itemids":["order_8","order_9"],'
        '"selectedlegend":["order_8","order_9"],'
        '"markingsettings":[],"custommarkingsettings":[],"showsetting":[]}],'
        '"thresholdIds":[],'
        '"countersInfo":['
        '{"key":"order_8","id":"C019901990","itemposition":0,"itemposition1":0},'
        '{"key":"order_9","id":"C019911991","itemposition":0,"itemposition1":0}'
        ']}'
    ),
    "favorite_id": "4e033c70f47943318d2d77717b80eb4e",
    "table_name": "HQ_M6K_FW_bnctp_15mins",
}

IPRAN_KPI_QUERY_CONFIGS = {
    'HQ_M6K_FW': _HQ_M6K_FW_CONFIG,
    'IPCORE_HQ_ODC': {
        "favoriteconditionname": 'IPCORE HQ-ODC',
        "filterlayer": 'bnctp',
        "grouplayer": 'me,bnctp',
        "gr": '900',
        "displaymode": 1,
        "motid": 'BNCTN.PMP',
        "nfctid": 'bn.me.ZXR10.15K-M6000-8S-Plus',
        "items": ['C019911991', 'C019901990'],
        "itemsposition": [0, 0],
        "itemsposition1": [0, 0],
        "containvcell": 0,
        "indexfillingtype": 'zeroDenominator',
        "versiondatacompare": False,
        "uilocations": [{'id': 'f72f2173-766a-4ae2-9215-c33fd7fe2b07$ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'moc': 'bnag', 'model': 'bnag'}, {'id': 'f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd$ME{f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'moc': 'bnag', 'model': 'bnag'}],
        "reslocation": [{'id': 'ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'displayName': 'SmartGroup:9', 'nbiId': 'ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'labelDn': 'HQ-M6K-8S_Plus_PS01#SmartGroup:9', 'moc': 'bnag', 'path': [{'id': 'f72f2173-766a-4ae2-9215-c33fd7fe2b07', 'displayName': 'HQ-M6K-8S_Plus_PS01', 'model': 'wlme', 'nbiId': 'BN:ME{431941261}'}, {'id': 'ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'displayName': 'SmartGroup:9', 'model': 'bnag', 'nbiId': 'ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}'}]}, {'id': 'ME{f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'displayName': 'SmartGroup:9', 'nbiId': 'ME{f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'labelDn': 'HQ-M6K-8S_Plus_PS02#SmartGroup:9', 'moc': 'bnag', 'path': [{'id': 'f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd', 'displayName': 'HQ-M6K-8S_Plus_PS02', 'model': 'wlme', 'nbiId': 'BN:ME{431941262}'}, {'id': 'ME{f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}', 'displayName': 'SmartGroup:9', 'model': 'bnag', 'nbiId': 'ME{f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}'}]}],
        "chartsetting": '{"showchart":true,"layout":1,"showMarkLineLabel":false,"showDataZoom":true,"charts":[{"id":"3077dcfe-d162-cd21-3d6f90e06883988a","legendmode":0,"displayMode":1,"mos":["f72f2173-766a-4ae2-9215-c33fd7fe2b07$ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}"],"mosNames":["\\"HQ-M6K-8S_Plus_PS01\\"-SmartGroup:9"],"itemids":["C019911991","C019901990"],"selectedlegend":["C019911991","C019901990"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"28b7812a-bea0-6ca0-0d96641a4b0fb84c","legendmode":0,"displayMode":1,"mos":["f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd$ME{f6be7645-ab04-4d58-8a2b-0b0d8b0eb8fd},EQ={/r=0/sh=0/sl=255},FTP={/p=124_9}"],"mosNames":["\\"HQ-M6K-8S_Plus_PS02\\"-SmartGroup:9"],"itemids":["C019911991","C019901990"],"selectedlegend":["C019911991","C019901990"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]}],"thresholdIds":[]}',
        "invaliditems": [],
        "favorite_id": 'c298defce6224d209b075d03bdec75ed',
        "showtimezoneoffset": False,
        "table_name": 'IPCORE_HQ_ODC_bnctp_15mins',
    },
    'Metro_ring': {
        "favoriteconditionname": 'Metro-ring',
        "filterlayer": 'me',
        "grouplayer": 'me,bnctp',
        "gr": '900',
        "displaymode": 1,
        "motid": 'BNCTN.PMP',
        "nfctid": 'bn.me.ZXR10.15K-M6000-2S16,bn.me.ZXCTN.15K-9000-8EA,bn.me.ZXCTN.15K-9000-3EA',
        "items": ['C019901990', 'C019911991'],
        "itemsposition": [0, 0],
        "itemsposition1": [0, 0],
        "containvcell": 0,
        "indexfillingtype": 'zeroDenominator',
        "uilocations": [{'id': '027bcb01-a8bf-4e20-97a0-0776cbb20447', 'moc': 'bn.me.ZXCTN.15K-9000-8EA', 'model': 'wlme'}, {'id': '9a548085-7fcb-48be-8701-505d915329f9', 'moc': 'bn.me.ZXR10.15K-M6000-2S16', 'model': 'wlme'}, {'id': 'd51a277b-cf5c-499e-8495-61dca4fdd46e', 'moc': 'bn.me.ZXR10.15K-M6000-2S16', 'model': 'wlme'}, {'id': 'bcb8ce00-e497-4e8d-8dc3-c2231897b01c', 'moc': 'bn.me.ZXR10.15K-M6000-2S16', 'model': 'wlme'}, {'id': '28dbff5e-6a99-40d1-89b9-cdff87cb1fc8', 'moc': 'bn.me.ZXR10.15K-M6000-2S16', 'model': 'wlme'}, {'id': 'e613f196-66cb-4dcb-ae5d-d10812bc675e', 'moc': 'bn.me.ZXR10.15K-M6000-2S16', 'model': 'wlme'}, {'id': 'dfe167e4-d039-4d59-84c4-1939f1ca5aef', 'moc': 'bn.me.ZXCTN.15K-9000-3EA', 'model': 'wlme'}, {'id': '480f0009-d020-40ee-9d8a-823051a32918', 'moc': 'bn.me.ZXCTN.15K-9000-8EA', 'model': 'wlme'}],
        "reslocation": [],
        "chartsetting": '{"showchart":true,"layout":1,"showDataLabel":false,"showMarkLineLabel":false,"showDataZoom":true,"charts":[{"id":"4dbd3681-fc14-21d2-3a4e8acf02eb46e4","legendmode":0,"displayMode":1,"mos":["027bcb01-a8bf-4e20-97a0-0776cbb20447$ME{027bcb01-a8bf-4e20-97a0-0776cbb20447},EQ={/r=0/sh=0/sl=4/ssl=0},PTP={/p=1_1}"],"mosNames":["\\"9000-8EA_SPE01\\"-\\"P90E-2CGT-Q28[0-0-4-0]-100GE:1\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"ac82111b-6b57-1dd5-300cc8b9a9a769e0","legendmode":0,"displayMode":1,"mos":["480f0009-d020-40ee-9d8a-823051a32918$ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=4/ssl=0},PTP={/p=1_1}"],"mosNames":["\\"9000-8EA_SPE02\\"-\\"P90E-2CGT-Q28[0-0-4-0]-100GE:1\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"85ac9658-d34b-8a38-ce0be69df05af5a8","legendmode":0,"displayMode":1,"mos":["28dbff5e-6a99-40d1-89b9-cdff87cb1fc8$ME{28dbff5e-6a99-40d1-89b9-cdff87cb1fc8},EQ={/r=0/sh=0/sl=3/ssl=0},PTP={/p=1_1}"],"mosNames":["M6K_2S16_Logan_Town_UPE100-\\"RPN-02CG-H-VIRTUAL[0-0-3-0]-100GE:1\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"04f356d0-1889-5d5b-5ca48f7cf9e08ba0","legendmode":0,"displayMode":1,"mos":["d51a277b-cf5c-499e-8495-61dca4fdd46e$ME{d51a277b-cf5c-499e-8495-61dca4fdd46e},EQ={/r=0/sh=0/sl=3/ssl=0},PTP={/p=1_1}"],"mosNames":["M6K_2S16_Chocolate_City_UPE99-\\"RPN-02CG-H-VIRTUAL[0-0-3-0]-100GE:1\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"89d1e95b-1fb9-dfe1-7e88020f2546958f","legendmode":0,"displayMode":1,"mos":["e613f196-66cb-4dcb-ae5d-d10812bc675e$ME{e613f196-66cb-4dcb-ae5d-d10812bc675e},EQ={/r=0/sh=0/sl=3/ssl=0},PTP={/p=1_1}"],"mosNames":["M6K_2s16_SKD_UPE98-\\"RPN-02CG-H-VIRTUAL[0-0-3-0]-100GE:1\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"78c69708-2206-08b3-7be2783cab74df0c","legendmode":0,"displayMode":1,"mos":["dfe167e4-d039-4d59-84c4-1939f1ca5aef$ME{dfe167e4-d039-4d59-84c4-1939f1ca5aef},EQ={/r=0/sh=0/sl=2/ssl=0},PTP={/p=1_1}"],"mosNames":["\\"9000-3EA_LBS_UPE59\\"-\\"P90E-2CGT-Q28[0-0-2-0]-100GE:1\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"cefc086a-c554-9cc5-5b14121ed3411007","legendmode":0,"displayMode":1,"mos":["bcb8ce00-e497-4e8d-8dc3-c2231897b01c$ME{bcb8ce00-e497-4e8d-8dc3-c2231897b01c},EQ={/r=0/sh=0/sl=3/ssl=0},PTP={/p=1_1}"],"mosNames":["M6K_2s16_Nigeria_House_UPE97-\\"RPN-02CG-H-VIRTUAL[0-0-3-0]-100GE:1\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"9ae777ed-b59a-635b-d69d5fcb86403ee4","legendmode":0,"displayMode":1,"mos":["027bcb01-a8bf-4e20-97a0-0776cbb20447$ME{027bcb01-a8bf-4e20-97a0-0776cbb20447},EQ={/r=0/sh=0/sl=2/ssl=0},PTP={/p=1_3}"],"mosNames":["\\"9000-8EA_SPE01\\"-\\"P90E-3XLGET-QSFP+[0-0-2-0]-40GE:3\\""],"itemids":["C019901990","C019911991"],"selectedlegend":["C019901990","C019911991"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]}],"thresholdIds":[]}',
        "invaliditems": [],
        "favorite_id": '2cefcfdfe0e94e3c828d65479da18bf3',
        "showtimezoneoffset": True,
        "table_name": 'Metro_ring_me_15mins',
    },
    'Gbarnga_Buchanna_RIA_Kakata': {
        "favoriteconditionname": 'Gbarnga/Buchanna/RIA/Kakata',
        "filterlayer": 'me',
        "grouplayer": 'me,bnctp',
        "gr": '900',
        "displaymode": 0,
        "motid": 'BNCTN.PMP',
        "nfctid": 'bn.me.HG-FM,bn.me.ZXCTN.608,bn.me.ZXCTN.608P,bn.me.ZXCTN.609,bn.me.ZXCTN.6100,bn.me.ZXCTN.6110,bn.me.ZXCTN.6120,bn.me.ZXCTN.6120E,bn.me.ZXCTN.6120H,bn.me.ZXCTN.6120H-AB,bn.me.ZXCTN.6120H-C,bn.me.ZXCTN.15K-6120H-S,bn.me.ZXCTN.15K-6120H-SC,bn.me.ZXCTN.15K-6170H,bn.me.ZXCTN.6120S,bn.me.ZXCTN.6130-PTN,bn.me.ZXCTN.61-30XG,bn.me.ZXCTN.61-30XG-S,bn.me.ZXCTN.6150,bn.me.ZXCTN.6170H,bn.me.ZXCTN.6180,bn.me.ZXCTN.6180H,bn.me.ZXCTN.15K-6180H,bn.me.ZXCTN.15K-6180H-A,bn.me.ZXCTN.6190H,bn.me.ZXCTN.15K-6190H,bn.me.ZXCTN.6200,bn.me.ZXCTN.6220,bn.me.ZXCTN.6300,bn.me.ZXCTN.6500-16L,bn.me.ZXCTN.6500-32,bn.me.ZXCTN.6500-8,bn.me.ZXCTN.6700-12,bn.me.ZXCTN.6700-24,bn.me.ZXCTN.6700-32,bn.me.ZXCTN.810AB,bn.me.ZXCTN.15K-9000-16EX,bn.me.ZXCTN.15K-9000-18E,bn.me.ZXCTN.15K-9000-18EA,bn.me.ZXCTN.15K-9000-18ES,bn.me.ZXCTN.15K-9000-2E10,bn.me.ZXCTN.15K-9000-2E10A,bn.me.ZXCTN.15K-9000-2E4,bn.me.ZXCTN.15K-9000-2E4-Plus,bn.me.ZXCTN.15K-9000-2E8A,bn.me.ZXCTN.15K-9000-3E,bn.me.ZXCTN.15K-9000-3EA,bn.me.ZXCTN.15K-9000-4EX,bn.me.ZXCTN.15K-9000-5E,bn.me.ZXCTN.15K-9000-8E,bn.me.ZXCTN.15K-9000-8EA,bn.me.ZXCTN.15K-9000-8E-Plus,bn.me.ZXCTN.15K-9000-8ES,bn.me.ZXCTN.15K-9000-8EX,bn.me.ZXCTN.15K-9000-E-VND,bn.me.ZXCTN.9002,bn.me.ZXCTN.9004,bn.me.ZXCTN.9008,bn.me.ZXTC.3000,bn.me.ZXR10.15K-M6000-16SE,bn.me.ZXR10.15K-M6000-18S,bn.me.ZXR10.15K-M6000-18S-Plus,bn.me.ZXR10.15K-M6000-2S10,bn.me.ZXR10.15K-M6000-2S16,bn.me.ZXR10.15K-M6000-2S4,bn.me.ZXR10.15K-M6000-2S4-Plus,bn.me.ZXR10.15K-M6000-2S6,bn.me.ZXR10.15K-M6000-3S,bn.me.ZXR10.15K-M6000-3S-Plus,bn.me.ZXR10.15K-M6000-4SE,bn.me.ZXR10.15K-M6000-5S,bn.me.ZXR10.15K-M6000-6F,bn.me.ZXR10.15K-M6000-8S,bn.me.ZXR10.15K-M6000-8SE,bn.me.ZXR10.15K-M6000-8S-Plus,bn.me.ZXR10.15K-M6000-S-VND,bn.me.ZXR10.15K-M6000-S-VRC,bn.me.ZXR10.15K-ZXR10-Simulator',
        "items": ['C019911991', 'C019901990'],
        "itemsposition": [0, 0],
        "itemsposition1": [0, 0],
        "containvcell": 0,
        "indexfillingtype": 'zeroDenominator',
        "uilocations": [{'id': '4a55a623-3dac-4af5-9f05-1aad34505a3d', 'moc': 'bn.me.ZXCTN.15K-6180H-A', 'model': 'wlme'}, {'id': '71e920ec-4e6c-4a91-9a59-90d19c7338ca', 'moc': 'bn.me.ZXCTN.15K-6180H-A', 'model': 'wlme'}, {'id': 'c9d4710f-f0bc-47b5-92ef-b8d045c3c7f2', 'moc': 'bn.me.ZXR10.15K-M6000-2S16', 'model': 'wlme'}, {'id': 'd62267b0-f3fe-421b-b357-6f350d035676', 'moc': 'bn.me.ZXR10.15K-M6000-2S16', 'model': 'wlme'}],
        "reslocation": [],
        "chartsetting": '{"showchart":true,"layout":2,"showMarkLineLabel":false,"showDataZoom":true,"charts":[{"id":"1ad1a5a5-cfd9-dbfd-148db1741856a0ac","legendmode":0,"displayMode":0,"mos":["71e920ec-4e6c-4a91-9a59-90d19c7338ca$ME{71e920ec-4e6c-4a91-9a59-90d19c7338ca},EQ={/r=0/sh=1/sl=7},PTP={/p=1_1}"],"mosNames":["\\"6180H-A_Kakata_City_UPE29\\"-\\"OIXG4A[0-1-7]-10GE:1\\""],"itemids":["order_8","order_9"],"selectedlegend":["order_8","order_9"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"f53a00ff-40e8-1a29-9ca41aceb2392028","legendmode":0,"displayMode":0,"mos":["4a55a623-3dac-4af5-9f05-1aad34505a3d$ME{4a55a623-3dac-4af5-9f05-1aad34505a3d},EQ={/r=0/sh=1/sl=7},PTP={/p=1_2}"],"mosNames":["\\"6180H-A_RIA_UPE24\\"-\\"OIXG4A[0-1-7]-10GE:2\\""],"itemids":["order_8","order_9"],"selectedlegend":["order_8","order_9"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"b742f95f-693e-2b0f-3111dabda26a950f","legendmode":0,"displayMode":0,"mos":["c9d4710f-f0bc-47b5-92ef-b8d045c3c7f2$ME{c9d4710f-f0bc-47b5-92ef-b8d045c3c7f2},EQ={/r=0/sh=0/sl=1/ssl=0},PTP={/p=1_2}"],"mosNames":["M6k_2s16_Buchanan2_UPE77-\\"RPN-04XGL-H-VIRTUAL[0-0-1-0]-10GE:2\\""],"itemids":["order_8","order_9"],"selectedlegend":["order_8","order_9"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"e0ced865-7e22-30c7-226816c50b2a9e74","legendmode":0,"displayMode":0,"mos":["d62267b0-f3fe-421b-b357-6f350d035676$ME{d62267b0-f3fe-421b-b357-6f350d035676},EQ={/r=0/sh=0/sl=255},FTP={/p=124_20}"],"mosNames":["M6K_2s16_Gbarnga_UPE76-SmartGroup:20"],"itemids":["order_8","order_9"],"selectedlegend":["order_8","order_9"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]}],"thresholdIds":[],"countersInfo":[{"key":"order_8","id":"C019911991","itemposition":0,"itemposition1":0},{"key":"order_9","id":"C019901990","itemposition":0,"itemposition1":0}]}',
        "invaliditems": [],
        "favorite_id": 'b2c07ae1a70946a4a604b0f45ba529c6',
        "showtimezoneoffset": False,
        "table_name": 'Gbarnga_Buchanna_RIA_Kakata_me_15mins',
    },
    'Banjor_ELWA': {
        "favoriteconditionname": 'Banjor/ELWA',
        "filterlayer": 'me',
        "grouplayer": 'me,bnctp',
        "gr": '900',
        "displaymode": 0,
        "motid": 'BNCTN.PMP',
        "nfctid": 'bn.me.HG-FM,bn.me.ZXCTN.608,bn.me.ZXCTN.608P,bn.me.ZXCTN.609,bn.me.ZXCTN.6100,bn.me.ZXCTN.6110,bn.me.ZXCTN.6120,bn.me.ZXCTN.6120E,bn.me.ZXCTN.6120H,bn.me.ZXCTN.6120H-AB,bn.me.ZXCTN.6120H-C,bn.me.ZXCTN.15K-6120H-S,bn.me.ZXCTN.15K-6120H-SC,bn.me.ZXCTN.15K-6170H,bn.me.ZXCTN.6120S,bn.me.ZXCTN.6130-PTN,bn.me.ZXCTN.61-30XG,bn.me.ZXCTN.61-30XG-S,bn.me.ZXCTN.6150,bn.me.ZXCTN.6170H,bn.me.ZXCTN.6180,bn.me.ZXCTN.6180H,bn.me.ZXCTN.15K-6180H,bn.me.ZXCTN.15K-6180H-A,bn.me.ZXCTN.6190H,bn.me.ZXCTN.15K-6190H,bn.me.ZXCTN.6200,bn.me.ZXCTN.6220,bn.me.ZXCTN.6300,bn.me.ZXCTN.6500-16L,bn.me.ZXCTN.6500-32,bn.me.ZXCTN.6500-8,bn.me.ZXCTN.6700-12,bn.me.ZXCTN.6700-24,bn.me.ZXCTN.6700-32,bn.me.ZXCTN.810AB,bn.me.ZXCTN.15K-9000-16EX,bn.me.ZXCTN.15K-9000-18E,bn.me.ZXCTN.15K-9000-18EA,bn.me.ZXCTN.15K-9000-18ES,bn.me.ZXCTN.15K-9000-2E10,bn.me.ZXCTN.15K-9000-2E10A,bn.me.ZXCTN.15K-9000-2E4,bn.me.ZXCTN.15K-9000-2E4-Plus,bn.me.ZXCTN.15K-9000-2E8A,bn.me.ZXCTN.15K-9000-3E,bn.me.ZXCTN.15K-9000-3EA,bn.me.ZXCTN.15K-9000-4EX,bn.me.ZXCTN.15K-9000-5E,bn.me.ZXCTN.15K-9000-8E,bn.me.ZXCTN.15K-9000-8EA,bn.me.ZXCTN.15K-9000-8E-Plus,bn.me.ZXCTN.15K-9000-8ES,bn.me.ZXCTN.15K-9000-8EX,bn.me.ZXCTN.15K-9000-E-VND,bn.me.ZXCTN.9002,bn.me.ZXCTN.9004,bn.me.ZXCTN.9008,bn.me.ZXTC.3000',
        "items": ['C019901990', 'C019911991'],
        "itemsposition": [0, 0],
        "itemsposition1": [0, 0],
        "containvcell": 0,
        "indexfillingtype": 'zeroDenominator',
        "uilocations": [{'id': 'a1e68c46-9f7e-4c9e-9224-95fbf1859e09', 'moc': 'bn.me.ZXCTN.15K-6120H-S', 'model': 'wlme'}, {'id': '5d0b8d3c-7501-4f07-94ed-0023006651cf', 'moc': 'bn.me.ZXCTN.15K-6120H-S', 'model': 'wlme'}],
        "reslocation": [],
        "chartsetting": '{"showchart":true,"layout":1,"showMarkLineLabel":false,"showDataZoom":true,"charts":[{"id":"872ab1d1-edd2-c0bd-38976235d78fadb5","legendmode":0,"displayMode":0,"mos":["a1e68c46-9f7e-4c9e-9224-95fbf1859e09$ME{a1e68c46-9f7e-4c9e-9224-95fbf1859e09},EQ={/r=0/sh=1/sl=1},PTP={/p=1_20}"],"mosNames":["\\"6120H-S_Banjor_UPE18\\"-\\"SMGD[0-1-1]-25GE:20\\""],"itemids":["order_8","order_9"],"selectedlegend":["order_8","order_9"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]},{"id":"d796eafc-e17a-c5dc-b8ca043ba654909f","legendmode":0,"displayMode":0,"mos":["5d0b8d3c-7501-4f07-94ed-0023006651cf$ME{5d0b8d3c-7501-4f07-94ed-0023006651cf},EQ={/r=0/sh=1/sl=1},PTP={/p=1_33}"],"mosNames":["\\"6120H-S_ELWA_UPE68\\"-\\"SMGD[0-1-1]-100GE:33\\""],"itemids":["order_8","order_9"],"selectedlegend":["order_8","order_9"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]}],"thresholdIds":[],"countersInfo":[{"key":"order_8","id":"C019901990","itemposition":0,"itemposition1":0},{"key":"order_9","id":"C019911991","itemposition":0,"itemposition1":0}]}',
        "invaliditems": [],
        "favorite_id": 'c7a4f1a560ce44d28d066fa59ac21cbf',
        "showtimezoneoffset": False,
        "table_name": 'Banjor_ELWA_me_15mins',
    },
    'OLT': {
        "favoriteconditionname": 'OLT',
        "filterlayer": 'bnctp',
        "grouplayer": 'me,bnctp',
        "gr": '900',
        "displaymode": 1,
        "motid": 'BNCTN.PMP',
        "nfctid": 'bn.me.HG-FM,bn.me.ZXCTN.608,bn.me.ZXCTN.608P,bn.me.ZXCTN.609,bn.me.ZXCTN.6100,bn.me.ZXCTN.6110,bn.me.ZXCTN.6120,bn.me.ZXCTN.6120E,bn.me.ZXCTN.6120H,bn.me.ZXCTN.6120H-AB,bn.me.ZXCTN.6120H-C,bn.me.ZXCTN.15K-6120H-S,bn.me.ZXCTN.15K-6120H-SC,bn.me.ZXCTN.15K-6170H,bn.me.ZXCTN.6120S,bn.me.ZXCTN.6130-PTN,bn.me.ZXCTN.61-30XG,bn.me.ZXCTN.61-30XG-S,bn.me.ZXCTN.6150,bn.me.ZXCTN.6170H,bn.me.ZXCTN.6180,bn.me.ZXCTN.6180H,bn.me.ZXCTN.15K-6180H,bn.me.ZXCTN.15K-6180H-A,bn.me.ZXCTN.6190H,bn.me.ZXCTN.15K-6190H,bn.me.ZXCTN.6200,bn.me.ZXCTN.6220,bn.me.ZXCTN.6300,bn.me.ZXCTN.6500-16L,bn.me.ZXCTN.6500-32,bn.me.ZXCTN.6500-8,bn.me.ZXCTN.6700-12,bn.me.ZXCTN.6700-24,bn.me.ZXCTN.6700-32,bn.me.ZXCTN.810AB,bn.me.ZXCTN.15K-9000-16EX,bn.me.ZXCTN.15K-9000-18E,bn.me.ZXCTN.15K-9000-18EA,bn.me.ZXCTN.15K-9000-18ES,bn.me.ZXCTN.15K-9000-2E10,bn.me.ZXCTN.15K-9000-2E10A,bn.me.ZXCTN.15K-9000-2E4,bn.me.ZXCTN.15K-9000-2E4-Plus,bn.me.ZXCTN.15K-9000-2E8A,bn.me.ZXCTN.15K-9000-3E,bn.me.ZXCTN.15K-9000-3EA,bn.me.ZXCTN.15K-9000-4EX,bn.me.ZXCTN.15K-9000-5E,bn.me.ZXCTN.15K-9000-8E,bn.me.ZXCTN.15K-9000-8EA,bn.me.ZXCTN.15K-9000-8E-Plus,bn.me.ZXCTN.15K-9000-8ES,bn.me.ZXCTN.15K-9000-8EX,bn.me.ZXCTN.15K-9000-E-VND,bn.me.ZXCTN.9002,bn.me.ZXCTN.9004,bn.me.ZXCTN.9008,bn.me.ZXTC.3000',
        "items": ['C019911991', 'C019901990'],
        "itemsposition": [0, 0],
        "itemsposition1": [0, 0],
        "containvcell": 0,
        "indexfillingtype": 'zeroDenominator',
        "uilocations": [{'id': '480f0009-d020-40ee-9d8a-823051a32918$ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1},PTP={/p=1_3}', 'moc': 'bnptp', 'model': 'bnptp'}],
        "reslocation": [{'id': 'ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1},PTP={/p=1_3}', 'displayName': 'P90E-4XGET-SFP+[0-0-0-1]-10GE:3', 'nbiId': 'ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1},PTP={/p=1_3}', 'labelDn': '9000-8EA_SPE02#P90E-4XGET-SFP+[0-0-0-1]#P90E-4XGET-SFP+[0-0-0-1]-10GE:3', 'moc': 'bnptp', 'path': [{'id': '480f0009-d020-40ee-9d8a-823051a32918', 'displayName': '9000-8EA_SPE02', 'model': 'wlme', 'nbiId': 'BN:ME{431941252}'}, {'id': 'ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1}', 'displayName': 'P90E-4XGET-SFP+[0-0-0-1]', 'model': 'bneq', 'nbiId': 'ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1}'}, {'id': 'ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1},PTP={/p=1_3}', 'displayName': 'P90E-4XGET-SFP+[0-0-0-1]-10GE:3', 'model': 'bnptp', 'nbiId': 'ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1},PTP={/p=1_3}'}]}],
        "chartsetting": '{"showchart":true,"layout":1,"showMarkLineLabel":false,"showDataZoom":true,"charts":[{"id":"423378e7-d633-f99e-54f2c322ab81d946","legendmode":0,"displayMode":1,"mos":["480f0009-d020-40ee-9d8a-823051a32918$ME{480f0009-d020-40ee-9d8a-823051a32918},EQ={/r=0/sh=0/sl=0/ssl=1},PTP={/p=1_3}"],"mosNames":["\\"9000-8EA_SPE02\\"-\\"P90E-4XGET-SFP+[0-0-0-1]-10GE:3\\""],"itemids":["C019911991","C019901990"],"selectedlegend":["C019911991","C019901990"],"markingsettings":[],"custommarkingsettings":[],"showsetting":[]}],"thresholdIds":[]}',
        "invaliditems": [],
        "favorite_id": '558af12c5a9b41c582f27b5487344c8b',
        "showtimezoneoffset": False,
        "table_name": 'OLT_bnctp_15mins',
    },
}

IPRAN_KPI_TASKS = [
    {"key": 'HQ_M6K_FW'},
    {"key": 'IPCORE_HQ_ODC'},
    {"key": 'Metro_ring'},
    {"key": 'Gbarnga_Buchanna_RIA_Kakata'},
    {"key": 'Banjor_ELWA'},
    {"key": 'OLT'},
]


# ============================================================
# HTTP Session 高并发客户端
# ============================================================
class UmeBusinessError(Exception):
    """UME 返回 HTTP 499 + errorcode 的永久性业务错误（查询条件非法等），重试无效"""
    pass


class UmeRepeatedQueryError(UmeBusinessError):
    """Repeated query：服务端已有同名查询在跑或尚未释放，属暂时性错误，可退避重试"""
    pass


class UmeSessionClient:
    """封装 requests.Session，配有连接池与重试机制，专为并发优化"""
    def __init__(self, host: str, port: int):
        self.base_url = f"https://{host}:{port}"
        self.session = requests.Session()
        self.session.verify = False

        # 高并发连接池适配器配置
        adapter = HTTPAdapter(
            pool_connections=MAX_PARALLEL_WORKERS * 2,
            pool_maxsize=MAX_PARALLEL_WORKERS * 2,
            max_retries=Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        })
        self.forgery_token = ""
        # 会话续期：记录登录时间，供主动刷新与 401 自动重登录使用
        self._login_lock = threading.Lock()
        self.logged_in_at = None

    def rsa_encrypt(self, plaintext: str, public_key_b64: str) -> str:
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        from cryptography.hazmat.primitives import serialization
        pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
        public_key = serialization.load_pem_public_key(pem.encode())
        encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
        return base64.b64encode(encrypted).decode('ascii')

    def login(self):
        logger.info("[LOGIN] Starting authentication via requests.Session...")
        auth_url = f"{self.base_url}/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri={LOGIN_PORTAL}"
        resp1 = self.session.get(auth_url, timeout=20)
        
        for k, v in self.session.cookies.items():
            if "forgerydefense" in k:
                self.forgery_token = v

        lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', resp1.text)
        login_parameters = lp_match.group(1) if lp_match else ""

        pk_url = f"{self.base_url}/api/oauth2/v1/login/publickey"
        headers_extra = {"X-Requested-With": "XMLHttpRequest"}
        resp2 = self.session.get(pk_url, headers=headers_extra, timeout=20)
        public_key_b64 = resp2.json().get("rsaPublicKey", "")
        if not public_key_b64:
            raise Exception("无法获取 RSA 公钥，登录中止")

        encrypted_pwd = self.rsa_encrypt(PASSWORD, public_key_b64)
        login_payload = {
            "username": USERNAME,
            "password": encrypted_pwd,
            "parameters": login_parameters,
        }
        login_url = f"{self.base_url}/api/oauth2/v1/login_rsa"
        headers_login = {
            "Content-Type": "application/json",
            "Referer": auth_url,
            "X-Requested-With": "XMLHttpRequest",
        }
        if self.forgery_token:
            headers_login["forgerydefense"] = self.forgery_token

        resp3 = self.session.post(login_url, json=login_payload, headers=headers_login, timeout=20)
        
        for k, v in self.session.cookies.items():
            if "forgerydefense" in k:
                self.forgery_token = v

        if resp3.status_code not in (200, 302):
            raise Exception(f"登录失败: {resp3.status_code}, response: {resp3.text[:200]}")

        self.session.headers.update({
            "Content-Type": "application/json; charset=UTF-8",
            "Referer": HISTORY_REFERER,
            "X-Requested-With": "XMLHttpRequest",
            "language-option": "en-US",
            "timeZoneInfo": "Default,Atlantic/Reykjavik,",
        })
        if self.forgery_token:
            self.session.headers["forgerydefense"] = self.forgery_token

        logger.info("[LOGIN] SUCCESS - Session pool ready for parallel queries.")
        self.logged_in_at = time.time()

    def ensure_session_fresh(self, max_age: int = SESSION_REFRESH_SEC):
        """多任务共用同一 UME 会话（单账号单会话限制），需加锁避免并发重复登录。
        会话超过 max_age 秒则主动重新登录，防止长耗时任务中途 401。"""
        with self._login_lock:
            if self.logged_in_at is None or (time.time() - self.logged_in_at) > max_age:
                logger.info("[LOGIN] Proactive session refresh (age exceeded threshold)")
                self.login()
                self.logged_in_at = time.time()

    def request_with_retry(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}" if path.startswith("/") else path
        max_retries = kwargs.pop("max_retries", 2)
        req_timeout = kwargs.pop("timeout", 30)
        for attempt in range(max_retries + 1):
            try:
                resp = self.session.request(method, url, timeout=req_timeout, **kwargs)
                # 401 = UME 会话过期（约 30 分钟），重新登录一次后立即用新会话重试。
                # 多任务共用同一 session，加锁避免并发重复登录把彼此踢下线。
                if resp.status_code == 401:
                    logger.warning(f"[HTTP] 401 session expired on {method} {path} -> re-login & retry")
                    with self._login_lock:
                        self.login()
                        self.logged_in_at = time.time()
                    resp = self.session.request(method, url, timeout=req_timeout, **kwargs)
                # UME 用 HTTP 499 同时表达「业务条件不合法」和「网关中断」。
                # 业务错误响应体带 errorcode，属永久性失败，重试无意义，直接抛出并带上原因。
                if resp.status_code == 499:
                    body = (resp.text or "")[:400]
                    if "errorcode" in body:
                        if "Repeated query" in body:
                            raise UmeRepeatedQueryError(f"{method} {path} -> 499 {body}")
                        raise UmeBusinessError(f"{method} {path} -> 499 {body}")
                if resp.status_code in (499, 500, 502, 503, 504):
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue
                if not resp.ok:
                    raise requests.HTTPError(
                        f"{resp.status_code} {method} {path} -> {(resp.text or '')[:400]}",
                        response=resp,
                    )
                return resp
            except (UmeBusinessError, UmeRepeatedQueryError):
                raise
            except Exception as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(f"[HTTP] {method} {path} attempt {attempt+1} failed: {e}, retry in {wait}s")
                    time.sleep(wait)
                else:
                    raise e
        return resp


# ============================================================
# Core API Processing
# ============================================================
def _subtract_months(dt, months):
    import calendar
    year = dt.year
    month = dt.month - months
    while month < 1:
        month += 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def build_ipran_kpi_payload(cfg: dict) -> dict:
    now = datetime.now(timezone.utc)
    end_iso = now.replace(hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_dt = _subtract_months(now.replace(hour=0, minute=0, second=0, microsecond=0), MONTHS_BACK)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payload = {
        "arraycounterinfos": [],
        "displaymode": cfg.get("displaymode", 0),
        "favoriteconditionname": cfg["favoriteconditionname"],
        "gr": cfg["gr"],
        "groupattributetype": 0,
        "groupbygroup": False,
        "groupbyplmn": False,
        "grouptype": 0,
        "items": cfg["items"],
        "itemsposition": cfg["itemsposition"],
        "itemsposition1": cfg["itemsposition1"],
        "motid": cfg["motid"],
        "nfctid": cfg["nfctid"],
        "plmnpdfdisplaymode": False,
        "queryallbusiness": False,
        "showbusinesscolumn": False,
        "showintegrity": False,
        "straightquery": False,
        "needdeployfilter": False,
        "timeinfo": {
            "mode": 1,
            "start": start_iso,
            "end": end_iso,
            "relative": -7,
            "timezonetype": "1",
            "clienttimezone": "Atlantic/Reykjavik",
            "showtimezoneoffset": cfg.get("showtimezoneoffset", False),
            "querylongtime": {"type": 0, "value": 1},
            "timespanfilter": "00:00:00-24:00:00",
            "dayfiltertype": 0,
            "dayinmonthfilter": "1111111111111111111111111111111",
        },
        "indexfillingtype": cfg.get("indexfillingtype", "zeroDenominator"),
        "thresholdinfos": [],
        "sendalarm": False,
        "templatetype": 0,
        "filterlayer": cfg["filterlayer"],
        "grouplayer": cfg["grouplayer"],
        "containvcell": cfg.get("containvcell", 0),
        "resfilterattribute": "",
        "uilocations": cfg.get("uilocations", []),
        "reslocation": cfg.get("reslocation", []),
        "inexistenceres": False,
        "firstDayOfWeek": 7,
        "iswireless": False,
        "hidehistorystopbutton": False,
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
        "id": cfg.get("favorite_id", ""),
    }
    
    if "chartsetting" in cfg:
        payload["chartsetting"] = cfg["chartsetting"]
    if "versiondatacompare" in cfg:
        payload["versiondatacompare"] = cfg["versiondatacompare"]
    return payload


def create_history_query(client: UmeSessionClient, payload: dict) -> str:
    logger.info(f"[KPI] Submitting query for: {payload.get('favoriteconditionname')}")
    resp = client.request_with_retry("POST", HISTORY_PATH, json=payload)
    data = resp.json()
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned: {resp.text[:200]}")
    logger.info(f"[KPI] Created Query ID: {queryid} ({payload.get('favoriteconditionname')})")
    return queryid


def adaptive_poll_history_ready(client: UmeSessionClient, queryid: str, name: str, timeout: int = 2400) -> dict:
    """高频率自适应轮询，毫秒级感知网管计算完成"""
    path = f"{HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    deadline = time.time() + timeout
    
    # 极速阶梯策略：先快后稳
    intervals = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]
    idx = 0

    while time.time() < deadline:
        resp = client.request_with_retry("GET", path, max_retries=1)
        data = resp.json()
        progress = data.get("progress", 0)
        querystate = data.get("querystate", 0)
        
        if querystate == 1 or progress >= 100:
            logger.info(f"[KPI] Query READY -> {name} (ID: {queryid})")
            return data

        sleep_sec = intervals[idx] if idx < len(intervals) else 5.0
        if idx < len(intervals) - 1:
            idx += 1
        time.sleep(sleep_sec)

    raise Exception(f"KPI query timed out after {timeout}s: {name}")


def _extract_xlsx_stream(resp_bytes: bytes) -> io.BytesIO:
    """在内存中无落盘解包 ZIP 提取 Excel 内容"""
    if len(resp_bytes) >= 4 and resp_bytes[:2] == b'PK':
        try:
            import zipfile
            with zipfile.ZipFile(io.BytesIO(resp_bytes)) as z:
                xlsx_names = [n for n in z.namelist() if n.lower().endswith('.xlsx')]
                if xlsx_names:
                    return io.BytesIO(z.read(xlsx_names[0]))
                if len(z.namelist()) == 1:
                    return io.BytesIO(z.read(z.namelist()[0]))
        except Exception as e:
            logger.warning(f"[KPI] In-memory ZIP extraction bypassed: {e}")
    return io.BytesIO(resp_bytes)


def export_history_to_memory(client: UmeSessionClient, queryid: str, filename: str) -> io.BytesIO:
    payload = {
        "id": queryid,
        "filename": filename,
        "chartlayout": 1,
        "contentmode": 0,
        "customizefieldtype": "0",
        "exportfiletype": 1,
        "exportserialnumber": False,
        "exporttableheaders": False,
        "formatwithts": 0,
        "imageinfo": [],
        "itemshowtype": 0,
        "tableheaders": {},
    }
    # 导出接口响应慢（大数据量可达 2-5 分钟），超时设为 300s
    resp = client.request_with_retry("POST", HISTORY_EXPORT_PATH, json=payload, timeout=300, max_retries=2)
    return _extract_xlsx_stream(resp.content)


# ============================================================
# Excel 解析与 SQLite 高性能落盘
# ============================================================
def parse_xlsx_in_memory(stream: io.BytesIO) -> tuple[list, list]:
    """高性能内存在线解析 Excel 表格"""
    try:
        try:
            xls = pd.ExcelFile(stream, engine='calamine')
        except Exception:
            xls = pd.ExcelFile(stream, engine='openpyxl')

        for sname in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sname, header=None)
            if df.empty:
                continue
            
            for i in range(min(20, len(df))):
                row_vals = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[i].tolist()]
                if "Begin Time" in row_vals:
                    headers = row_vals
                    data_df = df.iloc[i + 1:].dropna(how='all')
                    data = data_df.astype(object).where(pd.notnull(data_df), None).values.tolist()
                    return headers, data
    except Exception as e:
        logger.error(f"[xlsx-memory] Memory parsing error: {e}")
    return [], []


def detect_key_cols(headers: list) -> list:
    if "Begin Time" not in headers:
        return []
    key_cols = ["Begin Time"]
    for cand in IDENTITY_COL_CANDIDATES:
        if cand in headers:
            key_cols.append(cand)
            break
    return key_cols


def build_filename(cfg: dict) -> str:
    name = cfg["favoriteconditionname"].replace(" ", "_").replace("/", "_").replace("\\", "_").replace("-", "_")
    layer = cfg["filterlayer"]
    gr_label = GR_RENAME.get(cfg["gr"], cfg["gr"])
    return f"{name}_{layer}_{gr_label}"


def sanitize_table_name(name: str) -> str:
    return name.replace(" ", "_").replace("-", "_")


def save_data_to_db_or_api(table_name: str, headers: list, data: list) -> int:
    """使用 INSERT OR REPLACE 实现原生超高速覆盖写入"""
    if not headers or not data:
        return 0

    # 1. API 客户端优先机制
    if _db_writer is not None:
        try:
            str_data = [[str(v) if v is not None else None for v in row] for row in data]
            res = _db_writer.write_data(
                db=DB_NAME,
                table=table_name,
                columns=headers,
                rows=str_data,
                mode="full_replace",
            )
            rows_written = res.get("rows_written", 0)
            logger.info(f"[DB][API] {table_name}: Written {rows_written} rows")
            return rows_written
        except Exception as e:
            logger.error(f"[DB][API] {table_name}: API write failed ({e}), falling back to local SQLite")

    # 2. SQLite 高并发 WAL 模式写入
    import sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=OFF")

    key_cols = detect_key_cols(headers)
    def _q(col): return f'"{col.replace('"', '""')}"'

    cols_decl = [f"{_q(h)} TEXT" for h in headers]
    pk_clause = f", PRIMARY KEY ({', '.join(_q(k) for k in key_cols)})" if key_cols else ""
    create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(cols_decl)}{pk_clause})'
    
    try:
        cursor.execute(create_sql)
    except sqlite3.OperationalError:
        cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(cols_decl)})')

    cols_str = ", ".join(_q(h) for h in headers)
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = f'INSERT OR REPLACE INTO "{table_name}" ({cols_str}) VALUES ({placeholders})'

    formatted_data = []
    for row in data:
        if len(row) < len(headers):
            row.extend([None] * (len(headers) - len(row)))
        formatted_data.append([str(v) if v is not None else None for v in row[:len(headers)]])

    cursor.executemany(insert_sql, formatted_data)
    conn.commit()
    conn.close()

    logger.info(f"[DB][LOCAL] {table_name}: Inserted/Replaced {len(formatted_data)} rows into SQLite")
    return len(formatted_data)


# ============================================================
# 并行管道调度
# ============================================================
def _run_single_kpi_pipeline(client: UmeSessionClient, task: dict) -> tuple[str, int]:
    """独立单任务流水线 (适合全并发执行)"""
    cfg = IPRAN_KPI_QUERY_CONFIGS[task["key"]]
    table_name = cfg.get("table_name") or sanitize_table_name(build_filename(cfg))
    file_prefix = build_filename(cfg)
    payload = build_ipran_kpi_payload(cfg)

    # 长耗时任务中途续期会话，避免 401
    client.ensure_session_fresh()

    # 创建查询：遇 Repeated query（服务端旧查询未释放）退避重试，等待其释放
    queryid = None
    last_err = None
    for attempt in range(MAX_CREATE_RETRIES):
        try:
            queryid = create_history_query(client, payload)
            break
        except UmeRepeatedQueryError as e:
            last_err = e
            if attempt < MAX_CREATE_RETRIES - 1:
                wait = CREATE_RETRY_WAIT
                logger.warning(
                    f"[KPI][{task['key']}] Repeated query, 退避 {wait}s 后重试 ({attempt+1}/{MAX_CREATE_RETRIES})"
                )
                # 等待期间会话可能过期，重试前续期
                client.ensure_session_fresh()
                time.sleep(wait)
            else:
                logger.error(f"[KPI][{task['key']}] Repeated query 重试耗尽，放弃")
        except Exception as e:
            last_err = e
            break
    if queryid is None:
        raise last_err or Exception("create query failed")

    try:
        # 轮询等待计算就绪
        adaptive_poll_history_ready(client, queryid, cfg["favoriteconditionname"])

        # 导出前再次续期，防止长轮询后会话已过期
        client.ensure_session_fresh()

        # 导出到内存
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{file_prefix}_{timestamp}"
        stream = export_history_to_memory(client, queryid, filename)

        # 内存快速解析
        headers, data = parse_xlsx_in_memory(stream)
        stream.close()

        # 解析失败必须抛异常，避免静默记为成功
        if not headers:
            raise Exception(f"Excel 解析失败: 未找到 'Begin Time' 表头 (sheets 可能为空或格式异常)")
        if not data:
            raise Exception(f"Excel 解析后无数据行 (表头已定位但数据为空)")

        # 原生高效写入/覆盖
        rows_written = save_data_to_db_or_api(table_name, headers, data)
        if rows_written == 0:
            raise Exception(f"数据写入失败: save_data_to_db_or_api 返回 0 行")
        return task["key"], rows_written
    finally:
        # 关键：释放服务端查询占用，避免堆积导致后续 Repeated query
        if queryid:
            try:
                del_url = f"{client.base_url}{HISTORY_POLL_PATH}?queryid={queryid}"
                rr = client.session.delete(del_url, headers=client.session.headers, timeout=20, verify=False)
                logger.info(f"[KPI][{task['key']}] 释放查询 {queryid} -> {rr.status_code}")
            except Exception as e:
                logger.warning(f"[KPI][{task['key']}] 释放查询 {queryid} 失败: {e}")


def run_ipran_kpi_sync():
    """高并发主入口"""
    t_start = time.time()
    logger.info(f"[iPRAN] High-Concurrency In-Memory KPI sync started. Workers={MAX_PARALLEL_WORKERS}")

    # 1. 建立长连接 Pooling Session 并登录
    client = UmeSessionClient(HOST, PORT)
    client.login()

    # 2. 全并发多线程执行
    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        future_to_task = {
            executor.submit(_run_single_kpi_pipeline, client, task): task 
            for task in IPRAN_KPI_TASKS
        }

        for future in as_completed(future_to_task):
            task = future_to_task[future]
            task_key = task["key"]
            try:
                key, rows = future.result()
                results.append((key, rows))
                logger.info(f"[iPRAN] [{task_key}] Sync Finished -> {rows} rows synced.")
            except Exception as e:
                errors.append((task_key, str(e)))
                logger.error(f"[iPRAN] [{task_key}] Pipeline Failed -> {e}")

    gc.collect()
    elapsed = time.time() - t_start
    total_rows = sum(r[1] for r in results)

    logger.info(f"[iPRAN] Sync Finished in {elapsed:.2f}s | Success={len(results)} | Failed={len(errors)} | Total Rows={total_rows}")

    return {
        "success": len(errors) == 0,
        "exported": len(results),
        "failed": len(errors),
        "errors": [f"{k}: {v}" for k, v in errors],
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 2),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = run_ipran_kpi_sync()
    print(f"\nExecution Result:\n{json.dumps(result, ensure_ascii=False, indent=2)}")