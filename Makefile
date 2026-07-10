# Grocery Tracker — Makefile
# Works on Linux and macOS (including Apple Silicon M1/M2)

BACKEND_DIR = backend

.PHONY: setup run test lint format help

help:
	@echo "Grocery Tracker Dev Commands"
	@echo "  make setup   — install dependencies and git hooks"
	@echo "  make run     — start local dev server (http://localhost:8000)"
	@echo "  make test    — run full pytest suite"
	@echo "  make lint    — ruff check + format check"
	@echo "  make format  — auto-fix formatting with ruff"

setup:
	cd $(BACKEND_DIR) && uv sync
	cd $(BACKEND_DIR) && uv run pre-commit install
	@echo "✅ Setup complete. Run 'make run' to start the server."

run:
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	cd $(BACKEND_DIR) && uv run pytest tests/ -v

lint:
	cd $(BACKEND_DIR) && uv run ruff check .
	cd $(BACKEND_DIR) && uv run ruff format --check .

format:
	cd $(BACKEND_DIR) && uv run ruff check --fix .
	cd $(BACKEND_DIR) && uv run ruff format .
