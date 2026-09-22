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
结构：{"v": 1, "savedAt": "2026-09-17T17:30:00", "items": [ <看板对象> … ],
       "subGroups": {"BO View": [ {"id": "wireless", "zh": "…", "en": "…"}, … ]},
       "order": {"FO View": [19, 13, …]},
       "groups": [ {"id": "CXO View", "zh": "…", "en": "…", "subZh": "…", "style": "spotlight"} ]}
      文件不存在 = 从未保存过，GET 返回 catalog=null，前端用 data.js 内置目录。
      「内置目录」与「服务端目录」的关系 = uniplam 的 INITIAL_DASHBOARDS 与
      portal-default.json：前者是出厂值，后者是运行时覆盖，DELETE 即可回退。

一级分组（2026-09-22 加）：分组名以前只在前端 data.js + 各机 localStorage
（msportal.renames.v1 / .groups.v1），改一次只在这台电脑生效。现在随目录一起落盘，
**数组顺序即展示顺序、id 不可改**（item.groups / order / subGroups 全都按 id 引用，
改名只动 zh/en 就不会打断引用）。语义与 subGroups 一致：键不存在 = 用内置分组。

子分组（2026-09-19 加）：BO View 正文里的「Radio, Power & Field Dispatch /
Core Network / IP Bearer」原来写死在前端常量 BO_SUBS + i18n 文案里，只能在代码里改。
现在改为随目录一起落盘，**所有分组都可以有自己的二级子分组**（不再限于 BO View）：
- `subGroups` = 父分组 id → 该父分组下的子分组定义，**数组顺序即展示顺序**；
- 看板归属用 item.subOf = {父分组 id: 子分组 id}，**按分组分别记录**。
  为什么不是单个 boSub：一个看板可以同时属于多个分组（实测 no=11/12/13/18/36
  同时挂在 FO View + FLM View），单值会导致「在 A 分组下改了子分组，B 分组里的
  同一张卡也跟着变」的串改。`boSub` 保留为**兼容字段**（旧客户端/旧数据仍写它），
  前端读取时按 subOf[父分组] → boSub 的顺序回落；
- subOf 里的值指向不存在的子分组 id 时，前端落到「其他系统」兜底桶
  （不报错、不丢看板）；
- 键**不存在** = 前端用内置的子分组（出厂值）；
  键**存在但数组为空** = 显式「该分组没有子分组」—— 两者语义不同，
  所以这里对空数组照样落盘，绝不因为「空」就把键删掉（删掉会悄悄变回出厂值）。

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
# ---- 子分组（二级分组）上限 ----
MAX_SUB_PARENTS = 60          # 允许定义子分组的父分组数
MAX_SUBS_PER_PARENT = 24      # 单个父分组下的子分组数
MAX_SUB_ID_LEN = 40           # 子分组 id（= item.boSub 的取值）
MAX_SUB_LABEL_LEN = 64        # 子分组中/英文显示名
# ---- 拖拽排序（catalog.order）上限 ----
MAX_ORDER_PARENTS = 60        # 允许自定义顺序的父分组数（与 MAX_SUB_PARENTS 同量级）
MAX_ORDER_ITEMS = 500         # 单个分组内的排序条目数（= MAX_ITEMS，防重复写爆）
# ---- 一级分组定义（catalog.groups）上限 ----
MAX_GROUPS = 60               # 一级分组数（内置 9 个，留足冗余）
MAX_GROUP_ID_LEN = 64         # 与 _str_list 里 item.groups 的取值同宽，两边必须一致
MAX_GROUP_LABEL_LEN = 64      # 分组中/英文显示名
MAX_GROUP_SUB_LEN = 200       # 分组副标题（面板头部那一行说明）
MAX_GROUP_STYLE_LEN = 20      # 版式名，未知值前端按默认版式渲染，不做枚举校验

PLATFORMS = {"myapp", "finebi", "external"}
STATUSES = {"online", "beta"}
DEFAULT_ICON = "dashboard"

