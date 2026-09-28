"""Agent 与 hook 引擎的集成测试（docs/ch12 T17，F31/F32）。

覆盖只有接进主循环才能验的三点：PreToolUse 拦截走通（工具真的没执行、
tool_result 是 `[hook ...]`）、注入的 prompt 落在**下一次**请求的 reminder 里、
Stop / Notification 在正确时刻 emit。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile

from mewcode.agent import Agent, SessionRuntime
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.conversation import Conversation
from mewcode.hook import Engine, Event
from mewcode.hook.rule import (
    AtomCondition,
    CombineMode,
    Condition,
    PromptAction,
    Rule,
    ShellAction,
)
from mewcode.llm import StreamEvent, ToolCall
from mewcode.permission import Mode
from mewcode.permission.matcher import ExactMatcher
from mewcode.tool import new_default_registry

from test_agent import FakeProvider  # 复用既有的可编程假 provider


def runtime() -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(tempfile.mkdtemp()),
        context_window=200000,
    )


def py(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


class SpyEngine(Engine):
    """记录每次分派的 event 与 payload，其余行为不变。"""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        super().__init__(rules or [], [])
        self.seen: list[dict] = []

    async def dispatch(self, event: Event, payload: dict):  # noqa: ANN201
        self.seen.append({"event": event.value, **payload})
        return await super().dispatch(event, payload)

    def events(self, name: str) -> list[dict]:
        return [s for s in self.seen if s["event"] == name]


def exit2_rule(name: str = "blocker", tool: str = "write_file") -> Rule:
    """拦截指定工具的 shell hook（exit 2 表达拦截）。"""
    return Rule(
        name=name,
        event=Event.PRE_TOOL_USE,
        action=ShellAction(
            command=py("import sys; print('no writes', file=sys.stderr); sys.exit(2)")
        ),
        condition=Condition(
            mode=CombineMode.ALL_OF,
            atoms=(AtomCondition("tool_name", ExactMatcher(tool)),),
        ),
    )


def prompt_rule(event: Event = Event.PRE_TOOL_USE, text: str = "记得用 zh-CN") -> Rule:
    return Rule(name="tip", event=event, action=PromptAction(text=text))


async def run_agent(provider, engine, mode: Mode = Mode.BYPASS):
    agent = Agent(provider, new_default_registry(), "test", runtime=runtime(), hook_engine=engine)
    conv = Conversation()
    conv.add_user("任务")
    events = [ev async for ev in agent.run(conv, mode, asyncio.Event())]
    return events, conv


def tool_results(conv: Conversation) -> list:
    return [m for m in conv.messages() if m.role == "tool"][-1].tool_results


# ---- PreToolUse 拦截 ----


async def test_pre_tool_use_block_skips_execution(tmp_path, monkeypatch):
    """被拦下的工具不执行，tool_result 是 `[hook <name>] <reason>`（AC4）。"""
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            id="1", name="write_file", input='{"path": "b.txt", "content": "hi"}'
                        )
                    ]
                )
            ],
            [StreamEvent(text="结束")],
        ]
    )
    events, conv = await run_agent(provider, Engine([exit2_rule()], []))

    assert tool_results(conv)[0].content == "[hook blocker] no writes"
    assert tool_results(conv)[0].is_error is True
    assert not (tmp_path / "b.txt").exists()  # 文件确实没被写

    phases = [e.tool.phase.name for e in events if e.tool is not None]
    assert "START" in phases and "END" in phases  # PhaseStart/End 照常 emit（F32）


async def test_pre_tool_use_block_is_scoped_to_matching_tool(tmp_path, monkeypatch):
    """条件只匹配 write_file，读文件不受影响（AC14 的「其它工具不受影响」）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "a.txt"}')]
                )
            ],
            [StreamEvent(text="结束")],
        ]
    )
    _, conv = await run_agent(provider, Engine([exit2_rule()], []))
    assert "hello" in tool_results(conv)[0].content


