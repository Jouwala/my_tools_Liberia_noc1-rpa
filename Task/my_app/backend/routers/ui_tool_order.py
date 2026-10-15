# -*- coding: utf-8 -*-
"""ui_tool_order.py - eFlow Q&A 工具块顺序配置（**全局共享**）
=============================================================
背景：`?page=eflow_qa` 页面上 6 个工具块可拖拽 `⋮⋮` 改顺序。此前顺序**只存浏览器
      localStorage**，于是「A 排出满意的顺序，B 打开还是老样子」——同一套系统不该
      各人一套默认。现在把「全局默认顺序」存到**服务端**（所有人读同一份），个人在
      本地拖拽仍然只改自己（localStorage），点「保存为默认顺序」才改这份全局默认。

与 `ui_config.py`（侧栏菜单结构）同构，遵循同一套约定：
- 结构存服务端，任意人可读；**只允许本机（或持 X-API-Token）修改**（require_protected），
  避免局域网里任何人误点把大家的默认顺序弄乱。
- 持久化：backend/data/ui_tool_order.json（原子替换写，避免半个文件）。

- GET    /api/ui/tool-order   任意人可读；返回 {keys, updated_at, editable}
- PUT    /api/ui/tool-order   仅本机可写（require_protected）；整体替换
- DELETE /api/ui/tool-order   仅本机可写；删除配置（前端回落代码内置默认）

注意：`VALID_TOOL_KEYS` 必须与前端 `frontend/src/pages/EflowQa.tsx` 的
      `DEFAULT_TOOL_BLOCKS` 保持一致（两处注释互指，是本功能的唯一改动点）。
      代码日后新增第 7 个工具块时，服务端存的旧顺序会缺该键，前端
      `mergeToolOrder` 会把缺的块按内置顺序补到末尾（不丢块）。
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
CONFIG_PATH = os.path.join(BACKEND_DIR, "data", "ui_tool_order.json")

# eFlow Q&A 页面的 6 个工具块 key（与前端 DEFAULT_TOOL_BLOCKS 一一对应）。
# 校验用 frozenset：未知 key / 重复 / 长度不符一律拒绝，不做「猜」的兜底。
VALID_TOOL_KEYS = frozenset({
    "knowledge-search",        # 知识库检索
    "tt-quick-analysis",       # TT 快速分析
    "tt-batch-check",          # TT 批量级别核查
    "wo-close",                # WO 清理
    "tt-postmortem",           # TT 复盘
    "ran-ume-alarm-analysis",  # RAN UME 告警分析
})
TOOL_COUNT = len(VALID_TOOL_KEYS)


# --------------------------- 读写 ---------------------------
def _read_order() -> Optional[dict]:
    """读取已保存的全局顺序；文件不存在/损坏返回 None（前端回落内置默认）。"""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ui-config] 读取工具块顺序失败（按未配置处理）: {e}")
        return None


def _write_order(order: dict) -> None:
    """原子替换写入（先写同目录临时文件，再 replace）。"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="ui_tool_order_", suffix=".tmp",
                               dir=os.path.dirname(CONFIG_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
        atomic_replace_file(tmp, CONFIG_PATH)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _normalize_order(raw: Any) -> dict:
    """校验 + 归一化；非法结构直接 400，不做「猜」的兜底。"""
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="keys 必须是数组")
    if len(raw) != TOOL_COUNT:
        raise HTTPException(status_code=400, detail=f"keys 必须恰好 {TOOL_COUNT} 项")
    keys: list = []
    seen: set = set()
    for k in raw:
        if not isinstance(k, str) or not k.strip():
            raise HTTPException(status_code=400, detail="keys 含非法项")
        s = k.strip()
        if s not in VALID_TOOL_KEYS:
            raise HTTPException(status_code=400, detail=f"未知工具块 key: {s}")
        if s in seen:
            raise HTTPException(status_code=400, detail=f"工具块 key 重复: {s}")
        seen.add(s)
        keys.append(s)
    return {"v": 1, "keys": keys}


# --------------------------- 路由 ---------------------------
@router.get("/tool-order")
def get_tool_order(request: Request):
    """读取全局工具块顺序。任何访问者都能读（默认顺序必须人人一致）。"""
    order = _read_order()
    updated_at = None
    if order and os.path.exists(CONFIG_PATH):
        try:
            updated_at = datetime.fromtimestamp(os.path.getmtime(CONFIG_PATH)).isoformat(timespec="seconds")
        except OSError:
            updated_at = None
    return {
        "keys": (order or {}).get("keys"),
        "updated_at": updated_at,
        # 前端据此决定是否显示「保存为默认顺序」入口：非本机只读
        "editable": is_privileged(request),
    }


@router.put("/tool-order", dependencies=[Depends(require_protected)])
def put_tool_order(payload: dict):
    """保存全局工具块顺序（仅本机 / 持令牌）。整体替换，返回落盘后的结构。"""
    order = _normalize_order((payload or {}).get("keys"))
    _write_order(order)
    logger.info("[ui-config] 工具块顺序已更新: %s", ",".join(order["keys"]))
    return {
        "keys": order["keys"],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "editable": True,
    }


@router.delete("/tool-order", dependencies=[Depends(require_protected)])
def delete_tool_order():
    """删除全局工具块顺序（仅本机 / 持令牌），前端回落代码内置默认。"""
    try:
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
    logger.info("[ui-config] 工具块顺序已重置为默认")
    return {"keys": None, "updated_at": None, "editable": True}
