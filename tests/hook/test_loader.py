"""hooks.yaml 加载与字段校验测试（docs/ch12 T9，F6–F8/F28）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.hook import ActionType, CombineMode, Event, load, parse_duration
from mewcode.hook.rule import HttpAction, PromptAction, ShellAction, SubagentAction

VALID = """
hooks:
  - name: block-writes
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: write_file}
    action:
      type: shell
      command: "echo blocked >&2; exit 2"
  - name: notify
    event: Stop
    timeout: 5s
    action:
      type: http
      url: http://localhost:9999/done
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def project_hooks(tmp_path: Path, text: str) -> Path:
    return write(tmp_path / "proj" / ".mewcode" / "hooks.yaml", text)


def test_load_valid(tmp_path, home):
    p = project_hooks(tmp_path, VALID)
    engine = load(tmp_path / "proj")

    assert len(engine.rules) == 2
    assert engine.sources == [str(p)]
    first = engine.rules[0]
    assert first.name == "block-writes"
    assert first.event is Event.PRE_TOOL_USE
    assert isinstance(first.action, ShellAction)
    assert first.condition is not None and first.condition.mode is CombineMode.ALL_OF
    assert first.source == str(p)

    second = engine.rules[1]
    assert isinstance(second.action, HttpAction)
    assert second.action.method == "POST"  # 缺省
    assert second.timeout == 5.0


def test_action_types_parsed(tmp_path, home):
    project_hooks(
        tmp_path,
        """
hooks:
  - {name: a, event: SessionStart, action: {type: prompt, text: 用 zh-CN 回复}}
  - {name: b, event: SessionEnd, action: {type: subagent, agent_name: foo, prompt: x}}
""",
    )
    rules = load(tmp_path / "proj").rules
    assert isinstance(rules[0].action, PromptAction)
    assert rules[0].action.text == "用 zh-CN 回复"
    assert isinstance(rules[1].action, SubagentAction)
    assert rules[1].action.agent_name == "foo"


def test_missing_files_is_empty_engine(tmp_path, home):
    engine = load(tmp_path / "nowhere")
    assert engine.rules == [] and engine.sources == []
    assert engine.has_rules() is False


def test_empty_file_ok(tmp_path, home):
    project_hooks(tmp_path, "")
    assert load(tmp_path / "proj").rules == []


def test_top_level_must_be_mapping_with_hooks(tmp_path, home, capsys):
    project_hooks(tmp_path, "- just\n- a list\n")
    assert load(tmp_path / "proj").rules == []
    assert "must be a mapping with a 'hooks' list" in capsys.readouterr().err


def test_yaml_syntax_error_keeps_running(tmp_path, home, capsys):
    project_hooks(tmp_path, "hooks: [{{{ broken\n")
    assert load(tmp_path / "proj").rules == []
    assert "parse failed" in capsys.readouterr().err


# ---- 字段校验：坏的那条跳过，好的照常 ----


def test_bad_rules_skipped_good_kept(tmp_path, home, capsys):
    project_hooks(
        tmp_path,
        """
hooks:
  - {name: "", event: Stop, action: {type: shell, command: "true"}}
  - {name: unknown-ev, event: UnknownEvent, action: {type: shell, command: "true"}}
  - {name: bad-action, event: Stop, action: {type: teleport}}
  - {name: no-command, event: Stop, action: {type: shell}}
  - {name: good, event: Stop, action: {type: shell, command: "true"}}
""",
    )
    engine = load(tmp_path / "proj")
    assert [r.name for r in engine.rules] == ["good"]
    err = capsys.readouterr().err
    assert "'name' is required" in err
    assert 'unknown event "UnknownEvent"' in err
    assert "unknown action type 'teleport'" in err
    assert "requires 'command'" in err


def test_both_all_of_and_any_of_rejected(tmp_path, home, capsys):
    project_hooks(
        tmp_path,
        """
hooks:
  - name: both
    event: Stop
    if:
      all_of: [{field: a, match: {type: exact, value: x}}]
      any_of: [{field: b, match: {type: exact, value: y}}]
    action: {type: shell, command: "true"}
  - {name: good, event: Stop, action: {type: prompt, text: hi}}
""",
    )
    engine = load(tmp_path / "proj")
    assert [r.name for r in engine.rules] == ["good"]
    assert "both all_of and any_of" in capsys.readouterr().err


