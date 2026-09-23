# -*- coding: utf-8 -*-
"""任务配置卡片守卫：页面上改的值，服务是不是真的用得上。

为什么单独成文件、且不用 pytest 断言框架（与 test_worker_group_coverage.py 同一个理由）：
    本机 venv 没装 pytest，跑不起来的守卫等于没有。本文件用纯计数 + __main__，
    `python tests/test_task_config_live_effect.py` 与 pytest 都能跑。

必须用 PATH 上的 python（系统 Python 3.12，即后端/worker 实际用的那个）跑：
    `Scripts/python.exe` 的 site-packages 没进 sys.path，缺 pandas/sqlalchemy →
    defaults_factory 静默 ImportError → 36 张卡全部"读不到"，那是假失败。

背景：Settings →「任务配置」的 36 张卡片由 `backend/services/task_configs_registry.py`
注册，每张卡的 schema 同时驱动页面渲染与后端校验，defaults_factory 从服务模块常量取
默认值。这个链路有四类只有真跑一遍才会暴露的问题，本文件逐类设防：

    A 保存链路  —— 走真实写入口 task_config_files.update_config()：曾因一个字段类型不符
      （groupchoice=null）让 cnn_kpi_sync 整卡保存失败；也验证 _merge_edited 没把字段
      静默丢掉（table 是整表替换，页面漏传的行会直接消失）。
    B 真实生效  —— 另起全新解释器导入服务模块（覆盖只发生在导入期），读
      defaults_factory() 的输出，按点路径逐点比对哨兵。抓的是「死字段」：卡片上有这个
      输入框、服务代码却从不读它。
    C 派生量    —— HOST/PORT 拼出来的常量（PM_REFERER / HISTORY_REFERER / DASHBOARD_URL /
      LOGIN_URL）做包含断言。抓的是「覆盖了源变量，但派生常量算在覆盖之前」——
      这种卡片平时全绿，只有真改主机时才暴露（已修过 4 处）。
    D 坏值拦截  —— 逗号整数字段（itemsposition / itemsposition1 / itempositionbusiness，
      schema 里标 int_list:true）填字母必须被保存挡下。因为服务是在**导入期** int()
      解析它们的，一个字母会让整个模块 import 失败 → 任务直接不起，而不是"这项没生效"。

⚠ 备份按**解析后的文件路径**去重、且在任何写入前一次性抓完：多张卡片共用同一个 json
  （mw_ume / ume_in / cell_availability / ems / olib / eflow / eflow_alarm 各两张），
  按 task_id 记备份会把前一张写的哨兵当"原文件"，收尾时把哨兵留在盘上。
  每张卡跑完立刻还原，后一张才不会被前一张的哨兵污染。
⚠ 本文件只调 service 层写入口，不经 HTTP，所以不会触发 routers/task_configs.py 的
  _restart_config_workers()（不会杀 worker）。也因此它验证的是"文件→服务读取"，
  重启 worker 让下次运行读到新值那一步要在页面上保存才有真实覆盖。
⚠ 运行期间会瞬时改写真实配置（每卡 <1s 后还原），别在任务正好要启动的窗口跑。

用法：
    cd D:/01_RPA/Task/my_app
    python tests/test_task_config_live_effect.py                 # 全部 36 张
    python tests/test_task_config_live_effect.py mw_ume_kpi_sync # 只查某几张
退出码：0 全绿；1 有问题（含"还原校验失败"）。
"""
import copy
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import task_config_files as tcf  # noqa: E402
import backend.services.task_configs_registry  # noqa: F401,E402

CHILD_FILE = Path(__file__).resolve().parent / "task_config_child_probe.py"
STR_SENT = "ZZSENTINEL"
SKIP = object()
_MISSING = ("__missing__",)

try:
    import pandas  # noqa: F401
    import sqlalchemy  # noqa: F401
except Exception as e:
    print(f"!! 当前解释器缺依赖（{e}）：请用后端实际运行的 python 启动本脚本 —— {sys.executable}")
    sys.exit(2)

