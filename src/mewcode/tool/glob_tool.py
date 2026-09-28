"""glob 工具：按模式找文件。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from . import Result

MAX_RESULTS = 100


class GlobTool:
    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return "按 glob 模式查找文件（如 **/*.py），返回匹配的文件路径列表。"

    @property
    def read_only(self) -> bool:
        return True

    @property
    def deferrable(self) -> bool:
        return False  # 内置工具常驻注入（docs/ch07 追加 F13）

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
                "path": {"type": "string", "description": "搜索根目录（默认当前目录）"},
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as exc:
            return Result(content=f"参数 JSON 解析失败: {exc}", is_error=True)
        pattern = data.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return Result(content="缺少必填参数 pattern", is_error=True)
        root = Path(data.get("path") or ".")

        matches: list[str] = []
        for p in root.glob(pattern):
            if p.is_file():
                matches.append(str(p))
            if len(matches) >= MAX_RESULTS:
                break
            await asyncio.sleep(0)
        matches.sort()

        if not matches:
            return Result(content="无匹配")
        text = f"找到 {len(matches)} 个文件：\n" + "\n".join(matches)
        if len(matches) >= MAX_RESULTS:
            text += f"\n…（达到 {MAX_RESULTS} 条上限）"
        return Result(content=text)
