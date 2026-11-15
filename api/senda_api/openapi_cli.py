"""Write the OpenAPI schema to a file: python -m senda_api.openapi_cli openapi.json (no data needed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .app import create_app


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m senda_api.openapi_cli <output.json>")
    schema = create_app(load_on_start=False).openapi()
    Path(args[0]).write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
