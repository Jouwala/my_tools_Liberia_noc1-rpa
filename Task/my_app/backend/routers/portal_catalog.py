# -*- coding: utf-8 -*-
"""portal_catalog.py - MsPortal 看板目录 API（**全局共享**）
==========================================================
背景：MsPortal（nginx 静态站 http://<host>/MsPortal/）的看板目录写死在前端
      `assets/data.js`（由 `TMP/build_msportal_data.py` 从 xlsx 自动生成，
      文件头明确写着 do not edit by hand），页面上原有的「编辑分组归属」
      只能改本机 localStorage —— 与 my_app 侧栏菜单当年遇到的是同一个问题：
      **A 改了，B 看不到；同一套门户不该有两份目录。**

现在：目录（有哪些看板、标题、描述、链接、分组归属、责任人…）以**服务端**为准，
      所有人读同一份；但**只允许本机（或持 X-API-Token）修改**，避免局域网里
      任何人误改把大家的门户弄乱 —— 权限模型与 `routers/ui_config.py` 严格一致。

端点：
- GET    /api/portal-catalog   已登录访客可读；返回 {catalog, updated_at, editable}
- PUT    /api/portal-catalog   仅本机可写（require_protected）；整体替换
- DELETE /api/portal-catalog   仅本机可写；删除目录，前端回落内置 data.js

持久化：backend/data/portal_catalog.json（原子替换写，避免半个文件）。
结构：{"v": 1, "savedAt": "2026-09-17T17:30:00", "items": [ <看板对象> … ]}
      文件不存在 = 从未保存过，GET 返回 catalog=null，前端用 data.js 内置目录。
      「内置目录」与「服务端目录」的关系 = uniplam 的 INITIAL_DASHBOARDS 与
      portal-default.json：前者是出厂值，后者是运行时覆盖，DELETE 即可回退。

鉴权：本接口**刻意不进** main.py 的 `_PUBLIC_API` 白名单 —— 未登录访客连目录
      都读不到（与 MsPortal 的整页门禁口径一致）。本机回环由中间件放行，
      服务器本机运维/开发不受影响；局域网登录用户持 myapp_session 也能读。
"""
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.security import is_privileged, require_protected
from backend.services.atomic_write import atomic_replace_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portal-catalog", tags=["portal-catalog"])

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../my_app/backend
CONFIG_PATH = os.path.join(BACKEND_DIR, "data", "portal_catalog.json")

# --------------------------- 上限（防误传巨大 JSON 把门户渲染拖垮） ---------------------------
MAX_ITEMS = 500            # 看板总数上限（当前 51，留足冗余）
MAX_TEXT = 600             # 短文本字段（标题/责任人/部门/频率/图标名）
MAX_LONG_TEXT = 2000       # 描述类长文本
MAX_TAGS = 24              # 单个看板的标签数
MAX_TAG_LEN = 40
MAX_GROUPS_PER_ITEM = 24   # 单个看板归属的分组数
MAX_GROUP_LEN = 64
MAX_URL_LEN = 1000
MAX_QC_IDS = 40

PLATFORMS = {"myapp", "finebi", "external"}
STATUSES = {"online", "beta"}
DEFAULT_ICON = "dashboard"

# 看板对象允许落盘的字段白名单。**必须白名单**：请求体来自浏览器，
# 不做过滤的话任何字段都会被原样存下来，再被前端 `esc()` 之外的地方读到。
_ITEM_FIELDS = (
    "no", "groups", "titleZh", "titleEn", "descZh", "descEn",
    "platform", "url", "tags", "owner", "ownerEn", "dept", "deptEn",
    "status", "freq", "clicks", "icon", "custom", "qc", "boSub",
)


# --------------------------- 读写 ---------------------------
def _read_catalog() -> Optional[dict]:
    """读取已保存的目录；文件不存在/损坏返回 None（前端回落内置 data.js）。"""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[portal-catalog] 读取看板目录失败（按未配置处理）: {e}")
        return None


