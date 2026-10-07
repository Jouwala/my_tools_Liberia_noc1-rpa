# -*- coding: utf-8 -*-
"""生产 PG 只读自检：核对 eflow_tt_whatsapp_alert_log 的实际列结构。

不依赖 psycopg2 / sqlalchemy / pip —— 用 Python 标准库直接讲 PostgreSQL 线协议
（socket + MD5 认证 + 简单查询）。任何装了 Python 3.7+ 的机器都能直接跑。

用法（在**能连到 192.168.100.20 的机器**上，例如你本机）：
    python backend/migrations/check_pg_alert_log.py
    python backend/migrations/check_pg_alert_log.py --host 192.168.100.20 --user myapp

只读：只发 SELECT / 系统目录查询，绝不写任何数据、绝不改表结构。

它回答的唯一问题：**PG 里那张表，到底缺不缺 last_error（以及其它列）？**
—— 这是整个诊断里唯一还没被直接证实的一环。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import socket
import struct
import sys

DEFAULT_HOST = "192.168.100.20"
DEFAULT_PORT = 5432
DEFAULT_USER = "myapp"
DEFAULT_PASSWORD = "Jlt-hjPBXkkX9g0Rfa8QZbKP"
DEFAULT_DB = "myapp"
SCHEMA = "app"
TABLE = "eflow_tt_whatsapp_alert_log"

# 代码期望的完整列（与 backend/services/tt_alarm_store.py 的 LOG_COLUMNS 对齐）。
# 若脚本报「缺列」中有 last_error，即证实诊断。
EXPECTED_COLUMNS = [
    "tt_no", "alarm_occur_time", "ticket_severity", "alarm_code",
    "site_id", "site_name", "title",
    "send_status", "send_count", "last_send_time", "last_tt_modified",
    "first_seen_time", "last_error", "updated_time",
    "last_alarm_seen_time", "last_known_update_time", "last_check_time",
    "mail_notified_time", "mail_summary_time",
]


# ----------------------------------------------------------------------
# 极简 PostgreSQL 线协议客户端（只够跑一次简单查询）
# ----------------------------------------------------------------------
class PgWire:
    def __init__(self, host, port, user, password, dbname, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.user, self.password, self.dbname = user, password, dbname
        self.params = {}   # 服务端在 AuthenticationOk 前下发的运行参数
        # SCRAM-SHA-256 会话状态
        self._scram_initial = b""
        self._scram_nonce = ""
        self._scram_server_sig = b""

    # --- 低层收发 ---
    def _send(self, msg_type: bytes, payload: bytes):
        self.sock.sendall(msg_type + struct.pack("!I", len(payload) + 4) + payload)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("PG 连接在读取中关闭")
            buf += chunk
        return buf

    def _read_msg(self):
        t = self._recv_exact(1)
        length = struct.unpack("!I", self._recv_exact(4))[0]
        payload = self._recv_exact(length - 4) if length > 4 else b""
        return t, payload

    @staticmethod
    def _cstr(s: bytes):
        return s.split(b"\x00")[0]

    # --- 握手 ---
    def connect(self):
        proto = struct.pack("!I", 196608)                 # 3.0
        params = (b"user\x00" + self.user.encode() + b"\x00"
                  + b"database\x00" + self.dbname.encode() + b"\x00"
                  + b"client_encoding\x00UTF8\x00\x00")
        self._send(b"", proto + params)                   # StartupMessage 无类型字节

        while True:
            t, payload = self._read_msg()
            if t == b"R":                                 # Authentication
                code = struct.unpack("!I", payload[:4])[0]
                if code == 0:
                    continue
                if code == 5:                             # MD5 口令
                    salt = payload[4:8]
                    inner = hashlib.md5((self.password + self.user).encode()).hexdigest()
                    outer = hashlib.md5(inner.encode() + salt).hexdigest()
                    self._send(b"p", b"md5" + outer.encode() + b"\x00")
                elif code == 3:                           # 明文口令
                    self._send(b"p", self.password.encode() + b"\x00")
                elif code == 10:                          # SASL（PG16 默认 SCRAM-SHA-256）
                    self._auth_scram(payload[4:])
                elif code == 11:                          # SASLContinue
                    self._scram_continue(payload[4:])
                elif code == 12:                          # SASLFinal（服务端校验签名）
                    sv = payload[4:]
                    if self._scram_server_sig and sv != self._scram_server_sig:
                        raise RuntimeError("SCRAM 服务端签名校验失败（口令或中间人？）")
                    continue
                else:
                    raise RuntimeError(f"不支持的 PG 认证方式 code={code}")
            elif t == b"S":                               # ParameterStatus
                k, _, rest = payload.partition(b"\x00")
                v = self._cstr(rest)
                self.params[k.decode()] = v.decode("utf-8", "replace")
            elif t == b"K":                               # BackendKeyData
                continue
            elif t == b"Z":                               # ReadyForQuery
                return
            elif t == b"E":                               # ErrorResponse
                raise RuntimeError("PG 认证/连接错误: " + self._parse_error(payload))

    @staticmethod
    def _parse_error(payload: bytes) -> str:
        parts, i = [], 0
        while i < len(payload):
            code = payload[i:i + 1]
            if code == b"\x00":
                break
            end = payload.index(b"\x00", i + 1)
            val = payload[i + 1:end].decode("utf-8", "replace")
            if code in (b"S", b"M", b"C", b"D"):
                parts.append(val)
            i = end + 1
        return " | ".join(parts)

    # --- SCRAM-SHA-256（PG16 默认认证；纯标准库实现）---
    def _auth_scram(self, mechs_payload: bytes):
        """处理 AuthenticationSASL(code=10)：选 SCRAM-SHA-256，发 client-first。"""
        # payload[4:] 是若干以 \0 结尾的机制名，最后再一个 \0
        mechs = [m for m in mechs_payload.split(b"\x00") if m]
        if b"SCRAM-SHA-256" not in mechs:
            raise RuntimeError(f"服务端未提供 SCRAM-SHA-256，仅: {mechs}")
        # 用户名需按 SASLprep 处理；此处实践中直接透传（ASCII 用户名足够）
        self._scram_nonce = base64.b64encode(os.urandom(18)).decode()
        client_first_bare = f"n={self.user},r={self._scram_nonce}"
        self._scram_initial = client_first_bare.encode()
        client_first = b"n,," + self._scram_initial
        # SASLInitialResponse:机制名\0 + int32 长度 + 数据
        body = b"SCRAM-SHA-256\x00" + struct.pack("!I", len(client_first)) + client_first
        self._send(b"p", body)

    def _scram_continue(self, sasl_data: bytes):
        """处理 AuthenticationSASLContinue(code=11)：算 client-final 并发送。"""
        server_first = sasl_data.decode("utf-8", "replace")
        attrs = dict(kv.split("=", 1) for kv in server_first.split(",") if "=" in kv)
        rnonce = attrs["r"]
        salt = base64.b64decode(attrs["s"])
        iterations = int(attrs["i"])

        if not rnonce.startswith(self._scram_nonce):
            raise RuntimeError("SCRAM: 服务端 nonce 前缀不匹配")
        channel = b"biws"                                # base64("n,,")

        # SaltedPassword = Hi(Normalize(password), salt, i)
        salted = hashlib.pbkdf2_hmac(
            "sha256", self.password.encode("utf-8"), salt, iterations)
        client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
        stored_key = hashlib.sha256(client_key).digest()
        auth_message = ",".join([
            self._scram_initial.decode(),
            server_first,
            "c=" + channel.decode() + ",r=" + rnonce,
        ]).encode()
        client_sig = hmac.new(stored_key, auth_message, hashlib.sha256).digest()
        proof = bytes(a ^ b for a, b in zip(client_key, client_sig))

        server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
        self._scram_server_sig = hmac.new(
            server_key, auth_message, hashlib.sha256).digest()

        client_final = f"c={channel.decode()},r={rnonce},p={base64.b64encode(proof).decode()}"
        self._send(b"p", client_final.encode("utf-8"))

    # --- 简单查询（只读）---
    def query(self, sql: str):
        self._send(b"Q", sql.encode("utf-8") + b"\x00")
        rows, cols = [], []
        err = None
        while True:
            t, payload = self._read_msg()
            if t == b"T":                                 # RowDescription
                n = struct.unpack("!H", payload[:2])[0]
                idx, cols = 0, []
                for _ in range(n):
                    end = payload.index(b"\x00", idx)
                    cols.append(payload[idx:end].decode("utf-8", "replace"))
                    idx = end + 1 + 18                    # 跳过定长字段
                n = n  # noqa
            elif t == b"D":                               # DataRow
                n = struct.unpack("!H", payload[:2])[0]
                idx, vals = 2, []
                for _ in range(n):
                    ln = struct.unpack("!i", payload[idx:idx + 4])[0]
                    idx += 4
                    if ln == -1:
                        vals.append(None)
                    else:
                        vals.append(payload[idx:idx + ln].decode("utf-8", "replace"))
                        idx += ln
                rows.append(vals)
            elif t == b"E":
                err = self._parse_error(payload)
            elif t == b"Z":
                if err:
                    raise RuntimeError("查询错误: " + err)
                return cols, rows

    def close(self):
        try:
            self._send(b"X", b"")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="只读核对 PG 中 eflow_tt_whatsapp_alert_log 列结构")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--password", default=DEFAULT_PASSWORD)
    ap.add_argument("--dbname", default=DEFAULT_DB)
    ap.add_argument("--schema", default=SCHEMA)
    ap.add_argument("--table", default=TABLE)
    args = ap.parse_args(argv)

    print(f"== 连接 {args.user}@{args.host}:{args.port}/{args.dbname} ...")
    pg = PgWire(args.host, args.port, args.user, args.password, args.dbname)
    try:
        pg.connect()
        print(f"== 已连接（server_version={pg.params.get('server_version', '?')}）")

        # 1) 表是否存在（在任意 schema）
        cols, rows = pg.query(
            "SELECT table_schema FROM information_schema.tables "
            f"WHERE table_name = '{args.table}'")
        schemas = sorted({r[0] for r in rows})
        print(f"== 表 {args.table} 所在 schema: {schemas or '【不存在】'}")

        # 2) 逐 schema 打印实际列
        actual = {}
        for s in schemas:
            cols, rows = pg.query(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = '{s}' AND table_name = '{args.table}' "
                "ORDER BY ordinal_position")
            names = [r[0] for r in rows]
            actual[s] = names
            print(f"\n--- schema `{s}`：共 {len(names)} 列 ---")
            print("   " + ", ".join(names))

        # 3) 与代码期望对齐（重点看 app schema）
        target = actual.get(args.schema)
        if target is None:
            print(f"\n!! schema `{args.schema}` 下没有该表 —— "
                  f"运行期 ensure_log_table 会按当前代码建全列")
            return 0
        missing = [c for c in EXPECTED_COLUMNS if c not in target]
        extra = [c for c in target if c not in EXPECTED_COLUMNS]

        print(f"\n===== 结论（schema `{args.schema}`）=====")
        print(f"期望列数: {len(EXPECTED_COLUMNS)} | 实际列数: {len(target)}")
        if missing:
            print(f"!! 缺列（{len(missing)} 个）: {missing}")
            if "last_error" in missing:
                print("   >> 证实诊断：PG 老表缺 last_error，"
                      "正是 UndefinedColumn 报错的根因。")
                print("   >> 修复：运行 fix_tt_alert_log_columns.py 补齐（或重启 worker 让新代码自动补）。")
            else:
                print("   >> 注意：缺的不是 last_error —— 需重新判断报错根因。")
        else:
            print("OK 无缺列 —— 表结构已与代码一致。")
            print("   （若报错仍在，则 UndefinedColumn 另有原因，需换方向排查。）")
        if extra:
            print(f"== 多出的列（无害）: {extra}")
        return 0 if not missing else 2
    except Exception as e:  # noqa: BLE001
        print(f"\n!! 无法连接或查询失败: {type(e).__name__}: {e}")
        print("   排查：本机是否与 192.168.100.20 同网段？PG 是否监听 5432？"
              "用户名/口令是否正确？")
        return 1
    finally:
        pg.close()


if __name__ == "__main__":
    sys.exit(main())