# 看板对象允许落盘的字段白名单。**必须白名单**：请求体来自浏览器，
# 不做过滤的话任何字段都会被原样存下来，再被前端 `esc()` 之外的地方读到。
# `boSub` = 该看板在父分组内的子分组归属，取值必须命中 catalog.subGroups[父分组][].id。
_ITEM_FIELDS = (
    "no", "groups", "titleZh", "titleEn", "descZh", "descEn",
    "platform", "url", "tags", "owner", "ownerEn", "dept", "deptEn",
    "status", "freq", "clicks", "icon", "custom", "qc", "boSub", "subOf",
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
    # 按分组分别记录的二级归属：{"<父分组 id>": "<子分组 id>"}。
    # 为什么需要它：一个看板可以同时属于多个分组（实测 no=11/12/13/18/36 同时挂在
    # FO View + FLM View），而 boSub 只有一个值 —— 那种「A 分组下改了子分组、
    # B 分组里的同一张卡也跟着变」的串改就是它引起的。subOf 让每个分组各存一份。
    sub_of = _normalize_sub_of(raw.get("subOf"))
    if sub_of:
        item["subOf"] = sub_of
    # 自建看板标记：前端据此允许删除内置目录里不存在的条目
    if raw.get("custom"):
        item["custom"] = True
    return item


def _normalize_sub_of(raw: Any) -> dict:
    """归一化「按分组记录的二级归属」：{父分组 id: 子分组 id}。

    与 _normalize_sub_groups 同样宽容：值不是字符串 / 为空 → 丢掉该键，
    不让整份目录因为一条归属写错而保存失败。
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for gid, sid in raw.items():
        parent = _clip(gid, MAX_GROUP_LEN)
        sub = _clip(sid, MAX_SUB_ID_LEN)
        if parent and sub:
            out[parent] = sub
    return out


def _normalize_order(raw: Any) -> dict:
    """归一化「拖拽排序」：{父分组 id: [看板编号, …]}，数组顺序即展示顺序。

    为什么是**按分组**存、而不是给每个看板加一个 order 数字：
    一个看板可以同时挂在多个分组（实测 no=11/12/13/18/36 同时属于 FO View +
    FLM View）。若用「看板级 order」，在 A 分组里把它拖到第 1 位，B 分组里它也会
    跳到第 1 位 —— 正是 subOf 当初要解决的那类串改。按分组存一份顺序表就没有这个问题。

    为什么不用 item.clicks 排序：clicks 同样是看板级、且它是「初始排序权重」，
    被拖动过的分组要以拖动结果为准，两者必须能并存。

    宽容度与 subGroups 一致：值不是数组 / 条目不是数字 → 丢掉该条，不让整份目录
    保存失败；但**结构**错了仍然 400（不是对象），否则现场表现为「提示保存成功、
    顺序却没变」，最难查。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="catalog.order 必须是对象")
    if len(raw) > MAX_ORDER_PARENTS:
        raise HTTPException(status_code=400, detail=f"排序的父分组数超过上限 {MAX_ORDER_PARENTS}")

    out: dict = {}
    for gid, nos in raw.items():
        parent = _clip(gid, MAX_GROUP_LEN)
        if not parent:
            continue
        if not isinstance(nos, list):
            raise HTTPException(status_code=400, detail=f"catalog.order[{parent}] 必须是数组")
        if len(nos) > MAX_ORDER_ITEMS:
            raise HTTPException(
                status_code=400,
                detail=f"catalog.order[{parent}] 条目数超过上限 {MAX_ORDER_ITEMS}",
            )
        seq: list = []
        for x in nos:
            n = _to_int(x, -1)
            # 去重：重复编号会让 indexOf 取到第一个，后面的位置永远排不上
            if n >= 0 and n not in seq:
                seq.append(n)
        # 空数组照样落盘 —— 与 subGroups 同一语义：
        # 键存在但为空 = 显式「这个分组没有自定义顺序」（前端回落到初始排序权重），
        # 键不存在 = 从未配过。两者对前端的含义不同，不能合并。
        out[parent] = seq
    return out


