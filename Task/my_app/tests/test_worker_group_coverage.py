"""worker 分组配置守卫：任务↔分组↔启动脚本组集合↔前端帮助必须一致。

为什么单独成文件、且不用 pytest 断言框架：
    本机 venv 没装 pytest（2026-09-18 实测 `No module named pytest`），
    跑不起来的守卫等于没有。本文件用纯 assert + __main__ 计数器，
    `python tests/test_worker_group_coverage.py` 与 `pytest` 两种方式都能跑。

必须用 PATH 上的 python（系统 Python 3.12）跑，不要用工作区的
`Scripts/python.exe` 与 `.venv/Scripts/python.exe`：两个虚拟环境都没装 apscheduler（2026-09-18 实测），
而本文件要 import worker_watchdog → apscheduler，缺它会让守卫「假失败」——
现象是 cron 解析报 ModuleNotFoundError，看起来像分组有问题，其实只是解释器选错。

五项一致性检查（都对应真实事故）：
    1. TASK_SPECS 的每个 task_id 都要在 GROUP_TASK_MAP 里
       —— 漏登记 → 分组模式下无 worker 认领 → 队列 pending 永久滞留，
          且陈旧 pending 占住单飞名额把后续每次调度全挡掉（已四次踩坑）。
    2. GROUP_TASK_MAP 的组键集合 == start_hidden.ps1 的 MY_APP_WORKER_GROUPS
       == restart_workers.py 的 ALL_GROUPS
       —— 2026-09-18 把 3 个 VMAX 任务从 n 组拆成独立 v 组时新增：只改分组表
          而启动脚本没启用该组，现象与「漏登记分组」完全一样（该组任务永不认领）；
          反向漏改（启用了没有清单的组）更危险，该 worker 会全量认领所有任务。
    3. 同一任务不得出现在多个组（认领者不确定，串行约束失效）。
    4. 共用本机 8790 VMAX 会话的任务必须同组（VMAX 门户会话数有限）。
    5. 前端帮助任务清单（frontend/src/pages/helpTaskDocs.ts 的 TASK_DOCS）必须与
       GROUP_TASK_MAP 一一对应且组名相同
       —— 2026-09-18 拆组时发现：帮助页写了「共 4 组 worker」而实际早已 5 组，
          13 个任务上线后从没有写进任务帮助（用户在看板上看不出哪个任务属于哪组、
          走哪条链路）。文档与代码同源，但没人手工同步，只能上守卫。

运行（注意上面的解释器要求）：
    cd D:/01_RPA/Task/my_app
    python tests/test_worker_group_coverage.py
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _group_task_map():
    from backend.worker_watchdog import GROUP_TASK_MAP
    return GROUP_TASK_MAP


def _task_specs():
    from backend.task_registry import TASK_SPECS
    return [s["task_id"] for s in TASK_SPECS]


def _flat_groups(gtm):
    """组名 -> [task_id]（去空白、保序）。"""
    return {g: [t.strip() for t in (tasks or "").split(",") if t.strip()]
            for g, tasks in gtm.items()}


def _ps1_worker_groups() -> set:
    """解析 start_hidden.ps1 里 $env:MY_APP_WORKER_GROUPS 的字面值。"""
    text = (ROOT / "start_hidden.ps1").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\$env:MY_APP_WORKER_GROUPS\s*=\s*'([^']*)'", text)
    assert m, "start_hidden.ps1 里找不到 $env:MY_APP_WORKER_GROUPS 赋值（脚本结构变了？）"
    return {g.strip() for g in m.group(1).split(",") if g.strip()}


def _restart_workers_all_groups() -> set:
    """取 restart_workers.py 的 ALL_GROUPS（其本身已从 GROUP_TASK_MAP 派生）。"""
    spec = importlib.util.spec_from_file_location("_rw_guard", ROOT / "restart_workers.py")
    assert spec and spec.loader, "无法加载 restart_workers.py"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod.ALL_GROUPS)


def _start_bat_groups() -> set:
    """解析 start.bat 里 `if exist ...worker_<g>.pid` 健康检查覆盖的组集合。

    2026-09-27 拆 n→n/s/w 时新增本守卫。当时该文件里写死 5 个 `if exist` 与
    `WCOUNT / 5`，拆组后 s、w 两组即使死掉也仍然报「7 / 7」式的全绿
    （实际是 5/5 全绿）—— 与它自己 :63 注释记录的「v 曾被漏掉，死组仍报全绿」
    是同一个坑的第二次。这里把它纳入自动校验，防止第三次。
    """
    text = (ROOT / "start.bat").read_text(encoding="utf-8", errors="replace")
    # worker_watchdog.pid 是看门狗自身，不是组；组名限定为单字母键
    found = set(re.findall(r"worker_([A-Za-z0-9_]+)\.pid", text))
    found.discard("watchdog")
    return found


def test_all_registered_tasks_have_worker_group():
    """每个注册任务都必须登记进 GROUP_TASK_MAP（否则队列 pending 永久滞留）。

    2026-09-18 第四次踩坑（前三次 finebi_report_sync / whatsapp_send_ext /
    sp_email_details）：olib_soc_kpi_daily_sync、olib_soc_vmax_report、
    vmax_multi_data_sync 上线时只写了 TASK_SPECS，分组模式下没有 worker 认领
    → 队列 pending 无人认领、陈旧 pending 又占住单飞名额把后续调度全挡掉，
    三个任务上线后一次也没执行过（task_execution_log 0 条），且不报任何错。
    本测试把「漏分组」从静默停摆变成跑测试就失败。
    """
    gtm = _group_task_map()
    grouped = {}
    for g, tasks in _flat_groups(gtm).items():
        for t in tasks:
            grouped.setdefault(t, []).append(g)

    specs = _task_specs()
    missing = sorted(set(specs) - set(grouped))
    assert not missing, f"未登记 worker 分组的任务（入队后无人认领、pending 卡死）: {missing}"
    ghost = sorted(set(grouped) - set(specs))
    assert not ghost, f"GROUP_TASK_MAP 里有 TASK_SPECS 之外的 task_id（拼写错/已下线）: {ghost}"


def test_no_task_in_multiple_groups():
    """同一任务只能属于一个组：多组认领者不确定，且组内串行假设会失效。"""
    grouped = {}
    for g, tasks in _flat_groups(_group_task_map()).items():
        for t in tasks:
            grouped.setdefault(t, []).append(g)
    dupes = {k: v for k, v in grouped.items() if len(v) > 1}
    assert not dupes, f"同一任务登记进多个组（认领者不确定）: {dupes}"


def test_group_sets_in_sync_with_launchers():
    """组键集合三处一致：GROUP_TASK_MAP == start_hidden.ps1 == restart_workers.py。

    拆 v 组（2026-09-18）时新增。漏改启动脚本 → 新组从不被拉起，该组任务全部
    pending 卡死（与漏登记分组同一现象）；反向漏改 → 该组 worker 无白名单、
    会全量认领所有任务，破坏数据源串行约束。
    """
    gtm_keys = set(_group_task_map())
    assert gtm_keys, "GROUP_TASK_MAP 为空？"
    ps1 = _ps1_worker_groups()
    assert gtm_keys == ps1, (
        f"worker 组集合不一致：GROUP_TASK_MAP={sorted(gtm_keys)} 但 "
        f"start_hidden.ps1 MY_APP_WORKER_GROUPS={sorted(ps1)}；"
        f"只加分组表不加启动脚本 → 该组 worker 从不拉起，任务永远 pending"
    )
    rw = _restart_workers_all_groups()
    assert gtm_keys == rw, (
        f"worker 组集合不一致：GROUP_TASK_MAP={sorted(gtm_keys)} 但 "
        f"restart_workers.py ALL_GROUPS={sorted(rw)}"
    )
    bat = _start_bat_groups()
    assert gtm_keys == bat, (
        f"worker 组集合不一致：GROUP_TASK_MAP={sorted(gtm_keys)} 但 "
        f"start.bat 健康检查覆盖={sorted(bat)}；"
        f"缺的组即使 worker 死掉也仍报全绿（start.bat 里 v 曾漏过一次）"
    )


def test_vmax_8790_tasks_are_one_group():
    """共用本机 8790 VMAX 单会话代理的任务必须同组（VMAX 门户会话数有限）。

    2026-09-18 拆组时把这 3 个任务从 n 组挪进独立的 v 组：它们彼此必须串行，
    但与 eFlow/网管任务无需串行；本测试锁住「三个 VMAX 任务同组」这一约束，
    防止后续有人把它们拆散到不同组（会互相挤 VMAX 会话）。
    """
    gtm = _group_task_map()
    flat = _flat_groups(gtm)
    vmax_tasks = ("cxo_dashboard_cache_sync", "vmax_cxo_daily_sync", "vmax_multi_data_sync")
    owner = {}
    for g, tasks in flat.items():
        for t in vmax_tasks:
            if t in tasks:
                owner.setdefault(g, []).append(t)
    assert len(owner) == 1, f"VMAX 8790 任务被拆散到多个组（必须同组串行）: {owner}"
    got = sorted(next(iter(owner.values())))
    assert got == sorted(vmax_tasks), f"VMAX 8790 任务缺少同组成员: 缺 {sorted(set(vmax_tasks) - set(got))}"


def _help_task_docs() -> dict:
    """解析前端帮助任务清单 TASK_DOCS：task_id -> 组名（页面展示的“哪个任务在哪组”就来自这里）。"""
    p = ROOT / "frontend" / "src" / "pages" / "helpTaskDocs.ts"
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    pairs = re.findall(r"id:\s*'([A-Za-z0-9_]+)',\s*group:\s*'([a-z])'", text)
    return {i: g for i, g in pairs}


def test_help_task_docs_match_groups():
    """前端任务帮助必须与 GROUP_TASK_MAP 一一对应，且组名一致。

    2026-09-18 拆 v 组时新增：当时 helpTaskDocs.ts 只写了 47/60 个任务，且顶部
    文字还写着「worker × 4 组」—— 分组改了、给用户看的帮助没改，等于把事故
    排查手册留在旧版本。本测试只锁“覆盖 + 组名”这两件可机检的事。
    新增任务时直接在 TASK_DOCS 补一条（含 zh/en 文案），不要靠改注释绕过。
    """
    docs = _help_task_docs()
    if not docs:
        # 前端目录不存在（例如只检出 backend）时降级跳过，不把守卫变成误报
        return
    owner = {}
    for g, tasks in _flat_groups(_group_task_map()).items():
        for t in tasks:
            owner[t] = g
    missing = sorted(set(owner) - set(docs))
    ghost = sorted(set(docs) - set(owner))
    wrong = sorted((t, docs[t], owner[t]) for t in set(docs) & set(owner) if docs[t] != owner[t])
    assert not missing, f"任务帮助（helpTaskDocs.ts）缺少这些已归组的任务: {missing}"
    assert not ghost, f"任务帮助里有 GROUP_TASK_MAP 之外的 task_id（已下线/拼错）: {ghost}"
    assert not wrong, f"任务帮助里的组名与 GROUP_TASK_MAP 不一致 (task, 帮助, 实际): {wrong}"


CHECKS = [
    test_all_registered_tasks_have_worker_group,
    test_no_task_in_multiple_groups,
    test_group_sets_in_sync_with_launchers,
    test_vmax_8790_tasks_are_one_group,
    test_help_task_docs_match_groups,
]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _gtm = _group_task_map()
    _flat = _flat_groups(_gtm)
    _n_tasks = len(_task_specs())
    print(f"[INFO] 分组：{ {g: len(t) for g, t in _flat.items()} }，共 {_n_tasks} 个任务已归组")
    passed = failed = 0
    for fn in CHECKS:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
        else:
            passed += 1
            print(f"[PASS] {fn.__name__}")
    print(f"\nPASS={passed} FAIL={failed}")
    sys.exit(1 if failed else 0)