# 派生常量探针：const 必须包含这些 schema 路径对应哨兵值（must_contain 写的是 schema 键名）
PROBES = {
    "ran_ume_daily": [{"name": "PM_REFERER", "module": "backend.services.ran_ume_service",
                       "const": "PM_REFERER", "must_contain": ["host", "port"]}],
    "mw_ume_kpi_sync": [{"name": "HISTORY_REFERER",
                         "module": "backend.services.mw_ume.mw_ume_kpi_service",
                         "const": "HISTORY_REFERER", "must_contain": ["host", "port"]}],
    "mw_ume_kpi_sync_rt": [{"name": "HISTORY_REFERER",
                            "module": "backend.services.mw_ume.mw_ume_kpi_service",
                            "const": "HISTORY_REFERER", "must_contain": ["host", "port"]}],
    "site_outage_screenshot": [
        {"name": "DASHBOARD_URL", "module": "backend.services.site_outage_service",
         "const": "DASHBOARD_URL", "must_contain": ["host", "port"]},
        {"name": "LOGIN_URL", "module": "backend.services.site_outage_service",
         "const": "LOGIN_URL", "must_contain": ["host", "port"]}],
}


def _norm(v):
    """比较用归一化：字符串去空格并大小写折叠（部分服务会 lower() 枚举值），容器递归。"""
    if isinstance(v, str):
        return v.strip().casefold()
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if v is None:
        return None
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return v


def _get_path(obj, path):
    """按 "a.b[0].c" 取值，取不到返回 _MISS。"""
    cur = obj
    for part in path.replace("]", "").replace("[", ".").split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return _MISS
    return cur


def _num_sent(cur, lo, hi, t="int"):
    """生成区间内且与当前值不同的哨兵；无法区分时返回 SKIP（不算失败）。

    优先取**大而有特征**的值：派生常量探针是子串包含判断，端口用 7 这种单位数会被
    28001 之类的原始值误判为通过。
    ⚠ int 字段只能回整数：曾经用一位小数兜底，被校验器判"必须为整数"→ 整卡保存失败，
      连带让 B 阶段全部字段"读不到"，看着像服务有死字段其实是用例自己写坏了。
    """
    lo = -10 ** 6 if lo is None else float(lo)
    hi = 10 ** 6 if hi is None else float(hi)
    if lo == hi:
        return SKIP
    cands = (60007, 60003, 60011, 60005, 12345, 317, 97, 71, 42, 17, 11, 7, 5, 3, 2, 1, 0)
    if t == "int":
        i_lo, i_hi = int(math.ceil(lo)), int(math.floor(hi))
        for c in cands:
            if i_lo <= c <= i_hi and c != _norm(cur):
                return c
        mid = (i_lo + i_hi) // 2
        for c in (mid, mid + 1, mid - 1, i_lo, i_hi):
            if i_lo <= c <= i_hi and c != _norm(cur):
                return c
        return SKIP
    for c in cands:
        if lo <= c <= hi and float(c) != _norm(cur):
            return float(c)
    k = int(math.ceil(lo * 10))
    while k <= int(hi * 10):
        v = k / 10.0
        if lo <= v <= hi and _norm(v) != _norm(cur):
            return v
        k += 1
    return SKIP


def _mutate_json(cur, tag):
    """深拷贝后改掉**第一个标量叶子**，结构保持合法。

    json/list 字段不能整块换成哨兵：服务导入时会按键取值或按结构解析，换掉会让子进程
    直接崩，报出来的"死字段"其实是用例把配置写坏了。
    """
    v = copy.deepcopy(cur)
    hit = []

    def walk(node):
        if hit:
            return
        if isinstance(node, dict):
            items = list(node.items())
        elif isinstance(node, list):
            items = [(i, x) for i, x in enumerate(node)]
        else:
            return
        for k, x in items:
            if isinstance(x, str) and x:
                node[k] = x + f"ZZ{tag}"
                hit.append(k)
                return
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                node[k] = x + tag
                hit.append(k)
                return
            walk(x)
            if hit:
                return
    walk(v)
    if hit:
        return v
    if isinstance(cur, list):      # 空容器没有叶子可改：整块换标记（服务只原样带出）
        return [f"ZZ{tag}"]
    if isinstance(cur, dict):
        return {"__zz__": tag}
    return SKIP


def _is_num_list(s):
    return isinstance(s, str) and bool(re.fullmatch(r"\s*-?\d+(\s*,\s*-?\d+)*\s*", s))


def _flat(obj, prefix=""):
    """配置摊成 {点路径: 标量}，用于查"这个字段在代码默认里长什么样"。

    磁盘 json 常缺字段（老文件），此时 cur=None，光看 cur 分不清它是普通字符串还是逗号
    整数串；给错哨兵会让子进程在导入期崩，看起来像卡片坏了其实是用例写坏了值。
    """
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                out.update(_flat(v, p))
            else:
                out[p] = v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{prefix}[{i}]"
            if isinstance(v, (dict, list)):
                out.update(_flat(v, p))
            else:
                out[p] = v
    return out


