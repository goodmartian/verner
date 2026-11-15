.PHONY: run test openapi db-up migrate

ENV = set -a; if [ -f ../.env ]; then . ../.env; fi; set +a;

run:
	set -a; if [ -f ../.env ]; then . ../.env; fi; set +a; \
	SENDA_DATA=$${SENDA_DATA:-../data/current} uv run uvicorn senda_api.app:app --host 127.0.0.1 --port 8026

test:
	OMP_NUM_THREADS=4 POLARS_MAX_THREADS=4 uv run pytest -q

openapi:
	uv run python -m senda_api.openapi_cli openapi.json

db-up:
	cd .. && docker compose up -d postgres

migrate:
	$(ENV) uv run alembic upgrade head
