# -*- coding: utf-8 -*-
"""
auth_health_check.py - 鉴权健康小巡检（只读，dry-run）
======================================================
用途：在「验证码 / 账号锁定 / 密码错误」真正影响取数之前提前预警。
扫描三处：
  1. auth_cache/.locked_*.json   —— 账号锁定熔断标记（含冷却剩余时间）
  2. log/*.log（近 N 天）        —— 验证码/锁定/密码错误/空密码护栏等终态登录错误
  3. auth_cache/*.json           —— 各主机:端口 会话缓存的年龄与新鲜度

设计原则：
  - 纯只读：不修改/删除任何业务文件，不触网、不登录。
  - 纯标准库：无需安装依赖，任意 Python 3.8+ 可跑。
  - 分类逻辑与 auth_manager._describe_login_failure 保持一致，
    特别是「密码错误文案里带 may be locked 属将来时警告，不是已锁定」，
    避免重蹈 2026-10-14 把密码错误报成账号被锁的误判。
  - 不扫描 log/auth_health_check_YYYYMMDD.log（计划任务把自己的 stdout
    重定向到这里）。「未发现验证码」和 auto_retry 回写的
    「鉴权健康 CRITICAL」都不是上游拒登（2026-11-12 自激误报）。

用法：
  python backend/scripts/auth_health_check.py                 # 近 1 天，只打印
  python backend/scripts/auth_health_check.py --days 3        # 近 3 天
  python backend/scripts/auth_health_check.py --save          # 另存 md 报告到 outputs/auth_health/
  python backend/scripts/auth_health_check.py --json          # 追加 JSON 明细（供其他脚本消费）

退出码：0=健康 / 1=有 WARN（密码错误/空密码拦截等） / 2=有 CRITICAL（验证码/锁定）
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------- 路径（可用环境变量覆盖，默认按本脚本位置推导项目根） ----------
SCRIPT_DIR = Path(__file__).resolve().parent          # backend/scripts
PROJECT_ROOT = SCRIPT_DIR.parent.parent               # my_app
import os
AUTH_CACHE_DIR = Path(os.environ.get("AUTH_CACHE_DIR",
                                     PROJECT_ROOT / "backend" / "services" / "auth_cache"))
LOG_DIR = Path(os.environ.get("MYAPP_LOG_DIR", PROJECT_ROOT / "log"))
EXTRA_LOG_DIRS = [PROJECT_ROOT / "backend" / "services" / "cn_ems" / "logs"]
REPORT_DIR = PROJECT_ROOT / "outputs" / "auth_health"

# ---------- 日志行格式：2026-11-11 00:00:01,108 [auth_manager] INFO ... ----------
LINE_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
# 按文件名里的日期快速过滤（backend_runtime_20261111.log / daily_20260825.log）
FILE_DATE_RE = re.compile(r"(\d{8})")
# 计划任务 auth_health_check_daily.bat 把本脚本 stdout 重定向到
# log/auth_health_check_YYYYMMDD.log。那份文件就是报告本身，不是登录日志。
OWN_REPORT_LOG_RE = re.compile(r"^auth_health_check_\d{8}(?:_alt\d+)?\.log$", re.I)

MAX_FILE_BYTES = 64 * 1024 * 1024   # 单文件超过 64MB 只读尾部，防止撑爆内存
MAX_HITS_PER_CAT = 50               # 每类最多留 50 条样例，计数仍全量


def _captcha_mention_is_not_a_failure(line: str) -> bool:
    """行里出现验证码字样，但不是上游拒登。

    2026-11-12 实测：08:30 巡检结论「未发现验证码」被写进
    log/auth_health_check_*.log，下一次扫描把它判成 CRITICAL；
    auto_retry 再把「鉴权健康 CRITICAL：…图形验证码…」写进 worker 日志，
    条数 2 → 3 → 4 自己滚上去。这些行必须排除，真登录失败不能误伤。
    """
    # authorize 页面含验证码关键字只是提示，仍会尝试 RSA 登录
    if "仅提示" in line:
        return True
    # 本巡检的 OK 结论（否定句）
    if ("未发现验证码" in line or "无验证码" in line
            or "没有验证码" in line or "不含验证码" in line):
        return True
    # 任务失败文案 / auto_retry 回声：引用的是上一次巡检结论
    if "鉴权健康 CRITICAL" in line or "鉴权健康巡检" in line:
        return True
    # 门户登录预填提示（RAIS 等人工补码），不是采集账号的脚本登录终态
    if "只预填" in line or "不自动提交" in line:
        return True
    return False


def classify(line: str):
    """把一行日志归类为终态鉴权错误；非目标行返回 None。
    顺序敏感：先密码错误（其文案含 'may be locked' 将来时警告），再锁定。"""
    low = line.lower()

    # 验证码（Battery 192.168.170.2 实测 code=1300112）
    if "verification code" in low or "captcha" in low or "验证码" in line:
        if _captcha_mention_is_not_a_failure(line):
            return None
        return ("CRITICAL", "captcha", "上游启用图形验证码，脚本登录无法通过")

    # 空密码护栏（本地拦截，未触网，但说明凭据组配置有问题）
    if "拒绝以空密码登录" in line:
        return ("WARN", "empty_password", "空密码被护栏拦截（凭据组未配置密码）")

    # 密码错误（含 'may be locked' 将来时警告 —— 不是已锁定！）
    if "incorrect user name or password" in low or "用户名或密码错误" in line:
        return ("WARN", "wrong_password", "用户名或密码错误（连续3次将触发上游锁定）")

    # 账号已被上游锁定
    if ("user has been locked" in low or "has been locked" in low
            or "user is locked" in low or "账号已被上游锁定" in line):
        return ("CRITICAL", "locked", "账号已被上游锁定，需管理员解锁")

    # 密码到期
    if ("密码已到期" in line or "密码到期" in line
            or ("password" in low and ("expire" in low or "到期" in line))):
        return ("WARN", "password_expired", "密码已到期，需改密并同步凭据")

    # 账号被禁用
    if "账号已被禁用" in line or ("disabled" in low and "账号" in line):
        return ("CRITICAL", "disabled", "账号已被禁用")

    return None


def iter_log_files(days: int):
    """收集近 N 天的日志文件（含今天），按 mtime 粗筛 + 文件名日期细筛。"""
    cutoff = time.time() - days * 86400
    today = datetime.now().strftime("%Y%m%d")
    dirs = [LOG_DIR] + [d for d in EXTRA_LOG_DIRS if d.is_dir()]
    seen = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.log")):
            if p in seen:
                continue
            seen.add(p)
            # 不扫自己的 stdout 报告，避免「未发现验证码」被当成验证码失败
            if OWN_REPORT_LOG_RE.match(p.name):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            m = FILE_DATE_RE.search(p.name)
            if m and m.group(1) < (datetime.now().strftime("%Y%m%d")):
                # 文件名带日期且早于今天：只保留 N 天窗口内的
                try:
                    fd = datetime.strptime(m.group(1), "%Y%m%d")
                    if (datetime.now() - fd).days >= days:
                        continue
                except ValueError:
                    pass
            yield p


def scan_logs(days: int):
    """扫描日志，返回 {category: {severity, desc, count, hits:[(time,file,line)]}}
    同一事件会同时出现在 worker_x 与 worker_runtime_x 两份日志里，
    按 (时间戳, 行内容) 去重，避免计数翻倍。"""
    cats = {}
    seen_events = set()
    files_scanned = 0
    for p in iter_log_files(days):
        files_scanned += 1
        try:
            size = p.stat().st_size
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                if size > MAX_FILE_BYTES:
                    f.seek(size - MAX_FILE_BYTES)
                    f.readline()  # 丢弃半行
                for raw in f:
                    line = raw.rstrip("\n")
                    hit = classify(line)
                    if not hit:
                        continue
                    sev, cat, desc = hit
                    ts_m = LINE_TS_RE.match(line)
                    ts = ts_m.group(1) if ts_m else ""
                    # 行级时间过滤（无时间戳的行跟随文件 mtime 粗筛结果）
                    if ts:
                        try:
                            lt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                            if (datetime.now() - lt).total_seconds() > days * 86400:
                                continue
                        except ValueError:
                            pass
                    event_key = (ts, line)
                    if event_key in seen_events:
                        continue
                    seen_events.add(event_key)
                    entry = cats.setdefault(cat, {"severity": sev, "desc": desc,
                                                  "count": 0, "hits": []})
                    entry["count"] += 1
                    if len(entry["hits"]) < MAX_HITS_PER_CAT:
                        entry["hits"].append({"time": ts, "file": p.name,
                                              "line": line[:400]})
        except OSError:
            continue
    return cats, files_scanned


def scan_lock_markers():
    """读取 .locked_*.json 熔断标记，区分冷却中 / 已过期残留。"""
    active, stale = [], []
    if not AUTH_CACHE_DIR.is_dir():
        return active, stale
    now = time.time()
    for p in sorted(AUTH_CACHE_DIR.glob(".locked_*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stale.append({"file": p.name, "note": "标记文件损坏/不可读"})
            continue
        until = d.get("until") or 0
        item = {
            "file": p.name,
            "target": f'{d.get("host", "?")}:{d.get("port", "?")}',
            "username": d.get("username", ""),
            "reason": (d.get("reason") or "")[:200],
            "locked_at": d.get("locked_at", ""),
        }
        if until > now:
            item["remain_min"] = round((until - now) / 60, 1)
            active.append(item)
        else:
            item["note"] = "冷却期已过（残留文件，下次登录会自动清理）"
            stale.append(item)
    return active, stale


def scan_cache_freshness():
    """各主机:端口 会话缓存年龄。只读元数据，不打印 cookie/token。"""
    rows = []
    if not AUTH_CACHE_DIR.is_dir():
        return rows
    now = datetime.now(timezone.utc)
    for p in sorted(AUTH_CACHE_DIR.glob("*.json")):
        if p.name.startswith(".locked_"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        created = d.get("created_at")
        age_min = None
        if created:
            try:
                ct = datetime.fromisoformat(created)
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=timezone.utc)
                age_min = round((now - ct).total_seconds() / 60, 1)
            except ValueError:
                pass
        rows.append({
            "target": f'{d.get("host", p.stem)}:{d.get("port", "?")}',
            "username": d.get("username", ""),
            "file": p.name,
            "created_at": created or "",
            "age_min": age_min,
            "expires_in": d.get("expires_in"),
        })
    rows.sort(key=lambda r: (r["age_min"] is None, -(r["age_min"] or 0)))
    return rows


def build_report(days, cats, files_scanned, active_locks, stale_locks, cache_rows):
    crit = {k: v for k, v in cats.items() if v["severity"] == "CRITICAL"}
    warn = {k: v for k, v in cats.items() if v["severity"] == "WARN"}
    if crit or active_locks:
        overall = "CRITICAL"
    elif warn:
        overall = "WARN"
    else:
        overall = "OK"

    L = []
    L.append(f"# 鉴权健康巡检报告")
    L.append("")
    L.append(f"- 巡检时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（本地时间）")
    L.append(f"- 扫描窗口：近 {days} 天 | 日志文件 {files_scanned} 个 | 缓存目录 `{AUTH_CACHE_DIR}`")
    L.append(f"- **总体结论：{overall}**"
             + ("（发现验证码/锁定，需人工介入）" if overall == "CRITICAL"
                else "（发现密码类隐患，建议核对凭据）" if overall == "WARN"
                else "（未发现验证码/锁定/密码错误迹象）"))
    L.append("")

    L.append("## 1. 账号锁定熔断标记（.locked_*）")
    if active_locks:
        L.append("| 目标 | 账号 | 冷却剩余(分) | 锁定时间 | 原因 |")
        L.append("|---|---|---|---|---|")
        for it in active_locks:
            L.append(f'| {it["target"]} | {it["username"]} | {it["remain_min"]} '
                     f'| {it["locked_at"]} | {it["reason"]} |')
    else:
        L.append("无冷却中的锁定标记。")
    if stale_locks:
        L.append("")
        L.append("过期/残留标记（不影响运行）：" + "、".join(s["file"] for s in stale_locks))
    L.append("")

    L.append("## 2. 日志中的终态鉴权错误")
    if not cats:
        L.append(f"近 {days} 天日志中未发现验证码/锁定/密码错误/空密码拦截记录。")
    else:
        order = ["captcha", "locked", "disabled", "wrong_password",
                 "password_expired", "empty_password"]
        for cat in order:
            if cat not in cats:
                continue
            v = cats[cat]
            L.append(f'### [{v["severity"]}] {v["desc"]} —— 共 {v["count"]} 条')
            for h in v["hits"][:10]:
                L.append(f'- `{h["time"]}` ({h["file"]})')
                L.append(f'  > {h["line"]}')
            if v["count"] > 10:
                L.append(f'- …（其余 {v["count"] - 10} 条略，完整明细见 --json 输出）')
            L.append("")

    L.append("## 3. 会话缓存新鲜度（参考）")
    L.append("> 年龄大≠故障：auth_manager 会在 TTL 到期/探活失败时自动重登；")
    L.append("> 此表用于发现「长期未刷新」的异常缓存。同一目标可能有带/不带账号后缀")
    L.append("> 的两代缓存文件，以最新一行为准，不带后缀的旧文件多为历史遗留。")
    L.append("")
    L.append("| 目标 | 账号 | 缓存文件 | 缓存时间(UTC) | 年龄(分) |")
    L.append("|---|---|---|---|---|")
    for r in cache_rows:
        age = "未知" if r["age_min"] is None else str(r["age_min"])
        L.append(f'| {r["target"]} | {r["username"]} | {r["file"]} | {r["created_at"]} | {age} |')
    L.append("")

    L.append("## 4. 处置建议")
    if overall == "OK":
        L.append("- 无需动作。建议将本巡检挂入计划任务每日跑一次（--save 留档）。")
    else:
        if crit.get("captcha") or any("验证码" in (a.get("reason") or "") for a in active_locks):
            L.append("- **验证码**：优先联系管理员为采集账号关闭验证码/加白名单；"
                     "过渡期人工登录一次刷新 auth_info.json（Battery 回退链）。")
        if crit.get("locked") or active_locks:
            L.append("- **锁定**：冷却期内脚本会自动停登（熔断保护）；"
                     "到期仍失败需联系 UME 管理员解锁，勿反复重试。")
        if warn.get("wrong_password") or warn.get("empty_password"):
            L.append("- **密码错误/空密码**：立即核对「设置→凭据」对应凭据组；"
                     "上游规则为连续 3 次密码错误锁 1440 分钟，勿放任重试。")
        if warn.get("password_expired"):
            L.append("- **密码到期**：在 UME 侧改密后同步更新凭据组。")
    L.append("")
    return overall, "\n".join(L)


def notify_weixin(overall, cats, active_locks, report_path):
    """仅 CRITICAL 时推微信（复用 weixin_notifier 的 pushplus 通道）。
    推送失败只记日志，绝不改变巡检退出码。WARN（密码类）不推，避免刷屏。"""
    if overall != "CRITICAL":
        return
    # 让 auth_health_check / weixin_notifier / credential_store 可按顶层模块导入
    for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend" / "services")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from weixin_notifier import send_weixin_message
    except Exception as e:  # noqa: BLE001
        logging.getLogger("auth_health").warning("微信通知模块不可用，跳过推送: %s", e)
        return

    lines = ["【鉴权巡检 CRITICAL】", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    for cat in ("captcha", "locked", "disabled"):
        if cat in cats:
            v = cats[cat]
            lines.append(f"- {v['desc']}：{v['count']} 条")
            if v["hits"]:
                h = v["hits"][0]
                lines.append(f"  最近：{h['time']} {h['line'][:120]}")
    for a in active_locks:
        lines.append(f"- 锁定冷却中：{a['target']} 剩余 {a.get('remain_min', '?')} 分钟")
    lines.append("处置：验证码→管理员白名单/人工登录刷新 auth_info；锁定→等冷却或联系管理员解锁。")
    lines.append(f"报告：{report_path}")
    text = "\n".join(lines)
    try:
        res = send_weixin_message(text)
        if res.get("success"):
            logging.getLogger("auth_health").info("CRITICAL 微信通知已发送")
        else:
            logging.getLogger("auth_health").warning("微信通知发送失败: %s", res.get("error"))
    except Exception as e:  # noqa: BLE001
        logging.getLogger("auth_health").warning("微信通知异常: %s", e)


def _save_report(report, overall, days, cats, active_locks, stale_locks,
                 cache_rows, with_json=False):
    """把巡检报告写盘（md + 可选 JSON 明细），返回 (md_path, json_path)。
    与 main() 的 --save 行为一致：目标被占用时短重试 + 降级另存。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = REPORT_DIR / f"auth_health_{stamp}.md"
    # 容忍目标被占用：短重试 + 降级另存
    for attempt in range(3):
        try:
            md_path.write_text(report, encoding="utf-8")
            break
        except OSError:
            if attempt == 2:
                md_path = REPORT_DIR / f"auth_health_{stamp}_alt{attempt}.md"
                md_path.write_text(report, encoding="utf-8")
            else:
                time.sleep(1)
    json_path = None
    if with_json:
        data = {"overall": overall, "days": days,
                "generated_at": datetime.now().isoformat(),
                "categories": cats, "active_locks": active_locks,
                "stale_locks": stale_locks, "cache": cache_rows}
        json_path = md_path.with_suffix(".json")
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return md_path, json_path