async def test_hook_block_visible_to_next_iteration(tmp_path, monkeypatch):
    """拦截原因回灌给模型，下一轮请求能看到（F32 的「回灌让模型调整」）。"""
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            id="1", name="write_file", input='{"path": "b.txt", "content": "hi"}'
                        )
                    ]
                )
            ],
            [StreamEvent(text="好的，我不写了")],
        ]
    )
    _, _ = await run_agent(provider, Engine([exit2_rule()], []))

    second = provider.received[1]
    # 工具结果的文本挂在 tool 消息的 tool_results 上，不在 Message.content
    contents = [tr.content for m in second.messages for tr in m.tool_results]
    assert any("[hook blocker] no writes" in c for c in contents)


# ---- prompt 注入的时机 ----


async def test_prompt_from_pre_tool_use_lands_in_next_request(tmp_path, monkeypatch):
    """工具执行期间注入的文本，下一次 LLM 请求的 reminder 才带上（F20/F33）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "a.txt"}')]
                )
            ],
            [StreamEvent(text="结束")],
        ]
    )
    await run_agent(provider, Engine([prompt_rule()], []))

    assert len(provider.received) == 2
    assert "记得用 zh-CN" not in provider.received[0].reminder
    assert "记得用 zh-CN" in provider.received[1].reminder


async def test_prompt_does_not_enter_conversation(tmp_path, monkeypatch):
    """注入文本走 reminder 通道，不进对话历史、不参与压缩（N4）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "a.txt"}')]
                )
            ],
            [StreamEvent(text="结束")],
        ]
    )
    _, conv = await run_agent(provider, Engine([prompt_rule()], []))
    assert all("记得用 zh-CN" not in m.content for m in conv.messages())


async def test_reminder_is_byte_identical_without_hooks(tmp_path, monkeypatch):
    """没配 hook 时 reminder 与 ch11 逐字节一致（回归护栏）。"""
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[StreamEvent(text="hi")]])
    await run_agent(provider, Engine([], []))
    assert provider.received[0].reminder == ""


# ---- 其它事件 ----


async def test_stop_fires_before_done_with_iter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[StreamEvent(text="答完")]])
    engine = SpyEngine()
    events, _ = await run_agent(provider, engine)

    stops = engine.events("Stop")
    assert len(stops) == 1
    assert stops[0]["iter"] == 1
    assert stops[0]["mode"] == str(Mode.BYPASS)
    assert stops[0]["session_id"] and stops[0]["cwd"]
    assert any(e.done for e in events)  # Done 确实发了


async def test_no_stop_on_cancellation(tmp_path, monkeypatch):
    """取消路径不触发 Stop（F9：「取消、出错路径不触发」）。"""
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[StreamEvent(text="x")]])
    engine = SpyEngine()
    agent = Agent(provider, new_default_registry(), "test", runtime=runtime(), hook_engine=engine)
    conv = Conversation()
    conv.add_user("任务")
    cancel = asyncio.Event()
    cancel.set()  # 一开始就取消

    _ = [ev async for ev in agent.run(conv, Mode.BYPASS, cancel)]
    assert engine.events("Stop") == []


async def test_notification_on_stream_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[StreamEvent(err=RuntimeError("模型炸了"))]])
    engine = SpyEngine()
    await run_agent(provider, engine)

    notes = engine.events("Notification")
    assert notes and notes[-1]["kind"] == "stream_error"
    assert "模型炸了" in notes[-1]["detail"]


async def test_notification_on_approval(tmp_path, monkeypatch):
    """ASK 弹审批时 emit Notification（F9）。"""
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            id="1", name="write_file", input='{"path": "b.txt", "content": "hi"}'
                        )
                    ]
                )
            ],
            [StreamEvent(text="结束")],
        ]
    )
    engine = SpyEngine()
    agent = Agent(provider, new_default_registry(), "test", runtime=runtime(), hook_engine=engine)
    conv = Conversation()
    conv.add_user("任务")

    async def consume() -> None:
        async for ev in agent.run(conv, Mode.DEFAULT, asyncio.Event()):
            if ev.approval is not None:
                from mewcode.permission import Outcome

                ev.approval.respond.set_result(Outcome.DENY_ONCE)

    await consume()
    notes = engine.events("Notification")
    assert notes and notes[0]["kind"] == "approval"
    assert notes[0]["detail"] == "write_file"


