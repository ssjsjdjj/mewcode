"""ch12 端到端：从真实 hooks.yaml 文件到可观察行为（docs/ch12 T25）。

与逐模块单测的区别在于这里**不手工构造 Rule**——写一份 `.mewcode/hooks.yaml`，
走 `hook.load()` 解析，再交给真实 App / Agent 跑，覆盖「配置写对了没」这一层。
本机无 tmux，按项目既有做法用 Textual headless 等价模拟。

覆盖 AC4（PreToolUse 拦截）、AC6（SessionStart 注入）、AC10（UserPromptSubmit 拦截）、
AC8（async + 拦截类被拒）、AC12（两层合并 + /hooks 来源）。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from mewcode import hook
from mewcode.llm import Request, StreamEvent, ToolCall
from mewcode.tool import new_default_registry
from mewcode.tui import ChatInput
from mewcode.tui.app import MewCodeApp

from test_tui import _test_runtime, cfg


class FakeProvider:
    """按帧脚本回放的假 provider，并记录完整 Request（要断言 reminder）。

    自带而非复用 test_agent 的：pytest 只把测试文件所在目录加进 sys.path，
    `tests/` 下的文件引不到 `tests/agent/test_agent.py`。
    """

    def __init__(self, scripts: list[list[StreamEvent]] | None = None) -> None:
        self._scripts = list(scripts or [[]])
        self.calls = 0
        self.received: list[Request] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request):
        self.received.append(req)
        idx = self.calls
        self.calls += 1
        frames = self._scripts[idx] if idx < len(self._scripts) else [StreamEvent(text="ok")]
        for frame in frames:
            yield frame
        if not any(f.done for f in frames):
            yield StreamEvent(done=True)


PY = f'"{sys.executable}"'


def write_hooks(root: Path, text: str) -> None:
    p = root / ".mewcode" / "hooks.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


HOOKS_YAML = f"""
hooks:
  - name: greet
    event: SessionStart
    action:
      type: prompt
      text: "记得用 zh-CN 回复"

  - name: block-writes
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {{type: exact, value: write_file}}
    action:
      type: shell
      command: '{PY} -c "import sys; print(''写文件被拦'', file=sys.stderr); sys.exit(2)"'

  - name: block-delete-prompts
    event: UserPromptSubmit
    if:
      any_of:
        - field: prompt
          match: {{type: regex, value: "(?i)delete"}}
    action:
      type: shell
      command: '{PY} -c "import sys; print(''别删'', file=sys.stderr); sys.exit(2)"'

  - name: not-skipped
    event: PostToolUse
    async: false
    action:
      type: prompt
      text: "工具跑完了"
"""


def make_app(root: Path, provider) -> MewCodeApp:
    engine = hook.load(root)
    return MewCodeApp(
        [cfg()],
        provider=provider,
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


async def wait_turn_done(app, pilot, timeout: float = 20.0) -> None:
    """等本轮真正跑完。

    hook 的 shell 动作要起真子进程（Windows 上每次上百毫秒），`pilot.pause()` 是
    紧的空转、不给真实时间，所以要按墙钟轮询；否则 App 会在回合未完时被拆除，
    `query_one` 报 NoMatches。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app.state.name == "IDLE" and app._stream_task is None:
            return
        await asyncio.sleep(0.02)
        await pilot.pause()
    raise AssertionError(f"turn did not finish within {timeout}s")


def test_e2e_ac6_session_start_prompt_in_first_request(tmp_path, monkeypatch):
    """AC6：SessionStart 的 prompt 进第一轮请求的 reminder，之后不再注入。"""
    monkeypatch.chdir(tmp_path)
    write_hooks(tmp_path, HOOKS_YAML)

    async def sc():
        provider = FakeProvider([[StreamEvent(text="你好")]])
        app = make_app(tmp_path, provider)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()
            await type_text(app, pilot, "第一句")
            await pilot.press("enter")
            await wait_turn_done(app, pilot)

            assert provider.received, "应发出过请求"
            assert "记得用 zh-CN 回复" in provider.received[0].reminder

    asyncio.run(sc())


def test_e2e_ac10_user_prompt_submit_blocks(tmp_path, monkeypatch):
    """AC10：含 delete 的输入被拦，输入框保留、历史不写。"""
    monkeypatch.chdir(tmp_path)
    write_hooks(tmp_path, HOOKS_YAML)

    async def sc():
        provider = FakeProvider([[StreamEvent(text="不该走到这")]])
        app = make_app(tmp_path, provider)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()
            await type_text(app, pilot, "请帮我 delete 那个文件")
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()

            assert [m for m in app.conv.messages() if m.role == "user"] == []
            assert app.input_area.text == "请帮我 delete 那个文件"
            assert provider.received == []  # 没发出请求

    asyncio.run(sc())


