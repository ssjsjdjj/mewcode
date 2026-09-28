"""两 provider 的工具调用流解析与 wire 格式测试（fake SDK client，docs/ch05 T8 适配）。"""

import asyncio
import json
from types import SimpleNamespace

from mewcode.config import ProviderConfig
from mewcode.llm import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    Message,
    Request,
    System,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from mewcode.llm.anthropic_provider import AnthropicProvider
from mewcode.llm.openai_provider import OpenAIProvider


def cfg(**overrides) -> ProviderConfig:
    base = dict(name="t", protocol="anthropic", api_key="k", model="m")
    base.update(overrides)
    return ProviderConfig(**base)


def tool_def(name="read_file"):
    return ToolDefinition(name=name, description="d", input_schema={"type": "object"})


def req(msgs, tools=(), system=None, reminder=""):
    return Request(
        messages=list(msgs), tools=list(tools), system=system or System(), reminder=reminder
    )


# ---------- fake SDK 对象 ----------


class FakeAnthropicStream:
    def __init__(self, events, final):
        self._events = list(events)
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._events:
            return self._events.pop(0)
        raise StopAsyncIteration

    async def get_final_message(self):
        return self._final


class FakeAnthropic:
    def __init__(self, stream):
        self._stream = stream
        self.params = None

    def stream(self, **params):
        self.params = params
        return self._stream


class FakeOpenaiChunks:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        raise StopAsyncIteration


class FakeOpenai:
    def __init__(self, chunks):
        self._chunks = chunks
        self.params = None

    async def create(self, **params):
        self.params = params
        return FakeOpenaiChunks(self._chunks)


USAGE = SimpleNamespace(input_tokens=10, output_tokens=5)


async def collect(provider, msgs, tools=(), system=None, reminder=""):
    return [ev async for ev in provider.stream(req(msgs, tools, system, reminder))]


# ---------- anthropic ----------


def _anthropic(events, final):
    fake = FakeAnthropic(FakeAnthropicStream(events, final))
    return AnthropicProvider(
        cfg(), client=SimpleNamespace(messages=SimpleNamespace(stream=fake.stream))
    ), fake


def test_anthropic_text_stream():
    ev = SimpleNamespace(
        type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="你")
    )
    final = SimpleNamespace(stop_reason="end_turn", content=[], usage=USAGE)
    provider, _ = _anthropic([ev], final)
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], [tool_def()]))
    assert [e.text for e in events if e.text] == ["你"]
    assert events[-1].done


def test_anthropic_tool_use_parsed():
    final = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="tool_use", id="toolu_1", name="read_file", input={"path": "x.txt"}
            )
        ],
        usage=USAGE,
    )
    provider, _ = _anthropic([], final)
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], [tool_def()]))
    calls = events[0].tool_calls
    assert len(calls) == 1
    assert calls[0].id == "toolu_1"
    assert calls[0].name == "read_file"
    assert json.loads(calls[0].input) == {"path": "x.txt"}


def test_anthropic_tools_and_reminder_woven():
    final = SimpleNamespace(stop_reason="end_turn", content=[], usage=USAGE)
    provider, fake = _anthropic([], final)
    asyncio.run(
        collect(
            provider,
            [Message(role="user", content="hi")],
            [tool_def("read_file")],
            reminder="<system-reminder>\nPLAN\n</system-reminder>",
        )
    )
    assert fake.params["tools"] == [
        {"name": "read_file", "description": "d", "input_schema": {"type": "object"}}
    ]
    last = fake.params["messages"][-1]
    assert isinstance(last["content"], list)
    assert last["content"][-1]["text"] == "<system-reminder>\nPLAN\n</system-reminder>"


def test_anthropic_thinking_disabled_with_tool_history():
    final = SimpleNamespace(stop_reason="end_turn", content=[], usage=USAGE)
    provider, fake = _anthropic([], final)
    provider._cfg = cfg(thinking=True)
    msgs = [
        Message(role=ROLE_ASSISTANT, tool_calls=[ToolCall(id="1", name="read_file", input="{}")]),
        Message(role=ROLE_TOOL, tool_results=[ToolResult(tool_call_id="1", content="ok")]),
    ]
    asyncio.run(collect(provider, msgs, [tool_def()]))
    assert "thinking" not in fake.params


def test_anthropic_wire_format():
    provider = AnthropicProvider(cfg())
    msgs = [
        Message(role="user", content="hi"),
        Message(
            role=ROLE_ASSISTANT,
            content="let me check",
            tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "x"}')],
        ),
        Message(role=ROLE_TOOL, tool_results=[ToolResult(tool_call_id="1", content="ok")]),
    ]
    out = provider._to_anthropic_messages(msgs)
    assert out[0] == {"role": "user", "content": "hi"}
    assert out[1]["content"][0] == {"type": "text", "text": "let me check"}
    assert out[1]["content"][1]["type"] == "tool_use"
    assert out[2]["content"][0]["type"] == "tool_result"
    assert out[2]["content"][0]["tool_use_id"] == "1"


