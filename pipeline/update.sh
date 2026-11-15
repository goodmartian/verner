#!/bin/bash
# Update everything: fetch FIRMS (open NRT windows are downloaded again), rebuild and publish a data version,
# refresh the weather. Run from anywhere: bash pipeline/update.sh [--skip-scan]
# --skip-scan skips fetch, scan and days and rebuilds from the last scan.
# The repository root (ROOT) and the data root (D) come from pipeline/paths.sh.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/paths.sh"
# one heavy step at a time, low priority, 4 threads
export OMP_NUM_THREADS=4 POLARS_MAX_THREADS=4
heavy() { nice -n 10 "$@"; }

cd "$ROOT/pipeline"
if [ "${1:-}" != "--skip-scan" ]; then
  uv run senda-pipeline fetch --data "$D" --year "$(date -u +%Y)"
  heavy uv run senda-pipeline scan --data "$D"
  uv run senda-pipeline days --data "$D"
fi
heavy uv run senda-pipeline build --data "$D"
heavy uv run senda-pipeline harmonize --data "$D"
heavy uv run senda-pipeline seam --data "$D"
heavy uv run senda-pipeline publish --data "$D"
uv run senda-pipeline verify --data "$D"
cd "$ROOT/api"
SENDA_DATA="$D/current" heavy uv run python scripts/build_events.py --data "$D/current"
cd "$ROOT/pipeline"
# the forecast reads the published version (and its events.json) and writes forecast.json/.parquet into the version
# folder like events.json, outside the manifest; a version that already has its forecast is skipped
heavy uv run senda-pipeline forecast --data "$D"
uv run senda-pipeline verify --data "$D"
# the sign for the API that this version is complete (forecast written, verified): an empty READY file in it,
# put there whole; the weather lives apart from the version and is not waited for
READY="$D/versions/$(basename "$(readlink "$D/current")")/READY"
: > "$READY.tmp" && mv "$READY.tmp" "$READY"
heavy uv run senda-pipeline weather --data "$D"
echo "UPDATE DONE $(readlink "$D/current")"
