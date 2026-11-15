"""senda-pipeline <command> [options]: each command lives in its own module with main(argv) -> int."""

from __future__ import annotations

import importlib
import sys

COMMANDS = {
    "fetch": "senda_pipeline.fetch_cli",
    "weather": "senda_pipeline.weather",
    "climate": "senda_pipeline.climate",
    "forecast": "senda_pipeline.forecast",
    "scan": "senda_pipeline.scan",
    "days": "senda_pipeline.days_cli",
    "build": "senda_pipeline.build",
    "cells": "senda_pipeline.cells",
    "regions": "senda_pipeline.regions",
    "harmonize": "senda_pipeline.harmonize",
    "seam": "senda_pipeline.seam",
    "publish": "senda_pipeline.publish",
    "verify": "senda_pipeline.verify",
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        print("usage: senda-pipeline <command> [options]\ncommands: " + ", ".join(COMMANDS), file=sys.stderr)
        return 2
    return int(importlib.import_module(COMMANDS[args[0]]).main(args[1:]) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
