import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from senda_api import meta
from senda_api.app import create_app
from senda_api.errors import SafeJSONResponse, clean


def test_clean_removes_non_finite_and_numpy_types():
    got = clean({"a": float("nan"), "b": [float("inf"), -np.inf], "c": np.int64(3), "d": np.float32(0.5),
                 "e": np.array([1, np.nan])})
    assert got == {"a": None, "b": [None, None], "c": 3, "d": 0.5, "e": [1.0, None]}
    assert type(got["c"]) is int


def test_response_never_writes_nan():
    text = SafeJSONResponse({"x": float("nan"), "y": np.float64("inf")}).body.decode()
    assert text == '{"x":null,"y":null}'
    json.loads(text, parse_constant=lambda c: pytest.fail(c))


def test_unexpected_exception_has_error_shape(store, monkeypatch):
    def boom(_):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(meta, "meta", boom)
    res = TestClient(create_app(store=store), raise_server_exceptions=False).get("/api/meta")
    assert res.status_code == 500
    assert res.json() == {"error": {"code": "internal_error", "message": "Internal error"}}


def test_validation_errors_use_error_shape(client):
    res = client.post("/api/calendar", content=b"not json", headers={"content-type": "application/json"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"
    assert client.put("/api/meta").status_code == 405
    assert client.put("/api/meta").json()["error"]["code"] == "method_not_allowed"


def test_openapi_is_served(client):
    spec = client.get("/api/openapi.json").json()
    assert "/api/calendar" in spec["paths"]
