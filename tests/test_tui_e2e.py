"""ch10 T15 端到端场景（Windows 无 tmux：用 Textual headless run_test 等价模拟）。

覆盖 checklist 端到端场景：
- A2 /help 输出 12 条命令名
- B1 /status 输出 6 字段 key
- C1 输入 / 弹补全菜单（12 条候选、可见行 ≤ MAX_ROWS）
- C2 输入 /s 过滤为 /session、/status
- C3 ↓ 切高亮、回车执行次条
- C4 回车执行 /status 出 6 字段
- C5 Esc 菜单消失、输入框文本保留
- C6 退格清空后菜单消失
- D1 /plan 切到 PLAN
- G1 未知命令提示"未知命令"与"/help"、不进对话历史
- H1 启动期同名命令冲突立即抛 RuntimeError
"""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Static

from mewcode.command.builtins import register_builtins
from mewcode.command.command import Command, Kind
from mewcode.command.registry import Registry
from mewcode.permission import Mode
from mewcode.tui import ChatInput
from mewcode.tui.complete import MAX_ROWS, CompletionMenu

from test_tui import BUILTIN_NAMES, _log_text, _tui_app


def _completion_text(app) -> str:
    """#completion Static 当前渲染的纯文本。"""
    w = app.query_one("#completion", Static)
    rendered = w.render()
    return getattr(rendered, "plain", str(rendered))


async def _type(app, pilot, text: str) -> None:
    """等价 pilot.type：Textual 8.2.8 Pilot 无 .type，用 TextArea.insert 逐字符驱动。"""
    input_ = app.query_one("#chat-input", ChatInput)
    for ch in text:
        input_.insert(ch)
        await pilot.pause()  # 让每个变更事件被 on_text_area_changed 消费
    await pilot.pause()


def test_e2e_help_lists_all_builtins():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/help")
            await pilot.press("enter")
            await pilot.pause()
            log = _log_text(app)
            for name in BUILTIN_NAMES:
                assert f"/{name}" in log

    asyncio.run(sc())


def test_e2e_status_six_fields():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/status")
            await pilot.press("enter")
            await pilot.pause()
            log = _log_text(app)
            for key in ("Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:"):
                assert key in log

    asyncio.run(sc())


def test_e2e_slash_pops_menu_with_all_builtins():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/")
            assert app.completion.active is True
            assert len(app.completion.items) == 13  # ch12 追加 /hooks
            assert _completion_text(app) != ""

    asyncio.run(sc())


def test_e2e_s_filters_to_matching_commands():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/s")
            assert app.completion.active is True
            # ch11 起 /skill 也以 s 起头，故为三项
            assert [c.name for c in app.completion.items] == ["session", "skill", "status"]

    asyncio.run(sc())


def test_e2e_down_enter_executes_selected():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/s")
            await pilot.press("down")  # [session, skill, status] → skill
            await pilot.pause()
            assert app.completion.selected() is not None
            assert app.completion.selected().name == "skill"
            await pilot.press("down")  # → status
            await pilot.pause()
            assert app.completion.selected().name == "status"
            await pilot.press("enter")
            await pilot.pause()
            assert "Mode:" in _log_text(app)  # /status 的特征输出

    asyncio.run(sc())


def test_e2e_escape_keeps_input():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/s")
            await pilot.press("escape")
            await pilot.pause()
            assert app.completion.active is False
            assert app.input_area.text == "/s"  # 输入框文本保留

    asyncio.run(sc())


def test_e2e_backspace_clears_menu():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/s")
            assert app.completion.active is True
            await pilot.press("backspace")
            await pilot.pause()
            await pilot.press("backspace")
            await pilot.pause()
            assert app.completion.active is False  # 不以 / 开头 → 菜单隐藏

    asyncio.run(sc())


def test_e2e_plan_switches_mode():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/plan")
            await pilot.press("enter")
            await pilot.pause()
            assert app.mode() == Mode.PLAN
            assert "已切换到 PLAN 模式" in _log_text(app)

    asyncio.run(sc())


def test_e2e_unknown_command_hints():
    async def sc():
        app = _tui_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _type(app, pilot, "/foobar")
            await pilot.press("enter")  # 无候选 → 菜单不吞回车，原样提交
            await pilot.pause()
            assert "未知命令" in _log_text(app) and "/help" in _log_text(app)
            assert len(app.conv.messages()) == 0  # 不进对话历史

    asyncio.run(sc())


def test_e2e_startup_conflict_detected():
    """H1：临时把 /help 注册两次，启动应抛 RuntimeError 且消息含命令名。"""
    reg = Registry()
    register_builtins(reg)
    with pytest.raises(RuntimeError) as exc:

        async def _dup(ui):
            pass

        reg.register(Command(name="help", description="dup", kind=Kind.LOCAL, handler=_dup))
    assert "help" in str(exc.value)


def test_menu_render_caps_at_max_rows():
    """C1 补充：12 条候选可见行 ≤ MAX_ROWS；连按 ↓ 越界后出现 ↑/↓ more。"""
    reg = Registry()
    register_builtins(reg)
    menu = CompletionMenu()
    menu.update("/", reg)
    lines = menu.render(80).splitlines()
    # 只统计候选行（以 / 或 reverse 高亮开头），排除 [/dim] 关闭标签与 more 提示
    candidate_lines = [ln for ln in lines if ln.startswith("/") or ln.startswith("[reverse]/")]
    assert len(candidate_lines) <= MAX_ROWS
    for _ in range(MAX_ROWS + 2):
        menu.move_down()
    tail = menu.render(80)
    assert "more" in tail
    assert menu.offset > 0
