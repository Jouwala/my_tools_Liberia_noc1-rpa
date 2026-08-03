# -*- coding: utf-8 -*-
"""
import logging
SQLite 远程写入客户端模块

供本地 RPA 脚本调用，将数据通过 HTTP POST 写入远程服务器上的 SQLite 数据库。
替代原有的 FTP 下载 → 本地修改 → FTP 上传 流程。

使用方式：
    from db_writer_client import DbWriterClient

    client = DbWriterClient()  # 默认连接 192.168.100.19:8765

    # 方式1：直接写入数据（适用于已处理好的 headers + rows）
    result = client.write_data(
        db="ran_kpi_daily.sqlite3",
        table="FDD_OLIB_Network_KPIs",
        columns=headers,
        rows=data,
        mode="upsert",
        pk_columns=["Begin Time", "Group"],
    )

    # 方式2：上传 Excel 文件（适用于 dedup_insert 场景）
    result = client.upload_excel(
        db="db.sqlite3",
        table="4G_Main_Kpi_Cell_Daily",
        excel_path="path/to/file.xlsx",
        table_type="Cells",
    )
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import mimetypes
import uuid

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:db_writer_client>: exception swallowed", exc_info=True)
    pass

# ============================================================
# 配置
# ============================================================
DEFAULT_API_HOST = "192.168.100.19"
DEFAULT_API_PORT = 8765
DEFAULT_TIMEOUT = 900  # 秒（大数据写入可能较慢）
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # 指数退避基数


class DbWriterClient:
    """远程 SQLite 写入客户端。"""

    def __init__(self, host: str = None, port: int = None, timeout: int = DEFAULT_TIMEOUT):
        self.host = host or os.environ.get("DB_WRITER_HOST", DEFAULT_API_HOST)
        self.port = port or int(os.environ.get("DB_WRITER_PORT", str(DEFAULT_API_PORT)))
        self.timeout = timeout
        self.base_url = f"http://{self.host}:{self.port}"

    def _request(self, method: str, path: str, data: bytes = None,
                 content_type: str = "application/json",
                 max_retries: int = MAX_RETRIES) -> dict:
        """发送 HTTP 请求（带重试）。"""
        url = f"{self.base_url}{path}"
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(
                    url, data=data, method=method,
                    headers={"Content-Type": content_type}
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode('utf-8')
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _request: exception swallowed", exc_info=True)
                body = e.read().decode('utf-8', errors='replace')
                last_error = f"HTTP {e.code}: {body[:500]}"
                if e.code < 500:
                    break  # 4xx 不重试
            except Exception as e:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _request: exception swallowed", exc_info=True)
                last_error = str(e)

            if attempt < max_retries:
                wait = RETRY_BACKOFF ** attempt
                print(f"[DbWriter] 请求失败 ({last_error})，{wait}s 后重试 ({attempt}/{max_retries})...")
                time.sleep(wait)

        raise ConnectionError(f"[DbWriter] 请求失败: {url} -> {last_error}")

    def health(self) -> dict:
        """健康检查。"""
        return self._request("GET", "/health")

    def write_data(self, db: str, table: str, columns: list, rows: list,
                   mode: str = "upsert", pk_columns: list = None,
                   table_type: str = "Group") -> dict:
        """
        写入数据到远程数据库。

        参数：
            db: 数据库名称 ("db.sqlite3" / "ran_kpi_daily.sqlite3")
            table: 目标表名
            columns: 列名列表
            rows: 数据行列表（每行为 list）
            mode: "upsert"（INSERT OR REPLACE）或 "dedup_insert"（按主键去重插入）
            pk_columns: 主键列（upsert 模式必须）
            table_type: 表类型（Cells/Sites/Group/NW），用于自动检测主键

        返回：
            {"success": True, "rows_written": N, ...}
        """
        payload = {
            "db": db,
            "table": table,
            "columns": columns,
            "rows": rows,
            "mode": mode,
            "table_type": table_type,
        }
        if pk_columns:
            payload["pk_columns"] = pk_columns

        data = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
        print(f"[DbWriter] 写入 {db}/{table}: {len(rows)} 行, mode={mode}")

        result = self._request("POST", "/api/write", data=data)
        print(f"[DbWriter] 完成: {result.get('rows_written', 0)} 行已写入")
        return result

    def upload_excel(self, db: str, table: str, excel_path: str,
                     table_type: str = "Group",
                     add_group_column: bool = False,
                     group_value: str = "NW") -> dict:
        """
        上传 Excel 文件到远程服务器并导入数据库。

        参数：
            db: 数据库名称
            table: 目标表名
            excel_path: 本地 Excel 文件路径
            table_type: Cells/Sites/Group/NW
            add_group_column: 是否添加 Group 列
            group_value: Group 列的值

        返回：
            {"success": True, "rows_written": N, ...}
        """
        if not os.path.exists(excel_path):
            raise FileNotFoundError(f"Excel 文件不存在: {excel_path}")
        with open(excel_path, 'rb') as f:
            file_bytes = f.read()
        filename = os.path.basename(excel_path)
        return self.upload_excel_bytes(db, table, file_bytes, filename,
                                        table_type, add_group_column, group_value)

    def upload_excel_bytes(self, db: str, table: str, file_bytes: bytes,
                           filename: str = "export.xlsx",
                           table_type: str = "Group",
                           add_group_column: bool = False,
                           group_value: str = "NW") -> dict:
        """
        直接从内存字节上传 Excel 并导入数据库（不落盘）。
        """
        print(f"[DbWriter] 上传 {filename} ({len(file_bytes) / 1024:.1f} KB) -> {db}/{table}")

        boundary = f"----DbWriter{uuid.uuid4().hex}"
        body_parts = []

        content_type_file = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body_parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f'Content-Type: {content_type_file}\r\n\r\n'.encode('utf-8')
        )
        body_parts.append(file_bytes)
        body_parts.append(b'\r\n')

        form_fields = {
            "db": db,
            "table": table,
            "table_type": table_type,
            "add_group_column": str(add_group_column).lower(),
            "group_value": group_value,
        }
        for key, value in form_fields.items():
            body_parts.append(
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f'{value}\r\n'.encode('utf-8')
            )

        body_parts.append(f'--{boundary}--\r\n'.encode('utf-8'))
        body = b''.join(body_parts)

        result = self._request(
            "POST", "/api/upload_excel",
            data=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        print(f"[DbWriter] 完成: {result.get('rows_written', 0)} 行已写入")
        return result

    def list_tables(self, db: str) -> dict:
        """列出数据库中的所有表。"""
        return self._request("GET", f"/api/tables?db={db}")


# ============================================================
# 便捷函数（无需实例化）
# ============================================================
_default_client = None


def _get_client() -> DbWriterClient:
    global _default_client
    if _default_client is None:
        _default_client = DbWriterClient()
    return _default_client


def write_data(db: str, table: str, columns: list, rows: list,
               mode: str = "upsert", pk_columns: list = None,
               table_type: str = "Group") -> dict:
    """便捷函数：写入数据到远程数据库。"""
    return _get_client().write_data(db, table, columns, rows, mode, pk_columns, table_type)


def upload_excel(db: str, table: str, excel_path: str,
                 table_type: str = "Group",
                 add_group_column: bool = False,
                 group_value: str = "NW") -> dict:
    """便捷函数：上传 Excel 并导入远程数据库。"""
    return _get_client().upload_excel(db, table, excel_path, table_type, add_group_column, group_value)


def health() -> dict:
    """便捷函数：健康检查。"""
    return _get_client().health()


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    total_start = time.time()
    print(f"[TEST] DbWriterClient 连接测试")
    print(f"[TEST] 目标: {DEFAULT_API_HOST}:{DEFAULT_API_PORT}")

    client = DbWriterClient()

    try:
        result = client.health()
        print(f"[TEST] 健康检查: {result}")
    except Exception as e:
        print(f"[TEST] 连接失败: {e}")
        print(f"[TEST] 请确认远程服务已启动: python db_writer_api.py")

    elapsed = time.time() - total_start
    print(f"\n[TEST] 完成，耗时 {elapsed:.2f} 秒")
