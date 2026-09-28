"""Skill 启动期接线测试（docs/ch11 T28）与 TUI 侧 UI 方法（T27）。

按 cli 的真实装配顺序走一遍：扫 Catalog → 注册两个 Skill 工具 → fail-fast 检查
→ 建 App → 查名字冲突 → 注册 Skill 命令。不启动 Textual 事件循环。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from mewcode.agent import SessionRuntime
from mewcode.command import (
    Kind,
    Registry,
    SkillSummary,
    register_builtins,
    register_skills_as_commands,
)
from mewcode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from mewcode.permission import new_engine
from mewcode.skills import Catalog, Executor
from mewcode.tool import new_default_registry
from mewcode.tool.install_skill import InstallSkillTool
from mewcode.tool.load_skill import LoadSkillTool


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def _skill(base: Path, name: str, extra: str = "", body: str = "SOP") -> None:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} 描述\n{extra}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _runtime() -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(tempfile.mkdtemp()),
        context_window=200000,
    )


def wire(tmp_path):
    """复刻 cli 的 Skill 装配段，返回 (catalog, registry, cmd_reg, executor)。"""
    work = tmp_path / "work"
    runtime = _runtime()
    registry = new_default_registry()
    catalog = Catalog.load(work)
    registry.register(LoadSkillTool(catalog, runtime.active_skills, registry))
    registry.register(InstallSkillTool(catalog, work))

    for issue in catalog.validate_tools(registry):
        print(
            f'skill {issue.skill_name}: allowed_tool "{issue.tool_name}" not registered, skipped',
            file=sys.stderr,
        )
        catalog.remove(issue.skill_name)

    engine, _ = new_engine(str(tmp_path))
    executor = Executor(catalog, registry, engine, "test", runtime)

    cmd_reg = Registry()
    register_builtins(cmd_reg)
    register_skills_as_commands(
        cmd_reg,
        [
            SkillSummary(s.meta.name, s.meta.description, str(s.source), s.meta.mode)
            for s in catalog.list()
        ],
        executor,
    )
    return catalog, registry, cmd_reg, executor


def test_both_skill_tools_registered(tmp_path, home):
    _, registry, _, _ = wire(tmp_path)
    assert registry.get("load_skill") is not None
    assert registry.get("install_skill") is not None
    assert registry.is_system("load_skill") is True
    assert registry.is_system("install_skill") is False
    assert registry.is_read_only("load_skill") is True


def test_builtin_skills_become_commands(tmp_path, home):
    """三个内置 Skill 注册成 /commit /review /test（AC1/AC2）。"""
    catalog, _, cmd_reg, _ = wire(tmp_path)
    for name in ("commit", "review", "test"):
        cmd = cmd_reg.lookup(name)
        assert cmd is not None, name
        assert cmd.kind is Kind.PROMPT
        assert cmd.is_skill is True
        assert cmd.description.endswith("[skill]")
    # 内置 /review 已让位给 Skill 版
    assert cmd_reg.lookup("review").is_skill is True
    # /skill 与 /help 仍在
    assert cmd_reg.lookup("skill") is not None
    assert cmd_reg.lookup("help") is not None


def test_missing_tool_skill_dropped_at_startup(tmp_path, home, capsys):
    """allowed_tools 引用未注册工具 → stderr 报错 + 从 Catalog 剔除（AC10）。"""
    work = tmp_path / "work"
    _skill(work / ".mewcode" / "skills", "broken", "allowed_tools: [NotExist]")
    catalog, _, cmd_reg, _ = wire(tmp_path)

    assert "broken" not in catalog.names()
    assert cmd_reg.lookup("broken") is None
    err = capsys.readouterr().err
    assert 'skill broken: allowed_tool "NotExist" not registered, skipped' in err


def test_load_skill_reference_is_allowed(tmp_path, home):
    """allowed_tools 里写 load_skill / install_skill 不算缺失（F15）。"""
    work = tmp_path / "work"
    _skill(work / ".mewcode" / "skills", "sysonly", "allowed_tools: [load_skill, install_skill]")
    catalog, _, cmd_reg, _ = wire(tmp_path)
    assert "sysonly" in catalog.names()
    assert cmd_reg.lookup("sysonly") is not None


def test_project_skill_command_registered_and_dispatchable(tmp_path, home):
    """项目级自定义 Skill 可被 /<name> 调到（AC21 的命令面）。"""
    import asyncio

    from mewcode.command import NopUI

    work = tmp_path / "work"
    _skill(work / ".mewcode" / "skills", "my-skill", "mode: inline", "自定义 SOP")

    class UI(NopUI):
        def __init__(self) -> None:
            self.injections: list[tuple[str, str]] = []

        def inject_and_send(self, label: str, prompt: str) -> None:
            self.injections.append((label, prompt))

    _, _, cmd_reg, _ = wire(tmp_path)
    ui = UI()
    asyncio.run(cmd_reg.lookup("my-skill").handler(ui))
    assert ui.injections[0][0] == "/my-skill"
    assert "自定义 SOP" in ui.injections[0][1]


def test_app_ui_methods(tmp_path, home):
    """TUI 侧 UI 方法：catalog 列表 / 激活列表 / 清空 / 回流 / 取消息。"""
    from mewcode.tui.app import MewCodeApp

    catalog = Catalog.load(tmp_path / "work")
    app = MewCodeApp([], registry=new_default_registry(), runtime=_runtime(), catalog=catalog)
    app.catalog = catalog

    names = [s.name for s in app.list_catalog_skills()]
    assert names == ["commit", "review", "test"]
    assert app.list_catalog_skills()[0].description == catalog.get("commit").meta.description

    assert app.list_active_skills() == []
    app.runtime.active_skills.activate("commit", "SOP")
    assert app.list_active_skills() == ["commit"]
    app.clear_active_skills()
    assert app.list_active_skills() == []

    app.conv.add_user("问题")
    assert [m.content for m in app.all_messages()] == ["问题"]
    assert app.recent_messages(1)[0].content == "问题"
    assert app.recent_messages(0) == []


def test_app_without_catalog_degrades(tmp_path, home):
    """未注入 catalog 的 App（测试构造路径）应零值退化，不抛异常。"""
    from mewcode.tui.app import MewCodeApp

    app = MewCodeApp([], registry=new_default_registry(), runtime=_runtime())
    assert app.list_catalog_skills() == []
    assert app.list_active_skills() == []


def test_conflicting_skill_dropped(tmp_path, home, capsys):
    """与内置命令同名的 Skill 不加载（F16）。"""
    from mewcode.cli import _drop_conflicting_skills

    work = tmp_path / "work"
    _skill(work / ".mewcode" / "skills", "help")
    catalog = Catalog.load(work)
    assert "help" in catalog.names()

    cmd_reg = Registry()
    register_builtins(cmd_reg)
    _drop_conflicting_skills(catalog, cmd_reg)

    assert "help" not in catalog.names()
    assert cmd_reg.lookup("help").is_skill is False  # 内置未被顶掉
    assert "conflicts with builtin command" in capsys.readouterr().err
