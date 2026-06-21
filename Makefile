# SmartCart AI — developer shortcuts using uv
.PHONY: install install-dev run dev lint format typecheck test clean

install:
	uv sync

install-dev:
	uv sync --dev

run:
	uv run python -m backend.main

dev:
	uv run uvicorn main:app --reload --port 8000

playwright:
	uv run playwright install chromium

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy backend/

test:
	uv run pytest -v

clean:
	rm -rf .venv __pycache__ .ruff_cache .mypy_cache dist
