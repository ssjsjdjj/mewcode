"""Hook 生命周期挂钩系统（docs/ch12）——在 Agent 的固定时刻自动跑配置好的动作。

用户在 `.mewcode/hooks.yaml` 里声明「事件 + 条件 + 动作」三要素，启动期加载校验，
运行期由 Agent / TUI 在 11 个时刻调 `Engine.dispatch` 触发。

动作失败只记日志、不中断 Agent；能阻止动作发生的只有拦截类事件
（PreToolUse / UserPromptSubmit）下的两种约定信号。
"""

from __future__ import annotations

from .engine import Engine
from .event import BLOCKING_EVENTS, Event, is_blocking, parse_event
from .executor import ExecutionResult, Executor
from .loader import compile_rule, load, parse_duration
from .matcher import eval_condition, get_by_path
from .rule import (
    Action,
    ActionType,
    AtomCondition,
    CombineMode,
    Condition,
    DispatchResult,
    HttpAction,
    Payload,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)

__all__ = [
    "BLOCKING_EVENTS",
    "Action",
    "ActionType",
    "AtomCondition",
    "CombineMode",
    "Condition",
    "DispatchResult",
    "Engine",
    "Event",
    "ExecutionResult",
    "Executor",
    "HttpAction",
    "Payload",
    "PromptAction",
    "Rule",
    "ShellAction",
    "SubagentAction",
    "compile_rule",
    "eval_condition",
    "get_by_path",
    "is_blocking",
    "load",
    "parse_duration",
    "parse_event",
]