def run_auth_health_check() -> dict:
    """任务入口：每日 07:00 只读巡检鉴权健康（days=1，--save 留档）。
    与 main() 等价的一次巡检，但不调 sys.exit、不往 stdout 打印报告。
    返回约定照 db_freshness_check：success + error（task_runner 的失败通知
    取 error 字段）；CRITICAL 判失败，WARN 只记详情不判失败。"""
    logger = logging.getLogger("auth_health")
    t_start = time.time()
    days = 1

    cats, files_scanned = scan_logs(days)
    active_locks, stale_locks = scan_lock_markers()
    cache_rows = scan_cache_freshness()
    overall, report = build_report(days, cats, files_scanned,
                                   active_locks, stale_locks, cache_rows)
    md_path, json_path = _save_report(report, overall, days, cats,
                                      active_locks, stale_locks, cache_rows,
                                      with_json=True)
    logger.info("[AuthHealth] 巡检完成: overall=%s 日志文件=%d 报告=%s",
                overall, files_scanned, md_path)

    if overall == "CRITICAL":
        try:
            notify_weixin(overall, cats, active_locks, md_path)
        except Exception as e:  # noqa: BLE001 - 通知故障不改变巡检结果
            logger.warning("[AuthHealth] CRITICAL 微信通知异常: %s", e)

    crit = {k: v for k, v in cats.items() if v["severity"] == "CRITICAL"}
    warn = {k: v for k, v in cats.items() if v["severity"] == "WARN"}
    error_text = None
    if overall == "CRITICAL":
        parts = [f"{v['desc']}{v['count']}条" for v in crit.values()]
        if active_locks:
            parts.append(f"锁定冷却中 {len(active_locks)} 个")
        error_text = "鉴权健康 CRITICAL：" + "；".join(parts)

    return {
        "success": overall != "CRITICAL",
        "error": error_text,
        "overall": overall,
        "days": days,
        "files_scanned": files_scanned,
        "critical": {k: {"desc": v["desc"], "count": v["count"]}
                     for k, v in crit.items()},
        "warn": {k: {"desc": v["desc"], "count": v["count"]}
                 for k, v in warn.items()},
        "active_locks": active_locks,
        "stale_locks": stale_locks,
        "report_path": str(md_path),
        "json_path": str(json_path) if json_path else "",
        "elapsed_seconds": round(time.time() - t_start, 2),
    }


