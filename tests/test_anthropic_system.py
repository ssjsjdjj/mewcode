"""Anthropic 系统提示缓存断点守卫（docs/ch05 T7）：稳定块带 cache_control、环境块不带。"""

import asyncio
from types import SimpleNamespace

from mewcode.config import ProviderConfig
from mewcode.llm import Message, Request, System
from mewcode.llm.anthropic_provider import AnthropicProvider


def cfg(**overrides) -> ProviderConfig:
    base = dict(name="t", protocol="anthropic", api_key="k", model="m")
    base.update(overrides)
    return ProviderConfig(**base)


class FakeStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return iter(()).__aiter__()

    async def get_final_message(self):
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def make_provider(captured: dict) -> AnthropicProvider:
    def _stream(**params):
        captured["params"] = params
        return FakeStream()

    return AnthropicProvider(
        cfg(), client=SimpleNamespace(messages=SimpleNamespace(stream=_stream))
    )


async def _collect(provider, req):
    async for _ in provider.stream(req):
        pass


def test_system_two_blocks_stable_has_cache_control():
    captured = {}
    provider = make_provider(captured)
    req = Request(
        messages=[Message(role="user", content="hi")],
        system=System(stable="STABLE BLOCK", environment="ENV: cwd / win32"),
    )
    asyncio.run(_collect(provider, req))
    system = captured["params"]["system"]
    assert isinstance(system, list)
    assert len(system) == 2
    assert system[0] == {
        "type": "text",
        "text": "STABLE BLOCK",
        "cache_control": {"type": "ephemeral"},
    }
    assert system[1] == {"type": "text", "text": "ENV: cwd / win32"}
    assert "cache_control" not in system[1]  # 环境块不打缓存断点


def test_environment_omitted_when_empty():
    captured = {}
    provider = make_provider(captured)
    req = Request(
        messages=[Message(role="user", content="hi")],
        system=System(stable="STABLE BLOCK", environment=""),
    )
    asyncio.run(_collect(provider, req))
    system = captured["params"]["system"]
    assert len(system) == 1  # 仅稳定块
    assert system[0]["cache_control"] == {"type": "ephemeral"}
