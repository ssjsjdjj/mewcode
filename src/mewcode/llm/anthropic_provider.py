"""Anthropic 适配器（docs/ch05 T7）。封装 AsyncAnthropic，缓存通道 + reminder 织入。"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import anthropic

from mewcode.config import ProviderConfig

from . import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    PromptTooLongError,
    Request,
    StreamEvent,
    ToolCall,
    Usage,
)

MAX_TOKENS = 4096
THINKING_BUDGET_TOKENS = 2048


def _assistant_used_tools(msgs: list[Message]) -> bool:
    return any(m.tool_calls or m.tool_results for m in msgs)


class AnthropicProvider:
    def __init__(
        self,
        cfg: ProviderConfig,
        *,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._cfg = cfg
        self._client = client or anthropic.AsyncAnthropic(
            api_key=cfg.api_key, base_url=cfg.base_url or None
        )

    @property
    def name(self) -> str:
        return self._cfg.name

    @property
    def model(self) -> str:
        return self._cfg.model

    @staticmethod
    def _is_prompt_too_long(exc: anthropic.BadRequestError) -> bool:
        """命中 "prompt is too long" / "context_length" 即视为上下文超窗。"""
        parts: list[str] = []
        msg = getattr(exc, "message", None)
        if msg:
            parts.append(str(msg))
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            parts.append(json.dumps(body))
        elif body is not None:
            parts.append(str(body))
        haystack = " ".join(parts)
        return "prompt is too long" in haystack or "context_length" in haystack

    # ---- wire 格式 ----

    def _to_anthropic_messages(self, msgs: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in msgs:
            if m.role == ROLE_ASSISTANT:
                if m.tool_calls:
                    content: list[dict] = []
                    if m.content:
                        content.append({"type": "text", "text": m.content})
                    for c in m.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": c.id,
                                "name": c.name,
                                "input": json.loads(c.input),
                            }
                        )
                    out.append({"role": "assistant", "content": content})
                else:
                    out.append({"role": "assistant", "content": m.content})
            elif m.role == ROLE_USER:
                out.append({"role": "user", "content": m.content})
            elif m.role == ROLE_TOOL:
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in m.tool_results
                ]
                out.append({"role": "user", "content": content})
        return out

    @staticmethod
    def _append_reminder(messages: list[dict], reminder: str) -> None:
        """把 reminder 并入最后一条 user 消息的 content 块；末条为 assistant 则新起 user（N3）。"""
        block = {"type": "text", "text": reminder}
        if not messages:
            messages.append({"role": "user", "content": [block]})
            return
        last = messages[-1]
        if last["role"] == ROLE_ASSISTANT:
            messages.append({"role": "user", "content": [block]})
            return
        if isinstance(last["content"], str):
            last["content"] = [{"type": "text", "text": last["content"]}]
        last["content"] = list(last["content"]) + [block]

    # ---- stream ----

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        system: list[dict] = []
        if req.system.stable:
            system.append(
                {
                    "type": "text",
                    "text": req.system.stable,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        if req.system.environment:
            system.append({"type": "text", "text": req.system.environment})

        messages = self._to_anthropic_messages(req.messages)
        if req.reminder:
            self._append_reminder(messages, req.reminder)

        params: dict = {
            "model": self._cfg.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": messages,
        }
        if req.tools:
            params["tools"] = [
                {
                    "name": d.name,
                    "description": d.description,
                    "input_schema": d.input_schema,
                }
                for d in req.tools
            ]
        # 历史含工具交互时（续答）不启用 thinking，避免缺 thinking 块签名导致 400
        if self._cfg.thinking and not _assistant_used_tools(req.messages):
            params["thinking"] = {"type": "enabled", "budget_tokens": THINKING_BUDGET_TOKENS}

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta_type = event.delta.type
                        if delta_type == "text_delta":
                            yield StreamEvent(text=event.delta.text)
                        # thinking_delta / input_json_delta：跳过（SDK 累加器保留完整 input）
                final = await stream.get_final_message()
                calls: list[ToolCall] = []
                if final.stop_reason == "tool_use":
                    for block in final.content:
                        if getattr(block, "type", None) == "tool_use":
                            calls.append(
                                ToolCall(
                                    id=block.id,
                                    name=block.name,
                                    input=json.dumps(block.input),
                                )
                            )
                if calls:
                    yield StreamEvent(tool_calls=calls)
                if final.usage is not None:
                    yield StreamEvent(
                        usage=Usage(
                            input_tokens=final.usage.input_tokens,
                            output_tokens=final.usage.output_tokens,
                            cache_write=getattr(final.usage, "cache_creation_input_tokens", 0) or 0,
                            cache_read=getattr(final.usage, "cache_read_input_tokens", 0) or 0,
                        )
                    )
                yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except anthropic.BadRequestError as exc:
            if self._is_prompt_too_long(exc):
                wrapped = PromptTooLongError("anthropic prompt too long")
                wrapped.__cause__ = exc
                yield StreamEvent(err=wrapped)
            else:
                yield StreamEvent(err=exc)
        except Exception as exc:  # noqa: BLE001 —— 包成 StreamEvent.err 交由上层显示
            yield StreamEvent(err=exc)
