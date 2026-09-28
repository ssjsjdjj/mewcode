"""12 条内置命令注册与 NopUI/RecordingUI 调用测试（docs/ch10 T8）。"""

from __future__ import annotations

import pytest

from mewcode import prompt
from mewcode.command.builtin_local import handle_status
from mewcode.command.builtin_prompt import handle_do
from mewcode.command.builtin_ui import handle_compact
from mewcode.command.builtins import register_builtins
from mewcode.command.registry import Registry
from mewcode.command.ui import NopUI
from mewcode.permission import Mode

BUILTIN_NAMES = [
    "clear",
    "compact",
    "do",
    "exit",
    "help",
    "memory",
    "permission",
    "plan",
    "resume",
    "review",
    "session",
    "status",
]


def _reg() -> Registry:
    reg = Registry()
    register_builtins(reg)
    return reg


def test_register_builtins_all_registered():
    reg = _reg()
    visible = reg.visible()
    assert len(visible) == 12
    assert [c.name for c in visible] == sorted(BUILTIN_NAMES)


def test_register_builtins_no_collision():
    _reg()  # 直接调用不抛 RuntimeError


@pytest.mark.asyncio
async def test_register_builtins_handlers_run_on_nop_ui():
    reg = _reg()
    ui = NopUI()
    for cmd in reg.visible():
        await cmd.handler(ui)  # 全部 handler 在 NopUI 上不抛


class RecordingUI(NopUI):
    """记录 println/error/set_mode/inject_and_send 调用的可观测桩。"""

    def __init__(self) -> None:
        self.printed: list[str] = []
        self.errors: list[str] = []
        self.modes: list[Mode] = []
        self.injections: list[tuple[str, str]] = []
        self.busy = False

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def set_mode(self, m: Mode) -> None:
        self.modes.append(m)

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        self.injections.append((display_label, preset_prompt))

    def idle(self) -> bool:
        return not self.busy


@pytest.mark.asyncio
async def test_handle_status_prints_all_keys():
    ui = RecordingUI()
    await handle_status(ui)
    assert len(ui.printed) == 1
    for key in ("Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:"):
        assert key in ui.printed[0]


@pytest.mark.asyncio
async def test_handle_compact_blocks_when_busy():
    ui = RecordingUI()
    ui.busy = True
    await handle_compact(ui)
    assert ui.errors == ["请等待当前任务完成"]


@pytest.mark.asyncio
async def test_handle_do_sets_mode_and_injects():
    ui = RecordingUI()
    await handle_do(ui)
    assert ui.modes == [Mode.DEFAULT]
    assert ui.injections and ui.injections[0][0] == "/do"
    assert ui.injections[0][1] == prompt.EXECUTE_DIRECTIVE