def _sentinel(sub, cur, seq, hint=None):
    t = sub.get("type") or "str"
    if t == "int":
        return _num_sent(cur, sub.get("min"), sub.get("max"), "int")
    if t == "float":
        return _num_sent(cur, sub.get("min"), sub.get("max"), "float")
    if t == "bool":
        return not bool(cur)
    if t == "str":
        hint_num = _is_num_list(hint)
        if sub.get("int_list") or _is_num_list(cur) or hint_num:
            # 逗号整数串：保持元素个数只换值，字母会让服务在导入期 int() 崩
            src = cur if _is_num_list(cur) else (hint if hint_num else "")
            n = max(1, len([x for x in str(src).split(",") if x.strip()]))
            return ",".join([str(60000 + (seq[0] or 1) % 9)] * n)
        return STR_SENT
    seq[0] += 1
    return _mutate_json(cur, seq[0])


def _gen(schema, cur, prefix, pairs, seq, skipped, base=None):
    """按 schema 生成"每个字段都不与当前值相同"的编辑值；pairs 记录 (路径, 哨兵)。

    字符串哨兵必须**逐字段唯一**（ZZSENTINEL5/6/…）：服务把这些行按 tech/key 收成字典，
    全部同名会让多行塌成一行 → 探针会误报"后面的行读不到"。
    """
    e = {}
    cur = cur if isinstance(cur, dict) else {}
    base = base if base is not None else {}
    for k, sub in schema.items():
        p = f"{prefix}.{k}" if prefix else k
        c = cur.get(k)
        t = sub.get("type")
        if t == "object":
            e[k] = _gen(sub.get("fields") or {}, c, p, pairs, seq, skipped, base)
        elif t == "table":
            rows = c if isinstance(c, list) and c else [{}]
            fields = sub.get("fields") or {}
            e[k] = [_gen(fields, row, f"{p}[{i}]", pairs, seq, skipped, base)
                    for i, row in enumerate(rows)]
        else:
            s = _sentinel(sub, c, seq, base.get(p))
            if s is SKIP:
                skipped.append(p)          # json / 空 list：只做 A 阶段回读，不断言服务侧
                continue
            if s == STR_SENT:
                seq[0] += 1
                s = f"{STR_SENT}{seq[0]}"
            e[k] = s
            pairs.append((p, s))
    return e


def _first_int_list_field(schema, obj):
    """编辑结果里第一个 int_list 字段，返回 (所在 dict, 键)；没有则 None。"""
    if not isinstance(obj, dict):
        return None
    for k, sub in (schema or {}).items():
        if k not in obj:
            continue
        t = sub.get("type")
        if t == "str" and sub.get("int_list"):
            return obj, k
        if t == "object":
            r = _first_int_list_field(sub.get("fields") or {}, obj[k])
            if r:
                return r
        elif t == "table" and isinstance(obj[k], list):
            for row in obj[k]:
                r = _first_int_list_field(sub.get("fields") or {}, row)
                if r:
                    return r
    return None


def _brief(v):
    s = repr(v)
    return s if len(s) <= 160 else s[:157] + "..."


def _check(pairs, live, tag):
    """逐点比对；live 为 None 时整卡视为"读不到"。"""
    if live is None:
        return [f"{tag}: 读不到配置（factory 返回 None）"]
    issues = []
    for path, sent in pairs:
        got = _get_path(live, path)
        if got == _MISSING:
            issues.append(f"{tag}: {path} 服务侧取不到（死字段？）")
        elif _norm(got) != _norm(sent):
            issues.append(f"{tag}: {path} 期望 {_brief(sent)} 实得 {_brief(got)}")
    return issues


