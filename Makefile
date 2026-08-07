.DEFAULT_GOAL := help
SHELL := /bin/bash

BE      := backend
VENV    := $(BE)/.venv/bin
PY      := $(VENV)/python
PNPM    := PATH="$$(npm config get prefix)/bin:$$PATH" pnpm

help:  ## show this help
	@grep -hE '^[a-z][a-z-]*:.*?##' $(MAKEFILE_LIST) \
	  | sort | awk -F':.*?## ' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ setup

install: install-backend install-clients  ## install everything

install-backend:  ## create backend venv and install deps
	python3 -m venv $(BE)/.venv
	$(VENV)/pip install -q uv
	cd $(BE) && .venv/bin/uv pip install -q -e ".[dev]"

install-clients:  ## install the pnpm workspace
	cd clients && $(PNPM) install

# ------------------------------------------------------------- infrastructure

up:  ## start Postgres, Redis, MinIO
	docker compose up -d db cache blobs

wait-db:  ## block until Postgres accepts connections
	@printf "waiting for postgres"
	@for i in $$(seq 1 60); do \
	  docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1 && { echo " ok"; exit 0; }; \
	  printf "."; sleep 1; \
	done; echo " TIMEOUT"; exit 1

down:  ## stop containers
	docker compose down

dev: up wait-db migrate seed  ## boot everything, then: make api / make web
	@echo
	@echo "  make api     backend on :8000"
	@echo "  make web     web on :3000"
	@echo "  make worker  pipeline stages"

# ------------------------------------------------------------------- run

api:  ## run the backend with reload
	cd $(BE) && .venv/bin/techtrend api --reload

worker:  ## run all pipeline stages
	cd $(BE) && .venv/bin/techtrend worker --stage collect,read,group,judge,match,maintenance

web:  ## run the Next.js app on :3000
	cd clients/apps/web && $(PNPM) dev

mobile:  ## run the Expo app
	cd clients/apps/mobile && $(PNPM) start

# ------------------------------------------------------------------ data

migrate:  ## apply migrations
	cd $(BE) && .venv/bin/alembic upgrade head

revision:  ## new migration:  make revision m="add x"
	cd $(BE) && .venv/bin/alembic revision --autogenerate -m "$(m)"

seed:  ## seed a demo user, topic and stories
	cd $(BE) && .venv/bin/techtrend seed-demo

psql:  ## open a psql shell
	docker compose exec db psql -U postgres techtrend

backlog:  ## jobs by stage and state
	cd $(BE) && .venv/bin/techtrend backlog

# ------------------------------------------------------------------ checks

test: test-backend test-clients  ## all tests

test-backend:  ## pytest (needs `make up`)
	cd $(BE) && .venv/bin/python -m pytest tests -q

test-unit:  ## fast loop, no I/O
	cd $(BE) && .venv/bin/python -m pytest tests/unit -q

test-clients:  ## vitest
	cd clients && $(PNPM) -r test

lint:  ## ruff
	cd $(BE) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests

types:  ## mypy + tsc
	cd $(BE) && .venv/bin/mypy src
	cd clients && $(PNPM) -r typecheck

contracts:  ## layer violations fail here
	cd $(BE) && .venv/bin/lint-imports

build-web:  ## production build of the web app
	cd clients && $(PNPM) --filter web build

check: lint types contracts test  ## everything CI runs

client:  ## regenerate the typed API client from the backend's OpenAPI schema
	cd $(BE) && .venv/bin/python -c "import json; from techtrend.api.app import create_app; \
	  json.dump(create_app().openapi(), open('../clients/packages/api-client/openapi.json','w'), indent=2)"
	cd clients && $(PNPM) --filter @techtrend/api-client generate

.PHONY: help install install-backend install-clients up down dev api worker web mobile \
        migrate revision seed psql backlog test test-backend test-unit test-clients \
        lint types contracts build-web check client
