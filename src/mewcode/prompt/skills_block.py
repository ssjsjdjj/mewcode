"""Skill 两阶段注入的文本渲染（docs/ch11 T11）。

- 第一阶段 `render_skills_catalog`：只列 name + description，进**稳定系统提示**
  （priority 90 槽位），落在 prompt cache 的稳定前缀区（F21/N2）
- 第二阶段 `render_active_skills_block`：拼已激活 Skill 的完整 SOP，进**环境上下文**
  尾部，每轮重装配（F22/N3）

两个函数在入参为空时都返回空串，由装配方跳过该块。入参按鸭子类型读
`.name` / `.description` / `.body`——skills 包的桥接类型与这里的 dataclass 都能直接传，
调用点无需二次转换。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

_LOAD_HINT = (
    'Call the LoadSkill tool with {"name": "<skill_name>"} to activate a skill\'s '
    "full SOP and specialized tools before executing it."
)


class _Named(Protocol):
    name: str


class _Described(_Named, Protocol):
    description: str


class _Bodied(_Named, Protocol):
    body: str


@dataclass(frozen=True)
class SkillCatalogItem:
    """第一阶段列表的一行。"""

    name: str
    description: str


@dataclass(frozen=True)
class ActiveSkillEntry:
    """第二阶段块的一项。"""

    name: str
    body: str


def render_skills_catalog(items: list[_Described]) -> str:
    """第一阶段：`## Available Skills` 列表 + LoadSkill 引导行。"""
    if not items:
        return ""
    lines = ["## Available Skills", ""]
    lines += [f"- {it.name}: {it.description}" for it in items]
    lines += ["", _LOAD_HINT]
    return "\n".join(lines)


def render_active_skills_block(entries: list[_Bodied]) -> str:
    """第二阶段：`## Active Skills` + 每个 Skill 的 SOP 正文。"""
    if not entries:
        return ""
    blocks = [f"### Skill: {e.name}\n\n{e.body}" for e in entries]
    return "\n\n".join(["## Active Skills", *blocks])
