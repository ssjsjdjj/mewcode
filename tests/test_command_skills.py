"""Skill 命令注册与 /skill 命令测试（docs/ch11 T23/T24，F18–F20/F16/F34）。"""

from __future__ import annotations

from mewcode.command import (
    Command,
    Kind,
    NopUI,
    Registry,
    SkillSummary,
    register_skills_as_commands,
    remove_skill_commands,
)
from mewcode.command.builtin_skill import handle_skill
from mewcode.command.builtin_ui import handle_clear
from mewcode.permission import Mode


class RecordingUI(NopUI):
    """记录调用顺序的可观测桩。"""

    def __init__(self) -> None:
        self.printed: list[str] = []
        self.calls: list[str] = []
        self.catalog: list[SkillSummary] = []

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def list_catalog_skills(self) -> list[SkillSummary]:
        return list(self.catalog)

    def clear_active_skills(self) -> None:
        self.calls.append("clear_active_skills")

    async def clear_and_new_session(self) -> None:
        self.calls.append("clear_and_new_session")


class Runner:
    """记录被要求执行哪个 Skill。"""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def execute(self, name: str, args: str, ui) -> None:  # noqa: ANN001
        self.seen.append((name, args))


def _summaries(*names: str) -> list[SkillSummary]:
    return [SkillSummary(name=n, description=f"{n} 的描述") for n in names]


def test_registers_as_prompt_commands_with_tag():
    reg = Registry()
    runner = Runner()
    done = register_skills_as_commands(reg, _summaries("commit", "review"), runner)
    assert done == ["commit", "review"]

    cmd = reg.lookup("commit")
    assert cmd is not None
    assert cmd.kind is Kind.PROMPT
    assert cmd.is_skill is True
    assert cmd.description == "commit 的描述 [skill]"
    assert cmd.hidden is False
    assert [c.name for c in reg.visible()] == ["commit", "review"]


async def test_each_command_dispatches_its_own_skill():
    """闭包绑定：每个命令必须指向自己的 Skill，而不是全部指向最后一个。"""
    reg = Registry()
    runner = Runner()
    register_skills_as_commands(reg, _summaries("commit", "review", "test"), runner)

    ui = NopUI()
    await reg.lookup("commit").handler(ui)
    await reg.lookup("review").handler(ui)
    await reg.lookup("test").handler(ui)
    assert runner.seen == [("commit", ""), ("review", ""), ("test", "")]


def test_name_conflict_with_builtin_is_skipped(capsys):
    """与既有命令同名/撞别名的 Skill 跳过并告警（F16）。"""
    reg = Registry()

    async def noop(ui) -> None:  # noqa: ANN001
        return None

    reg.register(Command("help", "内置帮助", Kind.LOCAL, noop, aliases=["h"]))
    done = register_skills_as_commands(reg, _summaries("help", "h", "ok"), Runner())

    assert done == ["ok"]
    assert reg.lookup("help").description == "内置帮助"  # 内置未被顶掉
    err = capsys.readouterr().err
    assert "help conflicts with an existing command" in err
    assert "h conflicts with an existing command" in err


def test_remove_skill_commands_only_removes_skills():
    reg = Registry()

    async def noop(ui) -> None:  # noqa: ANN001
        return None

    reg.register(Command("builtin", "内置", Kind.LOCAL, noop))
    register_skills_as_commands(reg, _summaries("commit", "review"), Runner())

    removed = remove_skill_commands(reg)
    assert removed == 2
    assert reg.lookup("commit") is None and reg.lookup("review") is None
    assert reg.lookup("builtin") is not None
    assert [c.name for c in reg.visible()] == ["builtin"]
    assert remove_skill_commands(reg) == 0  # 幂等


def test_registry_remove_if_clears_all_aliases():
    reg = Registry()

    async def noop(ui) -> None:  # noqa: ANN001
        return None

    reg.register(Command("a", "d", Kind.LOCAL, noop, aliases=["aa", "aaa"]))
    reg.register(Command("b", "d", Kind.LOCAL, noop))
    assert reg.remove_if(lambda c: c.name == "a") == 1
    for key in ("a", "aa", "aaa"):
        assert reg.lookup(key) is None
    assert reg.lookup("b") is not None
    assert [c.name for c in reg.visible()] == ["b"]


def test_registry_remove_if_keeps_visible_sorted():
    reg = Registry()

    async def noop(ui) -> None:  # noqa: ANN001
        return None

    for n in ("alpha", "beta", "gamma", "delta"):
        reg.register(Command(n, "d", Kind.LOCAL, noop))
    reg.remove_if(lambda c: c.name == "beta")
    assert [c.name for c in reg.visible()] == ["alpha", "delta", "gamma"]


async def test_skill_command_empty(capsys):
    ui = RecordingUI()
    await handle_skill(ui)
    assert ui.printed == ["No skills loaded."]


async def test_skill_command_lists_sorted_with_footer():
    ui = RecordingUI()
    ui.catalog = _summaries("review", "commit", "test")
    await handle_skill(ui)

    assert ui.printed[0] == "Available skills (3):"
    assert ui.printed[1] == f"  /{'commit':<20} commit 的描述"
    assert ui.printed[2] == f"  /{'review':<20} review 的描述"
    assert ui.printed[3] == f"  /{'test':<20} test 的描述"
    assert ui.printed[-1] == "Type /<skill-name> to invoke a skill."


async def test_clear_order_active_skills_before_new_session():
    """/clear 必须先清激活列表再新建会话（F25/N9）——顺序反过来就不满足要求。"""
    ui = RecordingUI()
    await handle_clear(ui)
    assert ui.calls == ["clear_active_skills", "clear_and_new_session"]


def test_nop_ui_skill_methods_are_zero_valued():
    ui = NopUI()
    assert ui.list_catalog_skills() == []
    assert ui.list_active_skills() == []
    assert ui.recent_messages(5) == []
    assert ui.all_messages() == []
    ui.clear_active_skills()
    ui.append_assistant_message("x")  # 不抛


def test_ui_mode_still_works():
    assert NopUI().mode() is Mode.DEFAULT
