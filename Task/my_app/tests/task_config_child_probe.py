# -*- coding: utf-8 -*-
"""子进程探针（由 test_task_config_live_effect.py 调用，不要单独跑）。

在全新解释器里导入服务模块：模块常量是在导入期被配置文件覆盖的，只有"新进程"才能
反映页面保存后服务真正会用的值。结果用 @@RESULT@@ 标记行输出，避免被服务自身的日志淹没。

环境变量 ZZ_IGNORE_CONFIG=1：把 load_json_config / ConfigResource.load 换成"文件不存在"，
于是 factory 输出即纯代码默认值 —— 用于对比磁盘配置与代码是否已经漂移。
"""
import importlib
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import task_config_files as tcf  # noqa: E402
import backend.services.task_configs_registry  # noqa: F401,E402

if os.environ.get("ZZ_IGNORE_CONFIG") == "1":
    # 各服务都是在导入期 `from ...task_config_files import load_json_config`，
    # 此刻替换掉即等价于"磁盘上没有配置文件"，拿到的就是纯代码默认。
    import copy as _copy

    tcf.load_json_config = lambda *a, **k: None
    tcf.ConfigResource.load = lambda self: (
        self.defaults_factory() if self.defaults_factory else _copy.deepcopy(self.defaults))


def main():
    tid = sys.argv[1]
    probes = []
    if len(sys.argv) > 2:
        try:
            with open(sys.argv[2], "r", encoding="utf-8") as f:
                probes = json.load(f).get("probes", [])
        except Exception as e:
            print(f"[probe] 读取探针规格失败: {e}")
    r = tcf.get_resource(tid)
    if r is None:
        raise SystemExit(f"未注册的任务: {tid}")
    out = {"task_id": tid, "factory": r.defaults_factory() if r.defaults_factory else None,
           "probes": {}}
    for p in probes:
        try:
            m = importlib.import_module(p["module"])
            out["probes"][p["name"]] = str(getattr(m, p["const"], "<缺失>"))
        except Exception as e:
            out["probes"][p["name"]] = f"<导入失败: {e}>"
    print("@@RESULT@@" + json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
