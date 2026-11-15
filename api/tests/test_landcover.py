import pytest
from landcover_support import FakeFetcher, land_cover_cog, land_cover_pattern

from senda_api.landcover import Cog, read_land_cover, tile_name

PIXEL = 0.004
# synthetic tiles are named by their south-west corner and drawn from their north-west corner
TILES = {
    "S30W057": (-57.0, -27.0),
    "S30W060": (-60.0, -27.0),
    "S33W057": (-57.0, -30.0),
    "S33W060": (-60.0, -30.0),
}
SHIFTS = {"S30W057": 0, "S30W060": 1, "S33W057": 2, "S33W060": 3}
BOX = (-56.3, -28.7, -56.1, -28.5)


def _fetcher(*names: str) -> FakeFetcher:
    return FakeFetcher(cogs={n: land_cover_cog(TILES[n], SHIFTS[n]) for n in names})


def _expected_class(lon: float, lat: float) -> str:
    """The class under a point, from the synthetic tile that holds it."""
    west = -60.0 if lon < -57.0 else -57.0
    north = -27.0 if lat > -30.0 else -30.0
    name = tile_name(int(north) - 3, int(west))
    x, y = int((lon - west) / PIXEL), int((north - lat) / PIXEL)
    return chr(48 + land_cover_pattern(x, y, SHIFTS[name]) // 10)


def _assert_grid_matches_tiles(
    fetcher: FakeFetcher, box: tuple[float, float, float, float]
) -> None:
    grid = read_land_cover(fetcher, box, {})
    west, south, east, north = grid.bbox

    assert len(grid.classes) == grid.width * grid.height
    assert abs(west - box[0]) < PIXEL
    assert abs(north - box[3]) < PIXEL
    assert abs(east - box[2]) < 2 * PIXEL
    assert abs(south - box[1]) < 2 * PIXEL
    step_x, step_y = (east - west) / grid.width, (north - south) / grid.height
    for row in range(0, grid.height, 5):
        for col in range(0, grid.width, 5):
            lon, lat = west + (col + 0.5) * step_x, north - (row + 0.5) * step_y
            assert grid.classes[row * grid.width + col] == _expected_class(lon, lat), (row, col)


def test_tile_name_is_the_3_degree_tile_by_its_south_west_corner() -> None:
    assert tile_name(-30, -57) == "S30W057"
    assert tile_name(-27, -60) == "S27W060"
    assert tile_name(9, 18) == "N09E018" and tile_name(-3, 12) == "S03E012" and tile_name(0, -3) == "N00W003"


def test_land_cover_inside_one_tile_matches_the_map_under_every_cell() -> None:
    _assert_grid_matches_tiles(_fetcher("S30W057"), BOX)


def test_a_box_over_a_vertical_seam_is_stitched_from_two_tiles() -> None:
    fetcher = _fetcher("S30W057", "S30W060")
    box = (-57.2, -28.7, -56.9, -28.5)  # the seam is at -57
    _assert_grid_matches_tiles(fetcher, box)

    grid = read_land_cover(fetcher, box, {})
    row = grid.classes[: grid.width]
    assert len(set(row)) > 1  # both tiles contribute


def test_a_box_over_a_horizontal_seam_is_stitched_from_two_tiles() -> None:
    _assert_grid_matches_tiles(_fetcher("S30W057", "S33W057"), (-56.4, -30.2, -56.1, -29.9))


def test_a_box_over_the_corner_of_four_tiles_is_stitched_from_four() -> None:
    _assert_grid_matches_tiles(_fetcher(*TILES), (-57.15, -30.12, -56.85, -29.88))


def test_a_box_on_the_tile_edge_does_not_open_the_next_tile() -> None:
    fetcher = _fetcher("S30W057")
    grid = read_land_cover(fetcher, (-57.0, -29.0, -56.5, -28.5), {})

    assert grid.width > 100
    assert not any("S30W060" in request for request in fetcher.requests)


def test_a_missing_tile_over_the_sea_is_no_data_and_the_rest_is_kept() -> None:
    grid = read_land_cover(_fetcher("S30W057"), (-57.2, -28.7, -56.9, -28.5), {})
    half = grid.width // 2

    assert set(grid.classes[0:half]) == {"0"}  # the west tile does not exist
    assert "0" not in grid.classes[grid.width - 5 : grid.width]


def test_a_box_with_no_tile_at_all_is_an_error() -> None:
    with pytest.raises(ValueError, match="no tile"):
        read_land_cover(FakeFetcher(), BOX, {})


def test_a_tile_is_opened_once_for_many_fires() -> None:
    fetcher = _fetcher("S30W057")
    cogs: dict[str, Cog | None] = {}
    read_land_cover(fetcher, BOX, cogs)
    read_land_cover(fetcher, (-56.6, -28.9, -56.4, -28.7), cogs)
    headers = [r for r in fetcher.requests if r.endswith("@0")]

    assert len(cogs) == 1
    assert len(headers) == 1


def test_a_file_that_is_not_a_tiff_is_refused() -> None:
    fetcher = FakeFetcher(cogs={"S30W057": b"not a tiff" * 100})
    with pytest.raises(ValueError, match="not a little-endian classic TIFF"):
        read_land_cover(fetcher, BOX, {})


# the service, the route and the chat tool

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from test_fires import live  # noqa: F401
from weather_files import START, write

from senda_api import contracts, landcover
from senda_api.app import create_app
from senda_api.settings import Settings


def app_with(store, tmp_path, fetcher):
    folder = write(tmp_path / "weather" / "current", start=START + timedelta(days=1))
    app = create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=folder))
    app.state.land = landcover.LandCover(tmp_path / "cache", fetcher)
    return TestClient(app)


