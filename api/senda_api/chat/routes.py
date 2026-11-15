"""What the chat endpoint shares: the one-question-at-a-time gate, the model choice and the event frame."""

from __future__ import annotations

import json
import threading

from ..errors import clean
from ..settings import Settings
from .llm import AnthropicModel, Model


class _OneAtATime:
    """At most one active chat request per client address."""

    def __init__(self):
        self._active: dict[str, object] = {}
        self._lock = threading.Lock()

    def acquire(self, who: str) -> object | None:
        """A token to release with, or None when this address already has a request running."""
        with self._lock:
            if who in self._active:
                return None
            token = self._active[who] = object()
            return token

    def release(self, who: str, token: object) -> None:
        with self._lock:
            if self._active.get(who) is token:
                del self._active[who]


def resolve_model(settings: Settings, model: Model | None) -> Model | None:
    if model is not None:
        return model
    return AnthropicModel(settings.anthropic_api_key) if settings.anthropic_api_key else None


def frame(event: str, data: dict) -> bytes:
    payload = json.dumps(clean(data), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()
