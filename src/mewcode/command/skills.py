"""把 Catalog 中的 Skill 注册成 Slash 命令（docs/ch11 T23，F18/F19）。

每个 Skill 注册一条 `Kind.PROMPT` 命令，名字即 Skill 名，描述末尾加 `[skill]`
标记。`is_skill=True` 让 `remove_skill_commands` 能在 reload 后整体清掉旧命令。

与内置命令同名/撞别名的 Skill 跳过并告警（F16）——`Registry.register` 遇重名是
硬抛异常，且启动期的注册顺序决定了必须先 `lookup` 预检。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Protocol

from mewcode.command.command import Command, Kind
from mewcode.command.registry import Registry

if TYPE_CHECKING:
    from mewcode.command.ui import SkillSummary, UI

SKILL_TAG = "[skill]"


class SkillRunner(Protocol):
    """执行器契约：把某个 Skill 跑起来（inline 注入 or fork 起子 Agent）。"""

    async def execute(self, name: str, args: str, ui: UI) -> None: ...


def _warn(msg: str) -> None:
    print(f"[skills] warn: {msg}", file=sys.stderr)


def _make_handler(runner: SkillRunner, name: str):
    """把 Skill 名绑成默认参数，避免循环里的闭包后期绑定（全部指向最后一个）。"""

    async def handler(ui: UI) -> None:
        await runner.execute(name, "", ui)

    return handler


def register_skills_as_commands(
    reg: Registry, items: list[SkillSummary], runner: SkillRunner
) -> list[str]:
    """注册全部 Skill 命令，返回实际注册成功的名字列表。"""
    registered: list[str] = []
    for item in sorted(items, key=lambda s: s.name):
        if reg.lookup(item.name) is not None:
            _warn(f"skill {item.name} conflicts with an existing command, skipped")
            continue
        reg.register(
            Command(
                name=item.name,
                description=f"{item.description} {SKILL_TAG}",
                kind=Kind.PROMPT,
                handler=_make_handler(runner, item.name),
                is_skill=True,
            )
        )
        registered.append(item.name)
    return registered


def remove_skill_commands(reg: Registry) -> int:
    """清掉全部 Skill 命令（reload 后重新注册前调），返回清除条数。"""
    return reg.remove_if(lambda c: c.is_skill)
