.PHONY: help lint format typecheck run read-tag

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

lint: ## Lint client code
	uv run ruff check tontraeger_client/

format: ## Format client code
	uv run ruff format tontraeger_client/

typecheck: ## Type check client code
	uv run mypy tontraeger_client/

run: ## Start client (RFID reader + sync)
	uv run python -m tontraeger_client.main

read-tag: ## Read an RFID tag ID
	uv run python -m tontraeger_client.read_rfid_tag_id
