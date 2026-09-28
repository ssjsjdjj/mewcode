"""取字段路径与条件求值测试（docs/ch12 T7，F13/F14）。"""

from __future__ import annotations

import pytest

from mewcode.hook.matcher import eval_condition, get_by_path
from mewcode.hook.rule import AtomCondition, CombineMode, Condition
from mewcode.permission.matcher import ExactMatcher, GlobMatcher, NotMatcher, RegexMatcher


@pytest.mark.parametrize(
    ("payload", "path", "expected"),
    [
        ({"tool_name": "write_file"}, "tool_name", "write_file"),
        ({"tool_input": {"path": "a.py"}}, "tool_input.path", "a.py"),
        ({"tool_input": {"path": "a.py"}}, "tool_input.missing", ""),
        ({"a": {"b": {"c": "deep"}}}, "a.b.c", "deep"),
        ({"a": {"b": {"c": "deep"}}}, "a.b.c.d", ""),  # 越过标量继续取
        ({"a": 1}, "a.b", ""),  # 中途不是 dict
        ({}, "anything", ""),
        ({"n": 7}, "n", "7"),  # int → str
        ({"n": 2.5}, "n", "2.5"),
        ({"flag": True}, "flag", "True"),  # bool 先于 int 判定
        ({"flag": False}, "flag", "False"),
        ({"obj": {"z": 1, "a": 2}}, "obj", '{"a": 2, "z": 1}'),  # 嵌套对象 → 字典序 JSON
        ({"s": ""}, "s", ""),
        ({"n": None}, "n", ""),  # None 视同缺失
    ],
)
def test_get_by_path(payload, path, expected):
    assert get_by_path(payload, path) == expected


def _cond(mode: CombineMode, *atoms: AtomCondition) -> Condition:
    return Condition(mode=mode, atoms=atoms)


def test_eval_condition_none_is_unconditional():
    assert eval_condition(None, {}) is True


def test_all_of_requires_every_atom():
    c = _cond(
        CombineMode.ALL_OF,
        AtomCondition("tool_name", ExactMatcher("write_file")),
        AtomCondition("tool_input.path", GlobMatcher("**/*.py", is_command=False)),
    )
    assert eval_condition(c, {"tool_name": "write_file", "tool_input": {"path": "a/b.py"}})
    assert not eval_condition(c, {"tool_name": "write_file", "tool_input": {"path": "a/b.txt"}})
    assert not eval_condition(c, {"tool_name": "read_file", "tool_input": {"path": "a/b.py"}})


def test_any_of_requires_one_atom():
    c = _cond(
        CombineMode.ANY_OF,
        AtomCondition("event", ExactMatcher("Stop")),
        AtomCondition("event", ExactMatcher("Notification")),
    )
    assert eval_condition(c, {"event": "Stop"})
    assert eval_condition(c, {"event": "Notification"})
    assert not eval_condition(c, {"event": "SessionStart"})


def test_regex_and_not_atoms():
    c = _cond(CombineMode.ALL_OF, AtomCondition("prompt", RegexMatcher(r"(?i)delete")))
    assert eval_condition(c, {"prompt": "请帮我 DELETE 那个文件"})
    assert not eval_condition(c, {"prompt": "帮我看看"})

    neg = _cond(CombineMode.ALL_OF, AtomCondition("is_error", NotMatcher(ExactMatcher("True"))))
    assert eval_condition(neg, {"is_error": "False"})
    assert not eval_condition(neg, {"is_error": "True"})


def test_missing_field_with_not_matcher_matches():
    """路径缺失 → 空串；`not` 语义下这会命中，用户要留意（文档已注明）。"""
    c = _cond(CombineMode.ALL_OF, AtomCondition("nope", NotMatcher(ExactMatcher("x"))))
    assert eval_condition(c, {}) is True
