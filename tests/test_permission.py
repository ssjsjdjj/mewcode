"""permission 模块单测（docs/ch06）：黑名单/沙箱/规则/引擎流水线/配置/持久化。"""

from pathlib import Path

import pytest

from mewcode.llm import ToolCall
from mewcode.permission import Decision, Mode, new_engine
from mewcode.permission.blacklist import hits_blacklist
from mewcode.permission.rule import Rule, RuleSet, escape_glob, match_pattern, parse_rule
from mewcode.permission.sandbox import eval_symlinks_or_ancestor, sandbox_ok
from mewcode.permission.settings import (
    SettingsError,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)
from mewcode.permission import Category


def C(id, name, inp):
    return ToolCall(id, name, inp)


def make_engine(tmp_path):
    engine, err = new_engine(str(tmp_path))
    assert err is None
    return engine


# ---------- 黑名单 ----------


def test_blacklist_hits_and_safe():
    for c in [
        "rm -rf /",
        "rm -fr ~",
        ":(){ :|:& };:",
        "dd if=/dev/zero of=/dev/sda",
        "chmod -R 777 /",
    ]:
        assert hits_blacklist(c), c
    for c in ["rm -rf ./build", "git status", "ls -la"]:
        assert not hits_blacklist(c), c


def test_blacklist_bypass_blocks(tmp_path):
    engine = make_engine(tmp_path)
    d, _ = engine.check(Mode.BYPASS, C("1", "bash", '{"command":"rm -rf /"}'), False)
    assert d == Decision.DENY


# ---------- 沙箱 ----------


def test_sandbox_inside_outside_ancestor(tmp_path):
    engine = make_engine(tmp_path)
    assert sandbox_ok(engine, "a.txt")  # 项目内（含未创建祖先回退）
    assert not sandbox_ok(engine, "/etc/passwd")
    assert not sandbox_ok(engine, "../outside")
    assert eval_symlinks_or_ancestor(str(tmp_path / "x/y.txt")).startswith(engine.root)


