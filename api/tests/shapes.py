"""Check an answer against its model in `senda_api.contracts`, the shapes `openapi.json` promises."""

from __future__ import annotations

from pydantic import TypeAdapter

from senda_api import contracts


def check(name: str, body) -> None:
    TypeAdapter(getattr(contracts, name)).validate_python(body)
