"""协议无关的 LLM 抽象与工厂。

ch02：Provider/Message/StreamEvent。ch03：新增工具相关类型（ToolCall/ToolResult/
ToolDefinition/ROLE_TOOL），扩展 Message 与 StreamEvent。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol

from mewcode.config import ProviderConfig


class PromptTooLongError(Exception):
    """Provider 上报上下文超出窗口时统一抛出的哨兵异常。"""


ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"  # 携带工具执行结果的回合


@dataclass
class ToolCall:
    """模型发起的一次工具调用（流式拼接完成后）。"""

    id: str
    name: str
    input: str  # 拼接完成的 JSON 参数字符串（raw JSON）


@dataclass
class ToolResult:
    """一次工具执行结果。"""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class ToolDefinition:
    """注册中心导出的协议无关工具定义。"""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # 仅 assistant
    tool_results: list[ToolResult] = field(default_factory=list)  # 仅 ROLE_TOOL


@dataclass
class Usage:
    """一轮请求的 token 用量。"""

    input_tokens: int = 0  # 本轮输入（含完整历史）
    output_tokens: int = 0  # 本轮输出
    cache_write: int = 0  # 缓存写入：Anthropic cache_creation_input_tokens；OpenAI 恒 0
    cache_read: int = 0  # 缓存读取：Anthropic cache_read_input_tokens；OpenAI cached_tokens


@dataclass
class StreamEvent:
    text: str = ""  # 文本增量
    tool_calls: list[ToolCall] = field(default_factory=list)  # 非空：本轮请求执行这些工具
    usage: Usage | None = None  # 非空：本轮 token 用量（done 之前一次性发出）
    done: bool = False
    err: Exception | None = None


@dataclass
class System:
    """系统提示两部分：稳定（可缓存）与环境（不缓存）。"""

    stable: str = ""
    environment: str = ""


@dataclass
class Request:
    """provider 流式请求的完整入参（docs/ch05 T6）。"""

    messages: list[Message] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)
    system: System = field(default_factory=System)
    reminder: str = ""


class Provider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def model(self) -> str: ...

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        """发起一轮流式对话。req 承载 messages / tools / system{stable,environment} / reminder。
        以 async generator 吐出 StreamEvent（文本增量 / 工具调用 / usage / done / err）。"""


def new_provider(cfg: ProviderConfig) -> Provider:
    """按 protocol 构造适配器。"""
    if cfg.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    raise ValueError(f"未知协议: {cfg.protocol}")
