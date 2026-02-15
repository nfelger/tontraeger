ifneq (,$(wildcard .env))
    include .env
endif

.PHONY: help test lint format typecheck check web control read-tag sync

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

test: ## Run tests
	uv run pytest

lint: ## Lint code
	uv run ruff check .

format: ## Format code
	uv run ruff format .

typecheck: ## Type check code
	uv run mypy tontraeger/

check: lint typecheck test ## Run all checks (lint, typecheck, test)

web: ## Start Flask web UI
	uv run python tontraeger/web.py

control: ## Start RFID control loop
	uv run python -m tontraeger.control

read-tag: ## Read an RFID tag ID
	uv run python -m tontraeger.read_rfid_tag_id

sync: ## Deploy to Pi via rsync
	./sync_to_pi.sh $(SYNC_DESTINATION)
