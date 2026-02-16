ifneq (,$(wildcard .env))
    include .env
endif

PI_HOST                ?= pi@tontraeger.local
PI_DIR                 ?= /home/pi/tontraeger
SONOS_SPEAKER_NAME     ?= Wohnzimmer
TONTRAEGER_SERVER      ?= http://tontraeger.local:5000
TONTRAEGER_CACHE_PATH  ?= /home/pi/tontraeger/client/mappings.json

.PHONY: help test test-server test-client lint format typecheck check web control read-tag \
        docker-build docker-up docker-down sync-client run-server install-client-service

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

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

sync-client: ## Sync client code to Pi via rsync and restart service
	rsync -av --filter=':- .gitignore' --exclude='tests/' \
		client/ $(PI_HOST):$(PI_DIR)/client/
	ssh $(PI_HOST) 'sudo systemctl restart tontraeger-client'

install-client-service: ## Generate service file from .env and install it on the Pi
	printf '[Unit]\nDescription=tontraeger Client (RFID reader + Sonos playback)\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nExecStart=/usr/bin/make -C %s control\nWorkingDirectory=%s/client\nRestart=always\nRestartSec=5\nEnvironment=SONOS_SPEAKER_NAME=%s\nEnvironment=TONTRAEGER_SERVER=%s\nEnvironment=TONTRAEGER_CACHE_PATH=%s\n\n[Install]\nWantedBy=multi-user.target\n' \
		'$(PI_DIR)' '$(PI_DIR)' '$(SONOS_SPEAKER_NAME)' '$(TONTRAEGER_SERVER)' '$(TONTRAEGER_CACHE_PATH)' \
		| ssh $(PI_HOST) 'sudo tee /etc/systemd/system/tontraeger-client.service > /dev/null'
	ssh $(PI_HOST) 'sudo systemctl daemon-reload && sudo systemctl enable tontraeger-client'
