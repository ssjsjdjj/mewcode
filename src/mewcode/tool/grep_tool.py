"""grep 工具：按正则搜索文件内容，返回 文件:行号:内容。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from . import Result

MAX_RESULTS = 100
MAX_LINE_CHARS = 500
LONG_LINE = 1_000_000  # 超过此长度视为「超长行」，避免读爆内存

_BINARY_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".exe",
    ".dll",
    ".so",
    ".pyc",
    ".woff",
    ".ttf",
    ".otf",
    ".ico",
    ".mp4",
    ".mp3",
}


class GrepTool:
    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return "在文件内容中按 Python 正则搜索，返回 文件:行号:内容 命中列表。"

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
                "pattern": {"type": "string", "description": "Python 正则表达式"},
                "path": {"type": "string", "description": "搜索根目录（默认当前目录）"},
                "glob": {"type": "string", "description": "文件名过滤，如 *.py"},
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
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return Result(content=f"正则非法: {exc}", is_error=True)

        root = Path(data.get("path") or ".")
        fglob = data.get("glob")
        files = list(root.rglob(fglob)) if fglob else list(root.rglob("*"))

        hits: list[str] = []
        for f in files:
            if not f.is_file() or f.suffix.lower() in _BINARY_EXTS:
                continue
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if len(line) > LONG_LINE:
                            hits.append(f"{f}:{lineno}:[行过长，未完整搜索]")
                            break
                        if rx.search(line):
                            content = line.rstrip()
                            if len(content) > MAX_LINE_CHARS:
                                content = content[:MAX_LINE_CHARS] + "…"
                            hits.append(f"{f}:{lineno}:{content}")
                            if len(hits) >= MAX_RESULTS:
                                return Result(
                                    content="\n".join(hits) + f"\n…（达到 {MAX_RESULTS} 条上限）"
                                )
            except OSError:
                continue
            await asyncio.sleep(0)

        if not hits:
            return Result(content="无命中")
        return Result(content="\n".join(hits))