def _normalize_sub_groups(raw: Any) -> dict:
    """归一化子分组定义：{父分组 id: [{"id","zh","en"}, …]}。

    宽容度刻意与 items 不同：子分组是展示层的组织方式，缺 id / 缺标签的条目
    丢弃即可，不该让整份目录（46+ 个看板）因为一条子分组写错而保存失败。
    但**结构**错了仍然 400（不是对象 / 值不是数组 / 条目不是对象）——
    否则前端传错结构会被静默吞掉，现场表现为「提示保存成功，但子分组没生效」，
    这种最难查。

    空数组照样保留（见模块头说明：键存在但为空 ≠ 键不存在）。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="catalog.subGroups 必须是对象")
    if len(raw) > MAX_SUB_PARENTS:
        raise HTTPException(status_code=400, detail=f"子分组的父分组数超过上限 {MAX_SUB_PARENTS}")

    out: dict = {}
    for gid, subs in raw.items():
        parent = _clip(gid, MAX_GROUP_LEN)
        if not parent:
            continue
        if not isinstance(subs, list):
            raise HTTPException(status_code=400, detail=f"catalog.subGroups[{parent}] 必须是数组")
        if len(subs) > MAX_SUBS_PER_PARENT:
            raise HTTPException(
                status_code=400,
                detail=f"catalog.subGroups[{parent}] 的子分组数超过上限 {MAX_SUBS_PER_PARENT}",
            )
        cleaned: list = []
        seen: set = set()
        for s in subs:
            if not isinstance(s, dict):
                raise HTTPException(
                    status_code=400, detail=f"catalog.subGroups[{parent}] 的条目必须是对象"
                )
            sid = _clip(s.get("id"), MAX_SUB_ID_LEN)
            if not sid or sid in seen:      # 缺 id / 同父下重名 → 丢弃（保留第一条）
                continue
            seen.add(sid)
            cleaned.append({
                "id": sid,
                "zh": _clip(s.get("zh"), MAX_SUB_LABEL_LEN),
                "en": _clip(s.get("en"), MAX_SUB_LABEL_LEN),
            })
        out[parent] = cleaned
    return out


def _normalize_groups(raw: Any) -> list:
    """归一化一级分组定义：[{"id","zh","en","subZh","subEn","style"}, …]，数组顺序即展示顺序。

    为什么 2026-09-22 才加：分组名以前只写在前端 `data.js`（出厂值）+ 各机
    localStorage（`msportal.renames.v1` / `.groups.v1`），改一次只在这台电脑上生效 ——
    和 subGroups 当初一模一样，所以照抄它的语义：

    - 键**不存在**（或空数组）= 前端用内置 `data.js` 的分组；键存在且非空 = 以此为准；
    - **id 不可改**：`item.groups`、`order` 的键、`subGroups` 的键全都按 id 引用。
      改名只动 zh/en/subZh/subEn，id 保持原值，所以一处改名不会把三处引用打断；
      新增分组才产生新 id（缺 id 时用 en→zh 兜底，与前端 addGroup 的取 id 规则一致）。
    - 重复 id 丢弃保留第一条（前端去重过，这里只是兜底，不让整份目录保存失败）。
    - `style` 不做枚举校验：未知值前端按默认版式渲染，比 400 掉整次保存划算。
    - 删除分组是**前端**的责任：要把该 id 从每个 item.groups 里摘掉再 PUT。这里如果
      替前端「自动清理孤儿引用」，就会出现「以为只删了个名字，结果看板被移出分组」，
      所以后端只如实落盘，指向不存在分组的 id 由前端忽略（看板不会丢）。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="catalog.groups 必须是数组")
    if len(raw) > MAX_GROUPS:
        raise HTTPException(status_code=400, detail=f"一级分组数超过上限 {MAX_GROUPS}")

    out: list = []
    seen: set = set()
    for g in raw:
        if not isinstance(g, dict):
            raise HTTPException(status_code=400, detail="catalog.groups 的条目必须是对象")
        zh = _clip(g.get("zh"), MAX_GROUP_LABEL_LEN)
        en = _clip(g.get("en"), MAX_GROUP_LABEL_LEN)
        gid = _clip(g.get("id"), MAX_GROUP_ID_LEN) or en or zh
        if not gid or gid in seen:
            continue
        seen.add(gid)
        out.append({
            "id": gid,
            "zh": zh or gid,
            "en": en or gid,
            "subZh": _clip(g.get("subZh"), MAX_GROUP_SUB_LEN),
            "subEn": _clip(g.get("subEn"), MAX_GROUP_SUB_LEN),
            "style": _clip(g.get("style"), MAX_GROUP_STYLE_LEN),
        })
    return out


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

    catalog = {
        "v": 1,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }
    # 整张 subGroups 为空（前端从未配过 / 已全部删干净且无父分组键）时不落这个键，
    # 前端据此回落到内置的三个子分组；只要还有任何一个父分组键（哪怕是空数组）
    # 就原样落盘，避免「显式清空」被误判成「从未配置」。
    sub_groups = _normalize_sub_groups(raw.get("subGroups"))
    if sub_groups:
        catalog["subGroups"] = sub_groups
    # 拖拽排序（2026-09-19 加）：与 subGroups 同样只在非空时落键，
    # 前端据此回落到「初始排序权重（item.clicks）」。空字典不落键的理由同 subGroups。
    order = _normalize_order(raw.get("order"))
    if order:
        catalog["order"] = order
    # 一级分组定义（2026-09-22 加）：非空才落键，空数组与「从未配置」同样回落到内置 data.js
    # —— 这里刻意不像 subGroups 那样区分「显式清空」：把全部一级分组删光等于把门户清空，
    # 没有合理语义，前端也不该发出这种请求。
    groups = _normalize_groups(raw.get("groups"))
    if groups:
        catalog["groups"] = groups
    return catalog


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
