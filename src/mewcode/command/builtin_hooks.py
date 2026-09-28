"""`/hooks` 命令：列出已加载的 hook（docs/ch12 T21，F34/F35）。

按 event 分组排列（同一 event 的规则相邻），每行给出 name / event / action.type
与 `[once]` `[async]` 标志，末尾附加载来源文件——排查「我配的 hook 到底生效没」时
一眼能看出三件事：读到了吗、规则是什么、从哪个文件读的。
"""

from __future__ import annotations

from mewcode.command.ui import UI


def _flags(rule) -> str:  # noqa: ANN001
    marks = []
    if rule.only_once:
        marks.append("[once]")
    if rule.asyncio_mode:
        marks.append("[async]")
    return " ".join(marks)


async def handle_hooks(ui: UI) -> None:
    """/hooks：打印已加载的 hook 列表。"""
    rules = ui.hook_rules()
    if not rules:
        ui.println("No hooks loaded.")
        return

    # 按声明顺序分组：同一 event 的规则聚在一起，组内保持 yaml 顺序
    order: list[str] = []
    grouped: dict[str, list] = {}
    for rule in rules:
        key = rule.event.value
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(rule)

    for event_name in order:
        for rule in grouped[event_name]:
            line = f"  {rule.name}  {event_name}  {rule.action.type.value}"
            flags = _flags(rule)
            if flags:
                line = f"{line}  {flags}"
            ui.println(line)

    sources = ui.hook_sources()
    ui.println(f"Loaded from: {', '.join(sources) if sources else '(none)'}")
