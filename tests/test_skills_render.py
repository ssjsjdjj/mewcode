"""Skill 正文渲染测试（docs/ch11 T8）：$ARGUMENTS 与建议工具提示。"""

from __future__ import annotations

from pathlib import Path

from mewcode.skills import Skill, SkillMeta, SkillSource, render_body


def make(body: str, allowed_tools: list[str] | None = None) -> Skill:
    return Skill(
        meta=SkillMeta(
            name="demo",
            description="d",
            allowed_tools=allowed_tools or [],
        ),
        prompt_body=body,
        source_dir=Path("/tmp/demo"),
        source=SkillSource.BUILTIN,
    )


def test_placeholder_replaced_with_args():
    out = render_body(make("步骤\n\n$ARGUMENTS\n"), "修复登录 bug")
    assert "修复登录 bug" in out
    assert "$ARGUMENTS" not in out


def test_placeholder_replaced_with_empty_args():
    """占位符存在但参数为空 → 原地替换成空串，不追加 User Request 段（F9）。"""
    out = render_body(make("步骤\n\n$ARGUMENTS\n"), "")
    assert "$ARGUMENTS" not in out
    assert "User Request" not in out


def test_no_placeholder_appends_user_request():
    out = render_body(make("步骤\n"), "帮我看看")
    assert out.endswith("## User Request\n\n帮我看看")


def test_no_placeholder_and_empty_args_appends_nothing():
    out = render_body(make("步骤\n"), "")
    assert out == "步骤\n"
    assert "User Request" not in out


def test_allowed_tools_hint_prepended():
    """allowed_tools 非空时在顶部插入建议工具提示（F27）。"""
    out = render_body(make("正文", ["bash", "read_file"]), "")
    assert out.startswith("This skill is designed to use only these tools: bash, read_file.")
    assert "Prefer them over other tools when possible." in out
    assert "\n\n---\n\n正文" in out


def test_no_hint_when_allowed_tools_empty():
    out = render_body(make("正文"), "")
    assert "This skill is designed" not in out
    assert out == "正文"


def test_hint_and_placeholder_together():
    out = render_body(make("干这个：$ARGUMENTS", ["grep"]), "找 bug")
    assert out.startswith("This skill is designed to use only these tools: grep.")
    assert out.endswith("干这个：找 bug")
