"""扩展作业的统一认领 / 回报层 —— 把两个互相独立的作业源收敛成一个端点。

## 为什么需要这一层

系统里有**两个**由 Chrome 扩展执行的 WhatsApp 作业源，各自维护自己的作业文件：

| 来源 | 作业文件 | 载荷 | 业务服务 |
| --- | --- | --- | --- |
| 定时发图 | `data/whatsapp_ext_job.json` | `items`（图片清单 + 备注） | `whatsapp_ext_service` |
| TT 告警文本 | `data/tt_alert_job.json` | `messages`（`{tt_no, text}`） | `tt_alarm_job` |

但扩展**只轮询一个端点**（`/api/whatsapp/ext/job`）。若各写一个端点，扩展就得并行轮询
两处，并自行处理「两个作业同时可发」时的互斥 —— 那会把并发问题推给浏览器端，
而扩展的发送是**串行且带 running 锁**的（`background.js` 的 `running` 标志）。

故本模块把「取一个可发作业」收敛到一处：**同一时刻最多认领一个作业**，
发图优先（它由人工/定时显式投递），其次才是 TT 告警文本。
扩展拿到的响应统一带 `kind`（`image` / `text`），按此分发到两条发送路径即可。

## 互斥与原子性

认领动作本身仍是各自服务里的「读 → 判 pending → 置 running → 原子写回」，
本模块只在**两者都空闲时**择一认领。两个来源的作业文件不同，故不存在交叉覆盖；
同一来源的并发认领由各自服务的原子写 + 状态判断防住。
"""
import logging
from typing import Any, Callable, Dict, Optional

from backend.services import tt_alarm_job
from backend.services import whatsapp_ext_service as ext

logger = logging.getLogger("whatsapp_job_claim")


def claim_next_job() -> Optional[Dict[str, Any]]:
    """认领下一个待发作业；无则 None。

    优先级：发图 > TT 告警文本。返回的字典带 `kind` 字段供扩展分发：
      * `kind == "image"` → `items` 是图片清单（沿用既有字段名）
      * `kind == "text"`  → `messages` 是 `[{tt_no, text}]`

    **返回体一律带 `pending: True`** —— 扩展以 `job.pending === true` 判定「有无作业」
    （`background.js` 的 `tryClaimJob`），缺这个字段文本作业会被直接丢掉。
    发图源自带该字段，文本源不带，故在这里统一补上。
    """
    image_job = _claim_safely(ext.claim_pending_job, "image")
    if image_job is not None:
        image_job["kind"] = "image"
        image_job["pending"] = True
        return image_job

    text_job = _claim_safely(tt_alarm_job.claim_pending_job, "text")
    if text_job is not None:
        text_job["kind"] = "text"
        text_job["pending"] = True
        return text_job

    return None


def _claim_safely(claim: Callable[[], Optional[Dict[str, Any]]],
                  label: str) -> Optional[Dict[str, Any]]:
    """调用某个来源的认领函数，异常降级为「无作业」而不是让整个端点 500。

    一个来源坏掉（例如图片目录不可读）不应连带让另一个来源也发不出去。
    """
    try:
        return claim()
    except Exception:  # noqa: BLE001
        logger.warning("[WAClaim] %s 作业认领失败，跳过该来源", label, exc_info=True)
        return None


def report_result(kind: str, job_id: str, result: Dict[str, Any]) -> bool:
    """按 `kind` 把结果回报给对应的作业源。job_id 不匹配返回 False。

    发图与文本的**回报字段名不同**（`groups_sent` vs `sent`），逐字转交即可 ——
    各业务服务自己解析，本层不替它们做字段翻译。
    """
    if kind == "text":
        return tt_alarm_job.complete_job(job_id, result)
    if kind == "image":
        return ext.complete_job(job_id, result)
    logger.warning("[WAClaim] 未知作业类型 %r，拒绝回报", kind)
    return False
