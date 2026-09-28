"""压缩后恢复附件构造（ch08 T10~T11）。

把最近读过的文件、当前可用工具与边界提示拼成纯文本块，由 run_summary 拼进
同一条 user 消息的 content，避免 user/user 连续违反 anthropic 协议。
纯函数，不持有外部状态。
"""

from __future__ import annotations

import json

from mewcode.llm import ToolDefinition

from .const import (
    ESTIMATE_CHARS_PER_TOKEN,
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
)
from .state import FileReadRecord

BOUNDARY_NOTICE: str = """以下内容基于压缩摘要生成，可能丢失细节。
当需要文件原文、错误原文、用户原话时，请使用文件读取工具重读对应路径，
不要依据摘要内容做猜测。"""


def render_file_block(rec: FileReadRecord) -> str:
    """渲染单个读文件条目；超长内容保留头部并追加 `(content truncated)` 行。"""
    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    fragment = rec.content
    if len(fragment) > char_limit:
        fragment = fragment[:char_limit] + "\n(content truncated)"
    return f"### {rec.path}\n[read at] {rec.timestamp.isoformat()}\n{fragment}\n"


def render_tools_block(defs: list[ToolDefinition]) -> str:
    """渲染工具清单：每个工具一行，第二行缩进展示 input_schema 紧凑 JSON。"""
    chunks = []
    for d in defs:
        schema = json.dumps(d.input_schema, separators=(",", ":"), ensure_ascii=False)
        chunks.append(f"- {d.name}: {d.description}\n  {schema}")
    return "\n".join(chunks) + ("\n" if chunks else "")


def build_recovery_attachment(
    snapshot: list[FileReadRecord],
    tool_defs: list[ToolDefinition],
) -> str:
    """拼接三段恢复附件：最近读过的文件 / 当前可用工具 / 边界提示。"""
    head = snapshot[:RECOVERY_FILE_LIMIT]

    if head:
        files_section = "## 最近读过的文件\n" + "".join(render_file_block(rec) for rec in head)
    else:
        files_section = "## 最近读过的文件\n(无)\n"

    return (
        files_section
        + "\n## 当前可用工具\n"
        + render_tools_block(tool_defs)
        + "\n## 边界提示\n"
        + BOUNDARY_NOTICE
    )
