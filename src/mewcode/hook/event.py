"""生命周期事件（docs/ch12 T6，F9）。

11 个固定时刻，分两类：**拦截类**（PreToolUse / UserPromptSubmit）可以阻止动作
发生并通过约定方式回传原因；其余只在动作已定之后做副作用，不能表达拦截。

拦截类不允许 `async: true`（异步无法回传拦截信号），加载期校验报错并跳过（F28）。
"""

from __future__ import annotations

from enum import StrEnum


class Event(StrEnum):
    """事件名与 YAML 字面量一一对应。"""

    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"


# 能阻止动作发生的两个时刻（F19/F25 的 exit 2 / decision:block 只在这两个事件有意义）
BLOCKING_EVENTS: frozenset[Event] = frozenset({Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT})


def is_blocking(e: Event) -> bool:
    """该事件是否可拦截。"""
    return e in BLOCKING_EVENTS


def parse_event(s: str) -> Event | None:
    """事件名字面量 → Event；未知返回 None（调用方报 stderr 并跳过该 hook）。"""
    try:
        return Event(s)
    except ValueError:
        return None
