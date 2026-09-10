# -*- coding: utf-8 -*-
"""ui_config.py - 界面配置 API（侧栏菜单结构，**全局共享**）
=========================================================
背景：目录/页面归属以前写死在前端 `App.tsx`，后来改成各浏览器 localStorage，
      结果是「A 改了目录名，B 看不到」——同一套系统不该有两套导航。
现在：结构存在**服务端**（所有人读同一份），但**只允许本机（或持 X-API-Token）修改**，
      避免局域网里任何人误改把大家的导航弄乱。

- GET  /api/ui/menu-layout   任意人可读；返回 {layout, updated_at, editable}
- PUT  /api/ui/menu-layout   仅本机可写（require_protected）；整体替换
- DELETE /api/ui/menu-layout 仅本机可写；删除配置（前端回落默认结构）

持久化：backend/data/ui_menu_layout.json（原子替换写，避免半个文件）。
结构（这里做类型/上限校验；前端 `App.tsx#normalizeMenuLayout` 还会再过滤一次
非法页面键、跨目录去重、并把代码里新增的页面并入最后一个目录）：
    {"v": 1,
     "groups": [{"key": "grp_sync", "label": "任务与报告", "hidden": true,
                 "items": ["sync", "email_reports"]}],
     "itemLabels": {"sync": "我的任务"}}

注意：`hidden` / `label` 只在**有值**时写入，所以显式 `false` 会被丢弃、
不会出现在返回结构里（前端把「无 hidden」等价为「显示」）。
目录顺序 = 数组顺序；页面顺序 = items 数组顺序（两者都由前端排序后整体 PUT）。
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

router = APIRouter(prefix="/api/ui", tags=["ui-config"])

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../my_app/backend
CONFIG_PATH = os.path.join(BACKEND_DIR, "data", "ui_menu_layout.json")

# 上限：防止误传巨大 JSON 把侧栏渲染拖垮（29 个页面，留足冗余）
MAX_GROUPS = 60
MAX_ITEMS_PER_GROUP = 200
MAX_KEY_LEN = 64
MAX_LABEL_LEN = 64
MAX_ITEM_LABELS = 200


# --------------------------- 读写 ---------------------------
def _read_layout() -> Optional[dict]:
    """读取已保存的布局；文件不存在/损坏返回 None（前端回落默认结构）。"""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ui-config] 读取菜单布局失败（按未配置处理）: {e}")
        return None


def _write_layout(layout: dict) -> None:
    """原子替换写入（先写同目录临时文件，再 replace）。"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="ui_menu_layout_", suffix=".tmp",
                               dir=os.path.dirname(CONFIG_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        atomic_replace_file(tmp, CONFIG_PATH)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _clean_str(v: Any, limit: int) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s[:limit] if s else None


def _normalize_layout(raw: Any) -> dict:
    """校验 + 归一化；非法结构直接 400，不做「猜」的兜底。"""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="layout 必须是对象")
    groups_raw = raw.get("groups")
    if not isinstance(groups_raw, list) or not groups_raw:
        raise HTTPException(status_code=400, detail="layout.groups 必须是非空数组")
    if len(groups_raw) > MAX_GROUPS:
        raise HTTPException(status_code=400, detail=f"目录数超过上限 {MAX_GROUPS}")

    groups: list = []
    seen_group_keys: set = set()
    for g in groups_raw:
        if not isinstance(g, dict):
            raise HTTPException(status_code=400, detail="目录必须是对象")
        key = _clean_str(g.get("key"), MAX_KEY_LEN)
        if not key:
            raise HTTPException(status_code=400, detail="目录缺少 key")
        if key in seen_group_keys:
            raise HTTPException(status_code=400, detail=f"目录 key 重复: {key}")
        seen_group_keys.add(key)
        items_raw = g.get("items")
        if not isinstance(items_raw, list):
            raise HTTPException(status_code=400, detail=f"目录 {key} 的 items 必须是数组")
        if len(items_raw) > MAX_ITEMS_PER_GROUP:
            raise HTTPException(status_code=400, detail=f"目录 {key} 页面数超过上限")
        items: list = []
        seen_items: set = set()
        for it in items_raw:
            if not isinstance(it, str) or not it.strip():
                raise HTTPException(status_code=400, detail=f"目录 {key} 含非法页面项")
            s = it.strip()[:MAX_KEY_LEN]
            if s in seen_items:
                raise HTTPException(status_code=400, detail=f"页面 {s} 在目录 {key} 内重复")
            seen_items.add(s)
            items.append(s)
        entry = {"key": key, "items": items}
        label = _clean_str(g.get("label"), MAX_LABEL_LEN)
        if label:
            entry["label"] = label
        if g.get("hidden") is True:
            entry["hidden"] = True
        groups.append(entry)

    item_labels_raw = raw.get("itemLabels")
    item_labels: dict = {}
    if isinstance(item_labels_raw, dict):
        for k, v in list(item_labels_raw.items())[:MAX_ITEM_LABELS]:
            kk = _clean_str(k, MAX_KEY_LEN)
            vv = _clean_str(v, MAX_LABEL_LEN)
            if kk and vv:
                item_labels[kk] = vv

    layout = {"v": 1, "groups": groups}
    if item_labels:
        layout["itemLabels"] = item_labels
    return layout


# --------------------------- 路由 ---------------------------
@router.get("/menu-layout")
def get_menu_layout(request: Request):
    """读取全局菜单布局。任何访问者都能读（导航必须人人一致）。"""
    layout = _read_layout()
    updated_at = None
    if layout and os.path.exists(CONFIG_PATH):
        try:
            updated_at = datetime.fromtimestamp(os.path.getmtime(CONFIG_PATH)).isoformat(timespec="seconds")
        except OSError:
            updated_at = None
    return {
        "layout": layout,
        "updated_at": updated_at,
        # 前端据此决定是否显示「自定义菜单」入口：非本机只读
        "editable": is_privileged(request),
    }


@router.put("/menu-layout", dependencies=[Depends(require_protected)])
def put_menu_layout(payload: dict):
    """保存全局菜单布局（仅本机 / 持令牌）。整体替换，返回落盘后的结构。"""
    layout = _normalize_layout((payload or {}).get("layout"))
    _write_layout(layout)
    logger.info(
        "[ui-config] 菜单布局已更新: %d 个目录 / %d 个页面（含隐藏目录 %d）",
        len(layout["groups"]),
        sum(len(g["items"]) for g in layout["groups"]),
        sum(1 for g in layout["groups"] if g.get("hidden")),
    )
    return {
        "layout": layout,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "editable": True,
    }


@router.delete("/menu-layout", dependencies=[Depends(require_protected)])
def delete_menu_layout():
    """删除全局菜单布局（仅本机 / 持令牌），前端回落内置默认结构。"""
    try:
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
    logger.info("[ui-config] 菜单布局已重置为默认")
    return {"layout": None, "updated_at": None, "editable": True}
