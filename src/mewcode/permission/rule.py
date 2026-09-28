"""规则引擎：allow/deny 规则、解析与 glob 匹配（docs/ch06 T4 / F3）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import Decision


@dataclass
class Rule:
    tool: str  # 工具名（友好名或 mcp__server__tool）；含 glob 元字符时按通配匹配
    pattern: str  # 模式段；"" 表示匹配该工具全部调用
    allow: bool  # True=allow, False=deny


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        """先 deny 再 allow；返回 (Allow|Deny, 命中?)。"""
        for rule in self.deny:
            if _tool_hits(rule.tool, friendly) and match_pattern(rule.pattern, target):
                return Decision.DENY, True
        for rule in self.allow:
            if _tool_hits(rule.tool, friendly) and match_pattern(rule.pattern, target):
                return Decision.ALLOW, True
        return Decision.ALLOW, False


def _tool_hits(rule_tool: str, friendly: str) -> bool:
    """工具名命中：精确相等优先；含 `*?[` 元字符时按 glob 通配（支持 `mcp__server__*` 类规则）。

    纯增量扩展：不含元字符的规则仍走精确比较，行为与 ch06 完全一致（N4 无行为性改动）。
    """
    if rule_tool == friendly:
        return True
    return any(c in rule_tool for c in "*?[") and match_pattern(rule_tool, friendly)


def parse_rule(s: str) -> tuple[Rule, bool]:
    """解析 `Tool(pattern)` 或 `Tool`；非法返回 (Rule("","",False), False)。"""
    s = s.strip()
    if not s:
        return Rule("", "", False), False
    if "(" in s or ")" in s:
        m = re.fullmatch(r"([A-Za-z]+)\s*\((.*)\)", s)
        if not m:
            return Rule("", "", False), False
        return Rule(tool=m.group(1), pattern=m.group(2), allow=True), True
    return Rule(tool=s, pattern="", allow=True), True


def _glob_to_regex(glob_str: str, within_segment: bool = False) -> str:
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


def _match_seg(pat: str, seg: str) -> bool:
    """段内匹配：`*` 匹配段内任意字符序列。"""
    return re.fullmatch(_glob_to_regex(pat, within_segment=True), seg) is not None


def _match_segments(pats: list[str], segs: list[str]) -> bool:
    """路径段匹配：`**` 匹配任意层数段。"""
    if not pats:
        return not segs
    if pats[0] == "**":
        return any(_match_segments(pats[1:], segs[i:]) for i in range(len(segs) + 1))
    if not segs:
        return False
    return _match_seg(pats[0], segs[0]) and _match_segments(pats[1:], segs[1:])


def match_pattern(pattern: str, target: str) -> bool:
    """glob 匹配。pattern 为空恒匹配；含 / 视为文件路径段匹配，否则按命令串整串匹配。"""
    if pattern == "":
        return True
    if "/" in pattern or "/" in target:
        return _match_segments(pattern.split("/"), target.split("/"))
    return re.fullmatch(_glob_to_regex(pattern), target) is not None


def escape_glob(s: str) -> str:
    """转义 glob 元字符，使规则精确匹配字面内容（供持久化精确规则用）。"""
    return re.sub(r"([*?\[\]])", r"\\\1", s)
