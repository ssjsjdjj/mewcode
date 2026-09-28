"""命令注册中心（docs/ch10 T2）：注册 + 冲突检测 + 前缀匹配。

主名与全部别名都映射到同一 Command；冲突在注册期立即 raise，启动即失败
（F2/N4）；_visible 只含非 hidden 命令且按 name 字典序（F18 排序来源）。
"""

from __future__ import annotations

from typing import Callable

from mewcode.command.command import Command


class Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}  # 主名 + 别名 → 同一 Command（key 全小写）
        self._visible: list[Command] = []  # 非 hidden，按 name 字典序

    def register(self, cmd: Command) -> None:
        """注册命令；名/别名非空小写校验，冲突立即抛 RuntimeError 含具体键。"""
        if not cmd.name or cmd.name.lower() != cmd.name:
            raise ValueError(f"命令名必须非空且全小写: {cmd.name!r}")
        for alias in cmd.aliases:
            if not alias or alias.lower() != alias:
                raise ValueError(f"别名必须非空且全小写: {alias!r}")
        for key in (cmd.name, *cmd.aliases):
            if key in self._by_name:
                raise RuntimeError(f"command conflict: {key}")
            self._by_name[key] = cmd
        if not cmd.hidden:
            self._visible.append(cmd)
            self._visible.sort(key=lambda c: c.name)

    def lookup(self, name: str) -> Command | None:
        """按主名或别名查找（大小写不敏感，F4）。"""
        return self._by_name.get(name.lower())

    def visible(self) -> list[Command]:
        """可见命令的排序副本（防外部改动）。"""
        return list(self._visible)

    def prefix_match(self, prefix: str) -> list[Command]:
        """按命令名前缀过滤可见命令（F25：不匹配别名/描述）；p 为空返回全部。"""
        p = prefix.lstrip("/").lower()
        if p == "":
            return list(self._visible)
        return [c for c in self._visible if c.name.startswith(p)]

    def remove_if(self, pred: Callable[[Command], bool]) -> int:
        """按谓词移除命令，返回移除条数（docs/ch11 T24）。

        主名与全部别名都要从 `_by_name` 摘掉；`_visible` 本身按 name 有序，
        删元素不破坏有序性，无需重排。

        去重按 `id()` 而不是 `set()`——`Command` 是 `slots=True` 的 dataclass，
        生成了 `__eq__` 因而不可哈希；同一 Command 会以多个别名键出现。
        """
        unique: dict[int, Command] = {id(c): c for c in self._by_name.values()}
        doomed = [c for c in unique.values() if pred(c)]
        if not doomed:
            return 0
        for cmd in doomed:
            for key in (cmd.name, *cmd.aliases):
                self._by_name.pop(key, None)
        removed = {id(c) for c in doomed}
        self._visible = [c for c in self._visible if id(c) not in removed]
        return len(doomed)
