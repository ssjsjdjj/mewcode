"""命令输入解析（docs/ch10 T3）。

parse 只做纯字符串切分，判定输入是否为 / 命令形态并提取小写 name；
携带参数（空白外尾随字符）返回 ("", True)，让 lookup 必然 miss 走未命中分支
（F7：本期所有内置命令均为零参数）。
"""

from __future__ import annotations


def parse(input_text: str) -> tuple[str, bool]:
    """返回 (name, is_slash)。

    - 空白/空串/非 / 开头 → ("", False)（F5：不进分发器）
    - 仅 "/" → ("", True)
    - "/<name>" 无参数 → (小写 name, True)
    - "/<name> <args>" → ("", True)（参数尾巴走未命中）
    """
    s = input_text.strip()
    if not s.startswith("/"):
        return ("", False)
    if s == "/":
        return ("", True)
    rest = s[1:]
    # 首个空白前为 name。str.split 会吞掉前导空白（"/ /help" 的 name 是空串），
    # 因此先显式判断 rest 是否以空白开头，保证退化输入返回空名走未命中分支。
    if rest[:1].isspace():
        return ("", True)
    parts = rest.split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        return ("", True)
    return (parts[0].lower(), True)
