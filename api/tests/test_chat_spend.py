from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient

from senda_api.app import create_app
from senda_api.chat import api as chat_api
from senda_api.chat import loop
from senda_api.chat.llm import AnthropicModel, ModelRequest, Usage
from senda_api.chat.spend import PRICES, DailySpend, Metered, cost_usd
from senda_api.settings import Settings

pytestmark = pytest.mark.usefixtures("database")

# a million output tokens of the default model: 10 dollars
DEAR = Usage(0, 1_000_000)


@pytest.fixture(autouse=True)
def _free_gate():
    chat_api.GATE._active.clear()


def client_with(store, model, cap):
    return TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, chat_daily_usd=cap),
                                 chat_model=model))


def ask(client):
    return client.post("/api/chats/new/messages", json={"text": "How was 2019?"})


def test_the_cost_of_a_question_comes_from_the_price_table():
    usage = Usage(1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert cost_usd("claude-sonnet-5-5", usage) == pytest.approx(2.00 + 10.00 + 0.10 + 2.50)
    # a model not in the table counts at the dearest row: it can only stop the chat early
    assert cost_usd("claude-unknown", usage) == pytest.approx(sum(PRICES["claude-opus-5-5"]))


def test_under_the_cap_questions_pass_and_the_one_that_crosses_it_is_the_last(store):
    model = ScriptedModel(say("Fine."), replace(say("Busy."), usage=DEAR), say("Never asked."))
    client = client_with(store, model, cap=5.0)
    assert parse_sse(ask(client).text)[-1][0] == "done"
    assert parse_sse(ask(client).text)[-1][0] == "done"  # this one brings the day over the cap, and is answered
    refused = ask(client)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "rate_limited"
    assert len(model.requests) == 2  # the model was not called for the refused question


def test_the_day_rolls_over_and_a_cap_of_zero_never_stops(store):
    model = ScriptedModel(replace(say("Busy."), usage=DEAR), say("Next day."))
    client = client_with(store, model, cap=5.0)
    ask(client)
    assert ask(client).status_code == 429
    spend: DailySpend = client.app.state.chat_spend
    tomorrow = spend.today() + timedelta(days=1)
    spend.today = lambda: tomorrow
    assert parse_sse(ask(client).text)[-1][0] == "done"
    free = client_with(store, ScriptedModel(*[replace(say("Busy."), usage=DEAR)] * 3), cap=0)
    assert all(parse_sse(ask(free).text)[-1][0] == "done" for _ in range(3))


def test_every_call_of_a_question_is_counted_with_its_cache_tokens(store):
    used = Usage(100, 50, 1000, 2000)
    model = ScriptedModel(replace(call("find_region", {"query": "xland"}), usage=used), replace(say("Xland."), usage=used))
    spend = DailySpend(10.0, lambda: date(2026, 11, 15))
    got = list(loop.run(Metered(model, spend), store, Settings(anthropic_api_key=None),
                        [{"role": "user", "text": "Where is Xland?"}]))
    done = got[-1][1]
    assert (done["input_tokens"], done["output_tokens"]) == (200, 100)
    assert (done["cache_read_input_tokens"], done["cache_creation_input_tokens"]) == (2000, 4000)
    assert spend.spent() == pytest.approx(2 * cost_usd("claude-sonnet-5-5", used))


def test_the_request_caches_the_tools_and_the_system_prompt(monkeypatch):
    model = AnthropicModel("test-key")
    sent = {}

    def create(**params):
        sent.update(params)
        usage = SimpleNamespace(input_tokens=3, output_tokens=2, cache_read_input_tokens=None,
                                cache_creation_input_tokens=7)
        return SimpleNamespace(content=[], usage=usage, stop_reason="end_turn")

    monkeypatch.setattr(model._client.messages, "create", create)
    turn = model.complete(ModelRequest("m", "the rules", [{"name": "t"}], [{"role": "user", "content": "q"}], 10, True, 5.0))
    assert sent["system"] == [{"type": "text", "text": "the rules", "cache_control": {"type": "ephemeral"}}]
    assert sent["tools"] == [{"name": "t"}]  # tools render before the system block: the one marker caches both
    assert turn.usage == Usage(3, 2, 0, 7)


def test_an_answer_cut_at_max_tokens_is_not_shown_as_an_answer(store):
    model = ScriptedModel(replace(say("The fires of 2019 were"), stop_reason="max_tokens"))
    got = parse_sse(ask(client_with(store, model, cap=0)).text)
    assert [n for n, _ in got] == ["start", "error"] and got[-1][1]["code"] == "interrupted"
    assert all(n != "text" for n, _ in got)
