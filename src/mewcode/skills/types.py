"""Skill 技能包类型定义（docs/ch11 T1）。

四种来源按扫描顺序排列，后者覆盖前者：内置 < 用户级 < 项目级（F12/F13）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal


class SkillSource(StrEnum):
    """Skill 的加载来源，值即覆盖优先级（数值越大越优先）。"""

    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"


@dataclass
class SkillMeta:
    """SKILL.md frontmatter 的解析结果（F2–F8）。"""

    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    mode: Literal["inline", "fork"] = "inline"
    fork_context: Literal["none", "recent", "full"] = "none"
    model: str | None = None

    def is_fork(self) -> bool:
        """fork 模式在 Python 端起子 Agent 跑；inline 直接注入主对话（F6）。"""
        return self.mode == "fork"


@dataclass
class ToolSpec:
    """`tool.json` 声明的一条 Skill 专属工具（F10）。"""

    name: str
    description: str
    input_schema: dict
    command: list[str]  # argv；首元素相对 base_dir 解析
    base_dir: Path  # exec 时的 cwd，固定为 Skill 目录


@dataclass
class Skill:
    """一个已加载的 Skill（F1）。"""

    meta: SkillMeta
    prompt_body: str  # SKILL.md 去 frontmatter 后的正文（启动时缓存，执行时重读覆盖）
    source_dir: Path  # 绝对路径；重读 SKILL.md / 解析 tool.json 时用
    source: SkillSource
    tool_specs: list[ToolSpec] = field(default_factory=list)


@dataclass
class ActiveEntry:
    """一个已激活 Skill 的 SOP 快照（F24）。"""

    name: str
    body: str
