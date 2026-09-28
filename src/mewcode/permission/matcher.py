"""匹配器：精确 / glob / 正则 / 反向四种类型（docs/ch12 T1，F1–F3）。

ch06 只有一种「裸 glob」匹配；本章把它拆成四类，权限规则与 Hook 条件共用同一套
语义（N7）。字符串语法（F2）：

    Bash(=git status)   精确：整串相等
    Bash(~^npm (install|test)$)   正则：`re.search` 语义
    Bash(!~^rm)         反向：对 inner 取反，inner 自身按同规则解析，可嵌套
    Bash(git *)         裸值：glob，向后兼容 ch06

两种 glob 语义（F3），由 `is_command` 选择：

- **命令**（`is_command=True`）：整串匹配，`*` 跨任意字符**含 `/`**。用于 Bash 的
  命令串——`Bash(rm *)` 必须能命中 `rm -rf /tmp`。
- **路径**（默认）：按 `/` 分段，段内 `*` 不跨 `/`，`**` 跨任意层数段。

`glob_to_regex` / `match_segments` / `match_pattern` / `escape_glob` 是从 ch06 的
`rule.py` 原样搬来的（`match_pattern` 的自动判别逻辑一字未改，保证旧配置行为不变）；
搬家的原因是 `rule.py` 现在要反过来 import 本模块的 `compile_matcher`，避免循环依赖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class Matcher(Protocol):
    """一种匹配语义；`str()` 回显语法形式，供日志与错误信息用。"""

    def match(self, s: str) -> bool: ...

    def __str__(self) -> str: ...


@dataclass(frozen=True)
class ExactMatcher:
    """整串相等（F3）。"""

    value: str

    def match(self, s: str) -> bool:
        return s == self.value

    def __str__(self) -> str:
        return f"={self.value}"


@dataclass(frozen=True)
class GlobMatcher:
    """glob 匹配；`is_command` 决定 `*` 是否跨 `/`（F3）。"""

    pattern: str
    is_command: bool = False

    def match(self, s: str) -> bool:
        if self.is_command:
            return match_command(self.pattern, s)
        return match_path(self.pattern, s)

    def __str__(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class RegexMatcher:
    """`re.search` 语义；`src` 在构造期编译一次，加载后复用（F3/F15）。"""

    src: str
    compiled: re.Pattern[str] = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "compiled", re.compile(self.src))

    def match(self, s: str) -> bool:
        return self.compiled.search(s) is not None

    def __str__(self) -> str:
        return f"~{self.src}"


@dataclass(frozen=True)
class NotMatcher:
    """对 inner 取反；inner 可以是任意类型，含嵌套的 not（F3）。"""

    inner: Matcher

    def match(self, s: str) -> bool:
        return not self.inner.match(s)

    def __str__(self) -> str:
        return f"!{self.inner}"


def compile_matcher(pattern: str, *, is_command: bool = False) -> Matcher:
    """按前缀把规则串编译成 Matcher；非法输入抛 `ValueError`（带原因，供 stderr 用）。

    空串一律非法——「匹配该工具全部调用」由 `Rule.matcher is None` 表达，
    不靠空串表达，避免两种含义混淆。
    """
    if not pattern:
        raise ValueError("empty matcher pattern")
    if pattern.startswith("="):
        value = pattern[1:]
        if not value:
            raise ValueError("empty exact matcher (want '=value')")
        return ExactMatcher(value)
    if pattern.startswith("~"):
        src = pattern[1:]
        if not src:
            raise ValueError("empty regex matcher (want '~regex')")
        try:
            return RegexMatcher(src)
        except re.error as exc:
            raise ValueError(f"invalid regex {src!r}: {exc}") from exc
    if pattern.startswith("!"):
        inner = pattern[1:]
        if not inner:
            raise ValueError("empty not matcher (want '!inner')")
        return NotMatcher(compile_matcher(inner, is_command=is_command))
    return GlobMatcher(pattern, is_command=is_command)


# ---- glob 原语（ch06 原样搬运，行为不变）----


def glob_to_regex(glob_str: str, within_segment: bool = False) -> str:
    """把 glob 串转正则：`*` 通配（段内或整串）；`\\*` 转义为字面 `*`。"""
    out: list[str] = []
    i = 0
    while i < len(glob_str):
        c = glob_str[i]
        if c == "\\" and i + 1 < len(glob_str) and glob_str[i + 1] == "*":
            out.append(r"\*")  # 字面星号
            i += 2
        elif c == "*":
            out.append("[^/]*" if within_segment else ".*")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def match_seg(pat: str, seg: str) -> bool:
    """段内匹配：`*` 匹配段内任意字符序列。"""
    return re.fullmatch(glob_to_regex(pat, within_segment=True), seg) is not None


def match_segments(pats: list[str], segs: list[str]) -> bool:
    """路径段匹配：`**` 匹配任意层数段。"""
    if not pats:
        return not segs
    if pats[0] == "**":
        return any(match_segments(pats[1:], segs[i:]) for i in range(len(segs) + 1))
    if not segs:
        return False
    return match_seg(pats[0], segs[0]) and match_segments(pats[1:], segs[1:])


def match_command(pattern: str, target: str) -> bool:
    """命令语义：整串 glob，`*` 跨任意字符（含 `/`）。"""
    if pattern == "":
        return True
    return re.fullmatch(glob_to_regex(pattern), target) is not None


def match_path(pattern: str, target: str) -> bool:
    """路径语义：按 `/` 分段，段内 `*` 不跨 `/`，`**` 跨多段。"""
    if pattern == "":
        return True
    return match_segments(pattern.split("/"), target.split("/"))


def match_pattern(pattern: str, target: str) -> bool:
    """ch06 的自动判别匹配（保留原行为）：含 `/` 走路径语义，否则整串匹配。

    仅供工具名通配（`mcp__server__*`）与既有测试使用；新代码请直接用
    `match_command` / `match_path` 表明意图。
    """
    if pattern == "":
        return True
    if "/" in pattern or "/" in target:
        return match_path(pattern, target)
    return match_command(pattern, target)


def escape_glob(s: str) -> str:
    """转义 glob 元字符，使规则精确匹配字面内容（供持久化精确规则用）。"""
    return re.sub(r"([*?\[\]])", r"\\\1", s)
