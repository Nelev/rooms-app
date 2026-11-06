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

# The same, without Postgres: the API serves the stub graph (fixtures and the fake model, in memory), paced to look live.
dev-stub: install
	trap 'kill 0' EXIT; \
	(cd backend && DATABASE_URL= OPENROUTER_API_KEY= STUB_PACE=0.3 uv run uvicorn app.main:app --reload $(ENV_FILE)) & \
	(cd frontend && pnpm dev) & \
	wait

test:
	cd backend && uv run pytest -q
	cd frontend && pnpm test

lint:
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy
	cd frontend && pnpm check && pnpm typecheck

# JSON Schema of the domain models in contracts/schemas/, the API's contracts/openapi.json and its TypeScript types
gen:
	cd backend && uv run python -m app.schemas.export && uv run python -m app.api.export
	cd frontend && pnpm gen

# The eval of a pipeline variant (baseline, full, no_critic...): eval/results/<variant>-<time>/report.md; offline (fake models) without
# OPENROUTER_API_KEY. `make eval VARIANT=full`
.PHONY: eval
eval:
	cd backend && PYTHONPATH=..:../eval uv run $(ENV_FILE) python -m eval run --variant $(or $(VARIANT),baseline) --repeats 3

# Several variants in one report with charts (eval/ablation.py): eval/results/ablation-<time>/. `make ablate ARGS="--judge --repeats 1"`
.PHONY: ablate
ablate:
	cd backend && PYTHONPATH=..:../eval uv run $(ENV_FILE) python -m eval ablate $(ARGS)

# The E2E suite (e2e/, Playwright) on the docker compose stack, the real graph answering from the model calls recorded in
# e2e/recordings/ (offline: no key, no model calls). The stack's ports: FRONTEND_PORT, BACKEND_PORT, DB_PORT, MINIO_PORT.
E2E_STACK := docker compose -p rooms-e2e -f docker-compose.yml -f e2e/compose.yml
.PHONY: e2e e2e-record
e2e: # the stack's logs end up in e2e/test-results/stack.log, which CI uploads on failure
	trap 'mkdir -p e2e/test-results; $(E2E_STACK) logs --no-color > e2e/test-results/stack.log 2>&1; $(E2E_STACK) down -v' EXIT; \
	$(E2E_STACK) up -d --build --wait && \
	(cd e2e && pnpm install --frozen-lockfile && pnpm typecheck && pnpm exec playwright install chromium && \
		BASE_URL=http://localhost:$${FRONTEND_PORT:-3000} pnpm test)

# Records the model calls of the suite that e2e/recordings/ lacks, with OPENROUTER_API_KEY exported in the shell: it costs money
# (capped by LLM_RECORD_MAX_COST, default 0.4 USD, over all the recordings). Commit the new recordings. Only this target passes the
# key to the stack: `make e2e` never records, whatever the root .env holds.
e2e-record:
	test -n "$$OPENROUTER_API_KEY"
	E2E_OPENROUTER_API_KEY="$$OPENROUTER_API_KEY" E2E_RECORD=1 $(MAKE) e2e
