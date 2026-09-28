"""补全菜单状态机 + 渲染（docs/ch10 T11）。

输入框首字符为 / 时激活；候选来自 Registry.prefix_match（按命令名前缀过滤，
不含别名/描述匹配）；光标在可见窗口 [offset, offset+MAX_ROWS) 内移动，
上下溢出时显示 ↑/↓ N more 提示行。_handle_completion_key / _execute_selected /
_sync_completion_from_input 定义在本模块，但在 app.py 类体内绑定为 App 方法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mewcode.command.command import Command
from mewcode.command.registry import Registry

if TYPE_CHECKING:
    from textual import events

    from mewcode.tui.app import MewCodeApp

MAX_ROWS = 8  # 菜单最大可见行数


@dataclass
class CompletionMenu:
    """一条 / 命令补全菜单的状态与渲染（纯 Python，不依赖 Textual 组件）。"""

    items: list[Command] = field(default_factory=list)
    cursor: int = 0
    offset: int = 0
    active: bool = False

    def update(self, input_text: str, reg: Registry) -> None:
        """输入框内容变化时刷新候选；不以 / 开头则隐藏菜单。"""
        value = input_text.strip()
        if not value.startswith("/"):
            self.hide()
            return
        self.items = reg.prefix_match(value)
        self.active = True
        if not self.items:
            # 无匹配仍激活：render 显示"无匹配命令"占位
            self.cursor = 0
            self.offset = 0
            return
        # 候选列表收缩时夹紧光标/偏移
        self.cursor = max(0, min(self.cursor, len(self.items) - 1))
        self._clamp_offset()

    def move_up(self) -> None:
        if not self.items:
            return
        self.cursor = max(0, self.cursor - 1)
        self._clamp_offset()

    def move_down(self) -> None:
        if not self.items:
            return
        self.cursor = min(len(self.items) - 1, self.cursor + 1)
        self._clamp_offset()

    def selected(self) -> Command | None:
        """当前高亮项；无候选返回 None。"""
        if not self.items:
            return None
        return self.items[self.cursor]

    def hide(self) -> None:
        self.active = False
        self.items = []
        self.cursor = 0
        self.offset = 0

    def _clamp_offset(self) -> None:
        """让 cursor 始终落在可见窗口 [offset, offset+MAX_ROWS) 内。"""
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + MAX_ROWS:
            self.offset = self.cursor - MAX_ROWS + 1
        self.offset = max(0, min(self.offset, max(0, len(self.items) - 1)))

    def render(self, width: int) -> str:
        """渲染为 markup 字符串供 Static(widget) 直接写入。

        未激活返回空串；无匹配显示占位行；每行先裁到 width 再加高亮标签，
        保证可见宽度不超 width。
        """
        if not self.active:
            return ""
        if not self.items:
            return "[dim]无匹配命令[/dim]"
        name_w = max(len(c.name) for c in self.items)
        shown = self.items[self.offset : self.offset + MAX_ROWS]
        rows = []
        for idx, cmd in enumerate(shown):
            row = f"/{cmd.name:<{name_w}}  {cmd.description}"
            if width > 0:
                row = row[:width]
            if idx == self.cursor - self.offset:
                rows.append(f"[reverse]{row}[/reverse]")
            else:
                rows.append(row)
        if self.offset > 0:
            rows.insert(0, f"[dim]↑ {self.offset} more[/dim]")
        if self.offset + len(shown) < len(self.items):
            rows.append(f"[dim]↓ {len(self.items) - self.offset - len(shown)} more[/dim]")
        return "\n".join(rows)


async def _handle_completion_key(self: MewCodeApp, event: events.Key) -> bool:
    """App 键位拦截：菜单激活时消费 up/down/escape/enter/tab。

    App._on_key 走 capture phase，先于 ChatInput._on_key 拿到按键，因此能在
    菜单激活时吞掉回车/方向键，再让输入框继续处理其余键（docs/ch10 T12）。
    """
    if not self.completion.active:
        return False
    if event.key == "up":
        self.completion.move_up()
        self._render_completion()
        event.stop()
        return True
    if event.key == "down":
        self.completion.move_down()
        self._render_completion()
        event.stop()
        return True
    if event.key == "escape":
        self.completion.hide()
        self._render_completion()
        event.stop()
        return True
    if event.key in ("enter", "tab"):
        sel = self.completion.selected()
        if sel is not None:
            await self._execute_selected(sel)
            self._render_completion()
            event.stop()
            return True
        if event.key == "enter":
            # 无候选（如 /foobar、"/ /help"）：不消费，让输入框原样提交走未命中
            # 提示（checklist 场景 G1 要求一次回车即出"未知命令"）。
            return False
        self.completion.hide()  # tab 无候选：只收起菜单，不提交文本
        self._render_completion()
        event.stop()
        return True
    return False


async def _execute_selected(self: MewCodeApp, sel: Command) -> None:
    """执行高亮命令：填入输入框后走 submit（submit 内部已清空输入框）。"""
    self.input_area.text = "/" + sel.name
    await self.submit(self.input_area.text)
    self.completion.hide()


def _sync_completion_from_input(self: MewCodeApp) -> None:
    """输入框内容变化时刷新补全菜单（注意是 cmd_registry，勿用 tool_registry）。"""
    if self.cmd_registry is None:
        return
    self.completion.update(self.input_area.text, self.cmd_registry)
    self._render_completion()
