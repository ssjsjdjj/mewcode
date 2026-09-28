"""权限配置加载与工具映射（docs/ch06 T5 / F3/F4）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mewcode.llm import ToolCall

from . import Category
from .rule import RuleSet, parse_rule


class SettingsError(Exception):
    """配置解析错误；调用方降级跳过该文件（N5）。"""


@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Settings:
    default_mode: str = ""
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)


def load_settings(path: str) -> Settings:
    """读单个权限配置文件；文件不存在返回空 Settings，解析失败抛 SettingsError。"""
    p = Path(path)
    if not p.is_file():
        return Settings()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        raise SettingsError(f"权限配置解析失败: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        return Settings()
    default_mode = raw.get("default_mode", "")
    perms = raw.get("permissions", {})
    block = PermissionsBlock()
    if isinstance(perms, dict):
        allow = perms.get("allow", [])
        deny = perms.get("deny", [])
        if isinstance(allow, list):
            block.allow = [str(x) for x in allow]
        if isinstance(deny, list):
            block.deny = [str(x) for x in deny]
    return Settings(default_mode=str(default_mode), permissions=block)


def to_rule_set(settings: Settings) -> RuleSet:
    """把 Settings 转成 RuleSet；非法规则条目跳过。"""
    rs = RuleSet()
    for s in settings.permissions.allow:
        rule, ok = parse_rule(s)
        if ok:
            rule.allow = True
            rs.allow.append(rule)
    for s in settings.permissions.deny:
        rule, ok = parse_rule(s)
        if ok:
            rule.allow = False
            rs.deny.append(rule)
    return rs


_FRIENDLY = {
    "bash": "Bash",
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "glob": "Glob",
    "grep": "Grep",
}


def friendly_name(internal: str) -> str:
    """内部工具名 → 友好名；未知原样返回。"""
    return _FRIENDLY.get(internal, internal)


def categorize(internal: str, read_only: bool) -> Category:
    """工具类别：read_only 优先归只读；否则 write/edit 归写、其余（含 bash/未知）归执行。"""
    if read_only:
        return Category.READ
    if internal in ("write_file", "edit_file"):
        return Category.WRITE
    return Category.EXEC  # bash、未知工具（N7 最严）


def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    """提取判定目标。返回 (target, is_file, ok)；解析失败 ok=False。

    - read_file/write_file/edit_file：path（is_file=True）
    - glob/grep：path（搜索根目录，空→"."，is_file=True）
    - bash：command（is_file=False）
    - 未知工具 → ("", False, False)
    """
    name = call.name
    is_file_tool = name in ("read_file", "write_file", "edit_file", "glob", "grep")
    try:
        if isinstance(call.input, str):
            data = json.loads(call.input) if call.input.strip() else {}
        elif isinstance(call.input, dict):
            data = call.input
        else:
            return "", is_file_tool, False
    except (json.JSONDecodeError, TypeError):
        # 解析失败：文件工具仍按 is_file=True 处理 → 沙箱层判 Deny（安全默认）
        return "", is_file_tool, False

    if name in ("read_file", "write_file", "edit_file"):
        path = data.get("path")
        if not isinstance(path, str) or not path:
            return "", True, False
        return path, True, True
    if name in ("glob", "grep"):
        path = data.get("path")
        if path is None or path == "":
            return ".", True, True
        if not isinstance(path, str):
            return "", True, False
        return path, True, True
    if name == "bash":
        command = data.get("command")
        if not isinstance(command, str):
            return "", False, False
        return command, False, True
    # 未知工具
    return "", False, False
