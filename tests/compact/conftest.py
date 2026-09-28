"""compact 包测试共享 fixture（docs/ch08 T22）。"""

from __future__ import annotations

import pytest

from mewcode.llm import StreamEvent, Usage


class FakeCompactProvider:
    """脚本化 provider：script 为 list[list[StreamEvent]]，按调用次数依次弹出。

    摘要请求（content 含 [conversation]）会累计 summarize_calls 与 user_lines；
    最后一帧为 done 且帧内无 usage 时，在 done 之前自动补一条 Usage 事件。
    """

    def __init__(self, script: list[list[StreamEvent]]) -> None:
        self.script = list(script)
        self.calls = 0
        self.summarize_calls = 0
        self.user_lines: list[int] = []
        self.name = "fake"
        self.model = "fake"

    def stream(self, req):
        async def gen():
            self.calls += 1
            content = req.messages[0].content if req.messages else ""
            if "[conversation]" in content:
                self.summarize_calls += 1
                self.user_lines.append(content.count("user: "))
            if not self.script:
                yield StreamEvent(done=True)
                return
            frames = self.script.pop(0)
            has_usage = any(ev.usage is not None for ev in frames)
            for i, ev in enumerate(frames):
                if ev.done and i == len(frames) - 1 and not has_usage:
                    yield StreamEvent(usage=Usage(input_tokens=1, output_tokens=1))
                yield ev

        return gen()


@pytest.fixture
def fake_compact_provider():
    def make(script: list[list[StreamEvent]]) -> FakeCompactProvider:
        return FakeCompactProvider(script)

    return make
