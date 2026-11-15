"""The model behind the chat. The loop talks to the Model protocol; tests replace it with a replaying fake."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

log = logging.getLogger("uvicorn.error").getChild("senda.chat")


class ModelFailure(Exception):
    """The model call failed. `code` is one of upstream_error, timeout. The message never holds the key."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0  # the tokens read without the cache
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens,
                     self.cache_read_input_tokens + other.cache_read_input_tokens,
                     self.cache_creation_input_tokens + other.cache_creation_input_tokens)


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    tools: list[dict]
    messages: list[dict]
    max_tokens: int
    tools_allowed: bool
    timeout_s: float


@dataclass(frozen=True)
class Turn:
    content: list[dict]  # blocks as plain dicts: text, tool_use, thinking
    stop_reason: str
    usage: Usage = Usage()

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_uses(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]


class Model(Protocol):
    def complete(self, request: ModelRequest) -> Turn: ...


class AnthropicModel:
    """Claude Messages API. The key comes from the settings (the environment) and goes nowhere else."""

    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=2)

    def complete(self, request: ModelRequest) -> Turn:
        params: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            # the tools and the system prompt are the same in every call (fixed order, no per-request text): the
            # marker on the system block caches both, and the calls of a question and of the next minutes read them
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "tools": request.tools,
            "messages": request.messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "low"},
            "timeout": request.timeout_s,
        }
        if not request.tools_allowed:
            params["tool_choice"] = {"type": "none"}
        try:
            reply = self._client.messages.create(**params)
        except anthropic.APITimeoutError:
            raise ModelFailure("timeout", "The model did not answer in time.") from None
        except anthropic.APIStatusError as error:
            # the account is out of credit (402, or the older 400 that says so): asking again will not help, so the
            # person is told what a spent day tells them, that the assistant has answered all it can for now
            if error.status_code == 402 or "credit balance" in str(error).lower():
                log.warning("chat model refused: the account has no credit left")
                raise ModelFailure("rate_limited", "The model account has no credit left.") from None
            raise ModelFailure("upstream_error", "The model service failed.") from None
        except anthropic.APIError:
            # the message of an SDK error can echo request details: keep it out of ours
            raise ModelFailure("upstream_error", "The model service failed.") from None
        content = [block.model_dump(exclude_none=True) for block in reply.content]
        used = reply.usage
        usage = Usage(used.input_tokens, used.output_tokens, used.cache_read_input_tokens or 0,
                      used.cache_creation_input_tokens or 0)
        return Turn(content, reply.stop_reason or "end_turn", usage)
