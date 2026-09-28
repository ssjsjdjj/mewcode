"""第 2 层摘要压缩测试（docs/ch08 T22）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mewcode.compact.layer2 import (
    _join_after_summary,
    group_by_user_turn,
    pick_recent_tail,
    ptl_retry,
    run_summary,
)
from mewcode.compact.state import RecoveryState
from mewcode.llm import (
    Message,
    PromptTooLongError,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    StreamEvent,
)
from mewcode.llm import ToolCall, ToolDefinition, ToolResult

USER = Message(role=ROLE_USER, content="u")
ASSISTANT = Message(role=ROLE_ASSISTANT, content="a")


def _calls_msg(call_id: str) -> Message:
    return Message(
        role=ROLE_ASSISTANT, content="", tool_calls=[ToolCall(call_id, "read_file", "{}")]
    )


def _tool_msg(result_id: str, content: str = "t") -> Message:
    return Message(role=ROLE_TOOL, tool_results=[ToolResult(result_id, content)])


def test_pick_recent_tail_boundary():
    # 条数下界已满足但 token 不足 -> 必须扫到头返回全部
    short = [Message(role=ROLE_USER, content="x") for _ in range(8)]
    assert len(pick_recent_tail(short)) == 8

    # token 下界单条即满足但条数不足 5 -> 必须继续扫到 5 条
    huge = Message(role=ROLE_ASSISTANT, content="z" * 40000)
    msgs = [USER, ASSISTANT, _tool_msg("t"), USER, huge]
    tail = pick_recent_tail(msgs)
    assert len(tail) == len(msgs)


def test_pick_recent_tail_pair_fix():
    huge = Message(role=ROLE_ASSISTANT, content="z" * 40000)
    msgs = [
        USER,
        _calls_msg("a1"),
        _tool_msg("t1"),
        _tool_msg("lonely"),
        ASSISTANT,
        _tool_msg("t2"),
        USER,
        huge,
    ]
    tail = pick_recent_tail(msgs)
    assert tail[0].role != "tool"
    assert tail[0].tool_calls  # 前移到带 tool_calls 的 assistant


def test_join_after_summary_avoids_consecutive_user():
    summary = Message(role=ROLE_USER, content="## 历史会话摘要\nx")
    joined = _join_after_summary(summary, [USER])
    roles = [m.role for m in joined]
    assert roles[0] == "user" and roles[1] == "assistant" and roles[2] == "user"
    # assistant 开头直接拼接
    joined2 = _join_after_summary(summary, [ASSISTANT])
    assert [m.role for m in joined2] == ["user", "assistant"]


def test_group_by_user_turn():
    u = Message(role=ROLE_USER, content="u")
    a = Message(role=ROLE_ASSISTANT, content="a")
    t = _tool_msg("x")
    groups = group_by_user_turn([u, a, t, u, a])
    assert len(groups) == 2
    assert len(groups[0]) == 3 and len(groups[1]) == 2


async def test_ptl_retry_drops_exactly_one_group_per_step(fake_compact_provider):
    msgs = [Message(role=ROLE_USER, content=f"g{i}") for i in range(4)]
    provider = fake_compact_provider(
        [
            [StreamEvent(err=PromptTooLongError("long"))],
            [StreamEvent(err=PromptTooLongError("long"))],
            [StreamEvent(err=PromptTooLongError("long"))],
            [StreamEvent(text="<summary>ok</summary>"), StreamEvent(done=True)],
        ]
    )
    inp = SimpleNamespace(
        provider=provider,
        conv=SimpleNamespace(messages=lambda: msgs),
        tool_defs=[],
        recovery=RecoveryState(),
    )
    new_msgs = await run_summary(inp)
    assert "ok" in new_msgs[0].content
    assert provider.user_lines == [4, 3, 2, 1]


async def test_ptl_retry_fall_to_percentage(fake_compact_provider):
    msgs = [Message(role=ROLE_USER, content=f"g{i}") for i in range(10)]
    provider = fake_compact_provider([[StreamEvent(err=PromptTooLongError("long"))]] * 20)
    inp = SimpleNamespace(
        provider=provider, conv=SimpleNamespace(messages=lambda: msgs), tool_defs=[]
    )
    with pytest.raises(PromptTooLongError):
        await ptl_retry(inp, msgs, PromptTooLongError("first"))
    # 前 3 次逐组丢 1，之后按比例 ceil(剩余*0.2)，drop 至少 1
    assert provider.user_lines == [9, 8, 7, 5, 4, 3, 2, 1]
    for prev, nxt in zip([9, 8, 7, 5, 4, 3, 2], provider.user_lines[1:]):
        assert prev - nxt >= 1


async def test_ptl_retry_stops_before_empty_messages(fake_compact_provider):
    msgs = [Message(role=ROLE_USER, content="g") for _ in range(3)]
    provider = fake_compact_provider([[StreamEvent(err=PromptTooLongError("long"))]] * 20)
    inp = SimpleNamespace(
        provider=provider, conv=SimpleNamespace(messages=lambda: msgs), tool_defs=[]
    )
    with pytest.raises(PromptTooLongError):
        await ptl_retry(inp, msgs, PromptTooLongError("first"))
    # 绝不发送 messages 为空的摘要请求：每条请求至少 1 组
    assert provider.user_lines and min(provider.user_lines) >= 1


async def test_run_summary_basic(fake_compact_provider):
    defs = [ToolDefinition("read_file", "读取文件", {"path": "str"})]
    rec = RecoveryState()
    rec.record_file("/tmp/a.py", "print(1)")
    old = [Message(role=ROLE_USER, content="hi"), ASSISTANT, _tool_msg("r")]
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    inp = SimpleNamespace(
        provider=provider,
        conv=SimpleNamespace(messages=lambda: old),
        tool_defs=defs,
        recovery=rec,
    )
    new_msgs = await run_summary(inp)
    assert len(new_msgs) >= 1
    text = new_msgs[0].content
    assert "## 历史会话摘要" in text and "S" in text
    assert "## 最近读过的文件" in text and "## 当前可用工具" in text
    assert "read_file" in text
