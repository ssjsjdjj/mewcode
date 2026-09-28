"""token 估算测试（docs/ch08 T22）。"""

from __future__ import annotations

import math

from mewcode.llm import Message, Usage
from mewcode.compact.const import ESTIMATE_CHARS_PER_TOKEN
from mewcode.compact.token import estimate_tokens, usage_anchor


def test_estimate_tokens_anchor():
    # 空对话 + anchor=0 -> 0
    assert estimate_tokens(0, [], 0) == 0
    # anchor=1000, msgs=[m1, m2], anchor_msg_len=1 -> 只估算 tail=m2
    m1 = Message(role="user", content="hello")
    m2 = Message(role="assistant", content="世界你好中文测试")
    expected = 1000 + math.ceil(len(m2.content.encode("utf-8")) / ESTIMATE_CHARS_PER_TOKEN)
    assert estimate_tokens(1000, [m1, m2], 1) == expected


def test_estimate_tokens_large_no_issue():
    big = Message(role="user", content="x" * 1_000_000)
    result = estimate_tokens(2_000_000_000, [big], 0)
    assert isinstance(result, int)
    assert result > 2_000_000_000


def test_usage_anchor_sum():
    u = Usage(input_tokens=100, output_tokens=20, cache_write=5, cache_read=3)
    assert usage_anchor(u) == 128