def test_anthropic_usage_surfaced():
    final = SimpleNamespace(
        stop_reason="end_turn",
        content=[],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_creation_input_tokens=100,
            cache_read_input_tokens=200,
        ),
    )
    provider, _ = _anthropic([], final)
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], []))
    usages = [e.usage for e in events if e.usage]
    assert len(usages) == 1
    assert usages[0].input_tokens == 10
    assert usages[0].cache_write == 100
    assert usages[0].cache_read == 200


# ---------- openai ----------


def _ochunk(content=None, tool_calls=None, finish=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=usage
    )


def _openai(chunks):
    return OpenAIProvider(
        cfg(protocol="openai"),
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=FakeOpenai(chunks).create))
        ),
    )


def test_openai_text_stream():
    provider = _openai([_ochunk(content="你"), _ochunk(content="好")])
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], [tool_def()]))
    assert [e.text for e in events if e.text] == ["你", "好"]
    assert events[-1].done


def test_openai_tool_calls_accumulated():
    tc1 = SimpleNamespace(
        index=0, id="call_1", function=SimpleNamespace(name="read_file", arguments='{"pat')
    )
    tc2 = SimpleNamespace(
        index=0, id=None, function=SimpleNamespace(name=None, arguments='h": "x.txt"}')
    )
    provider = _openai(
        [_ochunk(tool_calls=[tc1]), _ochunk(tool_calls=[tc2]), _ochunk(finish="tool_calls")]
    )
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], [tool_def()]))
    calls = [e.tool_calls for e in events if e.tool_calls][0]
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read_file"
    assert json.loads(calls[0].input) == {"path": "x.txt"}


def test_openai_parallel_calls():
    provider = _openai(
        [
            _ochunk(
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="a",
                        function=SimpleNamespace(name="read_file", arguments='{"path": "1"}'),
                    )
                ]
            ),
            _ochunk(
                tool_calls=[
                    SimpleNamespace(
                        index=1,
                        id="b",
                        function=SimpleNamespace(name="glob", arguments='{"pattern": "**/*.py"}'),
                    )
                ]
            ),
            _ochunk(finish="tool_calls"),
        ]
    )
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], []))
    calls = [e.tool_calls for e in events if e.tool_calls][0]
    assert [c.name for c in calls] == ["read_file", "glob"]
    assert json.loads(calls[0].input) == {"path": "1"}


def test_openai_empty_arguments_normalized():
    provider = _openai(
        [
            _ochunk(
                tool_calls=[
                    SimpleNamespace(
                        index=0, id="a", function=SimpleNamespace(name="glob", arguments="")
                    )
                ]
            ),
            _ochunk(finish="tool_calls"),
        ]
    )
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], []))
    calls = [e.tool_calls for e in events if e.tool_calls][0]
    assert calls[0].input == "{}"


def test_openai_system_and_reminder_in_messages():
    fake = FakeOpenai([_ochunk(finish="stop")])
    provider = OpenAIProvider(
        cfg(protocol="openai"),
        client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake.create))
        ),
    )
    system = System(stable="STABLE", environment="ENV: x")
    asyncio.run(
        collect(
            provider,
            [Message(role="user", content="hi")],
            [tool_def("read_file")],
            system=system,
            reminder="<system-reminder>\nPLAN\n</system-reminder>",
        )
    )
    msgs = fake.params["messages"]
    assert msgs[0] == {"role": "system", "content": "STABLE\n\nENV: x"}
    assert msgs[-1] == {"role": "user", "content": "<system-reminder>\nPLAN\n</system-reminder>"}
    assert fake.params["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "d",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_openai_wire_format_tool_round():
    provider = OpenAIProvider(cfg(protocol="openai"))
    msgs = [
        Message(
            role=ROLE_ASSISTANT,
            tool_calls=[ToolCall(id="1", name="read_file", input='{"path": "x"}')],
        ),
        Message(role=ROLE_TOOL, tool_results=[ToolResult(tool_call_id="1", content="ok")]),
    ]
    out = provider._to_openai_messages(req(msgs))
    assert out[1]["tool_calls"][0]["function"]["arguments"] == '{"path": "x"}'
    assert out[2] == {"role": "tool", "tool_call_id": "1", "content": "ok"}


def test_openai_usage_surfaced_with_cached():
    usage_chunk = SimpleNamespace(
        prompt_tokens=7,
        completion_tokens=3,
        prompt_tokens_details=SimpleNamespace(cached_tokens=50),
    )
    provider = _openai([_ochunk(content="hi"), _ochunk(usage=usage_chunk)])
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], []))
    usages = [e.usage for e in events if e.usage]
    assert len(usages) == 1
    assert usages[0].cache_write == 0
    assert usages[0].cache_read == 50


def test_usage_missing_cache_fields_is_zero():
    provider = _openai(
        [
            _ochunk(content="hi"),
            _ochunk(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3)),
        ]
    )
    events = asyncio.run(collect(provider, [Message(role="user", content="hi")], []))
    usages = [e.usage for e in events if e.usage]
    assert usages[0].cache_read == 0
    assert usages[0].cache_write == 0
