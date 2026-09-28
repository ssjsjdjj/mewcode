"""5 条影响界面命令：/exit /plan /compact /resume /clear（docs/ch10 T6）。

影响界面类可改运行时模式/清空会话/退出/触发恢复，但不向对话历史追加 user
消息（F10）。idle 守护由 dispatch_slash 按 Kind 统一做一次；handler 内再做
一次防御性检查（T8 的 RecordingUI 测试直接调用 handler 时需要）。
"""

from __future__ import annotations

from mewcode.command.ui import UI
from mewcode.permission import Mode


async def handle_exit(ui: UI) -> None:
    """/exit：关闭 TUI 进程（F12）。"""
    ui.quit()


async def handle_plan(ui: UI) -> None:
    """/plan：切换到计划模式（F13，行为与 ch08 一致）。"""
    ui.set_mode(Mode.PLAN)
    ui.println("已切换到 PLAN 模式")


async def handle_compact(ui: UI) -> None:
    """/compact：手动触发上下文压缩（F15）。"""
    if not ui.idle():
        ui.error("请等待当前任务完成")
        return
    ui.force_compact()


async def handle_resume(ui: UI) -> None:
    """/resume：打开历史会话列表（F16，仅 idle 可用）。"""
    if not ui.idle():
        ui.error("请等待当前任务完成")
        return
    ui.open_resume_menu()


async def handle_clear(ui: UI) -> None:
    """/clear：结束当前会话并开启新会话（F17/N9，旧存档保留可 /resume）。

    docs/ch11 F25/N9 额外要求：清空已激活 Skill 必须发生在**新建 session writer
    之前**，否则新会话首轮 env context 可能还带着上一会话的 SOP。与 ch10 里
    `discovery.reset()` 刻意放在新会话建立**之后**的语义相反，两处顺序都不要动。
    """
    ui.clear_active_skills()
    await ui.clear_and_new_session()
    ui.println("已清空当前会话,开启新 session")
