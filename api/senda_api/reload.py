"""A new data version appears while the server runs: load it beside the old one and swap.

The version is the folder `data_dir` (the `current` symlink) points at; `Store.root` is that folder, resolved when
loaded, so the two are compared as they are. A version counts as finished when the pipeline has put `READY` in it
(`update.sh` does that last, after the forecast); a folder without it is waited for. A load that fails leaves the old
store serving and is tried again on the next tick."""

from __future__ import annotations

import asyncio
import gc
import logging
import time

from fastapi import FastAPI

from . import calendar_routes
from .store import Store

log = logging.getLogger("uvicorn.error").getChild("senda.reload")  # under uvicorn's logger its INFO lines show too
READY = "READY"


async def check(app: FastAPI) -> bool:
    """One look at the symlink; True when a newer version was loaded and put in place."""
    old: Store | None = app.state.store
    target = app.state.settings.data_dir.resolve()
    if old is None or target == old.root or not (target / READY).exists():
        return False
    started = time.monotonic()
    try:
        new = await asyncio.to_thread(Store.load, target)
    except Exception as err:  # noqa: BLE001 - files still being written, a broken file: stay on the old version
        problem = (target, f"{type(err).__name__}: {err}")
        if getattr(app.state, "reload_failed", None) != problem:  # one line per problem, not one per tick
            log.warning("data %s not loaded, still serving %s: %s", target.name, old.version, problem[1])
            app.state.reload_failed = problem
        return False
    app.state.store = new
    app.state.reload_failed = None
    log.info("data %s -> %s, loaded in %.1f s", old.version, new.version, time.monotonic() - started)
    calendar_routes.warm_later(new)  # what the first visitor of the world asks for, made before they ask
    del old
    await asyncio.to_thread(gc.collect)  # the caches of the old version hold it in cycles; requests in flight keep it until they end
    return True


async def watch(app: FastAPI, every: float) -> None:
    while True:
        await asyncio.sleep(every)
        try:
            await check(app)
        except Exception:
            log.exception("data reload check failed")
