"""2 条提示词命令：/do /review（docs/ch10 T7）。

提示词类向对话追加一条 user 消息（含固定文本）并立即触发 LLM 回合；该消息
与真实用户消息走同一持久化路径（F11/N3）。
"""

from __future__ import annotations

from mewcode import prompt
from mewcode.command.ui import UI
from mewcode.permission import Mode

REVIEW_DIRECTIVE = "请审查当前上下文中的代码变更/已读取的文件,指出潜在 bug、可读性问题和可简化处。"


async def handle_do(ui: UI) -> None:
    """/do：切回默认模式并注入执行指令触发回合（F14，行为与 ch08 一致）。"""
    ui.set_mode(Mode.DEFAULT)
    ui.inject_and_send("/do", prompt.EXECUTE_DIRECTIVE)


async def handle_review(ui: UI) -> None:
    """/review：注入代码审查请求触发回合（F23，不读 git diff）。"""
    ui.inject_and_send("/review", REVIEW_DIRECTIVE)