async def test_pre_compact_and_post_compact_fire(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[StreamEvent(text="hi")]])
    engine = SpyEngine()
    await run_agent(provider, engine)

    assert engine.events("PreCompact")[0]["trigger"] == "auto"
    post = engine.events("PostCompact")
    assert post and post[0]["trigger"] == "auto"
    assert "before_tokens" in post[0] and "after_tokens" in post[0]


async def test_pre_user_message_carries_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[StreamEvent(text="hi")]])
    engine = SpyEngine()
    await run_agent(provider, engine)

    pum = engine.events("PreUserMessage")
    assert pum and pum[0]["prompt"] == "任务"


async def test_tool_input_payload_is_parsed_dict(tmp_path, monkeypatch):
    """tool_input 是解析后的 dict，条件可取嵌套字段（F10/F13）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "a.txt"}')]
                )
            ],
            [StreamEvent(text="ok")],
        ]
    )
    engine = SpyEngine()
    await run_agent(provider, engine)

    pre = engine.events("PreToolUse")[0]
    assert pre["tool_name"] == "read_file"
    assert pre["tool_input"] == {"path": "a.txt"}

    post = engine.events("PostToolUse")[0]
    assert post["is_error"] is False
    assert "x" in post["tool_result"]


async def test_post_tool_use_fires_for_denied_tool(tmp_path, monkeypatch):
    """权限 Deny 的工具也触发 PostToolUse，is_error=True（F9）。"""
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="1", name="write_file", input='{"path": "x", "content": "c"}')
                    ]
                )
            ],
            [StreamEvent(text="ok")],
        ]
    )
    engine = SpyEngine()
    # 项目级 deny 规则拦下 write_file
    (tmp_path / ".mewcode").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".mewcode" / "settings.yaml").write_text(
        "permissions:\n  deny:\n    - 'Write(*)'\n", encoding="utf-8"
    )
    await run_agent(provider, engine, mode=Mode.DEFAULT)

    post = [s for s in engine.events("PostToolUse") if s["tool_name"] == "write_file"]
    assert post and post[0]["is_error"] is True


async def test_broken_hook_does_not_break_run(tmp_path, monkeypatch):
    """hook 命令失败只记日志，工具照常执行（G9/AC7 的容错面）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    bad = Rule(
        name="broken",
        event=Event.PRE_TOOL_USE,
        action=ShellAction(command="__no_such_command_xyz__"),
    )
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "a.txt"}')]
                )
            ],
            [StreamEvent(text="ok")],
        ]
    )
    _, conv = await run_agent(provider, Engine([bad], []))
    assert "hello" in tool_results(conv)[0].content  # 工具照常跑
    assert tool_results(conv)[0].is_error is False


async def test_plan_reminder_and_hook_prompt_coexist(tmp_path, monkeypatch):
    """plan reminder 与 hook 注入的 prompt 在同一轮 reminder 串里共存（checklist 集成项）。"""
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[StreamEvent(text="hi")]])
    engine = Engine([prompt_rule(event=Event.PRE_COMPACT, text="hook 说你好")], [])
    await run_agent(provider, engine, mode=Mode.PLAN)

    reminder = provider.received[0].reminder
    assert "PLAN MODE" in reminder  # plan 提醒（docs/ch05 F7）
    assert "hook 说你好" in reminder  # hook 注入（F20/F33）
    assert reminder.index("PLAN MODE") < reminder.index("hook 说你好")  # hook 排最后


async def test_pending_reminders_cleared_after_take():
    """take_reminders 取完即空：同一段文本不会被两次请求重复注入（checklist 集成项）。"""
    rt = runtime()
    rt.append_reminders(["a", "b"])
    assert rt.take_reminders() == ["a", "b"]
    assert rt.take_reminders() == []
    assert rt.pending_reminders == []


async def test_pending_reminders_cleared_on_new_session():
    rt = runtime()
    rt.append_reminders(["x"])
    rt.reset_for_new_session(new_session_context(tempfile.mkdtemp()))
    assert rt.pending_reminders == []
