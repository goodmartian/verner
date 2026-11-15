"""The question loop: model, tools, model. Yields (event, data) pairs for the SSE stream.

Only the final answer is shown, and only after the number check. Text the model writes before a tool call is dropped:
there is no data behind it yet. Any failure ends the stream with one `error` event.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from typing import Any

from ..access import Access
from ..climate import Climate
from ..landcover import LandCover
from ..settings import Settings
from ..store import Store
from ..weather import Weather
from .links import only_known
from .llm import Model, ModelFailure, ModelRequest, Usage
from .prompt import system_prompt
from .tools import TOOLS, ToolBox, ToolError
from .verify import kept, unverified

# a child of the server's own logger: its lines reach the console without a logging setup of ours
log = logging.getLogger("uvicorn.error").getChild("senda.chat")

UNVERIFIED = {
    "en": "I could not check this answer. Try a suggested question.",
    "ru": "Не удалось проверить этот ответ. Попробуйте один из предложенных вопросов.",
    "es": "No pude comprobar esta respuesta. Prueba una de las preguntas sugeridas.",
    "fr": "Je n'ai pas pu vérifier cette réponse. Essayez l'une des questions suggérées.",
}
RETRY = ("These numbers are in no tool result and not in my question: {numbers}. Write the answer again without them, "
         "in the language of my question. Where the data does not have something, say so in words.")
RETRY_MIN_S = 5.0  # a rewrite is asked for only when this much of the deadline is left
_SENTENCE = re.compile(r".*?(?:[.!?…](?:\s+|$)|\n|$)", re.DOTALL)


def sentences(text: str) -> Iterator[str]:
    for piece in _SENTENCE.findall(text):
        if piece:
            yield piece


def _tokens(usage: Usage) -> str:
    """The tokens of a question for the log: what it cost can be read from there."""
    return (f"input={usage.input_tokens} output={usage.output_tokens} cache_read={usage.cache_read_input_tokens} "
            f"cache_write={usage.cache_creation_input_tokens}")


def _error(code: str, message: str) -> tuple[str, dict]:
    return "error", {"code": code, "message": message}


def run(model: Model, store: Store, settings: Settings, messages: list[dict],
        weather: Callable[[], Weather | None] = lambda: None, language: str = "en", files: dict | None = None,
        land: Callable[[], LandCover | None] = lambda: None,
        access: Callable[[], Access | None] = lambda: None, drawn: int = 0,
        memory: dict | None = None, areas_drawn: dict[str, dict] | None = None,
        climate: Callable[[], Climate | None] = lambda: None) -> Iterator[tuple[str, dict]]:
    """`memory` is what the earlier answers of the chat left: `numbers` (they count as tool results) and `plans`.
    `areas_drawn` is what the person drew on the map, by name: the tools reach it as `{"drawn": name}`."""
    results: list[dict] = []
    earlier = (memory or {}).get("numbers", [])
    user_texts = [m["text"] for m in messages if m["role"] == "user"]
    box = ToolBox(store, settings, weather, files, lambda text: unverified(text, results, user_texts, earlier), land,
                  access, drawn, (memory or {}).get("plans"), areas_drawn, climate)
    system = system_prompt(store)
    convo: list[dict[str, Any]] = [{"role": m["role"], "content": m["text"]} for m in messages]
    started = time.monotonic()
    total = Usage()
    tool_calls = 0
    retried = False  # one rewrite per question when the number check fails
    try:
        for round_no in range(settings.chat_max_rounds):
            left = settings.chat_deadline_s - (time.monotonic() - started)
            if left <= 0:
                yield _error("timeout", "The question took too long.")
                return
            allowed = round_no < settings.chat_max_rounds - 1 and not retried
            request = ModelRequest(settings.chat_model, system, TOOLS, convo, settings.chat_max_tokens, allowed,
                                   min(settings.chat_call_timeout_s, left))
            try:
                turn = model.complete(request)
            except ModelFailure as failure:
                yield _error(failure.code, failure.message)
                return
            total = total + turn.usage
            if turn.stop_reason == "refusal":
                yield _error("refused", "The model declined to answer.")
                return
            uses = turn.tool_uses if allowed else []
            if not uses and turn.stop_reason == "max_tokens":
                # the answer was cut in the middle: a stump is not shown as an answer, the person may ask again
                log.info("chat cut at max_tokens model=%s %s", settings.chat_model, _tokens(total))
                yield _error("interrupted", "The answer was cut off before it was finished.")
                return
            if not uses:
                bad = _unchecked(turn.text.strip(), results, user_texts, earlier, box)
                left = settings.chat_deadline_s - (time.monotonic() - started)
                if bad and bad != ["<empty>"] and not retried and round_no < settings.chat_max_rounds - 1 and left > RETRY_MIN_S:
                    # one more call without tools: the model writes the answer again without the numbers it made up
                    retried = True
                    log.info("chat retry unverified_numbers=%d %s", len(bad), bad[:20])
                    convo.append({"role": "assistant", "content": turn.content})
                    convo.append({"role": "user", "content": RETRY.format(numbers=", ".join(bad[:20]))})
                    continue
                yield from _finish(turn.text.strip(), results, user_texts, earlier, settings, store, tool_calls, total,
                                   language, box, retried)
                return
            convo.append({"role": "assistant", "content": turn.content})
            blocks = []
            for use in uses:
                tool_calls += 1
                name, args = use.get("name", ""), use.get("input", {})
                log.info("chat tool %s args=%.200s", name, json.dumps(args, ensure_ascii=False))
                yield "tool", {"id": use["id"], "name": name, "status": "running"}
                try:
                    out = box.run(name, args)
                except ToolError as err:
                    log.info("chat tool %s error %s", name, err.code)
                    yield "tool", {"id": use["id"], "name": name, "status": "error", "code": err.code}
                    blocks.append({"type": "tool_result", "tool_use_id": use["id"], "is_error": True,
                                   "content": f"{err.code}: {err.message}"})
                    continue
                except Exception:
                    log.exception("chat tool %s failed", name)
                    yield "tool", {"id": use["id"], "name": name, "status": "error", "code": "internal_error"}
                    blocks.append({"type": "tool_result", "tool_use_id": use["id"], "is_error": True,
                                   "content": "internal_error: the tool failed."})
                    continue
                results.append(out.result)
                done: dict[str, Any] = {"id": use["id"], "name": name, "status": "ok", "args": args}
                if out.file:
                    done["file"] = out.file
                    log.info("chat file kind=%s", out.file["kind"])
                if out.widget:
                    done["widget"] = out.widget
                if out.action:
                    done["action"] = out.action
                yield "tool", done
                blocks.append({"type": "tool_result", "tool_use_id": use["id"],
                               "content": json.dumps(out.result, ensure_ascii=False, separators=(",", ":"))})
            convo.append({"role": "user", "content": blocks})
        yield _error("internal_error", "No answer was produced.")
    except Exception:
        log.exception("chat loop failed")
        yield _error("internal_error", "The chat failed.")


def _unchecked(text: str, results: list[dict], user_texts: list[str], earlier: list, box: ToolBox) -> list[str]:
    """The numbers of an answer that the check does not find; an empty answer counts as one."""
    text = only_known(text, box.next_shape - 1)
    return unverified(text, results, user_texts, earlier) if text else ["<empty>"]


def _finish(text: str, results: list[dict], user_texts: list[str], earlier: list, settings: Settings, store: Store,
            tool_calls: int, usage: Usage, language: str, box: ToolBox, retried: bool = False) -> Iterator[tuple[str, dict]]:
    bad = _unchecked(text, results, user_texts, earlier, box)
    text = only_known(text, box.next_shape - 1)
    log.info("chat answered model=%s %s tool_calls=%d retried=%s unverified_numbers=%d %s", settings.chat_model,
             _tokens(usage), tool_calls, retried, len(bad), bad[:20])
    done = {"model": settings.chat_model, "tool_calls": tool_calls, "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens, "cache_read_input_tokens": usage.cache_read_input_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens, "data_version": store.version,
            "memory": {"numbers": kept(results), "plans": box.requests}}
    if bad:
        yield "done", {**done, "verified": False, "text": UNVERIFIED.get(language, UNVERIFIED["en"])}
        return
    for piece in sentences(text):
        yield "token", {"text": piece}
    yield "done", {**done, "verified": True, "text": text}
