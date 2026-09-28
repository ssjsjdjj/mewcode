"""MCP 工具适配：把远端 Tool 包装成内置 Tool 协议（docs/ch07 T3）。

远端工具注册进工具中心后与内置工具无感：Agent 编排层 / provider 适配层 / 权限包
都不感知其来自远端（F7/N3）。协议错与超时一律转成结构化错误回灌，不抛 Python 异常。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

import mcp.types as mtypes

from mewcode.tool import Result

_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")

# 每次 call_tool 的模块级超时（非常量，单测可临时改小；生产 30s，F10）
call_timeout: float = 30.0

# 已对 full_name 告警过「非 text 内容块被丢弃」；每工具限一次，避免刷屏（F7）
_non_text_warn_once: set[str] = set()


def _warn(msg: str) -> None:
    print(f"[mcp] warn: {msg}", file=sys.stderr)


def _sdk_field(obj: Any, snake: str, camel: str, default: Any = None) -> Any:
    """读 mcp SDK 数据模型字段，兼容命名漂移。

    SDK ≤1.28 的字段是 snake_case（`input_schema`），1.29 起改回协议原名的 camelCase
    （`inputSchema`）且不再接受 snake_case 别名。两个名字都试，取到即用——
    否则读端要么 AttributeError，要么被 getattr 默认值静默吞掉。
    """
    value = getattr(obj, snake, None)
    if value is None:
        value = getattr(obj, camel, default)
    return value


class CallerSession(Protocol):
    """McpTool 依赖的最小会话接口；生产传入 mcp.ClientSession，单测可注入 stub。"""

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> mtypes.CallToolResult: ...


@dataclass
class McpTool:
    """一个远端 MCP 工具，实现 mewcode.tool.Tool 协议（docs/ch07 F7）。"""

    full_name: str  # "mcp__<server>__<tool>"
    remote_name: str  # server 上的原始工具名
    _description: str
    _parameters: dict[str, Any]
    read_only: bool  # 仅来自远端 annotations.read_only_hint==True（N2）
    caller: CallerSession = field(repr=False)
    # 允许被延迟加载（docs/ch07 追加 F13）。放末尾是因为 dataclass 不允许
    # 「有默认值的字段」先于 caller（无默认值）出现；适配层依赖该默认值。
    deferrable: bool = True

    def name(self) -> str:
        return self.full_name

    def description(self) -> str:
        return self._description

    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, args: str) -> Result:
        """执行一次远端调用；结果永远以值类型返回，从不抛 Python 异常给上层。

        args 是模型传来的 JSON 字符串（与内置工具一致的入参约定）；远端 text 内容块
        按序拼接，协议错 / 超时 / 远端 is_error 都映射为 is_error=True 的结构化错误。
        """
        arg_map: dict[str, Any] | None = None
        if args and args.strip():
            try:
                parsed = json.loads(args)
            except json.JSONDecodeError as exc:
                return Result(content=f"MCP 工具参数 JSON 解析失败: {exc}", is_error=True)
            if not isinstance(parsed, dict):
                return Result(content="MCP 工具参数必须是对象", is_error=True)
            arg_map = parsed if parsed else None  # 空 dict 视作无参数

        try:
            result = await asyncio.wait_for(
                self.caller.call_tool(self.remote_name, arg_map),
                timeout=call_timeout,
            )
        except asyncio.TimeoutError:
            return Result(content=f"MCP 工具调用超时 ({call_timeout:.0f}s)", is_error=True)
        except Exception as exc:  # noqa: BLE001 —— 协议错转结构化错误回灌，不中断 Loop（F7/F10）
            return Result(content=f"MCP 工具调用失败: {exc}", is_error=True)

        content_blocks = getattr(result, "content", None) or []
        is_error = bool(_sdk_field(result, "is_error", "isError", False))
        texts: list[str] = []
        dropped = False
        for block in content_blocks:
            if isinstance(block, mtypes.TextContent):
                texts.append(block.text)
            else:
                dropped = True
        if dropped and self.full_name not in _non_text_warn_once:
            _non_text_warn_once.add(self.full_name)
            _warn(f"tool {self.full_name} returned non-text content blocks (dropped)")
        return Result(content="\n".join(texts), is_error=is_error)


def adapt_tool(server_name: str, t: mtypes.Tool, session: CallerSession) -> McpTool | None:
    """把 SDK 返回的远端 Tool 适配成 McpTool；名字含禁用字符返回 None + 告警（F8）。"""
    full_name = f"mcp__{server_name}__{t.name}"
    if not _VALID_NAME.fullmatch(full_name):
        _warn(f"skip tool {full_name}: name contains illegal characters")
        return None
    description = t.description or f"来自 MCP server {server_name} 的工具 {t.name}"
    raw_schema = _sdk_field(t, "input_schema", "inputSchema")
    parameters = dict(raw_schema) if isinstance(raw_schema, dict) else {}
    if not parameters:
        parameters = {"type": "object"}
    read_only = bool(t.annotations and _sdk_field(t.annotations, "read_only_hint", "readOnlyHint"))
    return McpTool(
        full_name=full_name,
        remote_name=t.name,
        _description=description,
        _parameters=parameters,
        read_only=read_only,
        caller=session,
    )
