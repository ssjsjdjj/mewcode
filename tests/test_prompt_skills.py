"""Skill 两阶段注入的文本渲染测试（docs/ch11 T13）。"""

from __future__ import annotations

from pathlib import Path

from mewcode.prompt import (
    ActiveSkillEntry,
    SkillCatalogItem,
    build_system_prompt,
    render_active_skills_block,
    render_skills_catalog,
)
from mewcode.skills import (
    ActiveSkills,
    Catalog,
    PromptEntry,
    PromptItem,
    active_to_prompt_entries,
    catalog_to_prompt_items,
)


def test_render_skills_catalog_empty():
    assert render_skills_catalog([]) == ""


def test_render_skills_catalog_non_empty():
    out = render_skills_catalog(
        [SkillCatalogItem("commit", "生成提交"), SkillCatalogItem("review", "审查代码")]
    )
    assert out.startswith("## Available Skills\n")
    assert "- commit: 生成提交" in out
    assert "- review: 审查代码" in out
    assert 'LoadSkill tool with {"name": "<skill_name>"}' in out
    assert out.index("- commit") < out.index("- review")


def test_render_active_skills_block_empty():
    """未激活任何 Skill 时该块为空串，装配时被跳过。"""
    assert render_active_skills_block([]) == ""


def test_render_active_skills_block_non_empty():
    out = render_active_skills_block(
        [ActiveSkillEntry("commit", "步骤一\n步骤二"), ActiveSkillEntry("review", "审查要点")]
    )
    assert out.startswith("## Active Skills\n")
    assert "### Skill: commit\n\n步骤一\n步骤二" in out
    assert "### Skill: review\n\n审查要点" in out
    assert out.index("### Skill: commit") < out.index("### Skill: review")


def test_catalog_list_feeds_system_prompt(tmp_path, monkeypatch):
    """端到端：Catalog → 桥接 → 渲染 → 稳定系统提示里出现技能清单（F21）。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    catalog = Catalog.load(tmp_path / "work")
    catalog_text = render_skills_catalog(catalog_to_prompt_items(catalog))
    prompt = build_system_prompt("", "", catalog_text)

    assert "## Available Skills" in prompt
    for name in ("commit", "review", "test"):
        assert f"- {name}:" in prompt


def test_active_skills_feed_env_block():
    """端到端：ActiveSkills → 桥接 → 渲染 → 环境块含 SOP 正文（F22）。"""
    active = ActiveSkills()
    active.activate("commit", "先 git status 再 git diff")
    block = render_active_skills_block(active_to_prompt_entries(active))
    assert "### Skill: commit" in block
    assert "先 git status 再 git diff" in block


def test_duck_typed_entries_from_skills_package():
    """skills 包的桥接类型可直接喂给 prompt 渲染函数，无需二次转换。"""
    items = [PromptItem("demo", "示范")]
    entries = [PromptEntry("demo", "正文")]
    assert render_skills_catalog(items) == render_skills_catalog([SkillCatalogItem("demo", "示范")])
    assert render_active_skills_block(entries) == render_active_skills_block(
        [ActiveSkillEntry("demo", "正文")]
    )
