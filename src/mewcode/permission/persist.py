"""永久放行规则写入本地层配置（docs/ch06 T7 / F8）。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from mewcode.llm import ToolCall

from .rule import Rule, escape_glob, parse_rule
from .settings import Settings, SettingsError, extract_target, friendly_name, load_settings


def rule_for(call: ToolCall, root: str) -> tuple[Rule | None, str, bool]:
    """据调用生成精确 allow 规则。返回 (Rule, YAML 规则串, 是否成功)。

    规则串用 `escape_glob` 转义成字面 glob（docs/ch12 T3 的既定做法，不改持久化
    格式）；再交给 `parse_rule` 构造内存 Rule——两边走同一个解析器，磁盘与内存
    不可能对不上（`is_command` 之类由工具名自动判定，不需要在这里重复判断）。
    """
    target, is_file, ok = extract_target(call)
    friendly = friendly_name(call.name)
    if not ok or not target:
        return None, "", False
    if is_file:
        # 文件类用项目相对路径（slash 形式）
        rel = os.path.relpath(target, root).replace("\\", "/")
        pattern = escape_glob(rel)
    else:
        pattern = escape_glob(target)

    rule_str = f"{friendly}({pattern})"
    rule, _err = parse_rule(rule_str)
    if rule is None:
        return None, rule_str, False
    rule.allow = True
    return rule, rule_str, True


def persist_local_allow(engine: object, call: ToolCall) -> None:
    """把精确 allow 规则写入本地层配置文件并同步内存（异常向上抛，调用方捕获）。"""
    rule, rule_str, ok = rule_for(call, engine.root)
    if not ok:
        raise ValueError(f"无法为调用生成精确规则: {call.name}")

    path = Path(engine.local_path)
    try:
        settings = load_settings(str(path))
    except SettingsError:
        settings = Settings()

    if rule_str in settings.permissions.allow:
        return  # 幂等：已存在
    settings.permissions.allow.append(rule_str)

    payload = {
        "default_mode": settings.default_mode,
        "permissions": {"allow": settings.permissions.allow, "deny": settings.permissions.deny},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    # 同步内存规则集
    engine.local.allow.append(rule)
