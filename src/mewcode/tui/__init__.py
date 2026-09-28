"""TUI 包：共享状态机、输入组件与工具显示。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from textual.binding import Binding
from textual.widgets import TextArea


@dataclass
class ToolDisplay:
    """执行中工具行（ch04：支持并发批多个）。"""

    name: str
    args: str = ""


class SessionState(Enum):
    SELECTING = "selecting"  # 多 provider 选择界面
    IDLE = "idle"  # 等待用户输入
    STREAMING = "streaming"  # 等待/接收模型流
    APPROVING = "approving"  # 人在回路待批准（docs/ch06 F8）
    RESUMING = "resuming"  # /resume 会话选择列表（docs/ch09 T14）


class ChatInput(TextArea):
    """输入框：Enter 提交，Alt+Enter 换行。

    注：TextArea 的 `_on_key` 会把 enter 直接当作换行字符处理且不经 binding 系统，
    因此这里显式拦截 enter / alt+enter。
    """

    BINDINGS = [
        Binding("enter", "submit", "Send"),
        Binding("alt+enter", "insert_newline", "Newline"),
    ]

    async def _on_key(self, event) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            await self.app.submit(self.text)
            return
        if event.key == "alt+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)

    def action_submit(self) -> None:
        """供 binding 兜底（正常情况下由 _on_key 直接处理）。"""

    def action_insert_newline(self) -> None:
        self.insert("\n")
