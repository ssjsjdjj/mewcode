"""slash 命令系统（docs/ch10）：注册中心、解析、UI 抽象层与 12 条内置命令。

包不依赖 textual，纯领域逻辑；TUI 侧通过实现 command.UI Protocol 接入。
"""

from mewcode.command.builtins import register_builtins
from mewcode.command.command import Command, Handler, Kind
from mewcode.command.dispatch import parse
from mewcode.command.registry import Registry
from mewcode.command.ui import NopUI, UI

__all__ = [
    "Command",
    "Handler",
    "Kind",
    "NopUI",
    "Registry",
    "UI",
    "parse",
    "register_builtins",
]
