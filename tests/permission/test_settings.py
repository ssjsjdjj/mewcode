"""权限配置 → RuleSet 的失败反馈测试（docs/ch12 T5，F4）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mewcode.permission import Decision, Mode, new_engine
from mewcode.permission.settings import Settings, to_rule_set


def test_valid_rules_load_silently(capsys):
    from mewcode.permission.settings import PermissionsBlock

    s = Settings(
        permissions=PermissionsBlock(allow=["Bash(git *)", "Read"], deny=["Bash(=rm -rf /)"])
    )
    rs = to_rule_set(s)
    assert len(rs.allow) == 2 and len(rs.deny) == 1
    assert capsys.readouterr().err == ""


def test_bad_rule_reports_and_is_skipped(capsys):
    """非法规则：报 stderr + 不进 RuleSet，其余规则照常（F4/AC2）。

    三类失败各有各的原因：正则编译失败、括号不配对、空模式段。
    """
    from mewcode.permission.settings import PermissionsBlock

    s = Settings(
        permissions=PermissionsBlock(
            allow=["Bash(git *)", "Bash(~[unclosed)", "((bad"], deny=["Bash(~"]
        )
    )
    rs = to_rule_set(s)

    assert [str(r.matcher) for r in rs.allow] == ["git *"]  # 只留下合法的
    assert rs.deny == []
    err = capsys.readouterr().err
    assert err.count("parse failed") == 3
    assert "unclosed" in err and "invalid regex" in err
    assert "malformed rule" in err


def test_bad_rule_does_not_break_others_end_to_end(tmp_path, capsys):
    """写一份含坏规则的配置，engine 仍能读文件并被好规则生效。"""
    p = tmp_path / ".mewcode" / "settings.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "permissions:\n  allow:\n    - 'Bash(=git status)'\n    - 'Bash(~[unclosed)'\n",
        encoding="utf-8",
    )
    engine, err = new_engine(str(tmp_path))
    assert err is None
    assert capsys.readouterr().err.count("parse failed") == 1

    from mewcode.llm import ToolCall

    call = ToolCall(id="1", name="bash", input='{"command":"git status"}')
    assert engine.check(Mode.DEFAULT, call, False)[0] is Decision.ALLOW
    call2 = ToolCall(id="2", name="bash", input='{"command":"git status -s"}')
    assert engine.check(Mode.DEFAULT, call2, False)[0] is Decision.ASK


def test_missing_file_is_empty(tmp_path):
    from mewcode.permission.settings import load_settings

    s = load_settings(str(tmp_path / "nope.yaml"))
    assert s.permissions.allow == [] and s.permissions.deny == []


@pytest.mark.parametrize(
    ("rule", "command", "should_hit"),
    [
        ("Bash(=git status)", "git status", True),
        ("Bash(=git status)", "git status -s", False),  # 精确：多一个参数就不命中
        ("Bash(!=git status)", "git status -s", True),  # 反向
        ("Bash(!=git status)", "git status", False),
        ("Bash(~^git)", "git status -s", True),  # 正则
        ("Bash(~^npm)", "git status", False),
    ],
)
def test_new_syntax_reaches_engine(tmp_path, rule, command, should_hit):
    """新语法经过完整链路（yaml → parse → engine.check）生效（AC1/AC2/AC3）。"""
    from mewcode.llm import ToolCall

    p = Path(tmp_path) / ".mewcode" / "settings.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"permissions:\n  allow:\n    - '{rule}'\n", encoding="utf-8")
    engine, _ = new_engine(str(tmp_path))
    call = ToolCall(id="1", name="bash", input=json.dumps({"command": command}))
    hit_allow = engine.check(Mode.DEFAULT, call, False)[0] is Decision.ALLOW
    # 命中 allow 规则 → ALLOW；未命中 → 落到默认模式的 ASK
    assert hit_allow is should_hit
