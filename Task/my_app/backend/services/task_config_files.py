# -*- coding: utf-8 -*-
"""通用任务配置文件管理（Settings「任务配置」页签 → 配置文件管理）

把散落在服务实现里的配置（时间范围 / 指标模板 / 网元列表 / URL 等）外置为
独立 JSON 文件，页面可查看/编辑/导入导出。注册式：
    register_config(ConfigResource(task_id, path, defaults, schema, ...))

schema 同时驱动：后端校验 + 前端表单渲染。类型：
  int / str / bool / object(fields) / table(fields, min_items, max_items)
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REGISTRY: dict[str, "ConfigResource"] = {}


def load_json_config(path) -> dict | None:
    """通用：读取外部化配置 JSON；不存在/损坏返回 None（调用方回退内置默认）。

    供各任务服务模块复用（页面可编辑的 xxx_config.json 加载入口）。
    """
    p = Path(path)
    try:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
    except Exception as e:
        print(f"[CONFIG] 读取 {p.name} 失败，回退默认: {e}")
    return None


def serialize_query_configs(configs: dict) -> list:
    """服务内存的 {key: cfg} 查询配置 → 配置文件用的列表（items/positions 转逗号串）。

    uilocations 等复杂字段原样保留（JSON 序列化），仅 items/positions 转为逗号串便于编辑。
    """
    out = []
    for key, cfg in configs.items():
        d = dict(cfg)
        d.setdefault("key", key)
        for f in ("items",):
            if isinstance(d.get(f), (list, tuple)):
                d[f] = ",".join(str(x) for x in d[f])
        for f in ("itemsposition", "itemsposition1", "itempositionbusiness"):
            if isinstance(d.get(f), (list, tuple)):
                d[f] = ",".join(str(x) for x in d[f])
        out.append(d)
    return out


def normalize_query_configs(query_configs: list) -> dict:
    """配置文件里的 query_configs（items/positions 逗号串）→ 按 key 的服务内存 dict。

    除 items/positions 外其它字段（uilocations/reslocation/chartsetting/table_name 等）原样透传。
    """
    out = {}
    for row in query_configs:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("tech") or "").strip()
        if not key:
            continue
        d = dict(row)

        def _split(s, cast=str):
            return [cast(x.strip()) for x in str(s or "").split(",") if x.strip()]

        if isinstance(d.get("items"), str):
            d["items"] = _split(d["items"])
        for f in ("itemsposition", "itemsposition1", "itempositionbusiness"):
            if isinstance(d.get(f), str) and d[f].strip():
                d[f] = _split(d[f], int)
        out[key] = d
    return out


def _atomic_write_json(path, data):
    """原子写 JSON（临时文件 + os.replace，避免半写损坏）。"""
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


class ConfigResource:
    def __init__(self, task_id: str, path: str | os.PathLike,
                 defaults: dict | None = None, schema: dict | None = None,
                 description: str = "", description_en: str = "",
                 defaults_factory=None):
        self.task_id = task_id
        self.path = Path(path)
        self.defaults = copy.deepcopy(defaults or {})
        self.schema = schema or {}
        self.description = description
        self.description_en = description_en
        # 懒加载默认值工厂：文件不存在时从服务源码提取真实配置（避免手工抄写大段模板）
        self.defaults_factory = defaults_factory

    def load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                print(f"[CONFIG] {self.task_id} 读取 {self.path.name} 失败，回退默认: {e}")
        if self.defaults_factory is not None:
            try:
                return self.defaults_factory()
            except Exception as e:
                print(f"[CONFIG] {self.task_id} defaults_factory 失败: {e}")
        return copy.deepcopy(self.defaults)

    def save(self, data: dict):
        _atomic_write_json(self.path, data)

    def meta(self) -> dict:
        exists = self.path.exists()
        return {
            "task_id": self.task_id,
            "description": self.description,
            "description_en": self.description_en,
            "path": str(self.path),
            "exists": exists,
            "mtime": (self.path.stat().st_mtime if exists else None),
            "schema": self.schema,
        }


def register_config(resource: ConfigResource):
    _REGISTRY[resource.task_id] = resource


def get_resource(task_id: str) -> ConfigResource | None:
    return _REGISTRY.get(task_id)


def list_configs() -> list[dict]:
    return [r.meta() for r in _REGISTRY.values()]


def get_config(task_id: str) -> dict | None:
    r = get_resource(task_id)
    return None if r is None else r.load()


# ========== schema 校验 ==========

def _validate_value(key: str, schema: dict, value, errors: list, path: str = ""):
    t = schema.get("type", "str")
    label = schema.get("label_zh", key)
    where = f"{path}{key}"
    if t == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{where}: {label} 必须为整数")
            return
        if "min" in schema and value < schema["min"]:
            errors.append(f"{where}: {label} 不能小于 {schema['min']}")
        if "max" in schema and value > schema["max"]:
            errors.append(f"{where}: {label} 不能大于 {schema['max']}")
    elif t == "str":
        if not isinstance(value, str):
            errors.append(f"{where}: {label} 必须为字符串")
        elif schema.get("required") and not value.strip():
            errors.append(f"{where}: {label} 不能为空")
    elif t == "bool":
        if not isinstance(value, bool):
            errors.append(f"{where}: {label} 必须为布尔值")
    elif t == "json":
        if not isinstance(value, (dict, list)):
            errors.append(f"{where}: {label} 必须为 JSON 对象或数组")
    elif t == "object":
        if not isinstance(value, dict):
            errors.append(f"{where}: {label} 必须为对象")
            return
        for k, sub in (schema.get("fields") or {}).items():
            if k in value:
                _validate_value(k, sub, value[k], errors, path=f"{where}.")
    elif t == "table":
        if not isinstance(value, list):
            errors.append(f"{where}: {label} 必须为数组")
            return
        if "min_items" in schema and len(value) < schema["min_items"]:
            errors.append(f"{where}: {label} 至少 {schema['min_items']} 项")
        if "max_items" in schema and len(value) > schema["max_items"]:
            errors.append(f"{where}: {label} 最多 {schema['max_items']} 项")
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{where}[{i}]: 必须为对象")
                continue
            for k, sub in (schema.get("fields") or {}).items():
                if k in item:
                    _validate_value(k, sub, item[k], errors, path=f"{where}[{i}].")
                elif sub.get("required"):
                    errors.append(f"{where}[{i}].{k}: 必填")


def _merge_edited(schema: dict, old: dict, edited: dict) -> dict:
    """按 schema 把编辑值合并进旧配置；非 schema 键（内部字段）原样保留。"""
    result = copy.deepcopy(old)
    for key, sub in schema.items():
        if key in edited:
            if sub.get("type") == "object":
                obj = copy.deepcopy(result.get(key) if isinstance(result.get(key), dict) else {})
                for k2 in (sub.get("fields") or {}):
                    if k2 in edited[key]:
                        obj[k2] = edited[key][k2]
                result[key] = obj
            elif sub.get("type") == "table":
                result[key] = copy.deepcopy(edited[key])
            else:
                # 标量 / json（dict/list）/ object 整体赋值
                result[key] = edited[key]
    return result


def update_config(task_id: str, values: dict) -> dict:
    """按 schema 更新配置（只改 schema 内的键，内部字段保留）。"""
    r = get_resource(task_id)
    if r is None:
        return {"success": False, "error": f"任务 {task_id} 无配置文件管理"}
    if not isinstance(values, dict):
        return {"success": False, "error": "values 必须是对象"}
    errors: list[str] = []
    for key, sub in r.schema.items():
        if key in values:
            _validate_value(key, sub, values[key], errors)
    if errors:
        return {"success": False, "errors": errors[:8], "error": "; ".join(errors[:4])}
    current = r.load()
    merged = _merge_edited(r.schema, current, values)
    r.save(merged)
    return {"success": True, "task_id": task_id}


def export_config(task_id: str) -> dict | None:
    r = get_resource(task_id)
    return None if r is None else r.load()


def import_config(task_id: str, config) -> dict:
    """整体导入（替换）。校验 schema 键；非 schema 键保留。"""
    r = get_resource(task_id)
    if r is None:
        return {"success": False, "error": f"任务 {task_id} 无配置文件管理"}
    if not isinstance(config, dict):
        return {"success": False, "error": "config 必须是对象"}
    errors: list[str] = []
    for key, sub in r.schema.items():
        if key in config:
            _validate_value(key, sub, config[key], errors)
    if errors:
        return {"success": False, "applied": [], "errors": [{"index": i, "error": e} for i, e in enumerate(errors)]}
    r.save(copy.deepcopy(config))
    return {"success": True, "applied": [task_id], "errors": []}
