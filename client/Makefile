.PHONY: help lint lint-nfc-daemon format typecheck test run build-nfc-daemon

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

lint: lint-nfc-daemon ## Lint client code
	uv run ruff check tontraeger_client/

lint-nfc-daemon: ## Static analysis on NFC daemon C code
	$(MAKE) -C nfc-daemon lint

format: ## Format client code
	uv run ruff format tontraeger_client/

typecheck: ## Type check client code
	uv run mypy tontraeger_client/

test: ## Run client tests
	uv run pytest

run: ## Start client (NFC reader + sync)
	uv run python -m tontraeger_client.main

build-nfc-daemon: ## Build the NFC daemon binary
	$(MAKE) -C nfc-daemon
