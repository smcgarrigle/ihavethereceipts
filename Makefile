# Grocery Tracker — Makefile
# Works on Linux and macOS (including Apple Silicon M1/M2)

BACKEND_DIR = backend

# The app has no authentication, so it binds to loopback only by default.
# Reach it from other devices over Tailscale instead: `tailscale serve --bg 8000`
# publishes it to your tailnet over HTTPS without exposing it to the LAN.
# Override deliberately with `make run-lan` (or `make run HOST=0.0.0.0`).
HOST ?= 127.0.0.1

.PHONY: setup run run-lan test lint format demo help

help:
	@echo "Grocery Tracker Dev Commands"
	@echo "  make setup   — install dependencies and git hooks"
	@echo "  make run     — start local dev server (http://127.0.0.1:8000)"
	@echo "  make run-lan — same, but bound to 0.0.0.0 (no auth — trusted networks only)"
	@echo "  make test    — run full pytest suite"
	@echo "  make lint    — ruff check + format check"
	@echo "  make format  — auto-fix formatting with ruff"
	@echo "  make demo    — build the static demo site into site/demo"

setup:
	# --extra dev is required: pytest/ruff/mypy/pre-commit live in the dev
	# extra, and plain `uv sync` uninstalls them from an existing .venv.
	cd $(BACKEND_DIR) && uv sync --extra dev
	cd $(BACKEND_DIR) && uv run pre-commit install
	@echo "✅ Setup complete. Run 'make run' to start the server."

run:
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload --host $(HOST) --port 8000

run-lan:
	$(MAKE) run HOST=0.0.0.0

test:
	cd $(BACKEND_DIR) && uv run pytest tests/ -v

lint:
	cd $(BACKEND_DIR) && uv run ruff check .
	cd $(BACKEND_DIR) && uv run ruff format --check .

format:
	cd $(BACKEND_DIR) && uv run ruff check --fix .
	cd $(BACKEND_DIR) && uv run ruff format .

demo:
	cd $(BACKEND_DIR) && uv run python scripts/build_static_demo.py
	@echo "Preview: python3 -m http.server -d site/demo 8080"
