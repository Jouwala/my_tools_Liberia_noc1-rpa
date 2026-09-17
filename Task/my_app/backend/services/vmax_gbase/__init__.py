"""VMAX 数仓 GBase 8a 直连取数（MySQL 协议）。

与 `backend/services/vmax_multi_data`（走 VMAX 门户 vreport HTTP 接口）互为补充：
本包直连数据仓库，用 SQL 取明细，能拿到门户接口给不了的业务/APP/网元/站点维度，
且没有 RSA 信封、TopN 截断、单请求超时这些问题。

来源：用户提供的 JupyterLab notebook（`OLIB SOC VMAX Routine Report`）里
`VmaxTool.GetDBConn("GBASE")` + `QueryDB_df()`，实测连接信息见
`vmax_gbase_client.py` 顶部注释。
"""
from backend.services.vmax_gbase.vmax_gbase_client import (              # noqa: F401
    VmaxGbaseClient,
    VmaxGbaseError,
    VmaxGbaseUnavailable,
    available_days,
    partition_days,
    resolve_dsn,
)

__all__ = [
    "VmaxGbaseClient",
    "VmaxGbaseError",
    "VmaxGbaseUnavailable",
    "available_days",
    "partition_days",
    "resolve_dsn",
]
