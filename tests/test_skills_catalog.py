"""Catalog 三层加载、覆盖与依赖检查测试（docs/ch11 T6）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.skills import Catalog
from mewcode.tool import new_default_registry


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skill(dir_path: Path, name: str, description: str, extra: str = "") -> None:
    fm = f"name: {name}\ndescription: {description}"
    if extra:
        fm += f"\n{extra}"
    _write(dir_path / name / "SKILL.md", f"---\n{fm}\n---\n\n{name} 的正文\n")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """把 Path.home() 指到临时目录，隔离真实的 ~/.mewcode/skills。"""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def test_load_catalog_builtin_only(tmp_path, home):
    """空 work_dir + 空 HOME 时只剩三个内置 Skill（AC1）。"""
    c = Catalog.load(tmp_path / "work")
    assert c.names() == ["commit", "review", "test"]
    assert c.get("commit") is not None
    assert c.get("commit").source.value == "builtin"


def test_builtin_frontmatter_is_valid(tmp_path, home):
    """三个内置 Skill 的 frontmatter 都符合各自设计（F32）。"""
    c = Catalog.load(tmp_path / "work")
    commit, review, test = c.get("commit"), c.get("review"), c.get("test")
    assert commit.meta.allowed_tools == ["bash", "read_file", "grep"]
    assert commit.meta.mode == "inline"
    assert review.meta.is_fork() is True
    assert review.meta.fork_context == "none"
    assert test.meta.mode == "inline"


def test_load_catalog_user_override(tmp_path, home):
    """用户级同名 Skill 覆盖内置（F13）。"""
    _skill(home / ".mewcode" / "skills", "commit", "用户级的 commit")
    c = Catalog.load(tmp_path / "work")
    assert c.names() == ["commit", "review", "test"]
    assert c.get("commit").meta.description == "用户级的 commit"
    assert c.get("commit").source.value == "user"


def test_load_catalog_project_override(tmp_path, home):
    """项目级覆盖用户级与内置（F13）。"""
    _skill(home / ".mewcode" / "skills", "commit", "用户级的 commit")
    work = tmp_path / "work"
    _skill(work / ".mewcode" / "skills", "commit", "项目级的 commit")
    c = Catalog.load(work)
    assert c.get("commit").meta.description == "项目级的 commit"
    assert c.get("commit").source.value == "project"


def test_project_only_skill_is_added(tmp_path, home):
    """项目级新增的 Skill 与内置共存。"""
    work = tmp_path / "work"
    _skill(work / ".mewcode" / "skills", "my-skill", "自定义技能")
    c = Catalog.load(work)
    assert c.names() == ["commit", "my-skill", "review", "test"]


def test_broken_skill_skipped_others_survive(tmp_path, home, capsys):
    """单个 Skill 损坏只跳过自身（F11）。"""
    sd = home / ".mewcode" / "skills"
    _skill(sd, "good", "能用的")
    _write(sd / "bad" / "SKILL.md", "没有 frontmatter\n")
    c = Catalog.load(tmp_path / "work")
    assert "good" in c.names()
    assert "bad" not in c.names()
    assert "bad" in capsys.readouterr().err


def test_dir_without_skill_md_warns(tmp_path, home, capsys):
    """无 SKILL.md 的子目录跳过并告警（F14）。"""
    (home / ".mewcode" / "skills" / "empty").mkdir(parents=True)
    c = Catalog.load(tmp_path / "work")
    assert "empty" not in c.names()
    assert "no SKILL.md" in capsys.readouterr().err


def test_validate_tools_missing_tool(tmp_path, home):
    """allowed_tools 引用未注册工具 → 记一条 issue（F15/AC10）。"""
    sd = home / ".mewcode" / "skills"
    _skill(sd, "broken", "引用了不存在的工具", "allowed_tools: [NotExist]")
    c = Catalog.load(tmp_path / "work")
    issues = c.validate_tools(new_default_registry())
    assert [(i.skill_name, i.tool_name) for i in issues] == [("broken", "NotExist")]


def test_validate_tools_accepts_builtin_refs(tmp_path, home):
    """内置 Skill 引用的都是真实工具，且 load_skill/install_skill 视为可用。"""
    sd = home / ".mewcode" / "skills"
    _skill(sd, "sys", "只用系统工具", "allowed_tools: [load_skill, install_skill]")
    c = Catalog.load(tmp_path / "work")
    assert c.validate_tools(new_default_registry()) == []


def test_validate_tools_accepts_own_tool_json(tmp_path, home):
    """Skill 自己 tool.json 声明的专属工具算可用（F15）。"""
    import json

    sd = home / ".mewcode" / "skills" / "resume"
    _skill(home / ".mewcode" / "skills", "resume", "解析简历", "allowed_tools: [parse_resume]")
    _write(
        sd / "tool.json",
        json.dumps(
            {
                "tools": [
                    {
                        "name": "parse_resume",
                        "description": "d",
                        "input_schema": {"type": "object"},
                        "command": ["references/x.sh"],
                    }
                ]
            }
        ),
    )
    c = Catalog.load(tmp_path / "work")
    assert c.validate_tools(new_default_registry()) == []


def test_remove(tmp_path, home):
    _skill(tmp_path / "work" / ".mewcode" / "skills", "temp", "临时")
    c = Catalog.load(tmp_path / "work")
    assert "temp" in c.names()
    c.remove("temp")
    assert "temp" not in c.names()
    c.remove("temp")  # 幂等
    assert "temp" not in c.names()


def test_reload_picks_up_new_skill(tmp_path, home):
    """reload 重新扫描三层路径（F17）。"""
    work = tmp_path / "work"
    c = Catalog.load(work)
    assert c.names() == ["commit", "review", "test"]
    _skill(work / ".mewcode" / "skills", "fresh", "新装的")
    c.reload(work)
    assert "fresh" in c.names()


def test_reload_removes_deleted_skill(tmp_path, home):
    work = tmp_path / "work"
    _skill(work / ".mewcode" / "skills", "temp", "临时")
    c = Catalog.load(work)
    assert "temp" in c.names()
    import shutil

    shutil.rmtree(work / ".mewcode" / "skills" / "temp")
    c.reload(work)
    assert "temp" not in c.names()
