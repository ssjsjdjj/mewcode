"""1 条提示词命令：/do（docs/ch10 T7；ch11 T21 移走 /review）。

提示词类向对话追加一条 user 消息（含固定文本）并立即触发 LLM 回合；该消息
与真实用户消息走同一持久化路径（F11/N3）。

`/review` 在 ch11 被同名内置 Skill 接管（fork 模式，见
`mewcode/skills/builtin/review/SKILL.md`），此处不再提供。
"""

from __future__ import annotations

from mewcode import prompt
from mewcode.command.ui import UI
from mewcode.permission import Mode


async def handle_do(ui: UI) -> None:
    """/do：切回默认模式并注入执行指令触发回合（F14，行为与 ch08 一致）。"""
    ui.set_mode(Mode.DEFAULT)
    ui.inject_and_send("/do", prompt.EXECUTE_DIRECTIVE)