def main():
    ap = argparse.ArgumentParser(description="鉴权健康小巡检（只读）")
    ap.add_argument("--days", type=int, default=1, help="扫描近 N 天日志（默认 1）")
    ap.add_argument("--save", action="store_true", help="另存 md 报告到 outputs/auth_health/")
    ap.add_argument("--json", action="store_true", help="同时输出 JSON 明细")
    ap.add_argument("--notify", action="store_true",
                    help="仅 CRITICAL（验证码/锁定）时推微信；需与 --save 同用")
    args = ap.parse_args()
    days = max(1, args.days)

    # 强制 stdout/stderr 用 UTF-8 + replace：计划任务/服务上下文里控制台编码
    # 可能是 cp1252/GBK，直接 print 中文会抛 UnicodeEncodeError 导致整个巡检崩溃、
    # 报告存不下来（2026-11-11 实测）。reconfigure 后对任何控制台编码免疫。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

    cats, files_scanned = scan_logs(days)
    active_locks, stale_locks = scan_lock_markers()
    cache_rows = scan_cache_freshness()
    overall, report = build_report(days, cats, files_scanned,
                                   active_locks, stale_locks, cache_rows)

    # 控制台输出（stdout 已在 main 开头 reconfigure 为 UTF-8/replace，无需再兜底）
    print(report)

    md_path, json_path = (None, None)
    if args.save:
        md_path, json_path = _save_report(report, overall, days, cats,
                                          active_locks, stale_locks, cache_rows,
                                          with_json=args.json)
        print(f"\n[已保存] {md_path}")
        if json_path:
            print(f"[已保存] {json_path}")

    if args.notify:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
        notify_weixin(overall, cats, active_locks, md_path or "(未保存报告)")

    sys.exit({"OK": 0, "WARN": 1, "CRITICAL": 2}[overall])


if __name__ == "__main__":
    main()
