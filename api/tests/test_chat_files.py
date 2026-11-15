import json
from datetime import timedelta

import pytest
from fakes import ScriptedModel, call, parse_sse, say
from fastapi.testclient import TestClient
from test_fires import live  # noqa: F401
from weather_files import START, write

from senda_api.app import create_app
from senda_api.chat import api as chat_api
from senda_api.chat import files
from senda_api.settings import Settings

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(autouse=True)
def _free_gate():
    chat_api.GATE._active.clear()


def make(store, tmp_path, *steps):
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1))
    model = ScriptedModel(*steps)
    return model, TestClient(create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder),
                                        chat_model=model))


def ask(client, chat="new", text="Prepare it"):
    got = parse_sse(client.post(f"/api/chats/{chat}/messages", json={"text": text}).text)
    cid = next(d["chat_id"] for n, d in got if n == "start")
    return cid, got


def file_widgets(got):
    return [d["data"] for n, d in got if n == "widget" and d["type"] == "file"]


@pytest.mark.parametrize("kind,args,columns,name_part", [
    ("monthly", {"area": {"id": "XA"}}, files.MONTH_COLUMNS, "_months.csv"),
    ("days", {"area": {"id": "XA"}, "month": "2026-10"}, files.DAY_COLUMNS, "_days.csv"),
    ("fires", {"region": "XA"}, files.FIRE_COLUMNS, "verner_fires_xa_"),
])
def test_each_csv_kind_is_made_described_and_downloaded(store, tmp_path, live, kind, args, columns, name_part):  # noqa: F811
    model, client = make(store, tmp_path, call("prepare_file", {"kind": kind, **args}), say("Done."))
    cid, got = ask(client)
    [meta] = file_widgets(got)
    assert meta["kind"] == kind and name_part in meta["name"] and meta["mime"].startswith("text/csv")
    described = json.loads(model.tool_results(1)[0]["content"])
    assert described["file"]["columns"] == list(columns) and described["file"]["rows"] == meta["rows"]
    res = client.get(f"/api/chats/{cid}/files/{meta['id']}")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert f'filename="{meta["name"]}"' in res.headers["content-disposition"]
    assert res.headers["content-disposition"].startswith("attachment")
    lines = res.text.split("\r\n")
    assert lines[0] == ",".join(columns) and len(res.content) == meta["size"]
    assert len([line for line in lines[1:] if line]) == meta["rows"]
    # the history of the chat shows the file
    detail = client.get(f"/api/chats/{cid}").json()
    assert detail["messages"][-1]["widgets"][0]["data"]["id"] == meta["id"]


def test_the_fires_file_holds_the_numbers_of_the_list(store, tmp_path, live):  # noqa: F811
    model, client = make(store, tmp_path, call("prepare_file", {"kind": "fires", "region": "XA"}), say("Done."))
    cid, got = ask(client)
    described = json.loads(model.tool_results(1)[0]["content"])
    assert described["totals"]["fires_total"] == 2 and described["first_rows"][0]["area_ha"] > 0
    body = client.get(f"/api/chats/{cid}/files/{file_widgets(got)[0]['id']}").text
    assert "Westville" in body or "Eastford" in body


def test_the_numbers_of_the_description_pass_the_number_check(store, tmp_path, live):  # noqa: F811
    model, client = make(store, tmp_path, call("prepare_file", {"kind": "fires", "region": "XA"}), say("Done."))
    ask(client)
    out = json.loads(model.tool_results(1)[0]["content"])
    from senda_api.chat.verify import unverified
    total = out["totals"]["area_ha_total"]
    assert unverified(f"The file holds {out['file']['rows']} fires, {total} ha in all.", [out], []) == []
    assert unverified("The file holds 4321 ha.", [out], []) != []


def test_a_report_is_saved_after_the_number_check(store, tmp_path, live):  # noqa: F811
    model, client = make(store, tmp_path,
                         call("list_fires", {"region": "XA"}),
                         call("write_report", {"title": "Fires of XA / 2026", "text": "Two fires. 999999 ha burned."}),
                         say("Done."))
    cid, got = ask(client)
    assert file_widgets(got) == []  # refused: the number is in no tool result
    assert "unverified_numbers" in model.tool_results(2)[0]["content"]
    listed = json.loads(model.tool_results(1)[0]["content"])
    area = listed["fires"][0]["area_ha"]
    model, client = make(store, tmp_path, call("list_fires", {"region": "XA"}),
                         call("write_report", {"title": "Огни / 2026", "area": {"id": "XA"}, "text": f"The biggest fire is {area} ha."}),
                         say("Done."))
    cid, got = ask(client)
    [meta] = file_widgets(got)
    assert meta["kind"] == "report" and meta["mime"].startswith("text/markdown") and meta["rows"] is None
    assert "/" not in meta["name"] and meta["name"].startswith("verner_xa_") and meta["name"].endswith("_report.md")
    body = client.get(f"/api/chats/{cid}/files/{meta['id']}").text
    assert body.startswith("# Огни / 2026") and f"{area} ha" in body and f"Data version {store.version}" in body


def test_other_chats_cannot_download_and_deleting_the_chat_deletes_the_files(store, tmp_path, live):  # noqa: F811
    _, client = make(store, tmp_path, call("prepare_file", {"kind": "fires", "region": "XA"}), say("Done."),
                     say("Second chat."))
    cid, got = ask(client)
    fid = file_widgets(got)[0]["id"]
    other, _ = ask(client)
    assert other != cid
    assert client.get(f"/api/chats/{other}/files/{fid}").status_code == 404
    assert client.get(f"/api/chats/{cid}/files/{'0' * 32}").status_code == 404
    assert client.get(f"/api/chats/{cid}/files/..%2Fx").status_code in (404, 422)
    assert client.delete(f"/api/chats/{cid}").status_code == 204
    assert client.get(f"/api/chats/{cid}/files/{fid}").status_code == 404


def test_limits(store, tmp_path, live):  # noqa: F811
    steps = [call("prepare_file", {"kind": "fires", "region": "XA"}) for _ in range(files.MAX_PER_ANSWER + 1)]
    model, client = make(store, tmp_path, *steps, say("Done."))
    _, got = ask(client)
    assert len(file_widgets(got)) == files.MAX_PER_ANSWER
    assert "limit" in model.tool_results(files.MAX_PER_ANSWER + 1)[0]["content"]


def test_bad_input_goes_back_to_the_model(store, tmp_path, live):  # noqa: F811
    model, client = make(store, tmp_path, call("prepare_file", {"kind": "days", "area": {"id": "XA"}}), say("Sorry."))
    ask(client)
    assert "invalid_input" in model.tool_results(1)[0]["content"]


def test_names_are_safe():
    assert files.safe("../../etc/passwd") == "etc-passwd" and files.safe("Аргентина") == "file"


def test_booleans_are_written_in_lower_case(store, tmp_path, live):  # noqa: F811
    _, client = make(store, tmp_path, call("prepare_file", {"kind": "monthly", "area": {"id": "XA"}}), say("Done."))
    cid, got = ask(client)
    body = client.get(f"/api/chats/{cid}/files/{file_widgets(got)[0]['id']}").text
    assert "True" not in body and "False" not in body and ("true" in body or "false" in body)
