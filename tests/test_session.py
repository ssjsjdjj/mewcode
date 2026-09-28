"""会话子包测试（docs/ch09 T8）：JSONL 读写、压缩标记、恢复、列表、清理。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from mewcode.llm import Message, ToolCall, ToolResult
from mewcode.session.cleanup import clean_expired
from mewcode.session.list import list_sessions
from mewcode.session.load import _truncate_orphaned_tool_calls, load_session
from mewcode.session.writer import Writer


def _read_rows(path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _make_session(base, session_id: str, content: str, model: str = "", mtime=None):
    """手工构造一个含 conversation.jsonl 的会话目录，便于控制 mtime。"""
    d = base / session_id
    d.mkdir(parents=True, exist_ok=True)
    row = {"role": "user", "content": content, "ts": 0}
    if model:
        row["model"] = model
    (d / "conversation.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if mtime is not None:
        os.utime(d / "conversation.jsonl", (mtime, mtime))
    return d


def test_writer_append_and_read(tmp_path):
    """写入 3 条消息 → 逐行读回验证 JSON 结构。"""
    writer = Writer(str(tmp_path))
    writer.append(Message(role="user", content="hello"), model="m1", is_first=True)
    writer.append(Message(role="assistant", content="hi!"), model="", is_first=False)
    writer.append(
        Message(
            role="tool",
            content="result",
            tool_results=[ToolResult(tool_call_id="call_1", content="ok")],
        ),
        model="",
        is_first=False,
    )
    writer.close()

    rows = _read_rows(tmp_path / "conversation.jsonl")
    assert len(rows) == 3
    assert rows[0]["role"] == "user" and rows[0]["content"] == "hello"
    assert rows[0]["model"] == "m1"  # 首条携带 model
    assert rows[1]["role"] == "assistant"
    assert "model" not in rows[1]  # 非首条不写 model
    assert rows[2]["role"] == "tool"
    assert rows[2]["tool_results"] == [
        {"tool_call_id": "call_1", "content": "ok", "is_error": False}
    ]
    assert all("ts" in r for r in rows)


def test_writer_path(tmp_path):
    """path 属性 = 绝对 JSONL 路径，且文件存在；open_existing 同样填充。"""
    writer = Writer(str(tmp_path))
    assert writer.path == str((tmp_path / "conversation.jsonl").resolve())
    assert Path(writer.path).is_file()
    writer.close()

    writer2 = Writer.open_existing(str(tmp_path))
    assert writer2.path == str((tmp_path / "conversation.jsonl").resolve())
    writer2.close()


def test_writer_compact_marker(tmp_path):
    """消息 → compact 标记 → 新消息 → load_session 只返回 compact 后的。"""
    writer = Writer(str(tmp_path))
    writer.append(Message(role="user", content="before"), model="m1", is_first=True)
    writer.append(Message(role="assistant", content="pre"), model="", is_first=False)
    writer.write_compact_marker()
    writer.append(Message(role="user", content="after"), model="", is_first=False)
    writer.close()

    msgs = load_session(str(tmp_path))
    assert [m.content for m in msgs] == ["after"]


def test_load_session_bad_line_skip(tmp_path):
    """中间插入坏行 → 被跳过，其余正常。"""
    writer = Writer(str(tmp_path))
    writer.append(Message(role="user", content="one"), model="m1", is_first=True)
    writer.close()
    with open(tmp_path / "conversation.jsonl", "ab") as f:
        f.write(b"{broken json\n")
    writer2 = Writer.open_existing(str(tmp_path))
    writer2.append(Message(role="user", content="two"), model="", is_first=False)
    writer2.close()

    msgs = load_session(str(tmp_path))
    assert [m.content for m in msgs] == ["one", "two"]


def test_load_session_orphaned_tool_calls(tmp_path):
    """末尾是带 tool_calls 的 assistant → 被截断。"""
    writer = Writer(str(tmp_path))
    writer.append(Message(role="user", content="go"), model="m1", is_first=True)
    writer.append(
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="read_file", input="{}")],
        ),
        model="",
        is_first=False,
    )
    writer.close()

    msgs = load_session(str(tmp_path))
    assert len(msgs) == 1
    assert msgs[0].role == "user"


def test_truncate_orphaned_tool_calls_keeps_normal():
    """最后一条是普通消息 → 原样返回。"""
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="ok"),
    ]
    assert _truncate_orphaned_tool_calls(msgs) is msgs


def test_list_sessions(tmp_path):
    """3 个会话目录 → 返回 3 项，按修改时间倒序。"""
    now = datetime.now()
    ids = [now.strftime("%Y%m%d-%H%M%S") + f"-{i:04x}" for i in range(3)]
    for i, sid in enumerate(ids):
        _make_session(tmp_path, sid, f"msg-{i}", model=f"model-{i}", mtime=now.timestamp() + i)

    items = list_sessions(str(tmp_path))
    assert len(items) == 3
    assert [it.id for it in items] == list(reversed(ids))  # mtime 倒序
    assert items[0].title == "msg-2"
    assert items[0].model == "model-2"
    assert items[0].size > 0
    assert items[0].dir.startswith(str(tmp_path))


def test_list_sessions_skips_old_format(tmp_path):
    """混合新旧格式目录 → 只返回新格式。"""
    now = datetime.now()
    new_id = now.strftime("%Y%m%d-%H%M%S") + "-abcd"
    _make_session(tmp_path, new_id, "new")
    _make_session(tmp_path, "1717200000-ab12cd34", "old")  # 旧格式：unix 时间戳
    (tmp_path / "notes").mkdir()  # 非会话目录
    items = list_sessions(str(tmp_path))
    assert [it.id for it in items] == [new_id]


def test_clean_expired(tmp_path):
    """31 天前目录被删，1 天前目录保留。"""
    now = datetime.now()
    old_id = (now - timedelta(days=31)).strftime("%Y%m%d-%H%M%S") + "-aaaa"
    fresh_id = (now - timedelta(days=1)).strftime("%Y%m%d-%H%M%S") + "-bbbb"
    _make_session(tmp_path, old_id, "old")
    _make_session(tmp_path, fresh_id, "new")

    clean_expired(str(tmp_path), timedelta(days=30))

    assert not (tmp_path / old_id).exists()
    assert (tmp_path / fresh_id).exists()
