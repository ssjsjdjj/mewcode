"""OpenAI 适配器（docs/ch05 T8）。封装 AsyncOpenAI，缓存字段解析 + reminder 尾部注入。"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import openai

from mewcode.config import ProviderConfig

from . import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    PromptTooLongError,
    Request,
    StreamEvent,
    ToolCall,
    Usage,
)


class OpenAIProvider:
    def __init__(
        self,
        cfg: ProviderConfig,
        *,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self._cfg = cfg
        self._client = client or openai.AsyncOpenAI(
            api_key=cfg.api_key, base_url=cfg.base_url or None
        )

    @property
    def name(self) -> str:
        return self._cfg.name

    @property
    def model(self) -> str:
        return self._cfg.model

    @staticmethod
    def _is_context_length_exceeded(exc: openai.BadRequestError) -> bool:
        """error.code == 'context_length_exceeded' 即视为上下文超窗。"""
        code = getattr(exc, "code", None)
        if code == "context_length_exceeded":
            return True
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            return body.get("error", {}).get("code") == "context_length_exceeded"
        return False

    # ---- wire 格式 ----

    def _to_openai_messages(self, req: Request) -> list[dict]:
        # 单条 system：stable 在前（前缀缓存命中），environment 拼在其后
        system = req.system.stable
        if req.system.environment:
            system = system + "\n\n" + req.system.environment
        out: list[dict] = [{"role": "system", "content": system}]

        for m in req.messages:
            if m.role == ROLE_ASSISTANT:
                if m.tool_calls:
                    out.append(
                        {
                            "role": "assistant",
                            "content": m.content or None,
                            "tool_calls": [
                                {
                                    "id": c.id,
                                    "type": "function",
                                    "function": {"name": c.name, "arguments": c.input or "{}"},
                                }
                                for c in m.tool_calls
                            ],
                        }
                    )
                else:
                    out.append({"role": "assistant", "content": m.content})
            elif m.role == ROLE_USER:
                out.append({"role": "user", "content": m.content})
            elif m.role == ROLE_TOOL:
                for r in m.tool_results:
                    out.append(
                        {"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content}
                    )

        if req.reminder:
            out.append({"role": "user", "content": req.reminder})  # OpenAI 容忍尾部 user
        return out

    # ---- stream ----

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        messages = self._to_openai_messages(req)
        params: dict = {"model": self._cfg.model, "messages": messages}
        if req.tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": d.name,
                        "description": d.description,
                        "parameters": d.input_schema,
                    },
                }
                for d in req.tools
            ]

        try:
            stream_resp = await self._client.chat.completions.create(
                **params, stream=True, stream_options={"include_usage": True}
            )
            buf: dict[int, dict[str, str]] = {}
            finish_reason: str | None = None
            async for chunk in stream_resp:
                if chunk.usage is not None:
                    # 末尾 usage chunk（choices 为空但带 usage）
                    details = getattr(chunk.usage, "prompt_tokens_details", None)
                    cached = getattr(details, "cached_tokens", 0) or 0
                    yield StreamEvent(
                        usage=Usage(
                            input_tokens=chunk.usage.prompt_tokens,
                            output_tokens=chunk.usage.completion_tokens,
                            cache_write=0,
                            cache_read=cached,
                        )
                    )
                    continue
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if delta.content:
                    yield StreamEvent(text=delta.content)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        entry = buf.setdefault(idx, {})
                        if tc.id:
                            entry["id"] = tc.id
                        if tc.function and tc.function.name:
                            entry["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            entry["args"] = entry.get("args", "") + tc.function.arguments

            if buf or finish_reason == "tool_calls":
                calls = [
                    ToolCall(
                        id=buf[i].get("id", ""),
                        name=buf[i].get("name", ""),
                        input=buf[i].get("args") or "{}",
                    )
                    for i in sorted(buf)
                ]
                yield StreamEvent(tool_calls=calls)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except openai.BadRequestError as exc:
            if self._is_context_length_exceeded(exc):
                wrapped = PromptTooLongError("openai context length exceeded")
                wrapped.__cause__ = exc
                yield StreamEvent(err=wrapped)
            else:
                yield StreamEvent(err=exc)
        except Exception as exc:  # noqa: BLE001 —— 包成 StreamEvent.err 交由上层显示
            yield StreamEvent(err=exc)
