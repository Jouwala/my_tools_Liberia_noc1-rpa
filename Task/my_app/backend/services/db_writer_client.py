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
import logging
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
from backend.config.remote_host import get_api_host  # 远程主机统一来源（FTP/API/SMB 共用）

DEFAULT_API_PORT = 8765  # 端口可经 DB_WRITER_PORT 覆盖
DEFAULT_TIMEOUT = 900  # 秒（大数据写入可能较慢）
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # 指数退避基数

# 2026-11-07 A：区分「连接建立阶段失败」与「请求已发出但没拿到响应」。
#   - connect() 阶段（[WinError 10061] 主动拒绝 / 10065 无路由 / 10051 网络不可达）：
#     服务端根本没收到请求，upsert 幂等，重试不会写错数据。
#   - getresponse() 阶段的 [WinError 10054]、读超时 "timed out"、HTTP 500：
#     服务端可能已经提交（2026-11-07 06:46 的 10054 堆栈就停在
#     http.client.getresponse()），沿用 8d5d5786「upsert 不盲重试」的约束，
#     交给 auto_retry 重投，不在本层重试。
_CONNECT_STAGE_ERR_MARKERS = (
    "10061", "10065", "10051", "10064",
    "ConnectionRefusedError", "actively refused",
    "目标计算机积极拒绝",
)
CONNECT_STAGE_ONLY = "connect_stage_only"


def _is_connect_stage_error(exc: BaseException) -> bool:
    """仅当失败发生在 TCP 连接建立阶段（服务端未收到请求）时返回 True。"""
    text = str(exc)
    return (isinstance(exc, ConnectionRefusedError)
            or any(marker in text for marker in _CONNECT_STAGE_ERR_MARKERS))


class DbWriterClient:
    """远程 SQLite 写入客户端。"""

    def __init__(self, host: str = None, port: int = None, timeout: int = DEFAULT_TIMEOUT):
        self.host = host or get_api_host()
        self.port = port or int(os.environ.get("DB_WRITER_PORT", str(DEFAULT_API_PORT)))
        self.timeout = timeout
        self.base_url = f"http://{self.host}:{self.port}"

    def _request(self, method: str, path: str, data: bytes = None,
                 content_type: str = "application/json",
                 max_retries: int = MAX_RETRIES,
                 retry_policy: str = None) -> dict:
        """发送 HTTP 请求（带重试）。

        ``retry_policy=CONNECT_STAGE_ONLY`` 时只对连接建立阶段的失败重试；
        请求已发出但未拿到响应的错误（10054 / timed out / 5xx）立即上抛，
        避免在 upsert 场景下重复排队执行同一批写入（见 8d5d5786）。
        默认 ``None`` 保持原有行为，其它调用方不受影响。
        """
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
                # 4xx 一律不重试；connect_stage_only 策略下连 5xx 也不重试
                # （服务端已经响应，说明请求已送达，可能已提交）。
                if e.code < 500 or retry_policy == CONNECT_STAGE_ONLY:
                    break
            except Exception as e:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _request: exception swallowed", exc_info=True)
                last_error = str(e)
                if (retry_policy == CONNECT_STAGE_ONLY
                        and not _is_connect_stage_error(e)):
                    break

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
                   table_type: str = "Group",
                   connect_stage_retries: int = 0) -> dict:
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
            connect_stage_retries: 0（默认）= 保持 8d5d5786 的行为；>0 时
                仅对连接建立阶段的失败重试这么多次，其它错误立即上抛。
                由调用方显式开启，不影响其它 upsert 调用方。

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

        # upsert 超时时服务端可能已提交；盲重试只会再次排队执行同一批写入。
        # （8d5d5786，2026-11-06：默认对 upsert 不重试。）
        if connect_stage_retries > 0:
            # 2026-11-07 A：调用方显式开启时，只对「服务端未收到请求」的
            # 连接建立阶段失败重试；10054 / timed out / 5xx 仍立即上抛。
            result = self._request(
                "POST", "/api/write", data=data,
                max_retries=connect_stage_retries,
                retry_policy=CONNECT_STAGE_ONLY,
            )
        else:
            result = self._request(
                "POST", "/api/write", data=data,
                max_retries=1 if mode == "upsert" else MAX_RETRIES,
            )
        print(f"[DbWriter] 完成: {result.get('rows_written', 0)} 行已写入")
        return result

    def get_latest_value(self, db: str, table: str, column: str):
        """读取远端表某列的最大值；表不存在或读取失败时上抛，由调用方全量兜底。

        ``columns`` 必须传**裸列名**：线上服务的 /api/read 会自己给列名加引号，
        传 ``"Begin Time"`` 会变成 ``""Begin Time""`` 触发 SQL 语法错误
        （同坑已在 db_freshness_check.py 的 ``_api_window_max`` 记录过）。
        ``order_by`` 走原样拼接，与 where 同一套约定，所以要自己加引号。
        """
        payload = {
            "db": db,
            "table": table,
            "columns": [column],
            "order_by": f'"{column.replace(chr(34), chr(34) + chr(34))}" DESC',
            "limit": 1,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        result = self._request("POST", "/api/read", data=data, max_retries=1)
        rows = result.get("rows") or []
        return rows[0][0] if rows and rows[0] else None

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
    print(f"[TEST] 目标: {get_api_host()}:{DEFAULT_API_PORT}")

    client = DbWriterClient()

    try:
        result = client.health()
        print(f"[TEST] 健康检查: {result}")
    except Exception as e:
        print(f"[TEST] 连接失败: {e}")
        print(f"[TEST] 请确认远程服务已启动: python db_writer_api.py")

    elapsed = time.time() - total_start
    print(f"\n[TEST] 完成，耗时 {elapsed:.2f} 秒")
