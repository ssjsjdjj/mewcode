"""read_file 工具：读文件，带行号。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import Result, _truncate

MAX_LINES = 2000
MAX_CHARS = 256 * 1024


class ReadFileTool:
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "读取文件内容（带行号）。用于查看源码、配置、文档等。"

    @property
    def read_only(self) -> bool:
        return True

    @property
    def deferrable(self) -> bool:
        return False  # 内置工具常驻注入（docs/ch07 追加 F13）

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "要读取的文件路径"}},
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"参数 JSON 解析失败: {exc}", is_error=True)
        path = data.get("path")
        if not isinstance(path, str) or not path:
            return Result(content="缺少必填参数 path", is_error=True)

        p = Path(path)
        if p.is_dir():
            return Result(content=f"{path} 是目录，不是文件", is_error=True)
        if not p.is_file():
            return Result(content=f"文件不存在: {path}", is_error=True)
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Result(content=f"文件不是文本（无法以 UTF-8 解码）: {path}", is_error=True)
        except PermissionError:
            return Result(content=f"无权限读取: {path}", is_error=True)
        except OSError as exc:
            return Result(content=f"读取失败: {exc}", is_error=True)

        numbered = "\n".join(f"{i + 1:6d}\t{line}" for i, line in enumerate(text.splitlines()))
        return Result(content=_truncate(numbered, MAX_LINES, MAX_CHARS))