def test_sandbox_symlink_escape(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    outside = str(tmp_path.parent / "outside_secret")
    import mewcode.permission.sandbox as sb

    orig = sb.Path.resolve

    def fake_resolve(self, strict=False):
        if strict and "link.txt" in str(self):
            return Path(outside)
        return orig(self, strict=strict)

    monkeypatch.setattr(sb.Path, "resolve", fake_resolve)
    assert not sandbox_ok(engine, "link.txt")


# ---------- 规则 ----------


def test_rule_parse_and_match():
    r, ok = parse_rule("Bash(git *)")
    assert ok and r.tool == "Bash" and r.pattern == "git *"
    r2, ok2 = parse_rule("Read")
    assert ok2 and r2.pattern == ""
    r3, ok3 = parse_rule("(bad")
    assert not ok3
    assert match_pattern("git *", "git status")
    assert not match_pattern("git *", "npm i")
    assert match_pattern("src/**", "src/a/b.py")
    assert not match_pattern("src/**", "docs/x")
    assert match_pattern("git **", "git push")
    assert match_pattern(escape_glob("echo *"), "echo *")  # 转义字面星号


def test_deny_priority_same_level():
    rs = RuleSet(allow=[Rule("Bash", "git *", True)], deny=[Rule("Bash", "git push", False)])
    d, hit = rs.match("Bash", "git push")
    assert hit and d == Decision.DENY


# ---------- 配置 ----------


def test_settings_load_missing_and_invalid(tmp_path):
    assert load_settings(str(tmp_path / "nope.yaml")).default_mode == ""
    bad = tmp_path / "bad.yaml"
    bad.write_text("permissions: [bad", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(str(bad))


def test_settings_to_rule_set():
    from mewcode.permission.settings import PermissionsBlock, Settings

    s = Settings(
        default_mode="plan",
        permissions=PermissionsBlock(allow=["Bash(git *)", "((bad"], deny=["Bash(rm *)"]),
    )
    rs = to_rule_set(s)
    assert len(rs.allow) == 1 and len(rs.deny) == 1  # 非法条跳过


# ---------- 映射 ----------


def test_mapping():
    assert friendly_name("read_file") == "Read"
    assert friendly_name("unknown_x") == "unknown_x"
    assert categorize("read_file", True) == Category.READ
    assert categorize("write_file", False) == Category.WRITE
    assert categorize("bash", False) == Category.EXEC
    assert categorize("weird", False) == Category.EXEC
    assert extract_target(C("1", "read_file", '{"path": "a"}')) == ("a", True, True)
    assert extract_target(C("2", "bash", '{"command": "ls"}')) == ("ls", False, True)
    assert extract_target(C("3", "glob", "{}")) == (".", True, True)
    assert extract_target(C("4", "read_file", "{bad")) == (
        "",
        True,
        False,
    )  # 解析失败 → is_file 仍 True
    assert extract_target(C("5", "unknown", "{}")) == ("", False, False)


# ---------- 引擎流水线 ----------


def test_engine_pipeline(tmp_path):
    engine = make_engine(tmp_path)
    assert (
        engine.check(Mode.DEFAULT, C("1", "read_file", '{"path":"/etc/passwd"}'), True)[0]
        == Decision.DENY
    )
    assert (
        engine.check(Mode.DEFAULT, C("2", "write_file", '{"path":"../x"}'), False)[0]
        == Decision.DENY
    )
    assert (
        engine.check(
            Mode.DEFAULT, C("3", "write_file", '{"path":"new/f.txt","content":"x"}'), False
        )[0]
        == Decision.ASK
    )
    assert engine.check(Mode.DEFAULT, C("4", "bash", '{"command":"ls"}'), False)[0] == Decision.ASK
    assert engine.check(Mode.DEFAULT, C("5", "read_file", "{bad"), True)[0] == Decision.DENY
    assert engine.check(Mode.DEFAULT, C("6", "weird", "{}"), False)[0] == Decision.ASK


def test_mode_matrix(tmp_path):
    engine = make_engine(tmp_path)
    read = engine.check(Mode.DEFAULT, C("1", "read_file", '{"path":"a.txt"}'), True)[0]
    assert read == Decision.ALLOW
    assert (
        engine.check(
            Mode.ACCEPT_EDITS, C("2", "write_file", '{"path":"a.txt","content":"x"}'), False
        )[0]
        == Decision.ALLOW
    )
    assert (
        engine.check(Mode.ACCEPT_EDITS, C("3", "bash", '{"command":"ls"}'), False)[0]
        == Decision.ASK
    )
    assert engine.check(Mode.BYPASS, C("4", "bash", '{"command":"ls"}'), False)[0] == Decision.ALLOW
    assert (
        engine.check(Mode.PLAN, C("5", "write_file", '{"path":"a.txt","content":"x"}'), False)[0]
        == Decision.ASK
    )


def test_rule_priority(tmp_path):
    engine = make_engine(tmp_path)
    from mewcode.permission.rule import Rule

    engine.local.allow.append(Rule("Bash", "git *", True))
    engine.project.deny.append(Rule("Bash", "git status", False))
    assert (
        engine.check(Mode.DEFAULT, C("1", "bash", '{"command":"git status"}'), False)[0]
        == Decision.ALLOW
    )  # 本地 allow 就近
    engine2 = make_engine(tmp_path)
    engine2.project.deny.append(Rule("Bash", "git status", False))
    engine2.user.allow.append(Rule("Bash", "git *", True))
    assert (
        engine2.check(Mode.DEFAULT, C("1", "bash", '{"command":"git status"}'), False)[0]
        == Decision.DENY
    )  # 项目 deny 盖用户 allow


def test_persist_local_allow(tmp_path):
    engine = make_engine(tmp_path)
    engine.persist_local_allow(C("1", "bash", '{"command":"ls"}'))
    text = (tmp_path / ".mewcode" / "settings.local.yaml").read_text(encoding="utf-8")
    assert "Bash(ls)" in text
    engine.persist_local_allow(C("1", "bash", '{"command":"ls"}'))  # 幂等
    assert text.count("Bash(ls)") == 1
    e2, _ = new_engine(str(tmp_path))
    assert e2.check(Mode.DEFAULT, C("1", "bash", '{"command":"ls"}'), False)[0] == Decision.ALLOW
