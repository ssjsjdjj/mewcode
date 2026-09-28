"""单级笔记存储：笔记文件 CRUD 与 MEMORY.md 索引读写（docs/ch09 F19）。

每个笔记是一个 `<type>_<slug>.md` 文件，带 YAML frontmatter
（type/title/slug/created/updated）；MEMORY.md 保存索引行
`- [<title>](<filename>) — <一行摘要>`，供系统提示注入。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

import yaml

from mewcode.memory.types import UpdateAction

_INDEX_FILE = "MEMORY.md"

# 索引行 hook 截断长度
_HOOK_MAX = 60


def _frontmatter_block(data: dict) -> str:
    """用 yaml.safe_dump 生成 frontmatter 文本（docs/ch09 决策表）。"""
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---"


def _parse_note(raw: str) -> tuple[dict, str]:
    """手写解析 --- 包裹的 YAML frontmatter + 正文；失败降级为 ({}, 全文)。"""
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            header = raw[4:end]
            body = raw[end + 4 :].lstrip("\n")
            try:
                data = yaml.safe_load(header) or {}
            except Exception:  # noqa: BLE001 - frontmatter 损坏不阻塞更新
                data = {}
            return data, body
    return {}, raw


def _one_line_hook(content: str) -> str:
    """取正文首非空行做索引 hook（单行、截断）。"""
    first = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    return first[:_HOOK_MAX]


def _line_mentions(line: str, filename: str) -> bool:
    return f"({filename})" in line


class Store:
    """管理单级（项目级或用户级）的笔记文件和索引。"""

    def __init__(self, dir: str) -> None:
        self._dir = dir
        self._lock = threading.Lock()

    def ensure_dir(self) -> None:
        os.makedirs(self._dir, exist_ok=True)

    def load_index(self) -> str:
        """读取 MEMORY.md 内容；不存在返回空字符串。"""
        path = Path(self._dir) / _INDEX_FILE
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def apply(self, actions: list[UpdateAction]) -> None:
        """按顺序执行 create/update/delete；未知 action 静默跳过。"""
        with self._lock:
            self.ensure_dir()
            for action in actions:
                if action.action == "create":
                    self._create(action)
                elif action.action == "update":
                    self._update(action)
                elif action.action == "delete":
                    self._delete(action)

    def _create(self, action: UpdateAction) -> None:
        filename = f"{action.type}_{action.slug}.md"
        now = datetime.now().isoformat(timespec="seconds")
        data = {
            "type": action.type,
            "title": action.title,
            "slug": action.slug,
            "created": now,
            "updated": now,
        }
        self._write_note(filename, data, action.content)
        self._append_index_line(action.title, filename, action.content)

    def _update(self, action: UpdateAction) -> None:
        filename = action.filename
        path = Path(self._dir) / filename
        data, content = self._parse_file(path)
        created = data.get("created") or datetime.now().isoformat(timespec="seconds")
        new_title = action.title or data.get("title", "")
        new_data = {
            "type": data.get("type", ""),
            "title": new_title,
            "slug": data.get("slug", ""),
            "created": created,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_note(filename, new_data, action.content or content)
        self._replace_index_line(new_title, filename, action.content or content)

    def _delete(self, action: UpdateAction) -> None:
        filename = action.filename
        try:
            os.remove(str(Path(self._dir) / filename))
        except OSError:
            pass  # 文件本就不存在则幂等
        self._remove_index_line(filename)

    def _write_note(self, filename: str, data: dict, content: str) -> None:
        text = f"{_frontmatter_block(data)}\n\n{content}\n"
        (Path(self._dir) / filename).write_text(text, encoding="utf-8")

    def _parse_file(self, path: Path) -> tuple[dict, str]:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return {}, ""
        return _parse_note(raw)

    def _append_index_line(self, title: str, filename: str, content: str) -> None:
        line = f"- [{title}]({filename}) — {_one_line_hook(content)}"
        with open(Path(self._dir) / _INDEX_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _replace_index_line(self, title: str, filename: str, content: str) -> None:
        path = Path(self._dir) / _INDEX_FILE
        if not path.is_file():
            self._append_index_line(title, filename, content)
            return
        new_line = f"- [{title}]({filename}) — {_one_line_hook(content)}"
        lines = [
            new_line if _line_mentions(line, filename) else line
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _remove_index_line(self, filename: str) -> None:
        path = Path(self._dir) / _INDEX_FILE
        if not path.is_file():
            return
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not _line_mentions(line, filename)
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
