"""已激活 Skill 列表（docs/ch11 T7）。

挂在 `SessionRuntime` 上，与会话同生命周期：`/clear` 与 `/resume` 时清空（F25/N9）。
按激活顺序保存，重复激活同名 Skill 覆盖其内容但位置不变（SOP 恒靠前可读）。
"""

from __future__ import annotations

import threading

from .types import ActiveEntry


class ActiveSkills:
    """当前会话已激活的 Skill SOP 集合。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[ActiveEntry] = []
        self._index: dict[str, int] = {}

    def activate(self, name: str, body: str) -> None:
        """激活一个 Skill；已激活则原地更新正文（F24）。"""
        with self._lock:
            pos = self._index.get(name)
            if pos is not None:
                self._entries[pos] = ActiveEntry(name=name, body=body)
                return
            self._index[name] = len(self._entries)
            self._entries.append(ActiveEntry(name=name, body=body))

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._index = {}

    def snapshot(self) -> list[ActiveEntry]:
        """拷贝出当前列表，供 env context 装配（F22）。"""
        with self._lock:
            return [ActiveEntry(name=e.name, body=e.body) for e in self._entries]

    def names(self) -> list[str]:
        with self._lock:
            return [e.name for e in self._entries]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
