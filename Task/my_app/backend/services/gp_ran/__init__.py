"""gp_ran —— RAN Greenplum（193.168.0.6，经 control1 跳板）只读取数客户端。

与 `vmax_gbase`（GBase 8a / MySQL 协议 / pymysql 直连）**不是一套东西**：
这里的 SQL 用了 `::TIMESTAMP`、`EXTRACT(EPOCH FROM ...)`，且需要 `gpadmin` + `psql`，
是 ZTE PaaS 托管的 Greenplum 集群。数据库端口 5432 对本机不可达，只能走 SSH 两跳。

用法:
    from backend.services.gp_ran import GpRanClient
    with GpRanClient() as c:
        csv_text = c.query_csv("SELECT 1")
"""
from .gp_ran_client import (
    GpRanClient,
    GpRanError,
    GpRanUnavailable,
    resolve_endpoints,
    endpoints_summary,
    sql_volte_users,
    sql_n78_users,
    epoch_of,
    EPOCH_BASE,
)

__all__ = [
    "GpRanClient", "GpRanError", "GpRanUnavailable",
    "resolve_endpoints", "endpoints_summary",
    "sql_volte_users", "sql_n78_users", "epoch_of", "EPOCH_BASE",
]
