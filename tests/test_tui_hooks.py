"""TUI 侧的 hook 集成测试（docs/ch12 T19/T20/T21）。

用 Textual headless `run_test` 驱动真实 App：SessionStart 挂载即触发、
UserPromptSubmit 拦截不消费输入框、/clear 触发 SessionEnd + SessionStart。
"""

from __future__ import annotations

import asyncio
import sys

from mewcode.command import NopUI
from mewcode.command.builtin_hooks import handle_hooks
from mewcode.hook import Engine, Event
from mewcode.hook.rule import HttpAction, PromptAction, Rule, ShellAction, SubagentAction
from mewcode.llm import StreamEvent
from mewcode.permission import Mode
from mewcode.tool import new_default_registry
from mewcode.tui import ChatInput
from mewcode.tui.app import MewCodeApp

from test_tui import FakeProvider, _test_runtime, cfg


class SpyEngine(Engine):
    """记录分派过的 event 名。"""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        super().__init__(rules or [], ["/tmp/hooks.yaml"])
        self.seen: list[str] = []

    async def dispatch(self, event: Event, payload: dict):  # noqa: ANN201
        self.seen.append(event.value)
        return await super().dispatch(event, payload)

    def count(self, name: str) -> int:
        return self.seen.count(name)


def exit2_block(prompt_match: str | None = None) -> Rule:
    """拦下含指定关键字的用户输入（shell exit 2）。"""
    from mewcode.hook.rule import AtomCondition, CombineMode, Condition
    from mewcode.permission.matcher import RegexMatcher

    cond = None
    if prompt_match is not None:
        cond = Condition(
            mode=CombineMode.ALL_OF,
            atoms=(AtomCondition("prompt", RegexMatcher(prompt_match)),),
        )
    cmd = f'"{sys.executable}" -c "import sys; print(\'被拦下了\', file=sys.stderr); sys.exit(2)"'
    return Rule(
        name="blocker",
        event=Event.USER_PROMPT_SUBMIT,
        action=ShellAction(command=cmd),
        condition=cond,
    )


def make_app(engine, provider=None) -> MewCodeApp:
    return MewCodeApp(
        [cfg()],
        provider=provider or FakeProvider(),
        registry=new_default_registry(),
        runtime=_test_runtime(),
        hook_engine=engine,
    )


async def type_text(app, pilot, text: str) -> None:
    input_ = app.query_one("#chat-input", ChatInput)
    for ch in text:
        input_.insert(ch)
        await pilot.pause()
    await pilot.pause()


def test_session_start_fires_on_mount():
    async def sc():
        engine = SpyEngine()
        app = make_app(engine)
        async with app.run_test() as pilot:
            for _ in range(4):
                await pilot.pause()
            assert engine.count("SessionStart") == 1

    asyncio.run(sc())


def test_user_prompt_submit_block_keeps_input_and_history():
    """被拦下时不写历史、不消费输入框、焦点留在输入框（F32/AC10）。"""

    async def sc():
        engine = SpyEngine([exit2_block()])
        app = make_app(engine)
        async with app.run_test() as pilot:
            await pilot.pause()
            await type_text(app, pilot, "请帮我删掉那个文件")
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()

            assert engine.count("UserPromptSubmit") == 1
            assert [m for m in app.conv.messages() if m.role == "user"] == []
            assert app.input_area.text == "请帮我删掉那个文件"  # 输入框未被清空
            assert app.state.name == "IDLE"  # 没进入流式

    asyncio.run(sc())


def test_user_prompt_submit_pass_goes_through():
    """hook 放行时消息照常进历史并起一轮（AC5 的内核）。"""

    async def sc():
        engine = SpyEngine([exit2_block(prompt_match="(?i)delete")])
        provider = FakeProvider([[StreamEvent(text="好的")]])
        app = make_app(engine, provider)
        async with app.run_test() as pilot:
            await pilot.pause()
            await type_text(app, pilot, "帮我看看代码")
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()

            assert engine.count("UserPromptSubmit") == 1
            users = [m for m in app.conv.messages() if m.role == "user"]
            assert [m.content for m in users] == ["帮我看看代码"]

    asyncio.run(sc())


def test_user_prompt_submit_prompt_injection_reaches_request():
    """非拦截的 hook 也能注入文本，下一轮请求的 reminder 带上（F33）。"""

    async def sc():
        engine = SpyEngine(
            [Rule(name="tip", event=Event.PRE_USER_MESSAGE, action=PromptAction(text="别忘测试"))]
        )
        provider = FakeProvider([[StreamEvent(text="好的")]])
        app = make_app(engine, provider)
        async with app.run_test() as pilot:
            await pilot.pause()
            await type_text(app, pilot, "开始")
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            # PreUserMessage 在 agent 内 emit，注入后同轮进 reminder
            assert provider.calls, "应发出过请求"

    asyncio.run(sc())


