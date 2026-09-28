"""ToolSearch：把「拉取 / 搜索」暴露成一个普通内置工具（docs/ch07 追加 F16–F18）。

模型只需记住一条调用规则——`keyword` 传 `select:<完整工具名>` 走精确拉取，传别的一律
当关键词搜索。单入口是刻意的：在「精确」与「搜索」两个工具之间做选择，选错就要多烧
一轮，而两个动作的实现都在 Discovery 里。
"""

from __future__ import annotations

import json
from typing import Any

from mewcode.tool import Result
from mewcode.tool.deferred import Discovery

SELECT_PREFIX = "select:"


class ToolSearchTool:
    """只读、不可延迟的内置工具：按需换取尚未加载的工具的完整定义。

    它是普通注册工具，因此不参与延迟判定、也不计入「连续未知工具」计数（F16）。
    """

    def __init__(self, discovery: Discovery) -> None:
        self._discovery = discovery

    def name(self) -> str:
        return "tool_search"

    def description(self) -> str:
        return (
            "按需获取尚未加载的工具的完整定义。keyword 传 'select:<完整工具名>' 精确拉取；"
            "传普通关键词则按名字与描述模糊搜索（最多返回 5 个）。"
            "命中后该工具从下一轮起出现在你的工具列表里。"
        )

    @property
    def read_only(self) -> bool:
        """只读：不触碰文件与系统，因此 Plan Mode 下同样可见（F22）。"""
        return True

    @property
    def deferrable(self) -> bool:
        return False

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": (
                        "要拉取的完整工具名（形如 select:mcp__<server>__<tool>），"
                        "或一个搜索关键词（如 github、sql）"
                    ),
                }
            },
            "required": ["keyword"],
        }

    async def execute(self, args: str) -> Result:
        """参数是模型传来的 JSON 字符串（与内置工具一致的入参约定）。

        参数缺失 / 非法、以及「没找到」都返回结构化结果而非抛异常——异常会中断
        agent 循环，而「没找到」是正常结果，模型应当据此换个关键词继续（AC19）。
        """
        try:
            parsed = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"tool_search 参数 JSON 解析失败: {exc}", is_error=True)
        if not isinstance(parsed, dict):
            return Result(content="tool_search 参数必须是对象", is_error=True)
        keyword = parsed.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            return Result(
                content="tool_search 需要 keyword 参数：select:<完整工具名> 或搜索关键词",
                is_error=True,
            )
        text = keyword.strip()
        if text.startswith(SELECT_PREFIX):
            # 前缀后再 strip 一次：`select:  name` 的中间空格在此收口，不依赖
            # Discovery.select 自己的 strip。
            return self._discovery.select(text[len(SELECT_PREFIX) :].strip())
        return self._discovery.search(text)
