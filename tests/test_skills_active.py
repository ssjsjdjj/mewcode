"""ActiveSkills 激活列表测试（docs/ch11 T7）。"""

from __future__ import annotations

from mewcode.skills import ActiveSkills


def test_activate_appends_in_order():
    a = ActiveSkills()
    a.activate("commit", "C1")
    a.activate("review", "R1")
    assert a.names() == ["commit", "review"]
    assert [e.body for e in a.snapshot()] == ["C1", "R1"]
    assert len(a) == 2


def test_reactivate_updates_body_keeps_position():
    """重复激活同名 Skill：内容更新，位置不变（F24）。"""
    a = ActiveSkills()
    a.activate("commit", "旧正文")
    a.activate("review", "R")
    a.activate("commit", "新正文")
    assert a.names() == ["commit", "review"]
    assert a.snapshot()[0].body == "新正文"
    assert len(a) == 2


def test_clear():
    a = ActiveSkills()
    a.activate("commit", "C")
    a.clear()
    assert a.names() == []
    assert a.snapshot() == []
    assert len(a) == 0
    a.activate("commit", "C2")  # clear 后可重新激活
    assert a.names() == ["commit"]


def test_snapshot_is_a_copy():
    """snapshot 返回拷贝，外部改动不影响内部状态（F22）。"""
    a = ActiveSkills()
    a.activate("commit", "C")
    snap = a.snapshot()
    snap.append(snap[0])
    snap[0].body = "被改坏了"
    assert a.names() == ["commit"]
    assert a.snapshot()[0].body == "C"