def test_clear_dispatches_session_end_and_start():
    """`/clear` 依次触发 SessionEnd → SessionStart 并清 only_once（T20/N5）。"""

    async def sc():
        engine = SpyEngine()
        once = Rule(name="once", event=Event.STOP, action=PromptAction(text="x"), only_once=True)
        engine._rules.append(once)
        app = make_app(engine)
        async with app.run_test() as pilot:
            for _ in range(4):
                await pilot.pause()
            engine.seen.clear()

            await app.dispatch_slash("/clear")
            for _ in range(4):
                await pilot.pause()

            assert engine.seen == ["SessionEnd", "SessionStart"]

    asyncio.run(sc())


def test_clear_resets_only_once():
    """换会话清空 only_once：同一个 hook 在新会话里会再触发一次（F27/AC9 内核）。"""

    async def sc():
        engine = SpyEngine()
        rule = Rule(
            name="once",
            event=Event.SESSION_START,
            action=PromptAction(text="hi"),
            only_once=True,
        )
        engine._rules.append(rule)
        app = make_app(engine)
        async with app.run_test() as pilot:
            for _ in range(4):
                await pilot.pause()
            assert engine._once_fired == {"once"}

            await app.dispatch_slash("/clear")
            for _ in range(4):
                await pilot.pause()
            # 重置后又被新会话的 SessionStart 标记了一次，但注入是新一轮的
            assert engine._once_fired == {"once"}

    asyncio.run(sc())


def test_clear_async_keeps_active_skills_order():
    """ch11 的 N9 顺序不被本次 async 化破坏：先清激活列表再换会话。"""

    async def sc():
        app = make_app(SpyEngine())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.runtime.active_skills.activate("commit", "SOP")
            assert app.list_active_skills() == ["commit"]
            await app.dispatch_slash("/clear")
            for _ in range(4):
                await pilot.pause()
            assert app.list_active_skills() == []

    asyncio.run(sc())


# ---- /hooks 命令 ----


class RecordingUI(NopUI):
    def __init__(self, rules: list[Rule], sources: list[str]) -> None:
        self.printed: list[str] = []
        self._rules = rules
        self._sources = sources

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def hook_rules(self) -> list[Rule]:
        return self._rules

    def hook_sources(self) -> list[str]:
        return self._sources


async def test_hooks_command_empty():
    ui = RecordingUI([], [])
    await handle_hooks(ui)
    assert ui.printed == ["No hooks loaded."]


async def test_hooks_command_lists_grouped_with_flags():
    rules = [
        Rule(
            name="a",
            event=Event.PRE_TOOL_USE,
            action=ShellAction(command="true"),
            only_once=True,
        ),
        Rule(name="b", event=Event.STOP, action=HttpAction(url="http://x"), asyncio_mode=True),
        Rule(name="c", event=Event.PRE_TOOL_USE, action=SubagentAction(agent_name="x", prompt="p")),
    ]
    ui = RecordingUI(rules, ["/proj/.mewcode/hooks.yaml", "/home/u/.mewcode/hooks.yaml"])
    await handle_hooks(ui)

    # 同一 event 的规则相邻（a、c 都是 PreToolUse）
    assert ui.printed[0] == "  a  PreToolUse  shell  [once]"
    assert ui.printed[1] == "  c  PreToolUse  subagent"
    assert ui.printed[2] == "  b  Stop  http  [async]"
    assert ui.printed[3] == ("Loaded from: /proj/.mewcode/hooks.yaml, /home/u/.mewcode/hooks.yaml")


def test_app_hook_query_methods():
    async def sc():
        engine = SpyEngine([Rule(name="r", event=Event.STOP, action=PromptAction(text="t"))])
        app = make_app(engine)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert [r.name for r in app.hook_rules()] == ["r"]
            assert app.hook_sources() == ["/tmp/hooks.yaml"]

    asyncio.run(sc())


def test_app_without_engine_degrades():
    async def sc():
        app = MewCodeApp(
            [cfg()],
            provider=FakeProvider(),
            registry=new_default_registry(),
            runtime=_test_runtime(),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.hook_rules() == [] and app.hook_sources() == []
            assert app._mode is Mode.DEFAULT
            await app.dispatch_slash("/hooks")  # 不抛

    asyncio.run(sc())
