"""恢复附件构造测试（docs/ch08 T22）。"""

from __future__ import annotations

from datetime import datetime

from mewcode.llm import ToolDefinition
from mewcode.compact.const import ESTIMATE_CHARS_PER_TOKEN, RECOVERY_TOKENS_PER_FILE
from mewcode.compact.recovery import (
    BOUNDARY_NOTICE,
    build_recovery_attachment,
    render_file_block,
)
from mewcode.compact.state import FileReadRecord

CHAR_LIMIT = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)


def test_render_file_block_truncate():
    rec = FileReadRecord("/big.py", "a" * (CHAR_LIMIT + 500), datetime(2026, 8, 16, 10, 0))
    block = render_file_block(rec)
    assert "(content truncated)" in block
    assert "a" * CHAR_LIMIT in block  # 头部保留
    assert ("a" * (CHAR_LIMIT + 100)) not in block  # 尾部截掉


def test_build_recovery_attachment_limit():
    defs = []
    records = [
        FileReadRecord(f"/f{i}", f"content{i}", datetime(2026, 8, 16, 10, i)) for i in range(7)
    ]
    records.sort(key=lambda r: r.timestamp, reverse=True)
    text = build_recovery_attachment(records, defs)
    for i in (6, 5, 4, 3, 2):
        assert f"/f{i}" in text
    for i in (0, 1):
        assert f"/f{i}" not in text
    assert text.index("/f6") < text.index("/f5") < text.index("/f4")


def test_build_recovery_attachment_tools_exact():
    defs = [
        ToolDefinition("read_file", "读取文件", {"path": "str"}),
        ToolDefinition("write_file", "写入文件", {"path": "str", "content": "str"}),
    ]
    text = build_recovery_attachment([], defs)
    found = {name for name in ("read_file", "write_file") if name in text}
    assert found == {"read_file", "write_file"}
    # 空文件列表显示占位
    assert "(无)" in text


def test_boundary_notice_stable():
    defs = [ToolDefinition("read_file", "d", {"p": "s"})]
    records = [FileReadRecord(f"/f{i}", f"c{i}", datetime(2026, 8, 16, 10, i)) for i in range(3)]
    records.sort(key=lambda r: r.timestamp, reverse=True)
    a = build_recovery_attachment(records, defs)
    b = build_recovery_attachment(records, defs)
    assert a == b
    assert BOUNDARY_NOTICE in a
