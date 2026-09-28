"""第 1 层落盘替换测试（docs/ch08 T22）。"""

from __future__ import annotations

from pathlib import Path

from mewcode.compact import layer1
from mewcode.compact.const import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
)
from mewcode.compact.layer1 import build_preview, offload_and_snip, spill_single
from mewcode.compact.state import ContentReplacementState, SessionContext
from mewcode.llm import Message, ToolResult, ROLE_TOOL


def _tool_msg(*results: ToolResult) -> Message:
    return Message(role=ROLE_TOOL, tool_results=list(results))


def _session(tmp_path) -> SessionContext:
    # ch09 T1：SessionContext 新增必填 session_dir 字段
    return SessionContext(session_id="s", session_dir=str(tmp_path), spill_dir=str(tmp_path))


def test_spill_single_idempotent(tmp_path):
    ctx = _session(tmp_path)
    spill_single(ctx, "id1", "content")
    first = (tmp_path / "id1").stat().st_mtime_ns
    spill_single(ctx, "id1", "content")
    assert (tmp_path / "id1").stat().st_mtime_ns == first


def test_offload_single_result(tmp_path):
    ctx = _session(tmp_path)
    msgs = [_tool_msg(ToolResult("r1", "x" * 60000))]
    out = offload_and_snip(msgs, ContentReplacementState(), ctx)
    result = out[0].tool_results[0]
    assert result.content.startswith("[content offloaded]")
    assert (tmp_path / "r1").exists()
    head = result.content.split("[head preview]", 1)[1].split("完整内容已保存", 1)[0].strip()
    head_lines = head.splitlines()
    assert len(head_lines) <= PREVIEW_HEAD_LINES
    assert len(head.encode("utf-8")) <= PREVIEW_HEAD_BYTES


def test_offload_aggregate(tmp_path):
    ctx = _session(tmp_path)
    results = [ToolResult(f"r{i}", "y" * 80000) for i in range(3)]
    msgs = [_tool_msg(*results)]
    out = offload_and_snip(msgs, ContentReplacementState(), ctx)
    replaced = sum(1 for r in out[0].tool_results if r.content.startswith("[content offloaded]"))
    assert replaced >= 2
    agg = sum(len(r.content.encode("utf-8")) for r in out[0].tool_results)
    assert agg <= MESSAGE_AGGREGATE_LIMIT


def test_offload_decision_freeze(tmp_path):
    ctx = _session(tmp_path)
    msgs = [
        _tool_msg(
            ToolResult("f1", "c" * 60000),
            ToolResult("f2", "c" * 10000),
            ToolResult("f3", "c" * 30000),
        )
    ]
    state = ContentReplacementState()
    first = offload_and_snip(msgs, state, ctx)
    second = offload_and_snip(msgs, state, ctx)
    assert [r.content for r in first[0].tool_results] == [r.content for r in second[0].tool_results]


def test_offload_spill_failure_retryable(tmp_path, monkeypatch):
    ctx = _session(tmp_path)
    msgs = [_tool_msg(ToolResult("retry", "z" * 60000))]
    state = ContentReplacementState()

    def boom(*args, **kwargs):
        raise OSError("no space")

    monkeypatch.setattr(layer1, "spill_single", boom)
    out1 = offload_and_snip(msgs, state, ctx)
    assert out1[0].tool_results[0].content == "z" * 60000
    assert "retry" not in state._seen_ids

    monkeypatch.setattr(layer1, "spill_single", spill_single)
    out2 = offload_and_snip(msgs, state, ctx)
    assert out2[0].tool_results[0].content.startswith("[content offloaded]")
    assert (tmp_path / "retry").exists()


def test_preview_stable_across_rounds(tmp_path):
    ctx = _session(tmp_path)
    content = "a" * 60000
    spill_single(ctx, "p1", content)
    spill_path = str(Path(ctx.spill_dir) / "p1")
    head = layer1._head_preview(content)
    p1 = build_preview(len(content.encode("utf-8")), head, spill_path)
    p2 = build_preview(len(content.encode("utf-8")), head, spill_path)
    assert p1 == p2

    msgs = [_tool_msg(ToolResult("p1", content))]
    state = ContentReplacementState()
    offload_and_snip(msgs, state, ctx)
    reused = offload_and_snip(msgs, state, ctx)
    assert reused[0].tool_results[0].content == p1
