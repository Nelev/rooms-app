.PHONY: install dev dev-stub test lint gen

ENV_FILE := $(if $(wildcard .env),--env-file ../.env)

install:
	cd backend && uv sync
	cd frontend && pnpm install

# Postgres in Docker, the API (http://localhost:8000) and the frontend (http://localhost:3000) from source, with reload.
dev: install
	docker compose up -d --wait db
	trap 'kill 0' EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload $(ENV_FILE)) & \
	(cd frontend && pnpm dev) & \
	wait

dev-stub:
	@echo "TODO(S-03): run 'make dev' with the stub graph and the fake model" && exit 1

test:
	cd backend && uv run pytest -q
	cd frontend && pnpm test

lint:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy
	cd frontend && pnpm check && pnpm typecheck

# JSON Schema of the domain models in contracts/schemas/; TODO(S-03): also generate frontend/src/lib/api/generated/ from the OpenAPI schema
gen:
	cd backend && uv run python -m app.schemas.export
