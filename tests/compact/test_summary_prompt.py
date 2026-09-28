"""摘要 prompt 模板与解析测试（docs/ch08 T22）。"""

from __future__ import annotations

from mewcode.llm import Message, ROLE_USER
from mewcode.compact.summary_prompt import (
    build_summary_prompt,
    extract_summary,
    serialize_conversation,
)

SECTION_TITLES = [
    "## 1 主要请求和意图",
    "## 2 关键技术概念",
    "## 3 文件和代码段",
    "## 4 错误和修复",
    "## 5 问题解决过程",
    "## 6 所有用户消息原文（按时间顺序逐条保留）",
    "## 7 待办任务",
    "## 8 当前工作（最详细）",
    "## 9 可能的下一步",
]


def _msgs():
    return [
        Message(role="user", content="第一句"),
        Message(role="assistant", content="回复"),
    ]


def test_build_summary_prompt_shape():
    prompt = build_summary_prompt(_msgs())
    assert len(prompt) == 1
    assert prompt[0].role == ROLE_USER
    content = prompt[0].content
    for title in SECTION_TITLES:
        assert title in content
    assert "<analysis>" in content and "<summary>" in content
    assert "不要调用任何工具" in content
    assert "[conversation]" in content


def test_serialize_conversation_deterministic():
    msgs = _msgs()
    assert serialize_conversation(msgs) == serialize_conversation(msgs)


def test_extract_summary():
    assert extract_summary("abc<summary>xx</summary>yy") == "xx"
    # 缺失时返回原文
    assert extract_summary("no tags") == "no tags"
    # 嵌套/多对时取最后一对
    raw = "<summary>one</summary>x<summary>two</summary>"
    assert extract_summary(raw) == "two"
