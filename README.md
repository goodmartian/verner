# Verner

Verner is a web app that turns NASA MODIS and VIIRS active fire detections into one burning-activity calendar for any area of the world, from November 2000 to the latest complete date. It was built for NASA Space Apps 2026, challenge "Harmonization of MODIS and VIIRS Hot Spots". Team: Goodmartian Labs (goodmartian.dev). Verner is named after Verner E. Suomi, the father of satellite meteorology, after whom the Suomi NPP satellite is named.

Live site: [verner.earth](https://verner.earth)

Demo video: [youtu.be/GRkyzUrGhpY](https://youtu.be/GRkyzUrGhpY)

## What it does

- Harmonizes MODIS Aqua and MODIS Terra counts to the VIIRS S-NPP scale, with its own validation.
- Builds a daily series from one usable satellite of a fixed chain on each date.
- Works for any area: a country, a region, or a drawn area.
- Calendar: every month since November 2000 for the selected area, colored against the median of the same calendar month in the base years (from 2003), with the expected error of the area.
- Compares the current incomplete month with the median of the same dates in earlier years.
- Consistency check for the selected area: conversion fitted on 2012 to 2019 and checked blind on 2020 to 2021.
- Outlook: six months ahead for the area. Where a model beats the median of earlier years in its own check (by at least 10 percent, with a range that holds), the outlook uses the model. Elsewhere it uses the median of the same calendar month. Each month has a 10th to 90th percentile range and the error of its check. It uses no weather data.
- Fires: clusters of detections of the last three complete days, named by the nearest place, with an area estimate.
- Exports hot spots and monthly tables as CSV.
- Chat assistant on the Claude API. It answers questions about an area, a month or a fire from Verner's own data, checks every figure against that data, and builds draft work plans for live fires.

## How it works

Folders:

- `pipeline/` reads FIRMS archives and API responses, picks one satellite per date (MODIS Terra before 2002-07-04, then MODIS Aqua, then VIIRS from 2012-02), fits conversion factors, validates them and publishes a data version.
- `api/` loads a version into memory as sparse matrices (cell by month) and computes the calendar of an area as weights times matrix.
- `web/` is the web interface: the Fires screen, the Calendar board, the chat assistant and the map toolbar.
- The routes the web interface calls are in `api/senda_api/*_routes.py` and `base.py`. The full list is in `api/openapi.json`.

Data flow:

```
FIRMS zips (2000-2025) + FIRMS API (2026)
  -> pipeline: filter, mask static sources, local solar time
  -> satellite chain by day, pair days
  -> fit factors, validate -> harmonization.json
  -> published version in data/versions/<version>, link data/current
  -> forecast: model checked against the median of past years -> forecast.json, forecast.parquet
  -> api (SENDA_DATA=data/current) -> web
```

Method details: [docs/method.md](docs/method.md).

## Run locally

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js, make.

1. Copy `.env.example` to `.env`. Set `FIRMS_MAP_KEY` (free key from NASA FIRMS), `SENDA_ZIPS` and `SENDA_GEO`. Set `ANTHROPIC_API_KEY` to turn on the chat assistant.
2. Build the data. From `pipeline/`, in this order:

```
uv sync
uv run senda-pipeline fetch --data ../data --year 2026
uv run senda-pipeline scan --data ../data
uv run senda-pipeline days --data ../data
uv run senda-pipeline cells --data ../data
uv run senda-pipeline regions --data ../data
uv run senda-pipeline build --data ../data
uv run senda-pipeline harmonize --data ../data
uv run senda-pipeline seam --data ../data
uv run senda-pipeline publish --data ../data
uv run senda-pipeline verify --data ../data
(cd ../api && SENDA_DATA=../data/current uv run python scripts/build_events.py --data ../data/current)
uv run senda-pipeline forecast --data ../data
uv run senda-pipeline weather --data ../data
```

`build_events.py` writes the notable events of the version, `forecast` the outlook, `weather` the NOAA GFS fields. `pipeline/update.sh` runs the daily part of these steps (from `fetch` to `weather`) in one go; `pipeline/cron.sh` wraps it for cron. `senda-pipeline climate` (ERA5, needs `COPERNICUS_API_KEY`) is optional and run by hand.

`fetch` needs the key and network. The published data version takes 2.7 GiB on disk.

3. Chats and saved plans live in Postgres 18. Start it (port 5437 on 127.0.0.1) and create the tables; `SENDA_DB_PASSWORD` and `DATABASE_URL` are in `.env` (see `.env.example`):

```
docker compose up -d
make -C api migrate
```

Without the database the calendar, fires, weather and climate work; chats and plans answer 503 `storage_unavailable`.

4. Start the API on port 8026:

```
make -C api run
```

5. Start the web app on port 5184 (it proxies `/api` to `127.0.0.1:8026`):

```
cd web
npm install --legacy-peer-deps
npm run dev
```

The API reads the data from `SENDA_DATA`.

## Tests

```
cd pipeline && uv run pytest && uv run ruff check
make -C api test
cd web && npx tsc --noEmit && npx vitest run
```

Tests run without network access, on small fixtures. The tests of chats and plans use a database `senda_test_<pid>` on the Postgres server of `DATABASE_URL` (made for the run and dropped after it); without a running server they are skipped.

## Accuracy

Error is WAPE: the sum of absolute differences between converted MODIS and VIIRS S-NPP monthly counts, divided by the S-NPP total. Median over 24 supported zones, data version 20261113-75499fd2ca1b:

| Check | Without conversion (L0) | With conversion (L5) |
|---|---|---|
| Each year of 2012 to 2019 left out in turn (`loyo`) | 84.6 percent | 8.6 percent |
| Fit 2012 to 2019, test 2020 to 2021 (`forward`) | 85.0 percent | 10.2 percent |

- Median over countries: 8.6 percent (`loyo`) and 9.8 percent (`forward`). 41 of 50 candidate countries have their own factor.
- Bridge NOAA-20 to S-NPP, median zone error: 2.6 percent (`bridge_loyo`) and 2.8 percent (`bridge_forward`).
- MODIS Terra to S-NPP: median zone error 8.9 percent (`loyo`). Converted Terra against converted Aqua on 2003-01 to 2011-12: median zone error 12.5 percent, world bias -4.0 percent. Terra passed the rule set before the check (at most 15 percent, at most 20 percent, bias within 10 percent).
- Known fire seasons: 12 of 12 found (5 of 5 in the MODIS era, 7 of 7 in the VIIRS era).
- Without conversion, the world count of 2012 is 6.04 times that of 2011. With conversion it is 1.05 times.
- The site shows the expected error for the selected area. Examples: World 3.4 percent, Argentina 9.5 percent, Kazakhstan 10.2 percent, Corrientes 16.3 percent, Tajikistan 45.5 percent.

Full tables: [docs/method.md](docs/method.md).

## Limitations

- Values from November 2000 to January 2012 come from MODIS and are converted to the VIIRS scale. They are estimates, not measurements.
- Values before 2002-07-04 come from MODIS Terra, a morning satellite (equator crossing about 10:30 local time). MODIS Aqua and VIIRS cross at about 13:30.
- Months before 2003 are shown in the series, yearly totals, calendar grid and export. They are not in the base: medians, norms, rank among years, season, trend, expected error, the consistency check and the outlook use years from 2003.
- Active fire detections are not burned area.
- Small areas have larger error. The site shows the expected error for the selected area.
- Error on later held-out years is higher than on held-out fitting years: 10.2 percent against 8.6 percent. Per-country numbers are in [docs/method.md](docs/method.md).
- 43 dates have no usable satellite: 39 before 2003 and four later (2003-03-14, 2003-05-12, 2006-06-18, 2007-07-12). Their months are marked incomplete. The full list is in [docs/method.md](docs/method.md).
- NOAA-21 is not used.
- The outlook comes from a model only where it passed its check. The model (gradient boosting on 1 degree boxes) learns from past fire counts only, trained through 2026-10. It has no weather. The check covers 2015 to 2025: for each year, the model and the median are fitted on earlier years only, and each month is forecast from the data 2 to 7 months before it. For an area, the model is used on the first months of the outlook where its monthly error is at most 0.9 times the error of the median of past years and its range holds 70 to 90 percent of the real months. Elsewhere, and for drawn areas, the outlook is the median of the same calendar month in past years.
- Monthly error on that check: World 10.5 to 10.9 percent with the model against 12.1 percent with the median; Argentina 41.1 to 45.7 percent against 51.0 percent. Corrientes shows the median (model 62.7 to 67.7 percent, median 66.7 percent).
- The area of a fire is an estimate from the number of 375 m pixels with detections, not burned area.
- Weather and wind come from the NOAA GFS grid, not from the fire data. The spread outline and the suppression plan move the whole outline of a fire by the speed measured between two satellite passes and by that wind. They are an upper estimate. A path in a plan follows the land cover map when the map can be read; otherwise it is a straight line.
- Land cover under a live fire comes from ESA WorldCover. The way in to a fire comes from OpenStreetMap fire stations and OSRM driving routes, with Google as an optional fallback. When a source does not answer, the interface shows no land cover or route.
- Fires are listed only for the last three complete days. A fire needs at least 25 linked detections.
- Dates are in local solar time.
- When S-NPP has no data for a date, the series takes NOAA-20, then Aqua (the satellite chain is in [docs/method.md](docs/method.md)).
- Day and night counts were tested as separate models and rejected by the selection rule, so one factor covers both.

## Use of AI

Code, tests and texts of this project were written with Claude Code (Claude models). The team set the idea, the method and the requirements, and read and accepted the results. Accuracy numbers come from a calculation on FIRMS data. Details: [docs/ai-usage.md](docs/ai-usage.md).

## Sources

All data sources, credits and library licenses: [docs/sources.md](docs/sources.md).

We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Land, Atmosphere Near real-time Capability for Earth observations (LANCE) and NASA's Earth Science Data and Information System (ESDIS).

## License

GNU Affero General Public License v3.0 (AGPL-3.0-only), see [LICENSE](LICENSE). Copyright 2026 Goodmartian Labs.

You may use, change and share the code under the same license. If you run a changed version as a network service, you must offer its source to the users of that service.
