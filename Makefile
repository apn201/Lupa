# Lupa - build targets. Windows: run from Git Bash.
PY ?= $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python,$(if $(wildcard .venv/bin/python),.venv/bin/python,python))
PORT ?= 8000

.PHONY: help install run test import sample seed seed-check sync demo spike mcp openapi check secrets reset video-reset

help:
	@echo "install     venv dependencies"
	@echo "run         serve the API and UI on :$(PORT) (imports the sample on first run)"
	@echo "test        pytest"
	@echo "import      load the sample CSV into the ledger"
	@echo "sample      regenerate the synthetic sample"
	@echo "spike       S0 sandbox checks (needs .env)"
	@echo "seed        create sandbox products, plans, subscriptions, orders"
	@echo "seed-check  subscription status; registers ACTIVE ones as permissions"
	@echo "sync        Transaction Search + subscriptions -> ledger"
	@echo "demo        replay data/scenarios/demo_main.json against a running server"
	@echo "mcp         MCP server on stdio (for Claude Desktop)"
	@echo "openapi     write docs/api.md and docs/openapi.json"
	@echo "check       secrets scan + tests. run before every push"
	@echo "video-reset clean ledger + fresh sandbox subscriptions for recording"

install:
	python -m venv .venv
	$(PY) -m pip install -e ".[dev]"

run:
	@test -f var/lupa.db || $(PY) -m lupa import
	$(PY) -m uvicorn lupa.api.app:app --port $(PORT) --reload

test:
	$(PY) -m pytest

import:
	$(PY) -m lupa import

sample:
	$(PY) scripts/make_synthetic_sample.py

spike:
	$(PY) scripts/spike.py

seed:
	$(PY) scripts/seed_sandbox.py

seed-check:
	$(PY) scripts/seed_sandbox.py --check

sync:
	$(PY) -m lupa sync

demo:
	$(PY) scripts/demo.py --pause 1

mcp:
	$(PY) -m lupa.mcp.server

openapi:
	$(PY) -m lupa openapi

secrets:
	$(PY) tools/check_secrets.py

check: secrets test

reset:
	$(PY) -m lupa reset

# Before recording: stop the server first. Prints new approve links; then make seed-check && make sync.
video-reset: reset
	$(PY) -m lupa import
	$(PY) scripts/seed_sandbox.py --fresh
