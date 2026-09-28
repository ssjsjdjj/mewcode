"""Catalog / ActiveSkills → prompt 包的桥接类型（docs/ch11 T9）。

prompt 包不反向依赖 skills 包，所以这里定义中性的桥接结构；prompt 侧的渲染
函数按鸭子类型读 `.name` / `.description` / `.body`，调用点无需二次转换。
"""

from __future__ import annotations

from dataclasses import dataclass

from .active import ActiveSkills
from .catalog import Catalog


@dataclass(frozen=True)
class PromptItem:
    """第一阶段 `skills-catalog` 列表的一行（name + description）。"""

    name: str
    description: str


@dataclass(frozen=True)
class PromptEntry:
    """第二阶段 `active-skills` 块的一项（name + SOP 正文）。"""

    name: str
    body: str


def catalog_to_prompt_items(c: Catalog) -> list[PromptItem]:
    """按 Catalog 的稳定迭代序输出（F21）。"""
    return [PromptItem(p.meta.name, p.meta.description) for p in c.list()]


def active_to_prompt_entries(a: ActiveSkills) -> list[PromptEntry]:
    """按激活顺序输出（F22）。"""
    return [PromptEntry(e.name, e.body) for e in a.snapshot()]
