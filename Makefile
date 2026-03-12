ifneq (,$(wildcard .env))
    include .env
endif

.PHONY: help test test-server test-client lint format typecheck check web control \
        docker-build docker-up docker-down sync-client run-server install-client-service \
        build-nfc-daemon

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

test: test-server test-client ## Run all tests

test-server: ## Run server tests
	$(MAKE) -C server test

test-client: ## Run client tests
	$(MAKE) -C client test

lint: ## Lint code
	$(MAKE) -C server lint
	$(MAKE) -C client lint

format: ## Format code
	$(MAKE) -C server format
	$(MAKE) -C client format

typecheck: ## Type check code
	$(MAKE) -C server typecheck
	$(MAKE) -C client typecheck

check: lint typecheck test ## Run all checks (lint, typecheck, test)

web: ## Start Flask web UI (server)
	$(MAKE) -C server run

control: ## Start client (NFC reader + sync)
	$(MAKE) -C client run

build-nfc-daemon: ## Build the NFC daemon binary (requires libnfc-dev)
	$(MAKE) -C client build-nfc-daemon

# ── Local server (Docker) ────────────────────────────────

docker-build: ## Build server Docker image
	docker build -t tontraeger-server server/

docker-up: ## Start server via docker compose (without rebuilding)
	cd server/ && docker compose up -d

docker-down: ## Stop server via docker compose
	cd server/ && docker compose down

run-server: ## Rebuild image and restart server via docker compose
	cd server/ && docker compose up --build -d

# ── Client (Pi) ──────────────────────────────────────────

sync-client: ## Sync client code + .env to Pi via rsync and restart service
	ssh $(PI_HOST) "mkdir -p $(PI_DIR)/client/nfc-daemon"
	git ls-files -oc --exclude-standard client/ | rsync -av --files-from=- ./ $(PI_HOST):$(PI_DIR)/
	scp client/.env $(PI_HOST):$(PI_DIR)/client/.env
	ssh $(PI_HOST) 'cd $(PI_DIR)/client/nfc-daemon && make && sudo cp nfc-daemon /usr/local/bin/'
	ssh $(PI_HOST) 'sudo systemctl restart tontraeger-client' || true

install-client-service: ## Install the systemd service file on the Pi
	sed 's|__PI_DIR__|$(PI_DIR)|g' client/tontraeger-client.service \
		| sed 's|__PI_USER__|$(PI_USER)|g' \
		| sed 's|__PI_GROUP__|$(PI_GROUP)|g' \
		| sed 's|__PI_UV_BIN_DIR__|$(PI_UV_BIN_DIR)|g' \
		| ssh $(PI_HOST) 'sudo tee /etc/systemd/system/tontraeger-client.service > /dev/null'
	ssh $(PI_HOST) 'sudo systemctl daemon-reload && sudo systemctl enable tontraeger-client && sudo systemctl start tontraeger-client.service'

client-log-tail: ## Tail the client logs on the Pi
	ssh $(PI_HOST) 'journalctl -u tontraeger-client -f'
