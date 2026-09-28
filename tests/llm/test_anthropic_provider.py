"""Anthropic provider PTL 错误包装单测（docs/ch08 T20.5）。"""

from unittest.mock import MagicMock

import anthropic

from mewcode.config import ProviderConfig
from mewcode.llm import PromptTooLongError, Request
from mewcode.llm.anthropic_provider import AnthropicProvider


def _client_raising(exc: anthropic.BadRequestError) -> AnthropicProvider:
    client = MagicMock()
    client.messages.stream.return_value.__aenter__.side_effect = exc
    return AnthropicProvider(
        ProviderConfig(name="t", protocol="anthropic", api_key="k", model="m"), client=client
    )


async def _drain(agen):
    evs = []
    async for ev in agen:
        evs.append(ev)
    return evs


def _bad_request(message: str, body: dict) -> anthropic.BadRequestError:
    resp = MagicMock()
    resp.status_code = 400
    return anthropic.BadRequestError(message, response=resp, body=body)


async def test_anthropic_prompt_too_long_wrapped():
    exc = _bad_request(
        "prompt is too long: 123456 > 200000", {"error": {"type": "invalid_request_error"}}
    )
    evs = await _drain(_client_raising(exc).stream(Request(messages=[])))
    err = evs[-1].err
    assert isinstance(err, PromptTooLongError)
    assert err.__cause__ is exc


async def test_anthropic_keyword_in_body_wrapped():
    # message 不含关键词，仅 body 命中 "prompt is too long"（验证 body 分支）
    exc = _bad_request("bad request", {"error": {"message": "prompt is too long"}})
    evs = await _drain(_client_raising(exc).stream(Request(messages=[])))
    assert isinstance(evs[-1].err, PromptTooLongError)


async def test_anthropic_keyword_in_message_wrapped():
    # message 命中 "prompt is too long"（验证 message 分支）
    exc = _bad_request("prompt is too long: 1234567 tokens > 200000 maximum", {"error": {}})
    evs = await _drain(_client_raising(exc).stream(Request(messages=[])))
    assert isinstance(evs[-1].err, PromptTooLongError)


async def test_anthropic_other_400_not_wrapped():
    exc = _bad_request("bad request", {"error": {"type": "invalid_request_error"}})
    evs = await _drain(_client_raising(exc).stream(Request(messages=[])))
    assert isinstance(evs[-1].err, anthropic.BadRequestError)
    assert not isinstance(evs[-1].err, PromptTooLongError)
