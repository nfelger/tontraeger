PYTHON ?= uv run python

.PHONY: help run test lint format typecheck

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

run: ## Start Flask web UI
	$(PYTHON) -m tontraeger_server.main

test: ## Run server tests
	uv run pytest

lint: ## Lint server code
	uv run ruff check .

format: ## Format server code
	uv run ruff format tontraeger_server/

typecheck: ## Type check server code
	uv run mypy tontraeger_server/