def west(client):
    fires = client.get("/api/fires", params={"region": "XA"}).json()["fires"]
    return next(f for f in fires if f["nearest_place"]["name"] == "Westville")["id"]


def test_the_route_answers_the_form_with_legend_shares_and_source(store, tmp_path, live):  # noqa: F811
    client = app_with(store, tmp_path, FakeFetcher(any_tile=True))
    res = client.get(f"/api/fires/{west(client)}/land-cover")
    assert res.status_code == 200, res.text
    body = res.json()
    contracts.LandCover.model_validate(body)
    assert len(body["data"]) == body["width"] * body["height"] and body["width"] > 10
    assert [c["id"] for c in body["classes"]] == list(range(11))
    assert set(body["classes"][1]["name"]) == {"en", "ru", "es", "fr"}
    assert body["attribution"] == landcover.ATTRIBUTION and "ESA WorldCover" in body["attribution"]
    assert body["shares"] and abs(sum(s["share_pct"] for s in body["shares"]) - 100) < 0.5
    assert [s["share_pct"] for s in body["shares"]] == sorted((s["share_pct"] for s in body["shares"]), reverse=True)


def test_the_grid_is_kept_in_memory_and_on_disk(store, tmp_path, live):  # noqa: F811
    fetcher = FakeFetcher(any_tile=True)
    client = app_with(store, tmp_path, fetcher)
    fire = west(client)
    first = client.get(f"/api/fires/{fire}/land-cover").json()
    asked = len(fetcher.requests)
    assert asked > 0 and list((tmp_path / "cache").glob("*.json"))
    assert client.get(f"/api/fires/{fire}/land-cover").json() == first and len(fetcher.requests) == asked
    # a new app (a restart) reads the file, not the network
    again = app_with(store, tmp_path, FakeFetcher(failing=True))
    assert again.get(f"/api/fires/{fire}/land-cover").json() == first


