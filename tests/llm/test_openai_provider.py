"""OpenAI provider PTL 错误包装单测（docs/ch08 T20.5）。"""

from unittest.mock import MagicMock

import openai

from mewcode.config import ProviderConfig
from mewcode.llm import PromptTooLongError, Request
from mewcode.llm.openai_provider import OpenAIProvider


def _client_raising(exc: openai.BadRequestError) -> OpenAIProvider:
    client = MagicMock()
    client.chat.completions.create.side_effect = exc
    return OpenAIProvider(
        ProviderConfig(name="t", protocol="openai", api_key="k", model="m"), client=client
    )


async def _drain(agen):
    evs = []
    async for ev in agen:
        evs.append(ev)
    return evs


def _bad_request(message: str, body: dict) -> openai.BadRequestError:
    resp = MagicMock()
    resp.status_code = 400
    return openai.BadRequestError(message, response=resp, body=body)


async def test_openai_context_length_exceeded_wrapped():
    exc = _bad_request(
        "maximum context length is 200000",
        {"error": {"code": "context_length_exceeded", "message": "maximum context length"}},
    )
    evs = await _drain(_client_raising(exc).stream(Request(messages=[])))
    err = evs[-1].err
    assert isinstance(err, PromptTooLongError)
    assert err.__cause__ is exc


async def test_openai_other_400_not_wrapped():
    exc = _bad_request("other error", {"error": {"code": "other_error"}})
    evs = await _drain(_client_raising(exc).stream(Request(messages=[])))
    assert isinstance(evs[-1].err, openai.BadRequestError)
    assert not isinstance(evs[-1].err, PromptTooLongError)
