"""compact 状态类测试（docs/ch08 T22）。"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from mewcode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
    open_session_context,
    parse_session_time,
)


def test_new_session_context(tmp_path):
    """新格式 ID：YYYYMMDD-HHMMSS-xxxx，session_dir 与 spill_dir 派生正确。"""
    ctx = new_session_context(str(tmp_path))
    parts = ctx.session_id.split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 8 and parts[0].isdigit()  # YYYYMMDD
    assert len(parts[1]) == 6 and parts[1].isdigit()  # HHMMSS
    assert len(parts[2]) == 4  # 4 字符 hex
    assert Path(ctx.session_dir).is_absolute()
    assert ctx.session_dir.endswith(ctx.session_id)
    assert Path(ctx.spill_dir).is_absolute()
    assert ctx.spill_dir.endswith(f"{os.sep}tool-results")
    assert ctx.spill_dir == str(Path(ctx.session_dir) / "tool-results")


def test_new_session_context_rand_fail_fallback(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("no entropy")

    monkeypatch.setattr("mewcode.compact.state.secrets.token_hex", boom)
    ctx = new_session_context(str(tmp_path))
    parts = ctx.session_id.split("-")
    assert len(parts) == 3 and len(parts[2]) == 4


def test_parse_session_time_and_open(tmp_path):
    """parse_session_time 解析前 15 位；open_session_context 复用已有目录。"""
    ctx = new_session_context(str(tmp_path))
    ts = parse_session_time(ctx.session_id)
    assert ts.strftime("%Y%m%d-%H%M%S") == ctx.session_id[:15]
    reopened = open_session_context(str(tmp_path), ctx.session_id)
    assert reopened.session_dir == ctx.session_dir
    assert reopened.spill_dir == ctx.spill_dir


def test_open_session_context_missing_dir(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        open_session_context(str(tmp_path), "20260101-000000-aaaa")


def test_decide_once_freeze_kept():
    state = ContentReplacementState()
    first = state.decide_once("id1", "orig", lambda: ("kept", ""))
    assert first == "orig"
    # 第二次不再走回调，直接复用 kept 结果
    second = state.decide_once("id1", "orig", lambda: ("replaced", "should-not-happen"))
    assert second == "orig"


def test_decide_once_freeze_replaced():
    state = ContentReplacementState()
    first = state.decide_once("id1", "orig", lambda: ("replaced", "preview"))
    assert first == "preview"
    second = state.decide_once("id1", "orig", lambda: ("kept", ""))
    assert second == "preview"


def test_decide_once_skip_does_not_mark():
    state = ContentReplacementState()
    first = state.decide_once("id1", "orig", lambda: ("skip", ""))
    assert first == "orig"
    # skip 不写账本：下一次仍走回调
    second = state.decide_once("id1", "orig", lambda: ("replaced", "preview"))
    assert second == "preview"


def test_recovery_state_snapshot_order():
    rec = RecoveryState()
    a = os.path.abspath("/a")  # Windows 下 /a 非绝对路径，先归一到 C:\a
    b = os.path.abspath("/b")
    rec.record_file(a, "1")
    rec.record_file(b, "2")
    snap = rec.snapshot()
    assert [r.path for r in snap] == [b, a]
    # 返回的是拷贝，改它不影响内部
    snap.pop()
    assert len(rec.snapshot()) == 2


def test_recovery_state_concurrent():
    rec = RecoveryState()
    n = 50
    barrier = threading.Barrier(n)
    errs: list[Exception] = []

    def worker(i: int):
        try:
            barrier.wait()
            for _ in range(20):
                rec.record_file(f"/f{i}", str(i))
                rec.snapshot()
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs


def test_auto_tracking_consecutive_budget():
    cb = CompactCircuitBreaker()
    cb.record_failure()
    cb.record_failure()
    assert cb.tripped() is False
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    assert cb.tripped() is False
    cb.record_failure()
    assert cb.tripped() is True


def test_auto_tracking_concurrent():
    cb = CompactCircuitBreaker()
    n = 20
    barrier = threading.Barrier(n)
    errs: list[Exception] = []

    def worker():
        try:
            barrier.wait()
            for _ in range(200):
                cb.record_failure()
                cb.record_success()
                cb.tripped()
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errs
