"""Skill 正文渲染（docs/ch11 T8，F9/F27）。

inline 与 fork 两条路径都先经过这一层，产出最终要注入的文本。
"""

from __future__ import annotations

from .types import Skill

ARGS_PLACEHOLDER = "$ARGUMENTS"

_TOOL_HINT = (
    "This skill is designed to use only these tools: {tools}. "
    "Prefer them over other tools when possible."
)


def render_body(skill: Skill, args: str) -> str:
    """产出注入文本：建议工具提示行 + `$ARGUMENTS` 替换。

    - `allowed_tools` 非空时在正文顶部插入建议工具提示（F27）
    - 正文含 `$ARGUMENTS` 则原地替换；否则参数非空时在末尾追加
      `## User Request` 段；参数为空时不追加（F9）
    """
    body = skill.prompt_body

    if skill.meta.allowed_tools:
        hint = _TOOL_HINT.format(tools=", ".join(skill.meta.allowed_tools))
        body = f"{hint}\n\n---\n\n{body}"

    if ARGS_PLACEHOLDER in body:
        body = body.replace(ARGS_PLACEHOLDER, args)
    elif args.strip():
        body = f"{body.rstrip()}\n\n## User Request\n\n{args}"

    return body
