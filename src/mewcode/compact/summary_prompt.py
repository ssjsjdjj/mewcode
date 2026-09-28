"""摘要 Prompt 模板与解析（ch08 T9）。

SUMMARY_INSTRUCTION 是固定模板字符串，9 个小节标题必须与 extract_summary 的
<summary> 解析约定保持一致，保证 prompt 缓存命中。
"""

from __future__ import annotations

import json
import logging
import re

from mewcode.llm import Message, ROLE_USER

logger = logging.getLogger(__name__)

SUMMARY_INSTRUCTION: str = """你是 MewCode 的对话压缩器。请阅读下面 [conversation] 中的完整对话，分两阶段输出：

第一阶段：用 <analysis>...</analysis> 包裹你的分析草稿，梳理关键信息与决策脉络。

第二阶段：用 <summary>...</summary> 包裹正式摘要。正式摘要必须按以下 9 个固定小节顺序输出，每节用统一标题格式：
## 1 主要请求和意图
## 2 关键技术概念
## 3 文件和代码段
## 4 错误和修复
## 5 问题解决过程
## 6 所有用户消息原文（按时间顺序逐条保留）
## 7 待办任务
## 8 当前工作（最详细）
## 9 可能的下一步

不要调用任何工具，输出纯文本。"""


def serialize_conversation(msgs: list[Message]) -> str:
    """把对话序列化成可读文本（不暴露 ToolCall.input 原 JSON）：
      - 每条 user/assistant 消息：`role: <content>`
      - assistant 工具调用：`[call <name> id=<id> args=<json string>]`
      - tool 消息里的每条 result：`[result id=<id> is_error=<bool>] <content>`
    中间用 \n 分隔；纯函数，无外部状态，保证固定模板预测文本。
    """
    lines: list[str] = []
    for msg in msgs:
        if msg.role == "tool":
            for res in msg.tool_results:
                lines.append(
                    f"[result id={res.tool_call_id} is_error={res.is_error}] {res.content}"
                )
        else:
            if msg.content:
                lines.append(f"{msg.role}: {msg.content}")
            for call in msg.tool_calls:
                args = json.dumps(call.input, ensure_ascii=False, separators=(",", ":"))
                lines.append(f"[call {call.name} id={call.id} args={args}]")
    return "\n".join(lines)


def build_summary_prompt(msgs: list[Message]) -> list[Message]:
    """构造摘要请求：固定指令 + 序列化对话，包成一条 user 消息。"""
    serialized = serialize_conversation(msgs)
    content = SUMMARY_INSTRUCTION + "\n\n[conversation]\n" + serialized
    return [Message(role=ROLE_USER, content=content)]


def extract_summary(raw: str) -> str:
    """从模型返回中提取最后一对 <summary>...</summary> 的正文并 strip。

    找不到标签时不抛错：直接返回 raw 供上层降级使用，并打一条 warning。
    """
    matches = re.findall(r"<summary>(.*?)</summary>", raw, re.DOTALL)
    if not matches:
        logger.warning("summary tags not found")
        return raw
    return matches[-1].strip()