def test_e2e_ac10_non_matching_prompt_passes(tmp_path, monkeypatch):
    """条件不命中的输入照常放行（any_of 只匹配 delete）。"""
    monkeypatch.chdir(tmp_path)
    write_hooks(tmp_path, HOOKS_YAML)

    async def sc():
        provider = FakeProvider([[StreamEvent(text="好的")]])
        app = make_app(tmp_path, provider)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()
            await type_text(app, pilot, "帮我看看代码")
            await pilot.press("enter")
            await wait_turn_done(app, pilot)
            users = [m for m in app.conv.messages() if m.role == "user"]
            assert [m.content for m in users] == ["帮我看看代码"]
            assert provider.received  # 真的跑了一轮

    asyncio.run(sc())


def test_e2e_ac4_pre_tool_use_blocks_write(tmp_path, monkeypatch):
    """AC4：LLM 请求写文件被 hook 拦下，文件不存在，tool_result 带原因。"""
    monkeypatch.chdir(tmp_path)
    write_hooks(tmp_path, HOOKS_YAML)

    async def sc():
        provider = FakeProvider(
            [
                [
                    StreamEvent(
                        tool_calls=[
                            ToolCall(
                                id="1",
                                name="write_file",
                                input='{"path": "should-not-exist.txt", "content": "x"}',
                            )
                        ]
                    )
                ],
                [StreamEvent(text="好的，我没写")],
            ]
        )
        app = make_app(tmp_path, provider)
        async with app.run_test() as pilot:
            for _ in range(5):
                await pilot.pause()
            await type_text(app, pilot, "写个文件")
            await pilot.press("enter")
            await wait_turn_done(app, pilot)

        assert not (tmp_path / "should-not-exist.txt").exists()
        tool_msgs = [m for m in app.conv.messages() if m.role == "tool"]
        assert tool_msgs
        assert tool_msgs[-1].tool_results[0].content == "[hook block-writes] 写文件被拦"

    asyncio.run(sc())


def test_e2e_ac8_async_on_blocking_event_skipped(tmp_path, monkeypatch, capsys):
    """AC8：拦截类事件写 async → 该条被跳过并报 stderr，其余照常。"""
    monkeypatch.chdir(tmp_path)
    write_hooks(
        tmp_path,
        """
hooks:
  - name: bad-async
    event: PreToolUse
    async: true
    action: {type: shell, command: "true"}
  - name: good
    event: Stop
    action: {type: prompt, text: ok}
""",
    )
    engine = hook.load(tmp_path)
    assert [r.name for r in engine.rules] == ["good"]
    assert "async not allowed for blocking events" in capsys.readouterr().err


def test_e2e_ac12_two_layers_and_hooks_command(tmp_path, monkeypatch):
    """AC12：两层合并，`/hooks` 末尾列出来源文件。"""
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    (home / ".mewcode").mkdir(parents=True)
    (home / ".mewcode" / "hooks.yaml").write_text(
        "hooks:\n  - {name: user-level, event: Stop, action: {type: prompt, text: u}}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    write_hooks(tmp_path, HOOKS_YAML)

    engine = hook.load(tmp_path)
    names = [r.name for r in engine.rules]
    assert names == ["greet", "block-writes", "block-delete-prompts", "not-skipped", "user-level"]
    assert len(engine.sources) == 2

    async def sc():
        app = make_app(tmp_path, FakeProvider())
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.dispatch_slash("/hooks")
            for _ in range(3):
                await pilot.pause()
            log = "\n".join(str(x) for x in app.query_one("#log").lines)
            assert "greet  SessionStart  prompt" in log
            assert "block-writes  PreToolUse  shell" in log
            assert "Loaded from:" in log and "hooks.yaml" in log

    asyncio.run(sc())


def test_e2e_hooks_absent_is_silent(tmp_path, monkeypatch, capsys):
    """没有 hooks.yaml 时静默启动、/hooks 报空（F6/N9）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    engine = hook.load(tmp_path)
    assert engine.rules == [] and engine.sources == []
    assert capsys.readouterr().err == ""

    async def sc():
        app = make_app(tmp_path, FakeProvider())
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.dispatch_slash("/hooks")
            await pilot.pause()
            log = "\n".join(str(x) for x in app.query_one("#log").lines)
            assert "No hooks loaded." in log

    asyncio.run(sc())
