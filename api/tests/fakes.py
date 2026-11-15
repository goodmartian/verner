"""A replaying model for chat tests: no network. Each step is a Turn, or an exception to raise."""

from __future__ import annotations

import json
from dataclasses import replace

from senda_api.chat.llm import ModelRequest, Turn, Usage


def say(text: str) -> Turn:
    return Turn([{"type": "text", "text": text}], "end_turn", Usage(10, 5))


def call(name: str, args: dict, text: str = "", call_id: str = "t1") -> Turn:
    content = [{"type": "text", "text": text}] if text else []
    content.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
    return Turn(content, "tool_use", Usage(10, 5))


class ScriptedModel:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> Turn:
        self.requests.append(replace(request, messages=list(request.messages)))  # the loop keeps appending to its list
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(request) if callable(step) else step

    def tool_results(self, request_index: int) -> list[dict]:
        """The tool_result blocks the model was shown in the given request."""
        last = self.requests[request_index].messages[-1]
        return [b for b in last["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for chunk in text.strip().split("\n\n"):
        lines = chunk.split("\n")
        name = lines[0].removeprefix("event: ")
        events.append((name, json.loads(lines[1].removeprefix("data: "))))
    return events
