"""manage_context 编排测试（docs/ch08 T22）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mewcode.compact import TriggerKind
from mewcode.compact.compact import ManageInput, manage_context
from mewcode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
)
from mewcode.conversation import Conversation
from mewcode.llm import Message, PromptTooLongError, StreamEvent, ToolResult


def _input(
    provider,
    msgs,
    *,
    context_window,
    trigger=TriggerKind.AUTO,
    session=None,
    auto_tracking=None,
    usage_anchor=0,
    anchor_msg_len=0,
    estimated_token=0,
) -> ManageInput:
    conv = Conversation()
    conv.replace_history(msgs)
    if session is None:
        session = SimpleNamespace(session_id="s", spill_dir="<unused>")
    if auto_tracking is None:
        auto_tracking = CompactCircuitBreaker()
    return ManageInput(
        conv=conv,
        provider=provider,
        model="fake",
        context_window=context_window,
        tool_defs=[],
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=auto_tracking,
        session=session,
        usage_anchor=usage_anchor,
        anchor_msg_len=anchor_msg_len,
        estimated_token=estimated_token,
        trigger=trigger,
    )


async def test_auto_triggers_on_threshold(fake_compact_provider):
    big = Message(role="user", content="x" * 300000)
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    inp = _input(provider, [big], context_window=100000, estimated_token=100000)
    out = await manage_context(inp)
    assert provider.summarize_calls == 1
    msgs = inp.conv.messages()
    assert "## 历史会话摘要" in msgs[0].content
    assert out.after_tokens < out.before_tokens


async def test_auto_skipped_below_threshold(fake_compact_provider):
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    inp = _input(provider, [Message(role="user", content="hi")], context_window=100000)
    await manage_context(inp)
    assert provider.summarize_calls == 0
    assert inp.conv.messages() == [Message(role="user", content="hi")]


async def test_auto_uses_layer1_output(fake_compact_provider, tmp_path):
    big = Message(role="tool", tool_results=[ToolResult("r1", "y" * 80000)])
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    session = SimpleNamespace(session_id="s", spill_dir=str(tmp_path))
    inp = _input(provider, [big], context_window=100000, session=session)
    await manage_context(inp)
    # layer1 先落盘写回；重估后低于阈值故跳过 layer2，但 layer1 结果保留
    assert provider.summarize_calls == 0
    assert (tmp_path / "r1").exists()
    assert inp.conv.messages()[0].tool_results[0].content.startswith("[content offloaded]")


async def test_auto_skipped_when_tripped(fake_compact_provider):
    breaker = CompactCircuitBreaker()
    for _ in range(3):
        breaker.record_failure()
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    inp = _input(
        provider,
        [Message(role="user", content="x" * 300000)],
        context_window=100000,
        auto_tracking=breaker,
    )
    await manage_context(inp)
    assert provider.summarize_calls == 0


async def test_auto_failure_records_failure(fake_compact_provider):
    breaker = CompactCircuitBreaker()
    provider = fake_compact_provider([[StreamEvent(err=RuntimeError("boom"))]] * 3)
    inp = _input(
        provider,
        [Message(role="user", content="x" * 300000)],
        context_window=100000,
        auto_tracking=breaker,
        estimated_token=500,
    )
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await manage_context(inp)
    assert breaker.tripped()


async def test_auto_ptl_exhaustion_counts_as_failure(fake_compact_provider):
    breaker = CompactCircuitBreaker()
    provider = fake_compact_provider([[StreamEvent(err=PromptTooLongError("long"))]] * 3)
    inp = _input(
        provider,
        [Message(role="user", content="x" * 300000)],
        context_window=100000,
        auto_tracking=breaker,
    )
    for _ in range(3):
        with pytest.raises(PromptTooLongError):
            await manage_context(inp)
    assert breaker.tripped()


async def test_manual_bypasses_everything(fake_compact_provider):
    # 即便 estimated=500 远低于阈值，手动也强制压缩
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    inp = _input(
        provider,
        [Message(role="user", content="hi")],
        context_window=200000,
        estimated_token=500,
        trigger=TriggerKind.MANUAL,
    )
    await manage_context(inp)
    assert provider.summarize_calls == 1
    assert "## 历史会话摘要" in inp.conv.messages()[0].content


async def test_emergency_runs_layer1_then_force(fake_compact_provider, tmp_path):
    big = Message(role="tool", tool_results=[ToolResult("r1", "y" * 80000)])
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    session = SimpleNamespace(session_id="s", spill_dir=str(tmp_path))
    inp = _input(
        provider, [big], context_window=100000, session=session, trigger=TriggerKind.EMERGENCY
    )
    await manage_context(inp)
    assert (tmp_path / "r1").exists()  # 紧急路径先跑 layer1 落盘
    assert "## 历史会话摘要" in inp.conv.messages()[0].content


async def test_emergency_bypass_tracking(fake_compact_provider):
    breaker = CompactCircuitBreaker()
    for _ in range(3):
        breaker.record_failure()
    provider = fake_compact_provider([[StreamEvent(err=RuntimeError("boom"))]])
    inp = _input(
        provider,
        [Message(role="user", content="hi")],
        context_window=100000,
        auto_tracking=breaker,
        trigger=TriggerKind.EMERGENCY,
    )
    with pytest.raises(RuntimeError):
        await manage_context(inp)
    assert breaker._consecutive_failures == 3  # 紧急路径不触碰熔断器


async def test_auto_usage_anchor_replaced_not_accumulated(fake_compact_provider):
    # 每轮调用方传入的 usage_anchor 是"替换"后的最新值（1000/1500/2200），
    # 各自都 < threshold=3000；若被错误累加（4700）则会触发 layer2。
    provider = fake_compact_provider(
        [[StreamEvent(text="<summary>S</summary>"), StreamEvent(done=True)]]
    )
    old = [Message(role="user", content="anchor-period msg")]
    for anchor in (1000, 1500, 2200):
        msgs = old + [Message(role="user", content="a" * 100)]
        inp = _input(
            provider,
            msgs,
            context_window=36000,
            usage_anchor=anchor,
            anchor_msg_len=1,
            estimated_token=anchor + 10,
        )
        await manage_context(inp)
    assert provider.summarize_calls == 0
