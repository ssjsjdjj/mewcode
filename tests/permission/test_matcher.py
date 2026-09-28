"""匹配器四类型测试（docs/ch12 T2）：exact / glob / regex / not × 边界条件。

正则编译一次复用、`!inner` 可嵌套、命令与路径两种 glob 语义都要覆盖（N7）。
"""

from __future__ import annotations

import pytest

from mewcode.permission.matcher import (
    ExactMatcher,
    GlobMatcher,
    NotMatcher,
    RegexMatcher,
    compile_matcher,
    match_command,
    match_path,
)

# ---- 四种类型的命中/不命中（表驱动，id 即规则串）----

# (规则串, 目标, 期望, 是否命令语义)
CASES: list[tuple[str, str, bool, bool]] = [
    # 精确
    ("=git status", "git status", True, True),
    ("=git status", "git status -s", False, True),
    ("=git status", " git status", False, True),  # 不做 strip
    # 正则（search 语义）
    ("~^npm (install|test)$", "npm install", True, True),
    ("~^npm (install|test)$", "npm test", True, True),
    ("~^npm (install|test)$", "npm run dev", False, True),
    ("~rm", "rm -rf /", True, True),
    ("~rm", "echo rm", True, True),  # search 不是 fullmatch
    # glob（命令语义：`*` 跨 `/`）
    ("git *", "git status", True, True),
    ("git *", "npm i", False, True),
    ("rm *", "rm -rf /tmp", True, True),  # ch06 缺陷修复点
    ("*", "rm -rf /", True, True),
    # glob（路径语义：`*` 不跨 `/`）
    ("src/*", "src/a.py", True, False),
    ("src/*", "src/a/b.py", False, False),
    ("**/*.py", "a/b.py", True, False),
    # 反向
    ("!=foo", "foo", False, True),
    ("!=foo", "bar", True, True),
    ("!~^rm", "ls -lh", True, True),
    ("!~^rm", "rm -rf .", False, True),
    ("!git *", "npm install", True, True),
    ("!git *", "git status", False, True),
    ("!!git *", "git status", True, True),  # 双重否定
]


@pytest.mark.parametrize(
    ("pattern", "target", "expected", "is_command"),
    CASES,
    ids=[f"{c[0]}=>{c[1]}" for c in CASES],
)
def test_matcher_table(pattern, target, expected, is_command):
    m = compile_matcher(pattern, is_command=is_command)
    assert m.match(target) is expected


@pytest.mark.parametrize(
    ("pattern", "target", "expected"),
    [
        ("*.py", "x.py", True),
        ("*.py", "a/b.py", False),  # 路径语义：`*` 不跨 `/`
        ("**/*.py", "a/b/c.py", True),
        ("src/**", "src/a/b.py", True),
        ("src/**", "docs/x", False),
        ("*", "a/b", False),  # 单段通配不跨 `/`
    ],
)
def test_path_glob_semantics(pattern, target, expected):
    """路径语义：段内 `*` 不跨 `/`，`**` 跨多段（Hook 条件用这套）。"""
    assert compile_matcher(pattern, is_command=False).match(target) is expected


@pytest.mark.parametrize(
    ("pattern", "target", "expected"),
    [
        ("git *", "git log --oneline /etc/passwd", True),  # 命令语义：`*` 跨 `/`
        ("*", "a/b", True),
        ("=a b", "a b", True),
        ("!~^rm", "ls /tmp", True),
    ],
)
def test_command_glob_semantics(pattern, target, expected):
    assert compile_matcher(pattern, is_command=True).match(target) is expected


# ---- 类型判定与 __str__ 回显 ----


def test_compiled_types():
    assert isinstance(compile_matcher("=x"), ExactMatcher)
    assert isinstance(compile_matcher("~x"), RegexMatcher)
    assert isinstance(compile_matcher("!x"), NotMatcher)
    assert isinstance(compile_matcher("x"), GlobMatcher)
    assert isinstance(compile_matcher("!=x").inner, ExactMatcher)
    inner = compile_matcher("!~x").inner
    assert isinstance(inner, RegexMatcher)


def test_str_round_trip():
    for pattern in ("=git status", "~^rm", "!~^rm", "!git *", "git *"):
        assert str(compile_matcher(pattern)) == pattern


def test_regex_compiled_once():
    """正则加载期编译一次并复用（F3/F15）。"""
    m = compile_matcher("~^a+$")
    assert isinstance(m, RegexMatcher)
    assert m.compiled is m.compiled
    assert m.compiled.pattern == "^a+$"


# ---- 非法输入 ----


@pytest.mark.parametrize(
    "pattern",
    ["", "=", "~", "!", "~[invalid", "!~[invalid", "!"],
)
def test_invalid_patterns_raise(pattern):
    with pytest.raises(ValueError):
        compile_matcher(pattern)


def test_error_messages_are_actionable():
    with pytest.raises(ValueError, match="invalid regex"):
        compile_matcher("~[invalid")
    with pytest.raises(ValueError, match="empty matcher pattern"):
        compile_matcher("")
    with pytest.raises(ValueError, match="empty exact"):
        compile_matcher("=")


# ---- glob 原语直接调用 ----


def test_match_command_and_path_directly():
    assert match_command("rm *", "rm -rf /tmp") is True
    assert match_path("*.py", "/tmp/x.py") is False
    assert match_command("", "anything") is True
    assert match_path("", "anything") is True
