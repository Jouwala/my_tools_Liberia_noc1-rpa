# -*- coding: utf-8 -*-
"""凭据「测试连接」的地址来源守卫（2026-10-22）。

问题：`credential_store.CREDENTIAL_GROUPS` 里的 `test_host` / `test_port` 是
**硬编码**，而任务实际连接的地址来自页面可编辑的 `backend/services/<task>_config.json`。
两份值各维护一次 → 改了配置后点「测试连接」仍在测旧地址，结论不可信；更隐蔽的是
消息里报的主机跟真正连上的主机不是同一台（例如 `ume_keystone` 实际连
`ume_alarm_client.HOST`、`umc_portal` 实际连 `fw_kpi_services.HOST`，而消息里打印的是
组内的死值）。同一个死值还被「改凭据后清会话缓存」和「熔断状态查询」引用。

本文件锁四件事：
  1. 有配置文件的组，`resolve_endpoint()` 必须返回**文件里的值**（不是硬编码值）；
  2. 文件缺失（页面没保存过）→ 回退内置默认，来源标 `static`；
  3. 环境变量优先于配置文件（与各客户端自己读的 env 同名）；
  4. `run_test()` 必须把解析结果覆盖到 group **副本**上（不许改全局注册表）。

全部用例都把 `_SERVICES_DIR` 指向 tmp 目录，不读也不写真配置，零副作用。
"""
import json

import pytest

from backend.services import credential_store as CS
from backend.services import credential_tester as CT


@pytest.fixture()
def isolated_services(tmp_path, monkeypatch):
    """把配置目录指到 tmp（resolve_endpoint 只认这个变量），隔离真实文件。"""
    monkeypatch.setattr(CS, "_SERVICES_DIR", tmp_path)
    return tmp_path


def _write(dirpath, name, payload):
    (dirpath / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ============================================================
# 1) 配置文件赢过硬编码
# ============================================================
def test_config_file_wins_over_hardcoded(isolated_services):
    _write(isolated_services, "ran_ume_config.json", {"host": "10.9.9.9", "port": 1234})
    ep = CS.resolve_endpoint("zte_ume")
    assert (ep["host"], ep["port"]) == ("10.9.9.9", 1234)
    assert ep["source"] == "file:ran_ume_config.json"
    # 内置默认仍要能查出来（页面排障对照用）
    assert ep["default"] == "10.100.28.27:28001"


# ============================================================
# 2) 文件还没生成 → 回退内置默认
# ============================================================
def test_missing_file_falls_back_to_static(isolated_services):
    group = CS._GROUP_INDEX["cm_data"]
    ep = CS.resolve_endpoint("cm_data")           # cm_data_config.json 未生成
    assert ep["source"] == "static"
    assert (ep["host"], ep["port"]) == (group["test_host"], group["test_port"])


# ============================================================
# 3) 环境变量优先（ume_alarm 走 UME_ALARM_HOST，与客户端同名）
# ============================================================
def test_env_wins_over_config(isolated_services, monkeypatch):
    monkeypatch.setenv("UME_ALARM_HOST", "1.2.3.4")
    monkeypatch.setenv("UME_ALARM_PORT", "8443")
    ep = CS.resolve_endpoint("ume_alarm")
    assert (ep["host"], ep["port"]) == ("1.2.3.4", 8443)
    assert ep["source"] == "env:UME_ALARM_HOST"


# ============================================================
# 4) 同设备多任务配置的交叉核对（只改一个文件要能报出来）
# ============================================================
def test_peer_conflict_is_reported(isolated_services):
    _write(isolated_services, "ran_ume_config.json", {"host": "10.9.9.9", "port": 28001})
    _write(isolated_services, "main_kpi_config.json", {"host": "10.9.9.9", "port": 28001})
    _write(isolated_services, "network_kpi_config.json", {"host": "10.8.8.8", "port": 28001})
    ep = CS.resolve_endpoint("zte_ume")
    assert ep["host"] == "10.9.9.9"                        # 以主文件为准
    files = {c["file"] for c in ep["conflicts"]}
    assert files == {"network_kpi_config.json"}            # 只报不一致的那个


# ============================================================
# 5) 未登记配置的组不受配置目录影响（地址不在任务 json 里）
# ============================================================
def test_group_without_config_ref_ignores_files(isolated_services):
    _write(isolated_services, "battery_config.json", {"host": "9.9.9.9", "port": 1})
    ep = CS.resolve_endpoint("battery_ume")
    assert ep["source"] == "static"
    assert ep["host"] == CS._GROUP_INDEX["battery_ume"]["test_host"]


# ============================================================
# 6) 凭据列表展示的 test_target 必须与解析结果同源
# ============================================================
def test_list_credentials_target_matches_resolver(isolated_services):
    _write(isolated_services, "ipran_kpi_config.json", {"host": "10.7.7.7", "port": 28002})
    rows = {r["key"]: r for r in CS.list_credentials("zh")}
    assert rows["ipran_ume"]["test_target"] == "10.7.7.7:28002"
    assert rows["ipran_ume"]["test_target_source"] == "file:ipran_kpi_config.json"


# ============================================================
# 7) run_test 把解析结果覆盖到 group 副本（且不污染全局注册表）
# ============================================================
def test_run_test_uses_resolved_endpoint(isolated_services, monkeypatch):
    _write(isolated_services, "ran_ume_config.json", {"host": "10.6.6.6", "port": 28003})
    seen = {}

    def _fake(group, user, pwd, en):
        seen["host"] = group.get("test_host")
        seen["port"] = group.get("test_port")
        return True, "fake ok"

    # zte_ume 的 test_kind 是 zte_oauth2（真实链路在 router 里），这里只验分发层的覆盖
    monkeypatch.setitem(CT.TESTERS, "zte_oauth2", _fake)
    group = CS._GROUP_INDEX["zte_ume"]
    before = (group["test_host"], group["test_port"])

    res = CT.run_test("zte_ume", group, "u", "p", False)

    assert res["status"] == "ok"
    assert seen == {"host": "10.6.6.6", "port": 28003}
    assert res["endpoint"]["source"] == "file:ran_ume_config.json"
    # 关键：全局注册表里的死值不许被测试过程改写
    assert (group["test_host"], group["test_port"]) == before
