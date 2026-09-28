"""12 条内置命令一次性注册（docs/ch10 T8；ch11 T21 换成 12 条：删 /review、加 /skill）。

register_builtins 是唯一注入点：注册冲突在启动期立即暴露（F2/AC16）。
/help 的 handler 通过 make_help_handler 工厂捕获 reg，运行时从注册中心查询
（N7 单一信源）。
"""

from __future__ import annotations

from mewcode.command.builtin_local import (
    handle_memory,
    handle_permission,
    handle_session,
    handle_status,
    make_help_handler,
)
from mewcode.command.builtin_prompt import handle_do
from mewcode.command.builtin_skill import handle_skill
from mewcode.command.builtin_ui import (
    handle_clear,
    handle_compact,
    handle_exit,
    handle_plan,
    handle_resume,
)
from mewcode.command.command import Command, Kind
from mewcode.command.registry import Registry


def register_builtins(reg: Registry) -> None:
    """按字典序注册 12 条内置命令。

    ch11 起 `/review` 由同名内置 Skill 接管（fork 模式），改由
    `register_skills_as_commands` 注册；新增 `/skill` 列出已加载 Skill。
    """
    for cmd in (
        Command("clear", "清空当前会话，开启新会话", Kind.UI, handle_clear),
        Command("compact", "手动触发上下文压缩", Kind.UI, handle_compact),
        Command("do", "按计划开始执行", Kind.PROMPT, handle_do),
        Command("exit", "关闭 MewCode", Kind.UI, handle_exit),
        Command("help", "查看可用命令列表", Kind.LOCAL, make_help_handler(reg)),
        Command("memory", "列出已加载的记忆文件", Kind.LOCAL, handle_memory),
        Command("permission", "显示当前权限模式", Kind.LOCAL, handle_permission),
        Command("plan", "切换到计划模式（只读工具）", Kind.UI, handle_plan),
        Command("resume", "恢复历史会话", Kind.UI, handle_resume),
        Command("session", "显示当前会话信息", Kind.LOCAL, handle_session),
        Command("skill", "列出已加载的 Skill", Kind.LOCAL, handle_skill),
        Command("status", "显示模式/用量/工具等状态", Kind.LOCAL, handle_status),
    ):
        reg.register(cmd)