@pytest.mark.parametrize(
    "if_block",
    [
        "{all_of: [{field: a, match: {type: bogus, value: x}}]}",
        "{all_of: [{field: a, match: {type: exact}}]}",
        "{all_of: [{field: a, match: {type: not}}]}",
        "{all_of: [{field: a, match: 'bare string'}]}",
        "{all_of: [{field: a}]}",
        "{all_of: [{match: {type: exact, value: x}}]}",
        "{all_of: []}",
        "{}",
    ],
)
def test_bad_condition_skipped(tmp_path, home, capsys, if_block):
    project_hooks(
        tmp_path,
        f"""
hooks:
  - name: bad
    event: Stop
    if: {if_block}
    action: {{type: shell, command: "true"}}
""",
    )
    assert load(tmp_path / "proj").rules == []
    assert "bad" in capsys.readouterr().err


def test_invalid_regex_skipped(tmp_path, home, capsys):
    project_hooks(
        tmp_path,
        """
hooks:
  - name: badre
    event: Stop
    if:
      any_of:
        - field: prompt
          match: {type: regex, value: "[unclosed"}
    action: {type: prompt, text: hi}
""",
    )
    assert load(tmp_path / "proj").rules == []
    assert "badre" in capsys.readouterr().err


def test_async_on_blocking_event_rejected(tmp_path, home, capsys):
    """拦截类事件不允许 async（F28/AC8）。"""
    project_hooks(
        tmp_path,
        """
hooks:
  - name: bad-async
    event: PreToolUse
    async: true
    action: {type: shell, command: "true"}
  - {name: ok-async, event: PostToolUse, async: true, action: {type: shell, command: "true"}}
""",
    )
    engine = load(tmp_path / "proj")
    assert [r.name for r in engine.rules] == ["ok-async"]
    assert engine.rules[0].asyncio_mode is True
    assert "async not allowed for blocking events" in capsys.readouterr().err


def test_user_prompt_submit_also_blocking(tmp_path, home, capsys):
    project_hooks(
        tmp_path,
        "hooks:\n  - {name: x, event: UserPromptSubmit, async: true,"
        ' action: {type: shell, command: "true"}}\n',
    )
    assert load(tmp_path / "proj").rules == []
    assert "async not allowed" in capsys.readouterr().err


# ---- 两层合并 ----


def test_two_layers_merge(tmp_path, home):
    write(
        home / ".mewcode" / "hooks.yaml",
        "hooks:\n  - {name: user-hook, event: Stop, action: {type: prompt, text: u}}\n",
    )
    p = project_hooks(
        tmp_path, "hooks:\n  - {name: proj-hook, event: Stop, action: {type: prompt, text: p}}\n"
    )
    engine = load(tmp_path / "proj")

    assert [r.name for r in engine.rules] == ["proj-hook", "user-hook"]  # 项目级先扫
    assert engine.sources == [str(p), str(home / ".mewcode" / "hooks.yaml")]


def test_duplicate_name_project_wins(tmp_path, home, capsys):
    """跨文件同名：先扫到的（项目级）保留，后到者跳过（F7）。"""
    write(
        home / ".mewcode" / "hooks.yaml",
        "hooks:\n  - {name: dup, event: Stop, action: {type: prompt, text: user}}\n",
    )
    project_hooks(
        tmp_path, "hooks:\n  - {name: dup, event: Stop, action: {type: prompt, text: proj}}\n"
    )
    engine = load(tmp_path / "proj")

    assert len(engine.rules) == 1
    assert engine.rules[0].action.text == "proj"
    assert "duplicate name" in capsys.readouterr().err


# ---- timeout 解析 ----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("30s", 30.0), ("5m", 300.0), ("1h", 3600.0), ("2.5", 2.5), (7, 7.0), ("90", 90.0)],
)
def test_parse_duration_ok(raw, expected):
    assert parse_duration(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "5x", "", "-3s", "s"])
def test_parse_duration_bad(raw):
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_bad_timeout_skips_rule(tmp_path, home, capsys):
    project_hooks(
        tmp_path,
        'hooks:\n  - {name: t, event: Stop, timeout: 5x, action: {type: shell, command: "true"}}\n',
    )
    assert load(tmp_path / "proj").rules == []
    assert "bad duration" in capsys.readouterr().err


def test_misplaced_rule_field_in_action_is_rejected(tmp_path, home, capsys):
    """把规则级字段写进 action 要报错，不能静默忽略（否则用户以为设了超时）。"""
    project_hooks(
        tmp_path,
        """
hooks:
  - name: misplaced
    event: Stop
    action: {type: shell, command: "true", timeout: 5s}
""",
    )
    assert load(tmp_path / "proj").rules == []
    err = capsys.readouterr().err
    assert "unknown action field" in err and "timeout" in err


def test_action_type_classvar_matches(tmp_path, home):
    """每条 Rule 的 action 能报出自己的类型（/hooks 展示用）。"""
    project_hooks(tmp_path, VALID)
    rules = load(tmp_path / "proj").rules
    assert rules[0].action.type is ActionType.SHELL
    assert rules[1].action.type is ActionType.HTTP
