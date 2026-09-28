"""parse 输入解析单测（docs/ch10 T3）。"""

from __future__ import annotations

import pytest

from mewcode.command.dispatch import parse


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ("", False)),
        ("   ", ("", False)),
        ("hello", ("", False)),
        ("/", ("", True)),
        ("/help", ("help", True)),
        ("  /HELP  ", ("help", True)),
        ("/help xx", ("", True)),  # 参数尾巴 → lookup 必然 miss
        ("/help  ", ("help", True)),  # 尾随空白被 strip，无参数
        ("//double", ("/double", True)),
        ("/ /help", ("", True)),  # 首个空白前为空名 → miss
    ],
)
def test_parse(text, expected):
    assert parse(text) == expected
