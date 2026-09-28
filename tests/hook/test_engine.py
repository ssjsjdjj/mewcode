"""事件分派引擎测试（docs/ch12 T13，F27–F29/F32）。"""

from __future__ import annotations

import asyncio

import pytest

from mewcode.hook import Engine, Event
from mewcode.hook.executor import ExecutionResult, Executor
from mewcode.hook.rule import (
    AtomCondition,
    CombineMode,
    Condition,
    PromptAction,
    Rule,
    ShellAction,
)
from mewcode.permission.matcher import ExactMatcher


class StubExecutor:
    """按脚本返回结果的执行器；记录 (name, blocking) 调用序。"""

    def __init__(self, results: list[ExecutionResult] | None = None) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._results = list(results or [])
        self.gate = asyncio.Event()

    async def run(self, rule: Rule, payload: dict, *, blocking: bool) -> ExecutionResult:
        self.calls.append((rule.name, blocking))
        if self._results:
            return self._results.pop(0)
        return ExecutionResult()


def rule(
    name: str,
    event: Event = Event.STOP,
    *,
    action=None,  # noqa: ANN001
    condition: Condition | None = None,
    only_once: bool = False,
    asyncio_mode: bool = False,
    timeout: float = 30.0,
) -> Rule:
    return Rule(
        name=name,
        event=event,
        action=action or PromptAction(text=f"p-{name}"),
        condition=condition,
        only_once=only_once,
        asyncio_mode=asyncio_mode,
        timeout=timeout,
    )


async def test_rules_run_in_declaration_order():
    stub = StubExecutor([ExecutionResult(), ExecutionResult()])
    engine = Engine([rule("a"), rule("b")], [], executor=stub)
    await engine.dispatch(Event.STOP, {})
    assert [n for n, _ in stub.calls] == ["a", "b"]


async def test_only_matching_event_is_dispatched():
    stub = StubExecutor()
    engine = Engine([rule("a", Event.STOP), rule("b", Event.NOTIFICATION)], [], executor=stub)
    await engine.dispatch(Event.STOP, {})
    assert [n for n, _ in stub.calls] == ["a"]


async def test_first_block_wins_and_stops_rest():
    """拦截类事件下首个表达拦截的 hook 中断后续（F32）。"""
    stub = StubExecutor(
        [
            ExecutionResult(blocked=True, reason="no writes"),
            ExecutionResult(),  # 不该被执行到
        ]
    )
    engine = Engine(
        [rule("a", Event.PRE_TOOL_USE), rule("b", Event.PRE_TOOL_USE)], [], executor=stub
    )
    result = await engine.dispatch(Event.PRE_TOOL_USE, {})

    assert result.blocked is True
    assert result.reason == "no writes"
    assert result.blocking_hook_name == "a"
    assert [n for n, _ in stub.calls] == ["a"]
    assert stub.calls[0][1] is True  # 传了 blocking=True


async def test_blocked_ignored_on_non_blocking_event():
    """非拦截类事件下 blocked 不传递（F19/F25 的前提）。"""
    stub = StubExecutor([ExecutionResult(blocked=True, reason="x"), ExecutionResult()])
    engine = Engine([rule("a"), rule("b")], [], executor=stub)
    result = await engine.dispatch(Event.STOP, {})

    assert result.blocked is False
    assert [n for n, _ in stub.calls] == ["a", "b"]  # 没中断
    assert stub.calls[0][1] is False


async def test_prompt_actions_accumulate():
    stub = StubExecutor([ExecutionResult(prompt="one"), ExecutionResult(prompt="two")])
    engine = Engine([rule("a"), rule("b")], [], executor=stub)
    result = await engine.dispatch(Event.STOP, {})
    assert result.injected_prompts == ["one", "two"]


async def test_condition_filters_rules():
    cond = Condition(
        mode=CombineMode.ALL_OF, atoms=(AtomCondition("tool_name", ExactMatcher("write_file")),)
    )
    stub = StubExecutor()
    engine = Engine([rule("a", Event.PRE_TOOL_USE, condition=cond)], [], executor=stub)

    await engine.dispatch(Event.PRE_TOOL_USE, {"tool_name": "read_file"})
    assert stub.calls == []
    await engine.dispatch(Event.PRE_TOOL_USE, {"tool_name": "write_file"})
    assert [n for n, _ in stub.calls] == ["a"]


async def test_only_once_fires_then_skips():
    stub = StubExecutor()
    engine = Engine([rule("once", only_once=True)], [], executor=stub)

    await engine.dispatch(Event.STOP, {})
    await engine.dispatch(Event.STOP, {})
    assert [n for n, _ in stub.calls] == ["once"]


