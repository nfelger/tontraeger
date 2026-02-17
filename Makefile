ifneq (,$(wildcard .env))
    include .env
endif

PI_HOST ?= pi@tontraeger.local
PI_DIR  ?= /home/pi/tontraeger

.PHONY: help test test-server test-client lint format typecheck check web control read-tag \
        docker-build docker-up docker-down sync-client run-server install-client-service

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

test: test-server test-client ## Run all tests

test-server: ## Run server tests
	$(MAKE) -C server test

test-client: ## Run client tests
	cd client && uv run pytest

lint: ## Lint code
	$(MAKE) -C server lint
	cd client && uv run ruff check tontraeger_client/

format: ## Format code
	cd server && uv run ruff format tontraeger_server/
	cd client && uv run ruff format tontraeger_client/

typecheck: ## Type check code
	$(MAKE) -C server typecheck
	cd client && uv run mypy tontraeger_client/

check: lint typecheck test ## Run all checks (lint, typecheck, test)

web: ## Start Flask web UI (server)
	$(MAKE) -C server run

control: ## Start client (RFID reader + sync)
	cd client && uv run python -m tontraeger_client.main

read-tag: ## Read an RFID tag ID
	cd client && uv run python -m tontraeger_client.read_rfid_tag_id

# ── Local server (Docker) ────────────────────────────────

docker-build: ## Build server Docker image
	docker build -t tontraeger-server server/

docker-up: ## Start server via docker compose (without rebuilding)
	docker compose up -d

docker-down: ## Stop server via docker compose
	docker compose down

run-server: ## Rebuild image and restart server via docker compose
	docker compose up --build -d

# ── Client (Pi) ──────────────────────────────────────────

sync-client: ## Sync client code + .env to Pi via rsync and restart service
	rsync -av --filter=':- .gitignore' --exclude='tests/' \
		client/ $(PI_HOST):$(PI_DIR)/client/
	scp .env $(PI_HOST):$(PI_DIR)/.env
	ssh $(PI_HOST) 'sudo systemctl restart tontraeger-client'

install-client-service: ## Install the systemd service file on the Pi
	sed 's|__PI_DIR__|$(PI_DIR)|g' client/tontraeger-client.service \
		| ssh $(PI_HOST) 'sudo tee /etc/systemd/system/tontraeger-client.service > /dev/null'
	ssh $(PI_HOST) 'sudo systemctl daemon-reload && sudo systemctl enable tontraeger-client'
