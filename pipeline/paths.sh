# Sourced by the scripts of this folder: ROOT is the repository, D is the data root.
# The data root is the parent of SENDA_DATA (it points at <root>/current), from the environment or .env;
# default <repo>/data.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [ -z "${SENDA_DATA:-}" ] && [ -f "$ROOT/.env" ]; then
  SENDA_DATA=$(sed -n 's/^SENDA_DATA=//p' "$ROOT/.env" | tail -1)
fi
D=$(dirname "${SENDA_DATA:-$ROOT/data/current}")
