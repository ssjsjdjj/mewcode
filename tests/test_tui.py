"""TUI 无头测试（textual run_test + FakeProvider）。"""

import asyncio
import tempfile

from textual.widgets import OptionList, RichLog, Static

from mewcode.agent import CompactEvent, CompactPhase, Event, SessionRuntime
from mewcode.command.command import Command, Kind
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.config import ProviderConfig
from mewcode.llm import Message, StreamEvent, ToolCall
from mewcode.permission import Mode
from mewcode.prompt import EXECUTE_DIRECTIVE
from mewcode.tool import Registry, Result, new_default_registry
from mewcode.tui import ChatInput, SessionState
from mewcode.tui.app import MewCodeApp

BUILTIN_NAMES = [
    "clear",
    "compact",
    "do",
    "exit",
    "help",
    "hooks",
    "memory",
    "permission",
    "plan",
    "resume",
    "session",
    "skill",
    "status",
]


class EchoTool:
    def __init__(self):
        self.executions = 0

    def name(self):
        return "echo"

    def description(self):
        return "echo"

    def parameters(self):
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self):
        return False

    async def execute(self, args):
        self.executions += 1
        return Result(content="ok")


class FakeProvider:
    """实现 Provider Protocol，按调用次数弹出预置 StreamEvent。"""

    def __init__(
        self,
        name: str = "fake",
        model: str = "fake-model",
        responses: list | None = None,
    ) -> None:
        self._name = name
        self._model = model
        self._responses = responses or [[StreamEvent(text="你好"), StreamEvent(done=True)]]
        self.calls: list[list[Message]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def stream(self, req):
        self.calls.append(list(req.messages))
        idx = len(self.calls) - 1
        resp = self._responses[idx] if idx < len(self._responses) else []
        for ev in resp:
            yield ev


def cfg(name: str = "fake", protocol: str = "openai") -> ProviderConfig:
    return ProviderConfig(name=name, protocol=protocol, api_key="k", model="fake-model")


def test_single_provider_goes_idle():
    async def sc():
        app = MewCodeApp(
            [cfg()],
            provider=FakeProvider(),
            registry=new_default_registry(),
            runtime=_test_runtime(),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert app.provider is not None
            status = app.query_one("#statusbar", Static).render().plain
            assert "fake" in status and "fake-model" in status
            assert app.query_one("#select", OptionList).display is False

    asyncio.run(sc())


def test_multi_provider_shows_selection():
    async def sc():
        app = MewCodeApp(
            [cfg("a"), cfg("b")], registry=new_default_registry(), runtime=_test_runtime()
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.state == SessionState.SELECTING
            select = app.query_one("#select", OptionList)
            assert select.display is True
            assert len(select._options) == 2
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert app.provider.name == "a"

    asyncio.run(sc())


def test_submit_streams_and_finalizes():
    async def sc():
        provider = FakeProvider()
        app = MewCodeApp(
            [cfg()], provider=provider, registry=new_default_registry(), runtime=_test_runtime()
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            input_ = app.query_one("#chat-input", ChatInput)
            input_.insert("hi")
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert len(app.conv.messages()) == 2
            assert app.conv.messages()[0].content == "hi"
            assert app.conv.messages()[1].content == "你好"
            assert len(provider.calls) == 1
            # 回归：答复文本必须出现在 RichLog（曾因漏处理 ev.text 导致空白行）
            log_text = "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)
            assert "你好" in log_text

    asyncio.run(sc())


def test_tool_round_shows_tool_line_and_feeds_back():
    async def sc():
        provider = FakeProvider(
            responses=[
                [StreamEvent(tool_calls=[ToolCall(id="1", name="echo", input="{}")])],
                [StreamEvent(text="完成"), StreamEvent(done=True)],
            ]
        )
        registry = Registry()
        echo = EchoTool()
        registry.register(echo)
        app = MewCodeApp([cfg()], provider=provider, registry=registry, runtime=_test_runtime())
        app.set_mode(Mode.BYPASS)  # 绕过 Ask，专注测工具行渲染
        async with app.run_test() as pilot:
            await pilot.pause()
            input_ = app.query_one("#chat-input", ChatInput)
            input_.insert("do it")
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert echo.executions == 1
            roles = [m.role for m in app.conv.messages()]
            assert roles == ["user", "assistant", "tool", "assistant"]
            log = app.query_one("#log", RichLog)
            log_text = "\n".join(str(line) for line in log.lines)
            assert "echo" in log_text
            assert "ok" in log_text

    asyncio.run(sc())


def test_exit_command():
    async def sc():
        app = MewCodeApp(
            [cfg()],
            provider=FakeProvider(),
            registry=new_default_registry(),
            runtime=_test_runtime(),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.submit("/exit")
            await pilot.pause()
            assert app.is_running is False

    asyncio.run(sc())


# ---------- docs/ch06：TUI 权限交互 ----------


def make_echo_app():
    registry = Registry()
    registry.register(EchoTool())
    provider = FakeProvider(
        responses=[
            [StreamEvent(tool_calls=[ToolCall(id="1", name="echo", input="{}")])],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    return provider, registry


def test_shift_tab_cycles_mode():
    async def sc():
        app = MewCodeApp(
            [cfg()],
            provider=FakeProvider(),
            registry=new_default_registry(),
            runtime=_test_runtime(),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.mode() == Mode.DEFAULT
            await pilot.press("shift+tab")
            assert app.mode() == Mode.ACCEPT_EDITS
            await pilot.press("shift+tab")
            assert app.mode() == Mode.PLAN
            await pilot.press("shift+tab")
            assert app.mode() == Mode.BYPASS
            await pilot.press("shift+tab")
            assert app.mode() == Mode.DEFAULT

    asyncio.run(sc())


def test_status_bar_shows_mode_not_provider():
    async def sc():
        p = ProviderConfig(name="provider-a", protocol="openai", api_key="k", model="model-b")
        app = MewCodeApp(
            [p],
            provider=FakeProvider(name="provider-a", model="model-b"),
            registry=new_default_registry(),
            runtime=_test_runtime(),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            sb = app.query_one("#statusbar", Static).render().plain
            assert "DEFAULT" in sb
            assert "provider-a" not in sb  # 不显示 provider 名
            app.set_mode(Mode.BYPASS)
            app._update_statusbar()
            sb2 = app.query_one("#statusbar", Static).render().plain
            assert "BYPASS" in sb2

    asyncio.run(sc())


def test_approval_state_and_keys():
    async def sc():
        provider, registry = make_echo_app()
        app = MewCodeApp([cfg()], provider=provider, registry=registry, runtime=_test_runtime())
        async with app.run_test() as pilot:
            await pilot.pause()
            input_ = app.query_one("#chat-input", ChatInput)
            input_.insert("do")
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == SessionState.APPROVING
            assert app.pending is not None and app.approve_cursor == 0
            # 数字键 2 → ALLOW_FOREVER
            await pilot.press("2")
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert app.pending is None

    asyncio.run(sc())


def test_approval_deny_and_cancel():
    async def sc():
        provider, registry = make_echo_app()
        app = MewCodeApp([cfg()], provider=provider, registry=registry, runtime=_test_runtime())
        async with app.run_test() as pilot:
            await pilot.pause()
            input_ = app.query_one("#chat-input", ChatInput)
            input_.insert("do")
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == SessionState.APPROVING
            # Esc 取消 → 不退出、回 IDLE
            await pilot.press("escape")
            await pilot.pause()
            assert app.is_running is True
            assert app.state == SessionState.IDLE

    asyncio.run(sc())


def test_mode_persists_across_turns():
    async def sc():
        app = MewCodeApp(
            [cfg()],
            provider=FakeProvider(),
            registry=new_default_registry(),
            runtime=_test_runtime(),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("shift+tab")  # → ACCEPT_EDITS
            assert app.mode() == Mode.ACCEPT_EDITS
            input_ = app.query_one("#chat-input", ChatInput)
            input_.insert("hi")
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == SessionState.IDLE
            assert app.mode() == Mode.ACCEPT_EDITS  # 跨轮保持

    asyncio.run(sc())


# ---------- docs/ch08：命令分发 + Compact 渲染（T33/T34/T34a/T35）----------


def _test_runtime() -> SessionRuntime:
    """测试用临时 runtime：session 落系统临时目录，不污染项目 .mewcode。"""
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(tempfile.mkdtemp()),
        context_window=200000,
    )


def _tui_app():
    """标准测试 app：单 provider + 临时 runtime。"""
    return MewCodeApp(
        [cfg()], provider=FakeProvider(), registry=new_default_registry(), runtime=_test_runtime()
    )


def _log_text(app) -> str:
    return "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)


class MockAgent:
    """记录 run / run_force_compact 调用；run 默认 yield done 结束本轮。"""

    def __init__(self):
        self.run_calls = 0
        self.run_force_compact_calls = 0
        self.compact_result = (167000, 12000)

    async def run(self, conv, mode, cancel):
        self.run_calls += 1
        yield Event(done=True)

    async def run_force_compact(self, conv, defs):
        self.run_force_compact_calls += 1
        self.defs_arg = defs
        return self.compact_result


async def _compact_events(phase, before=0, after=0, err=None):
    """单条压缩状态事件 + done，驱动 _consume_events 走完。"""
    yield Event(compact=CompactEvent(phase=phase, before=before, after=after, err=err))
    yield Event(done=True)


def test_tui_renders_before_auto_notice():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._consume_events(_compact_events(CompactPhase.BEFORE_AUTO))
            assert "正在压缩上下文..." in _log_text(app)
            assert len(app.conv.messages()) == 0  # 状态事件不写对话历史

    asyncio.run(sc())


def test_tui_renders_before_emergency_notice():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._consume_events(_compact_events(CompactPhase.BEFORE_EMERGENCY))
            assert "上下文撞墙，自动压缩中..." in _log_text(app)
            assert len(app.conv.messages()) == 0

    asyncio.run(sc())


def test_tui_renders_after_compact_notice():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._consume_events(
                _compact_events(CompactPhase.AFTER_AUTO, before=167000, after=12000)
            )
            assert "已压缩，token 从 167000 降至 12000" in _log_text(app)
            await app._consume_events(
                _compact_events(CompactPhase.AFTER_AUTO, err=RuntimeError("boom"))
            )
            assert "压缩失败：" in _log_text(app)
            assert len(app.conv.messages()) == 0

    asyncio.run(sc())


def test_tui_slash_compact_routes_to_command():
    async def sc():
        mock = MockAgent()
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.agent = mock  # 替换 on_mount 构造的真实 Agent
            ok = await app.dispatch_slash("/compact")
            assert ok is True
            for _ in range(5):
                await pilot.pause()
                if mock.run_force_compact_calls >= 1:
                    break
            assert mock.run_force_compact_calls == 1
            assert mock.run_calls == 0  # 命令路径不调 LLM 主对话
            assert "已压缩，token 从 167000 降至 12000" in _log_text(app)
            assert len(app.conv.messages()) == 0  # 命令输入不进对话历史

    asyncio.run(sc())


def test_tui_unknown_slash_command_friendly():
    async def sc():
        mock = MockAgent()
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.agent = mock
            ok = await app.dispatch_slash("/foobar")
            assert ok is True
            await pilot.pause()
            assert "未知命令" in _log_text(app) and "/help" in _log_text(app)
            assert mock.run_calls == 0
            assert len(app.conv.messages()) == 0

    asyncio.run(sc())


def test_tui_dispatch_case_insensitive():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert await app.dispatch_slash("/Help") is True
            await pilot.pause()
            # /Help 与 /help 同效：命中 help 输出而非未知命令
            assert "/status" in _log_text(app)
            assert "未知命令" not in _log_text(app)

    asyncio.run(sc())


def test_tui_dispatch_help_lists_all_builtins():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.dispatch_slash("/help")
            await pilot.pause()
            log = _log_text(app)
            for name in BUILTIN_NAMES:
                assert f"/{name}" in log

    asyncio.run(sc())


def test_tui_dispatch_plan_local_only():
    async def sc():
        mock = MockAgent()
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.agent = mock
            assert await app.dispatch_slash("/plan") is True
            await pilot.pause()
            assert app.mode() == Mode.PLAN
            assert len(app.conv.messages()) == 0  # 纯本地：不进对话历史
            assert mock.run_calls == 0

    asyncio.run(sc())


def test_tui_dispatch_do_injects_and_sends():
    async def sc():
        mock = MockAgent()
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.agent = mock
            assert await app.dispatch_slash("/do") is True
            task = app._stream_task
            if task is not None:
                await task
            await pilot.pause()
            assert len(app.conv.messages()) == 1
            assert app.conv.messages()[0].content == EXECUTE_DIRECTIVE
            assert mock.run_calls == 1  # 注入后立即触发 LLM 回合

    asyncio.run(sc())


def test_tui_dispatch_compact_blocked_when_busy():
    async def sc():
        mock = MockAgent()
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.agent = mock
            app.state = SessionState.STREAMING
            assert await app.dispatch_slash("/compact") is True
            await pilot.pause()
            assert "请等待当前任务完成" in _log_text(app)
            assert mock.run_force_compact_calls == 0

    asyncio.run(sc())


def test_tui_dispatch_handler_exception_shows_error():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()

            async def _boom(ui):
                raise RuntimeError("boom")

            app.cmd_registry.register(
                Command(
                    name="boom",
                    description="boom",
                    kind=Kind.LOCAL,
                    handler=_boom,
                )
            )
            await app.dispatch_slash("/boom")
            await pilot.pause()
            assert "boom" in _log_text(app)  # error_block 渲染（含 ⚠）
            assert app.is_running is True  # 异常被捕获，App 未崩溃

    asyncio.run(sc())


def test_tui_migrated_exit_still_works():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.submit("/exit")
            await pilot.pause()
            assert app.is_running is False

    asyncio.run(sc())


def test_tui_migrated_plan_still_works():
    async def sc():
        mock = MockAgent()
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.agent = mock
            await app.submit("/plan")
            await pilot.pause()
            assert app.mode() == Mode.PLAN
            assert "已切换到 PLAN 模式" in _log_text(app)
            assert mock.run_calls == 0
            assert len(app.conv.messages()) == 0

    asyncio.run(sc())


def test_tui_migrated_do_still_works():
    async def sc():
        mock = MockAgent()
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.agent = mock
            await app.submit("/do")
            task = app._stream_task
            if task is not None:
                await task
            await pilot.pause()
            assert app.mode() == Mode.DEFAULT
            assert len(app.conv.messages()) == 1
            assert app.conv.messages()[0].content == EXECUTE_DIRECTIVE
            assert mock.run_calls == 1

    asyncio.run(sc())
