"""三层 MEWCODE.md 指令加载与 @include 展开（docs/ch09 F1-F8）。

路径优先级（高在前）：项目根 > 项目配置目录 > 用户级。@include 支持嵌套
（深度上限 5）、环路检测、路径逃逸与二进制文件防护。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_INCLUDE_RE = re.compile(r"^@include\s+(.+)$")

# 三种 @include 防护的警告注释文案（docs/ch09 F3/F4/F5）
_DEPTH_WARNING = "<!-- @include 超过最大嵌套深度，已跳过: {path} -->"
_LOOP_WARNING = "<!-- @include 检测到环路，已跳过: {path} -->"
_ESCAPE_WARNING = "<!-- @include 路径超出允许范围，已跳过: {path} -->"
_BINARY_WARNING = "<!-- @include 文件不可读（二进制），已跳过: {path} -->"


@dataclass
class Loader:
    """按优先级加载三层 MEWCODE.md，处理 @include 展开。

    user_home 缺省用当前用户主目录；max_depth 为 @include 最大嵌套深度。
    """

    project_root: str
    user_home: str = ""
    max_depth: int = 5

    def __post_init__(self) -> None:
        if not self.user_home:
            self.user_home = os.path.expanduser("~")

    def load(self) -> str:
        """扫描三个路径，按优先级拼接；缺失文件静默跳过，全空返回空串。"""
        project = str(Path(self.project_root))
        user = str(Path(self.user_home) / ".mewcode")
        candidates = [
            # (文件路径, 根边界)
            (str(Path(project) / "MEWCODE.md"), project),
            (str(Path(project) / ".mewcode" / "MEWCODE.md"), project),
            (str(Path(user) / "MEWCODE.md"), user),
        ]
        parts: list[str] = []
        for path, boundary in candidates:
            if not Path(path).is_file():
                continue  # 缺失文件静默跳过（docs/ch09 F6）
            text = self._load_file(path, boundary, depth=1, visited=set())
            if text.strip():
                parts.append(text)
        return "\n\n".join(parts)

    def _load_file(
        self,
        path: str,
        boundary: str,
        depth: int,
        visited: set[str],
    ) -> str:
        """加载单个指令文件，递归展开 @include；返回展开后内容。"""
        if depth > self.max_depth:
            return _DEPTH_WARNING.format(path=path)

        abs_path = os.path.realpath(path)
        if abs_path in visited:
            return _LOOP_WARNING.format(path=path)

        root = os.path.realpath(boundary)
        if not Path(abs_path).is_relative_to(Path(root)):
            return _ESCAPE_WARNING.format(path=path)

        if not Path(abs_path).is_file():
            return ""  # 找不到的文件静默跳过（docs/ch09 F6）

        try:
            raw = Path(abs_path).read_bytes()
        except OSError:
            return ""  # 读失败降级为空，不阻塞启动（docs/ch09 N5）
        if b"\x00" in raw[:512]:
            return _BINARY_WARNING.format(path=path)

        text = raw.decode("utf-8", errors="replace")
        new_visited = visited | {abs_path}
        lines: list[str] = []
        for line in text.splitlines():
            m = _INCLUDE_RE.match(line)
            if m is None:
                lines.append(line)  # 非独占行的 @include 保持原文
                continue
            rel = m.group(1).strip()
            # 路径相对当前文件所在目录解析
            target = os.path.join(os.path.dirname(abs_path), rel)
            lines.append(self._load_file(target, root, depth + 1, new_visited))
        return "\n".join(lines)
