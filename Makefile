ifneq (,$(wildcard .env))
    include .env
endif

.PHONY: help test test-server test-client lint format typecheck check web control read-tag sync

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

test: test-server test-client ## Run all tests

test-server: ## Run server tests
	cd server && uv run pytest

test-client: ## Run client tests
	cd client && uv run pytest

lint: ## Lint code
	uv run ruff check server/ client/

format: ## Format code
	uv run ruff format server/ client/

typecheck: ## Type check code
	cd server && uv run mypy tontraeger_server/
	cd client && uv run mypy tontraeger_client/

check: lint typecheck test ## Run all checks (lint, typecheck, test)

web: ## Start Flask web UI (server)
	cd server && uv run python -m tontraeger_server.main

control: ## Start client (RFID reader + sync)
	cd client && uv run python -m tontraeger_client.main

read-tag: ## Read an RFID tag ID
	cd client && uv run python -m tontraeger_client.read_rfid_tag_id

sync: ## Deploy to Pi via rsync
	./sync_to_pi.sh $(SYNC_DESTINATION)
