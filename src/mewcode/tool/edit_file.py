"""edit_file 工具：原文唯一匹配替换。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import Result


class EditFileTool:
    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "对文件的原文片段做唯一匹配替换；匹配 0 次或多于 1 次会失败并说明，需提供唯一上下文。"
            "编辑前请先用 read_file 读取目标文件，确认 old_string 唯一。"
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
            "properties": {
                "path": {"type": "string", "description": "要修改的文件路径"},
                "old_string": {"type": "string", "description": "原文片段（须唯一匹配）"},
                "new_string": {"type": "string", "description": "替换后的内容"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"参数 JSON 解析失败: {exc}", is_error=True)
        path = data.get("path")
        old_string = data.get("old_string")
        new_string = data.get("new_string")
        if not isinstance(path, str) or not path:
            return Result(content="缺少必填参数 path", is_error=True)
        if not isinstance(old_string, str):
            return Result(content="缺少必填参数 old_string", is_error=True)
        if not isinstance(new_string, str):
            return Result(content="缺少必填参数 new_string", is_error=True)

        p = Path(path)
        if not p.is_file():
            return Result(content=f"文件不存在: {path}", is_error=True)
        try:
            content = p.read_text(encoding="utf-8")
        except OSError as exc:
            return Result(content=f"读取失败: {exc}", is_error=True)

        count = content.count(old_string)
        if count == 0:
            return Result(content="未找到匹配的内容", is_error=True)
        if count > 1:
            return Result(
                content=f"匹配到 {count} 处，old_string 不唯一，请提供更长上下文使其唯一",
                is_error=True,
            )
        new_content = content.replace(old_string, new_string, 1)
        try:
            p.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return Result(content=f"写入失败: {exc}", is_error=True)
        return Result(content=f"已替换 {path} 中的一处匹配")
