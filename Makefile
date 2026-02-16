ifneq (,$(wildcard .env))
    include .env
endif

PI_HOST ?= pi@tontraeger.local
PI_DIR  ?= /home/pi/tontraeger

.PHONY: help test test-server test-client lint format typecheck check web control read-tag \
        docker-build docker-up docker-down deploy-client deploy-server

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

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

# ── Deployment ──────────────────────────────────────────

docker-build: ## Build server Docker image
	docker build -t tontraeger-server server/

docker-up: ## Start server via docker compose
	docker compose up -d

docker-down: ## Stop server via docker compose
	docker compose down

deploy-client: ## Deploy client to Pi via rsync and restart service
	rsync -av --filter=':- .gitignore' --exclude='tests/' \
		client/ $(PI_HOST):$(PI_DIR)/client/
	ssh $(PI_HOST) 'sudo systemctl restart tontraeger-client'

deploy-server: docker-build ## Build and deploy server via docker compose
	docker compose up -d
