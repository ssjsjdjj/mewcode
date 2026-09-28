"""ch07 AC11 集成：MCP 工具走 ch06 权限判定链路，permission 包零改动。

核心断言：mcp__<server>__<tool> 全名在既有的 categorize / friendly_name /
extract_target 语义下，按 read_only 走只读放行 / 执行 Ask / bypass 放行；
allow 规则可用精确名或 mcp__<server>__* 命中；黑名单与路径沙箱对 MCP 工具自动跳过。
"""

from pathlib import Path

from mewcode.llm import ToolCall
from mewcode.permission import Decision, Mode, new_engine


def call(name: str, args: str = "{}") -> ToolCall:
    return ToolCall(id="c1", name=name, input=args)


def _engine(root: Path):
    eng, err = new_engine(str(root))
    assert err is None
    return eng


def test_read_only_mcp_default_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    eng = _engine(tmp_path)
    decision, _ = eng.check(Mode.DEFAULT, call("mcp__github__list_issues"), True)
    assert decision == Decision.ALLOW  # readOnlyHint=True → READ 兜底放行


def test_exec_mcp_default_ask(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    eng = _engine(tmp_path)
    decision, _ = eng.check(Mode.DEFAULT, call("mcp__github__create_issue"), False)
    assert decision == Decision.ASK  # 无 readOnlyHint → EXEC 兜底 Ask


def test_exec_mcp_bypass_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    eng = _engine(tmp_path)
    decision, _ = eng.check(Mode.BYPASS, call("mcp__github__create_issue"), False)
    assert decision == Decision.ALLOW


def test_rule_mcp_wildcard_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    settings = tmp_path / ".mewcode" / "settings.yaml"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text('permissions:\n  allow: ["mcp__github__*"]\n', encoding="utf-8")
    eng = _engine(tmp_path)
    decision, reason = eng.check(Mode.DEFAULT, call("mcp__github__create_issue"), False)
    assert decision == Decision.ALLOW
    assert "mcp__github__create_issue" in reason


def test_mcp_exec_skips_blacklist(tmp_path, monkeypatch):
    """MCP 工具参数里的危险命令不触发黑名单（extract_target 返回 target="" 自动跳过）。"""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    eng = _engine(tmp_path)
    decision, _ = eng.check(Mode.BYPASS, call("mcp__bad__run", '{"command": "rm -rf /"}'), False)
    assert decision == Decision.ALLOW


def test_builtin_bash_still_blacklisted(tmp_path, monkeypatch):
    """内置 bash 工具不受影响：bypass 下 rm -rf / 仍被黑名单拦下。"""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    eng = _engine(tmp_path)
    decision, _ = eng.check(Mode.BYPASS, call("bash", '{"command": "rm -rf /"}'), False)
    assert decision == Decision.DENY
