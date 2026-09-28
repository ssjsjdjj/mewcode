"""slash 命令系统（docs/ch10）：注册中心、解析、UI 抽象层与 12 条内置命令。

包不依赖 textual，纯领域逻辑；TUI 侧通过实现 command.UI Protocol 接入。
ch11 起还承载 Skill 的命令注册（`register_skills_as_commands`）。
"""

from mewcode.command.builtins import register_builtins
from mewcode.command.command import Command, Handler, Kind
from mewcode.command.dispatch import parse
from mewcode.command.registry import Registry
from mewcode.command.skills import (
    SkillRunner,
    register_skills_as_commands,
    remove_skill_commands,
)
from mewcode.command.ui import NopUI, SkillSummary, UI

__all__ = [
    "Command",
    "Handler",
    "Kind",
    "NopUI",
    "Registry",
    "SkillRunner",
    "SkillSummary",
    "UI",
    "parse",
    "register_builtins",
    "register_skills_as_commands",
    "remove_skill_commands",
]
