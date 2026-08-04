# -*- coding: utf-8 -*-
"""
远程数据库读取器
通过 HTTP API 读取远程 SQLite 数据库中的数据
"""
import json
import logging
import urllib.request
import urllib.error
from typing import List, Optional, Dict, Any

logger = logging.getLogger("remote_db_reader")

API_BASE_URL = "http://192.168.100.19:8765"


class RemoteDBReader:
    """通过 HTTP API 读取远程 SQLite 数据库"""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
    
    def _request(self, path: str, data: dict = None, method: str = "GET") -> dict:
        """发送 HTTP 请求"""
        url = f"{self.base_url}{path}"
        
        if data:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method=method
            )
        else:
            req = urllib.request.Request(url, method=method)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            logger.error(f"HTTP Error {e.code}: {error_body}")
            raise Exception(f"HTTP {e.code}: {error_body[:200]}")
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise
    
    def list_tables(self, db: str) -> List[Dict[str, Any]]:
        """列出数据库中的表"""
        result = self._request(f"/api/tables?db={db}")
        return result.get("tables", [])
    
    def read_table(self, db: str, table: str, limit: int = 10000, 
                   columns: List[str] = None, where: str = None,
                   order_by: str = None) -> Dict[str, Any]:
        """
        读取表格数据
        
        Args:
            db: 数据库名称
            table: 表名
            limit: 最大返回行数
            columns: 要选择的列，None 表示全部
            where: SQL WHERE 条件（不含 WHERE 关键字）
            order_by: 排序字段
        """
        payload = {
            "db": db,
            "table": table,
            "limit": limit,
        }
        if columns:
            payload["columns"] = columns
        if where:
            payload["where"] = where
        if order_by:
            payload["order_by"] = order_by
        
        result = self._request("/api/read", data=payload, method="POST")
        return result
    
    def health_check(self) -> dict:
        """检查 API 状态"""
        return self._request("/health")


def get_remote_reader() -> RemoteDBReader:
    """获取远程数据库读取器单例"""
    return RemoteDBReader()


if __name__ == "__main__":
    reader = RemoteDBReader()
    
    # 测试健康检查
    print("Health check:")
    print(reader.health_check())
    
    # 测试列出 CNN 表
    print("\nCNN Tables:")
    for table in reader.list_tables("db_ps_cs_cn.sqlite3"):
        print(f"  {table['name']}: {table['rows']} rows")
    
    # 测试列出 IPRAN 表
    print("\nIPRAN Tables:")
    for table in reader.list_tables("ipran_ume_kpi.sqlite3"):
        print(f"  {table['name']}: {table['rows']} rows")
    
    # 测试读取少量数据
    print("\nSample data from FREE_RATING_GROUP_TEMPLATE_OSS_update_UME:")
    result = reader.read_table(
        db="db_ps_cs_cn.sqlite3",
        table="FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
        columns=["Begin Time", "Measurement Object", "C550400011", "C550400012", "C550400013"],
        where='"Measurement Object" = "30"',
        limit=5
    )
    print(f"Columns: {result.get('columns')}")
    print(f"Rows: {result.get('count')}")
    for row in result.get('rows', [])[:3]:
        print(f"  {row}")
