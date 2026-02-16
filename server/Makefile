PYTHON ?= uv run python

.PHONY: run test lint typecheck

run: ## Start Flask web UI
	$(PYTHON) -m tontraeger_server.main

test: ## Run server tests
	uv run pytest

lint: ## Lint server code
	uv run ruff check .

typecheck: ## Type check server code
	uv run mypy tontraeger_server/
