"""把 Skill 的 `tool.json` 声明适配成内置 Tool 协议（docs/ch11 T15，N12）。

参数以 JSON 序列化后经 stdin 传给脚本，stdout 作为 tool_result 文本；超时 30 秒
（与 bash 工具一致），`returncode != 0` 视为失败——这一点与 bash 的宽松语义不同
（bash 不看 returncode），因为 Skill 专属工具是脚本，非零退出就是出错。

tool 包不反向依赖 skills 包，所以这里不接收 `ToolSpec`，而是把字段打散成参数。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from . import Result, _truncate

SKILL_TOOL_TIMEOUT = 30.0
MAX_LINES = 2000
MAX_CHARS = 30000


class SkillTool:
    """一个由 `tool.json` 声明的 Skill 专属工具。"""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        command: list[str],
        base_dir: Path,
    ) -> None:
        self._name = name
        self._description = description
        self._input_schema = input_schema
        self._command = command
        self._base_dir = base_dir

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._description

    @property
    def read_only(self) -> bool:
        return False  # 专属工具是本地脚本，视为可能有副作用

    @property
    def deferrable(self) -> bool:
        return False

    @property
    def is_system(self) -> bool:
        return False  # 受 allowed_tools 白名单约束

    def parameters(self) -> dict[str, Any]:
        return self._input_schema

    async def execute(self, args: str) -> Result:
        payload = args.strip() if args and args.strip() else "{}"

        # Windows 的 ProactorEventLoop 不支持 text=True，统一用 bytes 再解码
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=str(self._base_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            return Result(content=f"专属工具 {self._name} 无法启动: {exc}", is_error=True)

        try:
            async with asyncio.timeout(SKILL_TOOL_TIMEOUT):
                stdout_b, stderr_b = await proc.communicate(payload.encode("utf-8"))
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return Result(
                content=f"专属工具 {self._name} 执行超时（>{SKILL_TOOL_TIMEOUT:.0f}s）",
                is_error=True,
            )

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            detail = stderr.strip() or stdout.strip() or "(无输出)"
            return Result(
                content=_truncate(
                    f"专属工具 {self._name} 失败（exit {proc.returncode}）:\n{detail}",
                    MAX_LINES,
                    MAX_CHARS,
                ),
                is_error=True,
            )
        text = stdout if not stderr.strip() else f"{stdout}\nstderr:\n{stderr}"
        return Result(content=_truncate(text, MAX_LINES, MAX_CHARS))


def new_skill_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    command: list[str],
    base_dir: Path,
) -> SkillTool:
    """工厂：把 ToolSpec 的字段打散后构造一个 `SkillTool`。"""
    return SkillTool(name, description, input_schema, command, base_dir)
