"""bash 工具：执行 shell 命令（受超时约束）。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from . import Result, _truncate

BASH_TIMEOUT = 30.0
MAX_LINES = 10000
MAX_CHARS = 30000


class BashTool:
    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return (
            "执行 shell 命令，返回 stdout/stderr/退出码。受超时约束。"
            "读文件、找文件、搜内容请优先用 read_file/glob/grep，不要用 bash 拼凑。"
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def deferrable(self) -> bool:
        return False  # 内置工具常驻注入（docs/ch07 追加 F13）

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}},
            "required": ["command"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"参数 JSON 解析失败: {exc}", is_error=True)
        command = data.get("command")
        if not isinstance(command, str) or not command:
            return Result(content="缺少必填参数 command", is_error=True)

        # Windows 的 ProactorEventLoop 不支持 text=True，统一用 bytes 再解码
        try:
            proc = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except OSError as exc:
            return Result(content=f"命令无法启动: {exc}", is_error=True)

        try:
            async with asyncio.timeout(BASH_TIMEOUT):
                stdout_b, stderr_b = await proc.communicate()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return Result(content=f"命令执行超时（>{BASH_TIMEOUT}s）: {command}", is_error=True)

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        text = f"exit_code: {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        return Result(content=_truncate(text, MAX_LINES, MAX_CHARS))
