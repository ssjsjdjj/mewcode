"""工具抽象、注册中心与默认工具集（docs/ch03 T2/T9）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mewcode.llm import ToolDefinition

DEFAULT_TIMEOUT: float = 30.0  # 单个工具执行的默认超时秒数（N1，不可配）


@dataclass
class Result:
    """工具执行结果——永远以值类型返回，从不抛 Python 异常给上层。"""

    content: str
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    def name(self) -> str: ...
    def description(self) -> str: ...
    def parameters(self) -> dict[str, Any]: ...
    @property
    def read_only(self) -> bool:
        """True=只读工具（可并发执行 & Plan Mode 放行）。"""
        ...

    @property
    def deferrable(self) -> bool:
        """True=允许被延迟加载，False=常驻注入（docs/ch07 追加 F13）。

        只表示「允许被延迟」，是否真的延迟由 Discovery 按「是否已发现」判定。
        内置工具与 tool_search 恒为 False；MCP 工具为 True。读取端一律
        `getattr(tool, "deferrable", False)`——缺省即不延迟，漏声明时失败方向是
        「多注入」而非「工具消失」。
        """
        ...

    async def execute(self, args: str) -> Result: ...


def _truncate(s: str, max_lines: int, max_chars: int) -> str:
    """超长截断并追加 [truncated] 标注。"""
    if len(s) > max_chars:
        s = s[:max_chars] + "\n[truncated]"
    lines = s.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["[truncated]"]
        s = "\n".join(lines)
    return s


class Registry:
    """集中登记、按名查找、导出定义、按名执行。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        name = t.name()
        if name in self._tools:
            raise ValueError(f"工具已注册: {name}")
        self._tools[name] = t
        self._order.append(name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=n,
                description=self._tools[n].description(),
                input_schema=self._tools[n].parameters(),
            )
            for n in self._order
        ]

    def read_only_definitions(self) -> list[ToolDefinition]:
        """Plan Mode：只导出 read_only==True 的工具定义，保留注册顺序。"""
        return [d for d in self.definitions() if self._tools[d.name].read_only]

    def is_read_only(self, name: str) -> bool:
        """分批判定；未知工具返回 False（按串行处理）。"""
        tool = self._tools.get(name)
        return tool is not None and tool.read_only

    def is_deferrable(self, name: str) -> bool:
        """该工具是否声明可延迟；未知工具与未声明者均返回 False。

        缺省 False = 不延迟 = 旧行为（第三方实现漏声明时的安全方向）。
        """
        tool = self._tools.get(name)
        return tool is not None and bool(getattr(tool, "deferrable", False))

    def has_deferrable(self) -> bool:
        """是否存在可延迟工具（docs/ch07 追加 F16）：cli 据此决定是否注册 tool_search。"""
        return any(self.is_deferrable(n) for n in self._order)

    def deferrable_names(self) -> list[str]:
        """可延迟工具的完整名，按注册顺序（docs/ch07 追加 F14/F15）。"""
        return [n for n in self._order if self.is_deferrable(n)]

    def is_system(self, name: str) -> bool:
        """该工具是否标记为系统工具（docs/ch11 F23）。

        与 `is_deferrable` 同一惯例：读端 `getattr` 取默认值，不把 `is_system`
        加进 `Tool` Protocol——那会波及全部既有工具实现。未声明者一律 False。
        """
        tool = self._tools.get(name)
        return tool is not None and bool(getattr(tool, "is_system", False))

    def system_definitions(self) -> list[ToolDefinition]:
        """只导出系统工具（docs/ch11 F23）。"""
        return [d for d in self.definitions() if self.is_system(d.name)]

    def definitions_filtered(self, allowed: list[str]) -> list[ToolDefinition]:
        """按白名单过滤工具定义，系统工具豁免（docs/ch11 F30）。

        空白名单 = 不再收窄（F30 第 5 步），等价 `definitions()`；因此即便调用方
        传了空 `allowed_tools`，`load_skill` 这类系统工具也仍在导出的定义里。
        """
        if not allowed:
            return self.definitions()
        wanted = set(allowed)
        return [d for d in self.definitions() if d.name in wanted or self.is_system(d.name)]

    def register_skill_tool(self, t: Tool) -> None:
        """登记 Skill 专属工具，重名静默覆盖（docs/ch11 F23）。

        与 `register` 的硬失败语义相反：Skill 的 `tool.json` 工具名可能与既有工具
        重名，此时以 Skill 的为准，不打断 LoadSkill 调用。
        """
        name = t.name()
        if name not in self._tools:
            self._order.append(name)
        self._tools[name] = t

    def count(self) -> int:
        """当前已注册工具数量（O(1)，docs/ch10 T0c，/status 命令数据源）。"""
        return len(self._order)

    async def execute(self, name: str, args: str, timeout: float = DEFAULT_TIMEOUT) -> Result:
        tool = self._tools.get(name)
        if tool is None:
            return Result(content=f"未知工具: {name}", is_error=True)
        try:
            return await asyncio.wait_for(tool.execute(args), timeout)
        except asyncio.TimeoutError:
            return Result(content=f"工具 {name} 执行超时（{timeout}s）", is_error=True)
        except Exception as exc:  # noqa: BLE001 —— 所有失败包成结构化结果
            return Result(content=f"工具 {name} 异常: {exc}", is_error=True)


def new_default_registry() -> Registry:
    """构造并注册 6 个工具。"""
    from .bash import BashTool
    from .edit_file import EditFileTool
    from .glob_tool import GlobTool
    from .grep_tool import GrepTool
    from .read_file import ReadFileTool
    from .write_file import WriteFileTool

    registry = Registry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ):
        registry.register(tool)
    return registry