async def test_only_once_not_marked_on_failure():
    """失败的 hook 不算命中，下一轮还该再试（F29）。"""
    stub = StubExecutor([ExecutionResult(err=RuntimeError("boom")), ExecutionResult()])
    engine = Engine([rule("f", only_once=True)], [], executor=stub)

    await engine.dispatch(Event.STOP, {})
    await engine.dispatch(Event.STOP, {})
    assert len(stub.calls) == 2  # 第二次仍然执行


async def test_failure_logs_and_continues(capsys):
    stub = StubExecutor([ExecutionResult(err=RuntimeError("boom")), ExecutionResult(prompt="ok")])
    engine = Engine([rule("bad"), rule("good")], [], executor=stub)
    result = await engine.dispatch(Event.STOP, {})

    assert result.injected_prompts == ["ok"]  # 后续规则照常
    err = capsys.readouterr().err
    assert "[hook bad] Stop failed: boom" in err


async def test_reset_for_new_session_clears_once():
    stub = StubExecutor()
    engine = Engine([rule("once", only_once=True)], [], executor=stub)

    await engine.dispatch(Event.STOP, {})
    assert len(stub.calls) == 1
    await engine.reset_for_new_session()
    await engine.dispatch(Event.STOP, {})
    assert len(stub.calls) == 2


async def test_async_rule_does_not_block_or_inject():
    """async 规则丢到后台跑，不参与拦截与 reminder（F28）。"""
    ran = asyncio.Event()

    class GatedExecutor(StubExecutor):
        async def run(self, r, payload, *, blocking):  # noqa: ANN001
            self.calls.append((r.name, blocking))
            ran.set()
            return ExecutionResult(blocked=True, reason="should be ignored", prompt="ignored")

    stub = GatedExecutor()
    engine = Engine([rule("bg", Event.PRE_TOOL_USE, asyncio_mode=True)], [], executor=stub)
    result = await engine.dispatch(Event.PRE_TOOL_USE, {})

    assert result.blocked is False
    assert result.injected_prompts == []
    await asyncio.wait_for(ran.wait(), timeout=1)  # 后台任务确实起来了
    assert stub.calls[0] == ("bg", False)  # 异步一律 blocking=False


async def test_async_only_once_marked_immediately():
    stub = StubExecutor()
    engine = Engine([rule("bg", asyncio_mode=True, only_once=True)], [], executor=stub)
    await engine.dispatch(Event.STOP, {})
    await asyncio.sleep(0)  # 让后台任务跑起来
    await engine.dispatch(Event.STOP, {})
    assert len(stub.calls) == 1


def test_properties_return_copies():
    r = rule("a")
    engine = Engine([r], ["/tmp/hooks.yaml"])
    engine.rules.append(rule("b"))
    engine.sources.append("/tmp/other.yaml")
    assert [x.name for x in engine.rules] == ["a"]
    assert engine.sources == ["/tmp/hooks.yaml"]


# ---- 与真实 Executor 的集成 ----


async def test_real_executor_shell_block_through_engine():
    """真 shell 动作经引擎 → blocked（AC4 的内核）。"""
    import sys

    cmd = f'"{sys.executable}" -c "import sys; print(\'blocked\', file=sys.stderr); sys.exit(2)"'
    r = rule("shell-block", Event.PRE_TOOL_USE, action=ShellAction(command=cmd))
    engine = Engine([r], [], executor=Executor())
    result = await engine.dispatch(Event.PRE_TOOL_USE, {"tool_name": "write_file"})

    assert result.blocked is True
    assert result.reason == "blocked"
    assert result.blocking_hook_name == "shell-block"


async def test_real_executor_prompt_through_engine(capsys):
    r = rule("p", Event.SESSION_START, action=PromptAction(text="用 zh-CN 回复"))
    engine = Engine([r], [], executor=Executor())
    result = await engine.dispatch(Event.SESSION_START, {})
    assert result.injected_prompts == ["用 zh-CN 回复"]
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("event", [Event.STOP, Event.PRE_TOOL_USE])
async def test_empty_engine_is_noop(event):
    engine = Engine([], [])
    result = await engine.dispatch(event, {})
    assert result.blocked is False and result.injected_prompts == []


async def test_only_once_preuser_message_across_clear(tmp_path):
    """场景 6 的内核：only_once 的 PreUserMessage hook 只在首轮触发，/clear 后重来。"""
    stub = StubExecutor([ExecutionResult(), ExecutionResult(), ExecutionResult()])
    engine = Engine([rule("first-turn", Event.PRE_USER_MESSAGE, only_once=True)], [], executor=stub)

    await engine.dispatch(Event.PRE_USER_MESSAGE, {})  # 第一轮
    await engine.dispatch(Event.PRE_USER_MESSAGE, {})  # 第二轮：跳过
    assert len(stub.calls) == 1

    await engine.reset_for_new_session()  # 等价 /clear 或 /resume
    await engine.dispatch(Event.PRE_USER_MESSAGE, {})  # 新会话首轮：再来一次
    assert len(stub.calls) == 2
