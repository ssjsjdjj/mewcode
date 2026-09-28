"""`/skill` 命令：列出已加载的 Skill（docs/ch11 T22，F34/F35）。

只输出 name + description，按字典序、固定列宽对齐；source / mode 等元信息
本期不展示（开发者可直接读 SKILL.md）。逐条 `println` 而不是拼一个多行块，
避免 notice_block 的多行渲染产生多余空行。
"""

from __future__ import annotations

from mewcode.command.ui import UI

_NAME_WIDTH = 20
_FOOTER = "Type /<skill-name> to invoke a skill."


async def handle_skill(ui: UI) -> None:
    """/skill：打印 Catalog 中的全部 Skill。"""
    skills = ui.list_catalog_skills()
    if not skills:
        ui.println("No skills loaded.")
        return

    ui.println(f"Available skills ({len(skills)}):")
    for item in sorted(skills, key=lambda s: s.name):
        ui.println(f"  /{item.name:<{_NAME_WIDTH}} {item.description}")
    ui.println(_FOOTER)
