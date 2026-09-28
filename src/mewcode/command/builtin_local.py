"""5 条纯本地命令：/help /status /memory /permission /session（docs/ch10 T5）。

纯本地类只向用户输出信息，不修改对话历史、不改运行模式、不消耗 token（F9）。
"""

from __future__ import annotations

from mewcode.command.command import Handler
from mewcode.command.registry import Registry
from mewcode.command.ui import UI


def make_help_handler(reg: Registry) -> Handler:
    """/help：按字典序输出所有可见命令的「名字 + 一句描述」两列对齐（F18/AC1）。"""

    async def _handler(ui: UI) -> None:
        commands = reg.visible()
        width = max((len(c.name) for c in commands), default=0)
        lines = [f"/{c.name.ljust(width)}  {c.description}" for c in commands]
        ui.println("\n".join(lines))

    return _handler


async def handle_status(ui: UI) -> None:
    """/status：六项 key:value 两列对齐（F19/AC4，渲染顺序固定）。"""
    keys = ["Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:"]
    width = max(len(k) for k in keys)
    # Mode 是 IntEnum，.value 为 0-3 整数；这里用 str() 取 "default"/"plan" 等名称
    # （docs/ch10 决策表声称 Mode.value 是枚举字符串，与实际 IntEnum 不符 → 用 str()）
    lines = [
        "MewCode Status",
        "",
        f"{'Mode:'.ljust(width)} {str(ui.mode())}",
        f"{'Tokens:'.ljust(width)} {ui.usage_in()} in / {ui.usage_out()} out",
        f"{'Tools:'.ljust(width)} {ui.tool_count()} enabled",
        f"{'Memories:'.ljust(width)} {len(ui.memory_files())} files",
        f"{'Model:'.ljust(width)} {ui.model_name()}",
        f"{'Directory:'.ljust(width)} {ui.cwd()}",
    ]
    ui.println("\n".join(lines))


async def handle_memory(ui: UI) -> None:
    """/memory：列出已加载的记忆文件名（F20/AC5，只列名不展开）。"""
    files = ui.memory_files()
    if not files:
        ui.println("无已加载的记忆文件")
        return
    ui.println("\n".join(files))


async def handle_permission(ui: UI) -> None:
    """/permission：输出当前权限模式名称（F21/AC6）。"""
    ui.println(str(ui.mode()))


async def handle_session(ui: UI) -> None:
    """/session：输出当前会话标识与存档路径（F22/AC7）。"""
    ui.println(f"Session: {ui.session_id()}\nPath: {ui.session_path()}")
