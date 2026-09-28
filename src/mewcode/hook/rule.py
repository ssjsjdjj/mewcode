"""Hook 规则的数据结构（docs/ch12 T6，F8/F14/F16）。

一条 hook = 事件 +（可选）条件 + 动作 + 执行控制。条件与动作都用 frozen dataclass
表达，加载期一次构造、运行期只读复用（F15）。

注意 `asyncio_mode`：YAML 里写 `async`，但那是 Python 关键字，字段名换个说法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from mewcode.permission.matcher import Matcher

from .event import Event

Payload = dict[str, Any]


class ActionType(StrEnum):
    SHELL = "shell"
    PROMPT = "prompt"
    HTTP = "http"
    SUBAGENT = "subagent"


class CombineMode(StrEnum):
    """多条件的组合方式；顶层只能有一种，不允许嵌套混用（F11）。"""

    ALL_OF = "all_of"
    ANY_OF = "any_of"


@dataclass(frozen=True)
class AtomCondition:
    """一个原子条件：取 payload 的某个字段路径，用 matcher 判定（F12）。"""

    field: str
    matcher: Matcher


@dataclass(frozen=True)
class Condition:
    mode: CombineMode
    atoms: tuple[AtomCondition, ...]


@dataclass(frozen=True)
class ShellAction:
    """执行 shell 命令；payload 以单行 JSON 从 stdin 传入（F17）。"""

    command: str

    type: ClassVar[ActionType] = ActionType.SHELL


@dataclass(frozen=True)
class PromptAction:
    """把 text 注入下一轮 LLM 请求的 reminder 区（F20）。"""

    text: str

    type: ClassVar[ActionType] = ActionType.PROMPT


@dataclass(frozen=True)
class HttpAction:
    """发 HTTP 请求；缺省 body 时把 payload 序列化成 JSON（F23）。"""

    url: str
    method: str = "POST"
    headers: dict[str, str] | None = None
    body: str | None = None

    type: ClassVar[ActionType] = ActionType.HTTP


@dataclass(frozen=True)
class SubagentAction:
    """启动子 Agent——**本期占位**，执行时只打一行 stderr 日志（F26）。"""

    agent_name: str
    prompt: str

    type: ClassVar[ActionType] = ActionType.SUBAGENT


Action = ShellAction | PromptAction | HttpAction | SubagentAction


@dataclass
class Rule:
    """一条已加载的 hook 规则。"""

    name: str  # 用于日志、only_once 跟踪、跨文件冲突检测（F7/F27）
    event: Event
    action: Action
    condition: Condition | None = None  # None = 无条件触发（F11）
    only_once: bool = False  # 同一会话内只跑一次（F27）
    asyncio_mode: bool = False  # YAML 的 async（F28）
    timeout: float = 30.0  # 命令 / HTTP 的最大执行时长（F18）
    source: str = ""  # 来源文件路径，供 /hooks 展示（F34）


@dataclass
class DispatchResult:
    """一次事件分派的结果。

    `injected_prompts` 交给调用方拼进 reminder 队列；`blocked` 只在拦截类事件下
    可能为真，`blocking_hook_name` 指出是哪条 hook 拦的（F32）。
    """

    injected_prompts: list[str] = field(default_factory=list)
    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""

    def merge_prompts(self, prompts: list[str]) -> None:
        self.injected_prompts.extend(prompts)
