"""规则引擎：allow/deny 规则与解析（docs/ch06 T4 / F3；ch12 T3 换用 Matcher）。

ch12 起 `Rule` 不再持 pattern 字符串，而是持一个 `Matcher`（`None` 表示「该工具
全部调用」），匹配语义由 `matcher.py` 的四种类型承担。规则串语法见 matcher.py。

`parse_rule` 现在返回 `(Rule | None, str | None)`——第二个值是错误描述，让调用方
（`settings.to_rule_set`）能把失败规则报到 stderr 而不是静默吞掉（F4）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import Decision
from .matcher import (
    Matcher,
    compile_matcher,
    escape_glob,
    glob_to_regex,
    match_command,
    match_path,
    match_pattern,
    match_seg,
    match_segments,
)

__all__ = [
    "Rule",
    "RuleSet",
    "compile_matcher",
    "escape_glob",
    "glob_to_regex",
    "match_command",
    "match_path",
    "match_pattern",
    "match_seg",
    "match_segments",
    "parse_rule",
]


@dataclass
class Rule:
    """一条 allow/deny 规则。

    `matcher is None` 表示模式段为空 → 匹配该工具的全部调用（ch06 的 `Tool` 写法）。
    `raw` 保留原始描述串，供日志回显与幂等比对。
    """

    tool: str  # 工具名（友好名或 mcp__server__tool）；含 glob 元字符时按通配匹配
    matcher: Matcher | None
    allow: bool  # True=allow, False=deny
    raw: str = ""

    def hits(self, friendly: str, target: str) -> bool:
        """工具名命中且模式命中。"""
        if not _tool_hits(self.tool, friendly):
            return False
        return self.matcher is None or self.matcher.match(target)


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        """先 deny 再 allow；返回 (Allow|Deny, 命中?)。"""
        for rule in self.deny:
            if rule.hits(friendly, target):
                return Decision.DENY, True
        for rule in self.allow:
            if rule.hits(friendly, target):
                return Decision.ALLOW, True
        return Decision.ALLOW, False


def _tool_hits(rule_tool: str, friendly: str) -> bool:
    """工具名命中：精确相等优先；含 `*?[` 元字符时按 glob 通配（支持 `mcp__server__*` 类规则）。

    纯增量扩展：不含元字符的规则仍走精确比较，行为与 ch06 完全一致（N4 无行为性改动）。
    """
    if rule_tool == friendly:
        return True
    return any(c in rule_tool for c in "*?[") and match_pattern(rule_tool, friendly)


def parse_rule(s: str) -> tuple[Rule | None, str | None]:
    """解析 `Tool(pattern)` 或 `Tool`；返回 (Rule, None) 或 (None, 错误描述)。

    模式段的类型由前缀决定（F2）；`Bash` 的裸 glob 走命令语义，其余工具走路径语义
    ——这修掉了 ch06 的一个缺陷：`Bash(rm *)` 过去匹配不上含 `/` 的命令（见
    docs/ch12/checklist.md 验收报告）。
    """
    s = s.strip()
    if not s:
        return None, "empty rule"
    if "(" in s or ")" in s:
        m = re.fullmatch(r"([A-Za-z]+)\s*\((.*)\)", s)
        if not m:
            return None, "malformed rule (want 'Tool(pattern)' or 'Tool')"
        tool, pattern = m.group(1), m.group(2)
    else:
        tool, pattern = s, ""

    if pattern == "":
        return Rule(tool=tool, matcher=None, allow=True, raw=s), None
    try:
        matcher = compile_matcher(pattern, is_command=(tool == "Bash"))
    except ValueError as exc:
        return None, str(exc)
    return Rule(tool=tool, matcher=matcher, allow=True, raw=s), None
