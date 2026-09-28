"""永久放行规则写入本地层配置（docs/ch06 T7 / F8）。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from mewcode.llm import ToolCall

from .rule import Rule, escape_glob
from .settings import Settings, SettingsError, extract_target, friendly_name, load_settings


def rule_for(call: ToolCall, root: str) -> tuple[Rule, str, bool]:
    """据调用生成精确 allow 规则。返回 (Rule, YAML 规则串, 是否成功)。"""
    target, is_file, ok = extract_target(call)
    friendly = friendly_name(call.name)
    if not ok or not target:
        return Rule("", "", False), "", False
    if is_file:
        # 文件类用项目相对路径（slash 形式）
        rel = os.path.relpath(target, root).replace("\\", "/")
        pattern = escape_glob(rel)
    else:
        pattern = escape_glob(target)
    rule = Rule(tool=friendly, pattern=pattern, allow=True)
    return rule, f"{friendly}({pattern})", True


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