def _write_catalog(catalog: dict) -> None:
    """原子替换写入（先写同目录临时文件，再 replace）。"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="portal_catalog_", suffix=".tmp",
                               dir=os.path.dirname(CONFIG_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
        atomic_replace_file(tmp, CONFIG_PATH)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# --------------------------- 校验 / 归一化 ---------------------------
def _clip(v: Any, limit: int) -> str:
    if v is None:
        return ""
    return str(v).strip()[:limit]


def _str_list(v: Any, max_items: int, max_len: int) -> list:
    """字符串数组：去空、去重、截断；非数组一律当空数组（宽容，不 400）。"""
    if not isinstance(v, list):
        return []
    out: list = []
    for x in v:
        s = _clip(x, max_len)
        if s and s not in out:
            out.append(s)
    return out[:max_items]


def _to_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _normalize_item(raw: Any, idx: int) -> Optional[dict]:
    """归一化单个看板。缺标题或链接的项直接丢弃（宁可少一条，不要一条点不开的卡片）。"""
    if not isinstance(raw, dict):
        return None
    title_zh = _clip(raw.get("titleZh"), MAX_TEXT)
    title_en = _clip(raw.get("titleEn"), MAX_TEXT)
    url = _clip(raw.get("url"), MAX_URL_LEN)
    if not (title_zh or title_en):
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        return None

    platform = raw.get("platform") if raw.get("platform") in PLATFORMS else "external"
    status = raw.get("status") if raw.get("status") in STATUSES else "online"

    item = {
        # no 是前端分组覆盖（localStorage 的 assign）与卡片锚点的键，必须稳定。
        # 自建看板由前端分配（内置最大号 + 1），这里只兜底。
        "no": _to_int(raw.get("no"), 100000 + idx),
        "groups": _str_list(raw.get("groups"), MAX_GROUPS_PER_ITEM, MAX_GROUP_LEN),
        "titleZh": title_zh,
        "titleEn": title_en,
        "descZh": _clip(raw.get("descZh"), MAX_LONG_TEXT),
        "descEn": _clip(raw.get("descEn"), MAX_LONG_TEXT),
        "platform": platform,
        "url": url,
        "tags": _str_list(raw.get("tags"), MAX_TAGS, MAX_TAG_LEN),
        "owner": _clip(raw.get("owner"), MAX_TEXT),
        "ownerEn": _clip(raw.get("ownerEn"), MAX_TEXT),
        "dept": _clip(raw.get("dept"), MAX_TEXT),
        "deptEn": _clip(raw.get("deptEn"), MAX_TEXT),
        "status": status,
        "freq": _clip(raw.get("freq"), MAX_TEXT),
        "clicks": max(0, _to_int(raw.get("clicks"), 0)),
        "icon": _clip(raw.get("icon"), 40) or DEFAULT_ICON,
    }
    qc = _str_list(raw.get("qc"), MAX_QC_IDS, MAX_GROUP_LEN)
    if qc:
        item["qc"] = qc
    bo_sub = _clip(raw.get("boSub"), 40)
    if bo_sub:
        item["boSub"] = bo_sub
    # 自建看板标记：前端据此允许删除内置目录里不存在的条目
    if raw.get("custom"):
        item["custom"] = True
    return item


def _normalize_catalog(raw: Any) -> dict:
    """校验 + 归一化整个目录；结构非法直接 400，不做「猜」的兜底。"""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="catalog 必须是对象")
    items_raw = raw.get("items")
    if not isinstance(items_raw, list):
        raise HTTPException(status_code=400, detail="catalog.items 必须是数组")
    if not items_raw:
        raise HTTPException(status_code=400, detail="看板目录不能为空（如需清空请用 DELETE 接口）")
    if len(items_raw) > MAX_ITEMS:
        raise HTTPException(status_code=400, detail=f"看板数超过上限 {MAX_ITEMS}")

    items: list = []
    seen_no: set = set()
    for i, it in enumerate(items_raw):
        norm = _normalize_item(it, i)
        if norm is None:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 条看板缺少标题或合法链接")
        if norm["no"] in seen_no:
            raise HTTPException(status_code=400, detail=f"看板编号重复: {norm['no']}")
        seen_no.add(norm["no"])
        items.append(norm)

    return {
        "v": 1,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }


# --------------------------- 路由 ---------------------------
@router.get("")
def get_catalog(request: Request):
    """读取全局看板目录。已登录访客可读（本机回环由中间件直接放行）。

    `editable` 与 PUT 的判据共用 `is_privileged`，避免「前端以为能改、一保存 403」。
    """
    catalog = _read_catalog()
    updated_at = None
    if catalog and os.path.exists(CONFIG_PATH):
        try:
            updated_at = datetime.fromtimestamp(os.path.getmtime(CONFIG_PATH)).isoformat(timespec="seconds")
        except OSError:
            updated_at = None
    return {
        "catalog": catalog,
        "updated_at": updated_at,
        # 前端据此决定是否显示「新增看板 / 编辑 / 删除」入口：非本机只读
        "editable": is_privileged(request),
    }


@router.put("", dependencies=[Depends(require_protected)])
def put_catalog(payload: dict):
    """保存全局看板目录（仅本机 / 持令牌）。整体替换，返回落盘后的结构。"""
    catalog = _normalize_catalog((payload or {}).get("catalog"))
    _write_catalog(catalog)
    logger.info(
        "[portal-catalog] 看板目录已更新: %d 个看板（自建 %d）",
        len(catalog["items"]),
        sum(1 for x in catalog["items"] if x.get("custom")),
    )
    return {"catalog": catalog, "updated_at": catalog["savedAt"], "editable": True}


@router.delete("", dependencies=[Depends(require_protected)])
def delete_catalog():
    """删除全局看板目录（仅本机 / 持令牌），前端回落内置 data.js 目录。"""
    try:
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
    logger.info("[portal-catalog] 看板目录已重置为内置默认")
    return {"catalog": None, "updated_at": None, "editable": True}
