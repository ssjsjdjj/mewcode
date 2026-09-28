"""命令注册中心单测（docs/ch10 T2）：注册、冲突、前缀匹配、visible 排序。"""

from __future__ import annotations

import pytest

from mewcode.command.command import Command, Kind
from mewcode.command.registry import Registry


def _cmd(name="alpha", *, aliases=None, hidden=False) -> Command:
    async def _handler(ui) -> None:  # noqa: ANN001
        pass

    return Command(
        name=name,
        description="描述",
        kind=Kind.LOCAL,
        handler=_handler,
        aliases=aliases or [],
        hidden=hidden,
    )


def test_register_ok():
    reg = Registry()
    reg.register(_cmd("alpha", aliases=["a"]))
    assert reg.lookup("alpha") is reg.lookup("a")  # 主名与别名指向同一 Command
    assert reg.lookup("ALPHA") is not None  # lookup 大小写不敏感
    assert reg.lookup("nope") is None


def test_register_duplicate_name_raises():
    reg = Registry()
    reg.register(_cmd("alpha"))
    with pytest.raises(RuntimeError) as exc:
        reg.register(_cmd("alpha"))
    assert "alpha" in str(exc.value)


def test_register_duplicate_alias_raises():
    reg = Registry()
    reg.register(_cmd("alpha", aliases=["a"]))
    with pytest.raises(RuntimeError) as exc:
        reg.register(_cmd("beta", aliases=["a"]))
    assert "a" in str(exc.value)


def test_register_invalid_name_or_alias_raises():
    reg = Registry()
    with pytest.raises(ValueError):
        reg.register(_cmd("ALPHA"))  # 大写
    with pytest.raises(ValueError):
        reg.register(_cmd("", aliases=["x"]))  # 空名
    with pytest.raises(ValueError):
        reg.register(_cmd("alpha", aliases=["X"]))  # 大写别名


def test_visible_sorted():
    reg = Registry()
    reg.register(_cmd("zeta"))
    reg.register(_cmd("alpha"))
    reg.register(_cmd("mike"))
    reg.register(_cmd("secret", hidden=True))
    assert [c.name for c in reg.visible()] == ["alpha", "mike", "zeta"]
    # 返回副本，外部改动不影响内部
    reg.visible().append(_cmd("x"))
    assert [c.name for c in reg.visible()] == ["alpha", "mike", "zeta"]


def test_prefix_match():
    reg = Registry()
    for n in ("session", "status", "review", "resume"):
        reg.register(_cmd(n))
    assert [c.name for c in reg.prefix_match("/s")] == ["session", "status"]
    assert [c.name for c in reg.prefix_match("s")] == ["session", "status"]  # 无前导 / 亦可
    assert [c.name for c in reg.prefix_match("/SE")] == ["session"]  # 大小写不敏感
    assert [c.name for c in reg.prefix_match("/x")] == []
    assert [c.name for c in reg.prefix_match("/")] == ["resume", "review", "session", "status"]
    assert [c.name for c in reg.prefix_match("")] == ["resume", "review", "session", "status"]