@pytest.mark.parametrize("fetcher", [FakeFetcher(failing=True), FakeFetcher()])
def test_no_network_and_no_tile_are_404(store, tmp_path, live, fetcher):  # noqa: F811
    client = app_with(store, tmp_path, fetcher)
    res = client.get(f"/api/fires/{west(client)}/land-cover")
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found" and res.json()["error"]["message"]
    assert client.get("/api/fires/nope/land-cover").status_code == 404


def test_the_card_does_not_wait_for_the_network(store, tmp_path, live):  # noqa: F811
    fetcher = FakeFetcher(any_tile=True)
    client = app_with(store, tmp_path, fetcher)
    assert client.get(f"/api/fires/{west(client)}").status_code == 200 and fetcher.requests == []


def test_the_chat_card_says_what_the_fire_burns_on(store, tmp_path, live, database):  # noqa: F811
    from fakes import ScriptedModel, call, parse_sse, say

    from senda_api.chat.verify import unverified
    fire = live.fires[0]
    app = create_app(store=store, settings=Settings(anthropic_api_key=None, weather_dir=None),
                     chat_model=ScriptedModel(call("get_fire", {"fire_id": fire.id}), say("Done.")))
    app.state.land = landcover.LandCover(None, FakeFetcher(any_tile=True))
    model = app.state.chat_model
    parse_sse(TestClient(app).post("/api/chats/new/messages", json={"text": "What does it burn on?"}).text)
    out = json.loads(model.tool_results(1)[0]["content"])
    shares = out["land_cover_shares"]
    assert shares and {"class", "share_pct"} == set(shares[0]) and shares[0]["class"] in {n[0] for _, n, _ in landcover.LAND_CLASSES}
    text = f"{shares[0]['share_pct']} % of it burns on {shares[0]['class'].lower()}.".replace(".", ",", 1)
    assert unverified(text, [out], []) == []
    app.state.land = landcover.LandCover(None, FakeFetcher(failing=True))
    model = ScriptedModel(call("get_fire", {"fire_id": fire.id}), say("Done."))
    app.state.chat_model = model
    TestClient(app).post("/api/chats/new/messages", json={"text": "Again"})
    assert json.loads(model.tool_results(1)[0]["content"])["land_cover_shares"] is None


def test_a_line_crosses_the_classes_under_it_and_nothing_outside_the_grid():
    grid = {"bbox": [0.0, 0.0, 0.4, 0.4], "width": 4, "height": 4,
            "classes": "1122" "1122" "3333" "3333"}  # west half 1 and 2 on the north half, 3 on the south half
    assert landcover.along(grid, [[0.05, 0.35], [0.15, 0.35]]) == [{"id": 1, "share_pct": 100.0}]
    mixed = landcover.along(grid, [[0.05, 0.35], [0.05, 0.05]])
    assert {m["id"] for m in mixed} == {1, 3} and sum(m["share_pct"] for m in mixed) == pytest.approx(100, abs=0.2)
    assert landcover.along(grid, [[1.0, 1.0], [2.0, 2.0]]) == []  # off the map: no data, no invented share
    assert len(landcover.along(grid, [[0.05, 0.35], [0.35, 0.05]], top=1)) == 1


def test_the_plan_says_what_each_way_in_crosses_and_waits_for_nothing(store, tmp_path, live):  # noqa: F811
    client = app_with(store, tmp_path, FakeFetcher(any_tile=True))
    fire = west(client)
    made = client.post(f"/api/fires/{fire}/plan", json={"crews": 2, "hours": 3}).json()
    contracts.FirePlan.model_validate(made)
    for crew in made["crews"]:
        assert crew["land"] and len(crew["land"]) <= 2 and all(0 < s["share_pct"] <= 100 for s in crew["land"])
    dark = app_with(store, tmp_path / "dark", FakeFetcher(failing=True))
    made = dark.post(f"/api/fires/{west(dark)}/plan", json={}).json()
    assert [c["land"] for c in made["crews"]] == [None] * len(made["crews"])
