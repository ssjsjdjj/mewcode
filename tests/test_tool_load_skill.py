"""LoadSkill 工具测试（docs/ch11 T16，F23/F24）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mewcode.skills import ActiveSkills, Catalog
from mewcode.tool import new_default_registry
from mewcode.tool.load_skill import LoadSkillTool


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: h))
    return h


def _write_skill(
    base: Path, name: str, body: str, extra_fm: str = "", tool_json: dict | None = None
):
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    fm = f"name: {name}\ndescription: {name} 技能"
    if extra_fm:
        fm += f"\n{extra_fm}"
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n\n{body}\n", encoding="utf-8")
    if tool_json is not None:
        (d / "tool.json").write_text(json.dumps(tool_json), encoding="utf-8")
    return d


def build(tmp_path, home):
    work = tmp_path / "work"
    catalog = Catalog.load(work)
    active = ActiveSkills()
    registry = new_default_registry()
    return LoadSkillTool(catalog, active, registry), active, registry, work


async def test_unknown_skill_returns_structured_error(tmp_path, home):
    tool, active, _, _ = build(tmp_path, home)
    r = await tool.execute('{"name": "nope"}')
    assert r.is_error is True
    assert r.content == "unknown skill: nope"
    assert active.names() == []


async def test_activate_builtin(tmp_path, home):
    tool, active, _, _ = build(tmp_path, home)
    r = await tool.execute('{"name": "commit"}')
    assert r.is_error is False
    assert "Skill commit activated" in r.content
    assert active.names() == ["commit"]
    assert "git status" in active.snapshot()[0].body


async def test_rereads_body_from_disk(tmp_path, home):
    """激活时从磁盘重读最新正文，用户改了 SKILL.md 立即生效（F23/N5）。"""
    work = tmp_path / "work"
    d = _write_skill(work / ".mewcode" / "skills", "demo", "第一版正文")
    tool, active, _, _ = build(tmp_path, home)
    await tool.execute('{"name": "demo"}')
    assert "第一版正文" in active.snapshot()[0].body

    (d / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo 技能\n---\n\n第二版正文\n", encoding="utf-8"
    )
    await tool.execute('{"name": "demo"}')
    assert "第二版正文" in active.snapshot()[0].body


async def test_reread_failure_falls_back_to_cache(tmp_path, home, capsys):
    """磁盘读失败回退启动期缓存并告警，不中断（N5）。"""
    work = tmp_path / "work"
    _write_skill(work / ".mewcode" / "skills", "demo", "缓存正文")
    tool, active, _, _ = build(tmp_path, home)
    skill = tool._catalog.get("demo")
    skill.source_dir = skill.source_dir / "已经不存在了"  # 制造读失败
    await tool.execute('{"name": "demo"}')
    assert "缓存正文" in active.snapshot()[0].body
    assert "re-read failed" in capsys.readouterr().err


async def test_registers_specialized_tools(tmp_path, home):
    """tool.json 声明的专属工具登记进 registry（F23/AC11）。"""
    work = tmp_path / "work"
    _write_skill(
        work / ".mewcode" / "skills",
        "resume",
        "解析简历",
        extra_fm="allowed_tools: [parse_resume]",
        tool_json={
            "tools": [
                {
                    "name": "parse_resume",
                    "description": "解析简历",
                    "input_schema": {"type": "object"},
                    "command": ["references/parse_resume.sh"],
                }
            ]
        },
    )
    tool, _, registry, _ = build(tmp_path, home)
    assert registry.get("parse_resume") is None
    r = await tool.execute('{"name": "resume"}')
    assert r.is_error is False
    assert "1 specialized tools registered" in r.content
    assert registry.get("parse_resume") is not None


async def test_flags(tmp_path, home):
    tool, _, _, _ = build(tmp_path, home)
    assert tool.name() == "load_skill"
    assert tool.read_only is True  # 权限引擎按 READ 类自动放行（F23/N4/AC7）
    assert tool.is_system is True  # 不受 allowed_tools 白名单约束
    assert tool.deferrable is False
    assert tool.parameters()["required"] == ["name"]


async def test_bad_arguments(tmp_path, home):
    tool, _, _, _ = build(tmp_path, home)
    r = await tool.execute("{not json")
    assert r.is_error is True and "JSON" in r.content
    r = await tool.execute("{}")
    assert r.is_error is True and "name" in r.content
