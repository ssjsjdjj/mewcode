"""路径沙箱（docs/ch06 T3 / F2）。

把文件类工具的读写限定在项目根内；先解析符号链接再做前缀比对，防软链接逃逸。
对尚不存在的新建文件按「最近已存在祖先目录」解析，不因目标不存在而误判。
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_root(root: str) -> str:
    """解析项目根为绝对、去符号链接的路径。失败抛异常（由 new_engine 兜底）。"""
    return str(Path(root).expanduser().resolve(strict=True))


def eval_symlinks_or_ancestor(abs_path: str) -> str:
    """对存在的目标解析符号链接；不存在则回退到最近已存在祖先目录后再拼回剩余段。"""
    p = Path(abs_path)
    try:
        return str(p.resolve(strict=True))
    except (FileNotFoundError, OSError):
        # 逐级回退找最近已存在祖先
        suffix: list[str] = []
        current = p
        while True:
            try:
                resolved_ancestor = current.resolve(strict=True)
                break
            except (FileNotFoundError, OSError):
                suffix.append(current.name)
                parent = current.parent
                if parent == current:  # 已到根仍不存在（极端）
                    return str(Path(abs_path))
                current = parent
        return str(Path(resolved_ancestor, *reversed(suffix)))


def sandbox_ok(engine: object, path: str) -> bool:
    """目标路径是否落在项目根内（先解析符号链接再前缀比对）。空 path 视为根。"""
    root = engine.root
    abs_path = path if os.path.isabs(path) else os.path.join(root, path)
    resolved = eval_symlinks_or_ancestor(abs_path)
    return resolved == root or resolved.startswith(root + os.sep)
