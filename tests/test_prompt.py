"""prompt 包单测（docs/ch05 T4）：装配顺序/跳空槽/确定性/双重强化/环境/reminder。"""

from mewcode.prompt import (
    Module,
    assemble_system,
    build_system_prompt,
    gather_environment,
    optional_modules,
    plan_reminder,
    system_reminder,
)


def test_assembly_order():
    text = build_system_prompt()
    identity = text.index("You are MewCode")
    tool_usage = text.index("Prefer the dedicated tools")
    assert identity < tool_usage  # 身份(10) 在 工具使用(50) 之前
    assert "\n\n" in text  # 模块以空行分隔


def test_empty_slots_skipped():
    mods = [
        Module("a", 10, "alpha"),
        Module("b", 20, ""),  # 空槽
        Module("c", 30, "gamma"),
        Module("d", 40, ""),  # 空槽
    ]
    text = assemble_system(mods)
    assert text == "alpha\n\ngamma"
    assert "b" not in text and "d" not in text
    assert "\n\n\n" not in text  # 无连续多空行


def test_extension_mounts():
    # 挂载即扩展：新增模块自动按优先级插入，不改装配逻辑
    text = assemble_system([Module("x", 25, "INSERTED"), Module("y", 10, "first")])
    assert text == "first\n\nINSERTED"


def test_determinism():
    assert build_system_prompt() == build_system_prompt()


def test_optional_modules_parameterized():
    """非空参数填充对应槽位，空槽仍为 content=\"\"。"""
    mods = optional_modules("指令文本", "记忆文本", "Skill 清单文本")
    assert mods[0].name == "custom_instructions" and mods[0].content == "指令文本"
    assert mods[1].name == "skills_catalog" and mods[1].content == "Skill 清单文本"
    assert mods[2].name == "long_term_memory" and mods[2].content == "记忆文本"

    empty = optional_modules("指令文本", "记忆文本")
    assert empty[1].name == "skills_catalog" and empty[1].content == ""  # 未传则空槽


def test_build_system_prompt_with_params():
    """非空指令/记忆/Skill 清单 → 对应模块出现在系统提示中且按优先级排列。"""
    text = build_system_prompt("按 MEWCODE.md 行事", "记忆：用户喜欢简洁", "## Available Skills")
    assert "按 MEWCODE.md 行事" in text
    assert "记忆：用户喜欢简洁" in text
    assert "## Available Skills" in text
    # custom-instructions(80) < skills-catalog(90) < long-term-memory(100)
    assert (
        text.index("按 MEWCODE.md 行事")
        < text.index("## Available Skills")
        < text.index("记忆：用户喜欢简洁")
    )


def test_build_system_prompt_empty_matches_old():
    """向后兼容：空参数输出与旧签名逐字节一致（skills-catalog 空槽不产生任何文本）。"""
    assert build_system_prompt() == build_system_prompt("", "")
    assert build_system_prompt() == build_system_prompt("", "", "")
    assert "Available Skills" not in build_system_prompt()


def test_double_reinforcement_in_system():
    text = build_system_prompt()
    # 编辑前必先读 + 优先用专用工具
    assert "read_file" in text and "before editing" in text
    assert "Prefer the dedicated tools" in text and "bash" in text


def test_environment_non_git(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # 非 git 目录
    env = gather_environment("0.1.0", "m")
    assert env.git_status == ""
    rendered = env.render()
    assert "Working directory" in rendered
    assert "Platform" in rendered
    assert "Date" in rendered
    assert "MewCode version: 0.1.0" in rendered
    assert "Model: m" in rendered


def test_plan_reminder_tags_and_levels():
    full = plan_reminder(True)
    concise = plan_reminder(False)
    assert "<system-reminder>" in full and "</system-reminder>" in full
    assert "PLAN MODE" in full and "/do" in full
    assert full != concise
    assert len(concise) < len(full)  # 精简版更短


def test_system_reminder_wrapper():
    assert system_reminder("hi") == "<system-reminder>\nhi\n</system-reminder>"
