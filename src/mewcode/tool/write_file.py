"""write_file 工具：写入（覆盖）文件，父目录自动创建。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import Result


class WriteFileTool:
    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "写入（覆盖）文件；父目录不存在时自动创建。"

    @property
    def read_only(self) -> bool:
        return False

    @property
    def deferrable(self) -> bool:
        return False  # 内置工具常驻注入（docs/ch07 追加 F13）

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要写入的文件路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"参数 JSON 解析失败: {exc}", is_error=True)
        path = data.get("path")
        content = data.get("content")
        if not isinstance(path, str) or not path:
            return Result(content="缺少必填参数 path", is_error=True)
        if not isinstance(content, str):
            return Result(content="缺少必填参数 content", is_error=True)

        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as exc:
            return Result(content=f"写入失败: {exc}", is_error=True)
        size = len(content.encode("utf-8"))
        return Result(content=f"已写入 {path}（{size} 字节）")
