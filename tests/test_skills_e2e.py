"""ch11 端到端场景（Windows 无 tmux：用 Textual headless run_test 等价模拟）。

沿 test_tui_e2e.py 的既有做法覆盖 checklist 的端到端流程：
- 启动即三个内置 Skill、`/skill` 列表格式
- `/help` 含 /skill 与三个 [skill] 命令
- `/commit` inline 注入 SOP；`/review` fork 回流 assistant 消息
- LoadSkill 激活后，下一轮请求的 env context 出现 active-skills 块（F22 关键）
- `/clear` 清空激活列表但 Catalog 不受影响
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.command import SkillSummary, register_builtins, register_skills_as_commands
from mewcode.command.registry import Registry
from mewcode.config import ProviderConfig
from mewcode.llm import Request, StreamEvent
from mewcode.permission import new_engine
from mewcode.skills import Catalog, Executor
from mewcode.tool import new_default_registry
from mewcode.tool.install_skill import InstallSkillTool
from mewcode.tool.load_skill import LoadSkillTool
from mewcode.tui import ChatInput
from mewcode.tui.app import MewCodeApp

from test_tui import _log_text, _test_runtime


class SpyProvider:
    """记录完整 Request 的假 provider（要断言 system/env 内容）。"""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.received: list[Request] = []
        self._replies = list(replies or ["好的"])

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request):
        self.received.append(req)
        text = self._replies.pop(0) if self._replies else "收到"
        yield StreamEvent(text=text)
        yield StreamEvent(done=True)


def cfg() -> ProviderConfig:
    return ProviderConfig(name="fake", protocol="openai", api_key="k", model="fake-model")


def build_app(tmp_path: Path, provider: SpyProvider) -> MewCodeApp:
    """按 cli 的装配顺序搭一个带 Skill 的 App。"""
    work = tmp_path / "work"
    runtime = _test_runtime()
    registry = new_default_registry()
    catalog = Catalog.load(work)
    registry.register(LoadSkillTool(catalog, runtime.active_skills, registry))
    registry.register(InstallSkillTool(catalog, work))
    engine, _ = new_engine(str(tmp_path))
    executor = Executor(catalog, registry, engine, "test", runtime, provider=provider)

    app = MewCodeApp(
        [cfg()],
        provider=provider,
        registry=registry,
        engine=engine,
        runtime=runtime,
        catalog=catalog,
        executor=executor,
    )
    register_skills_as_commands(
        app.cmd_registry,
        [
            SkillSummary(s.meta.name, s.meta.description, str(s.source), s.meta.mode)
            for s in catalog.list()
        ],
        executor,
    )
    return app


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


async def _type(app, pilot, text: str) -> None:
    input_ = app.query_one("#chat-input", ChatInput)
    for ch in text:
        input_.insert(ch)
        await pilot.pause()
    await pilot.pause()


def test_e2e_startup_has_three_builtin_skills(tmp_path, home):
    async def sc():
        provider = SpyProvider()
        app = build_app(tmp_path, provider)
        async with app.run_test() as pilot:
            await pilot.pause()
            names = [s.name for s in app.list_catalog_skills()]
            assert names == ["commit", "review", "test"]
            assert app.list_active_skills() == []
            assert app.state.name == "IDLE"

    asyncio.run(sc())


def test_e2e_help_lists_skill_commands(tmp_path, home):
    async def sc():
        app = build_app(tmp_path, SpyProvider())
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/help")
            await pilot.press("enter")
            await pilot.pause()
            log = _log_text(app)
            assert "/skill" in log
            for name in ("commit", "review", "test"):
                assert f"/{name}" in log

    asyncio.run(sc())


def test_e2e_skill_command_lists_three(tmp_path, home):
    async def sc():
        app = build_app(tmp_path, SpyProvider())
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/skill")
            await pilot.press("enter")
            await pilot.pause()
            log = _log_text(app)
            assert "Available skills (3):" in log
            for name in ("commit", "review", "test"):
                assert f"/{name}" in log
            assert "Type /<skill-name> to invoke a skill." in log

    asyncio.run(sc())


def test_e2e_inline_commit_injects_sop(tmp_path, home):
    """`/commit` 走 inline：主对话新增一条含 commit SOP 的 user 消息（AC4）。"""

    async def sc():
        app = build_app(tmp_path, SpyProvider())
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/commit")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            user_msgs = [m for m in app.conv.messages() if m.role == "user"]
            assert any("git status" in m.content for m in user_msgs)
            assert any(
                "This skill is designed to use only these tools" in m.content for m in user_msgs
            )

    asyncio.run(sc())


def test_e2e_fork_review_appends_assistant(tmp_path, home):
    """`/review` 走 fork：跑完后主对话多一条 assistant 消息（AC3）。"""

    async def sc():
        provider = SpyProvider(["审查报告：未发现问题"])
        app = build_app(tmp_path, provider)
        async with app.run_test() as pilot:
            await pilot.pause()
            before = [m for m in app.conv.messages() if m.role == "assistant"]
            await _type(app, pilot, "/review")
            await pilot.press("enter")
            for _ in range(12):
                await pilot.pause()
            after = [m for m in app.conv.messages() if m.role == "assistant"]
            assert len(after) == len(before) + 1
            assert after[-1].content == "审查报告：未发现问题"
            assert "审查报告：未发现问题" in _log_text(app)

    asyncio.run(sc())


def test_e2e_load_skill_pins_sop_into_env(tmp_path, home):
    """LoadSkill 激活后，下一轮请求的 env context 出现 active-skills 块（F22/AC6）。

    这是两阶段加载的关键断言：env 必须**同轮内**就能带上 SOP，而不是等下一轮。
    """

    async def sc():
        provider = SpyProvider(["回答一", "回答二"])
        app = build_app(tmp_path, provider)
        async with app.run_test() as pilot:
            await pilot.pause()
            # 第一轮：还没激活任何 Skill
            app.inject_and_send("test", "第一问")
            for _ in range(8):
                await pilot.pause()
            first_env = provider.received[0].system.environment
            assert "## Active Skills" not in first_env
            assert "## Available Skills" in provider.received[0].system.stable

            # 模拟模型调 LoadSkill
            r = await app.tool_registry.execute("load_skill", '{"name": "commit"}')
            assert r.is_error is False
            assert app.list_active_skills() == ["commit"]

            # 第二轮：env 里应带上 commit 的 SOP
            app.inject_and_send("test", "第二问")
            for _ in range(8):
                await pilot.pause()
            second = provider.received[-1]
            assert "## Active Skills" in second.system.environment
            assert "### Skill: commit" in second.system.environment
            assert "git status" in second.system.environment
            # SOP 不进对话历史，只走 env（N3）
            assert all("git status" not in m.content for m in app.conv.messages())

    asyncio.run(sc())


def test_e2e_clear_resets_active_but_keeps_catalog(tmp_path, home):
    """`/clear` 清激活列表，Catalog 保留（checklist 第 9 步）。"""

    async def sc():
        app = build_app(tmp_path, SpyProvider())
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.tool_registry.execute("load_skill", '{"name": "test"}')
            assert app.list_active_skills() == ["test"]

            await _type(app, pilot, "/clear")
            await pilot.press("enter")
            await pilot.pause()
            assert app.list_active_skills() == []
            assert [s.name for s in app.list_catalog_skills()] == ["commit", "review", "test"]

    asyncio.run(sc())


def test_builtins_after_skill_takeover():
    """内置命令表：仍是 12 条，但 /review 已让位、新增 /skill（AC2）。"""
    reg = Registry()
    register_builtins(reg)
    assert len(reg.visible()) == 12
    assert reg.lookup("review") is None  # 内置 /review 已删除，由同名 Skill 接管
    assert reg.lookup("skill") is not None


def test_e2e_tab_completion_offers_commit(tmp_path, home):
    """输入 /comm 时补全菜单出现 /commit [skill] 候选（checklist 第 5 节）。"""

    async def sc():
        app = build_app(tmp_path, SpyProvider())
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/comm")
            assert app.completion.active is True
            assert [c.name for c in app.completion.items] == ["commit"]
            assert app.completion.items[0].description.endswith("[skill]")

    asyncio.run(sc())


def test_load_skill_allowed_in_plan_mode(tmp_path, home):
    """Plan Mode 下 LoadSkill 仍可见且被放行（AC7）。

    可见性靠 `read_only_definitions()`（Plan 只导出只读工具），判定靠
    `categorize(read_only=True) -> Category.READ` 在任意模式都 ALLOW。
    """
    from mewcode.llm import ToolCall
    from mewcode.permission import Decision, Mode

    work = tmp_path / "work"
    runtime = _test_runtime()
    registry = new_default_registry()
    catalog = Catalog.load(work)
    registry.register(LoadSkillTool(catalog, runtime.active_skills, registry))

    names = [d.name for d in registry.read_only_definitions()]
    assert "load_skill" in names

    engine, _ = new_engine(str(tmp_path))
    call = ToolCall(id="1", name="load_skill", input='{"name":"commit"}')
    decision, _reason = engine.check(Mode.PLAN, call, read_only=True)
    assert decision is Decision.ALLOW
