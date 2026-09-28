"""系统提示工程化（docs/ch05）：模块化装配、环境信息、补充消息与启动 banner。

对外产出三类文本：
- 稳定系统提示（可缓存）：assemble_system(fixed_modules() + optional_modules())
- 环境信息段（不缓存）：Environment.render()
- system-reminder 包裹的补充指令：system_reminder / plan_reminder
"""

from __future__ import annotations

from .environment import Environment, gather_environment
from .modules import Module, fixed_modules, optional_modules
from .reminder import EXECUTE_DIRECTIVE, plan_reminder, system_reminder

__all__ = [
    "Module",
    "fixed_modules",
    "optional_modules",
    "assemble_system",
    "build_system_prompt",
    "Environment",
    "gather_environment",
    "system_reminder",
    "plan_reminder",
    "EXECUTE_DIRECTIVE",
    "CAT_BANNER",
    "READY_HINT",
    "render_banner",
]


def assemble_system(mods: list[Module]) -> str:
    """按优先级升序拼接模块，跳过空 content，以空行分隔。"""
    ordered = sorted(mods, key=lambda m: m.priority)
    blocks = [m.content for m in ordered if m.content.strip()]
    return "\n\n".join(blocks)


def build_system_prompt(instructions: str = "", memory: str = "") -> str:
    """完整稳定系统提示（固定模块 + 可选槽位；空槽自动跳过，与 ch08 一致）。

    ch09 起 custom-instructions（priority 80）填入指令文本、long-term-memory
    （priority 100）填入记忆索引（docs/ch09 F7/F43）。
    """
    return assemble_system(fixed_modules() + optional_modules(instructions, memory))


CAT_BANNER = r"""    /\_/\
   ( o.o )  mewcode
    > ^ <"""

READY_HINT = "已就绪,输入 /help 查看可用命令。"  # N7：不硬编码命令清单，只引导 /help


def render_banner(version: str, cwd: str) -> str:
    """拼出启动横幅：猫 + MewCode vX + cwd + 就绪提示行。"""
    return f"    /\\_/\\\n   ( o.o )  mewcode v{version}\n    > ^ <\n\n  {cwd}\n\n{READY_HINT}\n"
