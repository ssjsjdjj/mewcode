"""条件求值：payload 字段路径取值 + 原子条件组合（docs/ch12 T7，F13/F14/F15）。

字段路径用 `.` 分隔嵌套（`tool_input.path`）。路径不存在一律**按空字符串处理**
而不是报错——hook 不该因为某事件没带某字段就崩，条件不命中即可。

取值统一转成字符串再交给匹配器：bool / int / float 用 `str()`（`True` → `"True"`，
与 JSON 序列化一致，方便用户脚本 grep）；嵌套对象转 `json.dumps(sort_keys=True)`。
"""

from __future__ import annotations

import json
from typing import Any

from .rule import AtomCondition, CombineMode, Condition, Payload


def get_by_path(payload: Payload, path: str) -> str:
    """按 `.` 分隔取嵌套字段，转成字符串；中途缺失或类型不符返回空串。"""
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
        if current is None:
            return ""
    return _as_text(current)


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):  # 必须在 int 之前判——bool 是 int 的子类
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def eval_atom(atom: AtomCondition, payload: Payload) -> bool:
    return atom.matcher.match(get_by_path(payload, atom.field))


def eval_condition(condition: Condition | None, payload: Payload) -> bool:
    """条件求值；`None` 视为无条件触发（F11）。"""
    if condition is None:
        return True
    if condition.mode is CombineMode.ALL_OF:
        return all(eval_atom(a, payload) for a in condition.atoms)
    return any(eval_atom(a, payload) for a in condition.atoms)