def main() -> int:
    t0 = time.time()
    only = set(sys.argv[1:])
    metas = {m["task_id"]: m for m in tcf.list_configs()}
    tids = [t for t in metas if not only or t in only]
    unknown = only - set(metas)
    if unknown:
        print(f"!! 未注册的 task_id: {', '.join(sorted(unknown))}")
        return 2

    backups = {}
    for tid in tids:
        p = str(Path(tcf.get_resource(tid).path).resolve())
        if p not in backups:
            backups[p] = Path(p).read_bytes() if Path(p).exists() else None

    def restore(p):
        b, f = backups[p], Path(p)
        if b is None:
            if f.exists():
                f.unlink()
        else:
            f.write_bytes(b)

    total_issues = 0
    no_factory = []
    checkpoints = 0
    print(f"解释器: {sys.executable}")
    with tempfile.TemporaryDirectory() as td:
        spec_file = Path(td) / "probe_spec.json"
        for tid in tids:
            r = tcf.get_resource(tid)
            rp = str(Path(r.path).resolve())
            if r.defaults_factory is None:
                no_factory.append(tid)
                restore(rp)
                continue
            pairs, skipped = [], []
            base = _flat(r.defaults_factory() or {})
            edited = _gen(copy.deepcopy(r.schema), copy.deepcopy(r.load()), "",
                          pairs, [0], skipped, base)
            issues = []

            # --- A：真实保存链路 ---
            res = tcf.update_config(tid, edited)
            saved = bool(res.get("success"))
            if not saved:
                issues.append(f"SAVE: {res.get('error')} / {res.get('errors')}")
            else:
                issues += _check(pairs, tcf.get_config(tid), "READBACK")

            # --- B/C：全新解释器里服务真正读到的值 + 派生常量 ---
            # 保存没成功时跳过 B：否则"文件里还是旧值"会被误读成一片死字段。
            probes = PROBES.get(tid, []) if saved else []
            if not saved:
                issues.append("LIVE: 跳过（A 阶段保存失败，文件未更新）")
            else:
                spec_file.write_text(json.dumps({"probes": probes}, ensure_ascii=False),
                                     encoding="utf-8")
                cmd = [sys.executable, str(CHILD_FILE), tid, str(spec_file)]
                try:
                    cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", timeout=300, cwd=str(ROOT),
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                    line = next((l for l in (cp.stdout or "").splitlines()
                                 if l.startswith("@@RESULT@@")), None)
                    if line is None:
                        tail = (cp.stderr or cp.stdout or "").strip().splitlines()
                        issues.append(f"CHILD: 无结果输出: {' | '.join(tail[-14:])[:900]}")
                    else:
                        data = json.loads(line[len("@@RESULT@@"):])
                        issues += _check(pairs, data.get("factory"), "LIVE")
                        pv = {path: s for path, s in pairs}
                        for pr in probes:
                            val = _norm((data.get("probes") or {}).get(pr["name"], ""))
                            for need in pr["must_contain"]:
                                if need not in pv or _norm(str(pv[need])) in val:
                                    continue
                                issues.append(
                                    f"PROBE: {pr['const']} 未包含 {need}={pv[need]!r}"
                                    f"（派生量算在覆盖之前？） 实得 {val[:120]!r}")
                except Exception as e:
                    issues.append(f"CHILD: 异常 {type(e).__name__}: {e}")

            # --- D：坏值必须在保存时就被挡住 ---
            loc = _first_int_list_field(r.schema, edited)
            if loc:
                cont, key = loc
                good = cont[key]
                cont[key] = "ZZ1,abc"
                bad = tcf.update_config(tid, edited)
                restore(rp)                     # 万一真写进去了，立刻还原
                if bad.get("success"):
                    issues.append(f"GUARD: {key} 填非整数竟然保存成功（会崩在服务导入期）")
                cont[key] = good

            restore(rp)      # 立刻还原，下一张卡从干净文件开始
            checkpoints += len(pairs)
            total_issues += len(issues)
            print(f"[{'FAIL' if issues else 'OK  '}] {tid:32s} 检查点={len(pairs):3d} "
                  f"探针={len(probes)} 未断言={len(skipped)}"
                  + (f" ({','.join(skipped[:4])}…)" if skipped else ""))
            for it in issues:
                print(f"        - {it}")

    residue = []
    for p, b in backups.items():
        f = Path(p)
        now = f.read_bytes() if f.exists() else None
        if now != b:
            residue.append(f"文件与初始状态不一致: {p}")
        elif now is not None and STR_SENT.encode() in now:
            residue.append(f"哨兵残留: {p}")
    if no_factory:
        print("\n无 defaults_factory（只能静态检查）: " + ", ".join(no_factory))
    print(f"\n卡片={len(tids)} 检查点={checkpoints} 合计问题={total_issues} "
          f"还原校验={'通过' if not residue else '失败'}")
    for x in residue:
        print(f"  !! {x}")
    print(f"总耗时 {time.time() - t0:.1f}s")
    return 1 if (total_issues or residue) else 0


if __name__ == "__main__":
    sys.exit(main())
