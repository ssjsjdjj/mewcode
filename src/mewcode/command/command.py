"""命令元数据与类型定义（docs/ch10 T1）。

Kind 区分三类执行语义；Command 承载注册元数据；Handler 是 handler 的函数签名，
仅依赖 UI Protocol（前向引用字符串），不绑定具体 TUI 实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from mewcode.command.ui import UI

# UI 协议在 ui.py 声明（T4）；此处用字符串前向引用让类型注解合法
Handler = Callable[["UI"], Awaitable[None]]


class Kind(Enum):
    """命令执行类型（F8-F11）。"""

    LOCAL = "local"  # 纯本地：只打印、不改 App、不进 history
    UI = "ui"  # 影响界面：改 App 状态、不进 history
    PROMPT = "prompt"  # 提示词：注入 user 消息 + 触发回合、进 history


@dataclass(slots=True)
class Command:
    """一条注册命令的完整元数据（F1）。"""

    name: str  # 不带 "/" 前缀、全小写、全局唯一
    description: str  # 一句话，用于 /help 与补全菜单
    kind: Kind
    handler: Handler
    aliases: list[str] = field(default_factory=list)  # 不带 "/"、全小写、全局唯一（含 name）
    hidden: bool = False  # /help 与补全菜单不显示，但 dispatcher 仍可命中
    is_skill: bool = False  # 由 Skill 注册而来，reload 时按此标记整体清除（docs/ch11 T23）
