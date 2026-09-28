"""SKILL.md / tool.json 解析测试（docs/ch11 T3）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mewcode.skills import SkillSource, parse_skill_dir


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_skill(tmp_path: Path, name: str, frontmatter: str, body: str = "正文") -> Path:
    d = tmp_path / name
    _write(d / "SKILL.md", f"---\n{frontmatter}\n---\n\n{body}\n")
    return d


def test_parse_skill_dir_minimal(tmp_path):
    """仅 name + description 即合法（F2）。"""
    d = make_skill(tmp_path, "commit", "name: commit\ndescription: 生成提交")
    s = parse_skill_dir(d, SkillSource.BUILTIN)
    assert s.meta.name == "commit"
    assert s.meta.description == "生成提交"
    assert s.meta.allowed_tools == []
    assert s.meta.mode == "inline"
    assert s.meta.fork_context == "none"
    assert s.meta.model is None
    assert s.meta.is_fork() is False
    assert s.prompt_body == "正文\n"
    assert s.source is SkillSource.BUILTIN
    assert s.source_dir == d.resolve()
    assert s.tool_specs == []


def test_parse_skill_dir_invalid_name(tmp_path):
    """大写 / 下划线 / 超长的 name 一律拒绝（F3）。"""
    for bad in ("Commit", "my_skill", "a" * 33, "-x"):
        d = make_skill(tmp_path, "x", f"name: {bad}\ndescription: d")
        with pytest.raises(ValueError):
            parse_skill_dir(d, SkillSource.USER)


def test_parse_skill_dir_requires_description(tmp_path):
    d = make_skill(tmp_path, "x", "name: x")
    with pytest.raises(ValueError, match="description"):
        parse_skill_dir(d, SkillSource.USER)


def test_parse_skill_dir_no_skill_md(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        parse_skill_dir(tmp_path / "empty", SkillSource.PROJECT)


def test_parse_skill_dir_full_frontmatter(tmp_path):
    """五个可选字段全部就位。"""
    d = make_skill(
        tmp_path,
        "review",
        "name: review\ndescription: 审查代码\nallowed_tools: [read_file, grep]\n"
        "mode: fork\nfork_context: recent\nmodel: haiku",
    )
    s = parse_skill_dir(d, SkillSource.BUILTIN)
    assert s.meta.allowed_tools == ["read_file", "grep"]
    assert s.meta.mode == "fork"
    assert s.meta.is_fork() is True
    assert s.meta.fork_context == "recent"
    assert s.meta.model == "haiku"


def test_unknown_mode_and_fork_context_fall_back(tmp_path, capsys):
    """未知 mode / fork_context 打 warning 后回退默认，不抛错（F6/F7）。"""
    d = make_skill(tmp_path, "x", "name: x\ndescription: d\nmode: parallel\nfork_context: sidecar")
    s = parse_skill_dir(d, SkillSource.USER)
    assert s.meta.mode == "inline"
    assert s.meta.fork_context == "none"
    err = capsys.readouterr().err
    assert "unknown mode" in err and "unknown fork_context" in err


def test_parse_skill_dir_with_tool_json(tmp_path):
    """合法 tool.json 解析为 ToolSpec，base_dir 为 Skill 目录（F10）。"""
    d = make_skill(tmp_path, "resume", "name: resume\ndescription: 解析简历")
    _write(
        d / "tool.json",
        json.dumps(
            {
                "tools": [
                    {
                        "name": "parse_resume",
                        "description": "解析简历文件",
                        "input_schema": {"type": "object", "properties": {}},
                        "command": ["references/parse_resume.sh"],
                    }
                ]
            }
        ),
    )
    s = parse_skill_dir(d, SkillSource.PROJECT)
    assert len(s.tool_specs) == 1
    spec = s.tool_specs[0]
    assert spec.name == "parse_resume"  # 工具名用下划线（与项目既有工具一致）
    assert spec.command == ["references/parse_resume.sh"]
    assert spec.base_dir == d.resolve()


def test_tool_json_rejects_bad_shapes(tmp_path):
    """command 为空数组 / 缺 input_schema / 工具名非法都拒绝。"""
    cases = [
        {"tools": [{"name": "ok", "command": [], "input_schema": {}}]},
        {"tools": [{"name": "ok", "command": ["a"], "input_schema": "no"}]},
        {"tools": [{"name": "Bad-Name", "command": ["a"], "input_schema": {}}]},
        {"tools": "not-a-list"},
    ]
    for i, payload in enumerate(cases):
        d = make_skill(tmp_path, f"c{i}", f"name: c{i}\ndescription: d")
        _write(d / "tool.json", json.dumps(payload))
        with pytest.raises(ValueError):
            parse_skill_dir(d, SkillSource.USER)


def test_frontmatter_required(tmp_path):
    """没有 frontmatter 块 / 未闭合都报错。"""
    d = tmp_path / "nofm"
    _write(d / "SKILL.md", "# 没有 frontmatter\n")
    with pytest.raises(ValueError, match="frontmatter"):
        parse_skill_dir(d, SkillSource.USER)

    d2 = tmp_path / "unclosed"
    _write(d2 / "SKILL.md", "---\nname: x\ndescription: d\n")
    with pytest.raises(ValueError, match="unterminated"):
        parse_skill_dir(d2, SkillSource.USER)
