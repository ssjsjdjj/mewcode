"""单会话多轮历史（docs/ch02 T6；ch03 T13 扩展工具回合；ch08 T21 并发安全；ch09 T2 回调）。

docs/ch09 F44：可选 on_append/on_replace 回调，由会话存档 Writer 注入；未设置时行为与
既有完全一致。回调在持锁结束后调用（fsync 等阻塞工作不占用会话锁）。
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable

from mewcode.llm import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    Message,
    ToolCall,
    ToolResult,
)


class Conversation:
    def __init__(
        self,
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> None:
        self._messages: list[Message] = []
        # 加锁是防御性的——Python asyncio 单线程事件循环本身保证串行
        self._lock = threading.Lock()
        self._on_append = on_append
        self._on_replace = on_replace

    @classmethod
    def from_messages(
        cls,
        msgs: list[Message],
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> "Conversation":
        """从已有消息列表创建会话（docs/ch09 恢复场景）；浅拷贝入参。"""
        conv = cls(on_append=on_append, on_replace=on_replace)
        conv._messages = list(msgs)
        return conv

    def add_user(self, text: str) -> None:
        with self._lock:
            msg = Message(role="user", content=text)
            self._messages.append(msg)
        self._emit_append(msg)

    def add_assistant(self, text: str) -> None:
        with self._lock:
            msg = Message(role=ROLE_ASSISTANT, content=text)
            self._messages.append(msg)
        self._emit_append(msg)

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        with self._lock:
            msg = Message(role=ROLE_ASSISTANT, content=text, tool_calls=list(calls))
            self._messages.append(msg)
        self._emit_append(msg)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        with self._lock:
            msg = Message(role=ROLE_TOOL, tool_results=list(results))
            self._messages.append(msg)
        self._emit_append(msg)

    def _emit_append(self, msg: Message) -> None:
        if self._on_append is not None:
            self._on_append(msg)

    def messages(self) -> list[Message]:
        """返回副本，避免外部改动历史。"""
        with self._lock:
            return list(self._messages)

    def length(self) -> int:
        """当前消息条数（等价于 len(conv)）。"""
        with self._lock:
            return len(self._messages)

    def last_role(self) -> str:
        """返回最后一条消息的 role；空历史返回空串。"""
        with self._lock:
            return self._messages[-1].role if self._messages else ""

    def replace_history(self, msgs: list[Message] | None) -> None:
        """整体替换历史：深拷贝入参，不暴露外部引用；None/空列表等价清空。"""
        with self._lock:
            self._messages = copy.deepcopy(msgs or [])
            snapshot = list(self._messages)
        if self._on_replace is not None:
            self._on_replace(snapshot)

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)
