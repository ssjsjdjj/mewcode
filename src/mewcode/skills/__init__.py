"""Skill 技能包系统（docs/ch11）——把可复用的 AI 操作做成可编辑的 Markdown 目录。"""

from __future__ import annotations

from .active import ActiveSkills
from .adapter import PromptEntry, PromptItem, active_to_prompt_entries, catalog_to_prompt_items
from .catalog import Catalog, ValidationIssue, user_skills_dir
from .executor import Executor
from .parser import (
    parse_frontmatter_and_body,
    parse_skill_dir,
    parse_tool_json,
    read_skill_body,
)
from .render import render_body
from .types import ActiveEntry, Skill, SkillMeta, SkillSource, ToolSpec

__all__ = [
    "ActiveEntry",
    "ActiveSkills",
    "Catalog",
    "Executor",
    "PromptEntry",
    "PromptItem",
    "Skill",
    "SkillMeta",
    "SkillSource",
    "ToolSpec",
    "ValidationIssue",
    "active_to_prompt_entries",
    "catalog_to_prompt_items",
    "parse_frontmatter_and_body",
    "parse_skill_dir",
    "parse_tool_json",
    "read_skill_body",
    "render_body",
    "user_skills_dir",
]
