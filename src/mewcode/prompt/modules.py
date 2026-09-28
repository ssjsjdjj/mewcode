"""系统提示模块定义（docs/ch05 T1）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    """系统提示模块：按 priority 排序拼接；content 为空则跳过（可选空槽）。"""

    name: str  # 模块标识（身份、系统约束…），仅供可读性与测试断言
    priority: int  # 数值越小优先级越高、排越前；固定模块 10..70，可选模块 80..100
    content: str  # 模块正文；为空则装配时跳过


def fixed_modules() -> list[Module]:
    """七个固定模块（docs/ch05 F1）。"""
    return [
        Module(
            "identity",
            10,
            "You are MewCode, a terminal coding agent. You help the user in a command-line "
            "environment: answer questions, analyze code, and get things done using tools.",
        ),
        Module(
            "system_constraints",
            20,
            "Work within the boundaries of the user's working directory conventions. "
            "Never leak API keys or secrets. Be careful with destructive operations.",
        ),
        Module(
            "task_mode",
            30,
            "Work in a ReAct loop: think, call tools, observe results, and keep iterating across "
            "multiple steps until the task is complete. Read before editing. Only give your final "
            "concise answer once the task is done.",
        ),
        Module(
            "actions",
            40,
            "Call tools when you need files, command output, or search results. Consecutive "
            "read-only calls may run in parallel; be cautious with side-effecting operations.",
        ),
        Module(
            "tool_usage",
            50,
            "Prefer the dedicated tools (read_file, glob, grep) over piecing things together with "
            "bash. Always read a file with read_file before editing it.",
        ),
        Module(
            "tone",
            60,
            "Be concise, direct, and to the point. Do not flatter or over-apologize.",
        ),
        Module(
            "text_output",
            70,
            "Use Markdown when helpful (code blocks, lists, emphasis). Keep final answers concise.",
        ),
    ]


def optional_modules(instructions: str = "", memory: str = "") -> list[Module]:
    """三个可选槽位（docs/ch05 F1；ch09 T12 参数化）。

    custom_instructions 填充 MEWCODE.md 指令文本、long_term_memory 填充记忆索引；
    内容为空则装配时跳过（与 ch08 空槽行为一致）。
    """
    return [
        Module("custom_instructions", 80, instructions),
        Module("active_skills", 90, ""),  # 已激活 Skill（后续章节接入）
        Module("long_term_memory", 100, memory),
    ]
