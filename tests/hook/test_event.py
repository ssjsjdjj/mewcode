"""事件枚举与拦截类判定测试（docs/ch12 T6，F9）。"""

from __future__ import annotations

import pytest

from mewcode.hook import BLOCKING_EVENTS, Event, is_blocking, parse_event

ALL_NAMES = [
    "SessionStart",
    "SessionEnd",
    "SessionResume",
    "UserPromptSubmit",
    "Stop",
    "PreUserMessage",
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "Notification",
]


def test_all_eleven_events_declared():
    assert [e.value for e in Event] == ALL_NAMES


def test_is_blocking_only_for_two_events():
    """只有 PreToolUse / UserPromptSubmit 能表达拦截（F19/F25）。"""
    blocking = {e for e in Event if is_blocking(e)}
    assert blocking == {Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT}
    assert BLOCKING_EVENTS == frozenset(blocking)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_parse_event_round_trip(name):
    assert parse_event(name) is Event(name)


def test_parse_event_unknown_returns_none():
    assert parse_event("UnknownEvent") is None
    assert parse_event("") is None
    assert parse_event("pretooluse") is None  # 大小写敏感
