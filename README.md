# SmartCart AI — Backend

AI-powered product price comparison with offer intelligence across Amazon India & Flipkart.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — install via: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Quickstart

```bash
# 1. Clone / enter project directory
cd smartcart/backend

# 2. Create virtual env + install all dependencies (one command)
uv sync

# 3. Install Playwright browser
uv run playwright install chromium

# 4. Configure environment
cp .env.example .env
# → edit .env and set OPENAI_API_KEY=sk-...

# 5. Run the server
uv run python -m backend.main
# or with auto-reload for development:
uv run uvicorn backend.main:app --reload --port 8000
```

Server starts at: http://localhost:8000
API docs at:      http://localhost:8000/docs

## Makefile shortcuts

```bash
make install       # uv sync (production deps only)
make install-dev   # uv sync --dev (includes pytest, ruff, mypy)
make dev           # uvicorn with --reload
make lint          # ruff check
make format        # ruff format
make typecheck     # mypy
make test          # pytest
make clean         # remove .venv, caches
```

## Adding a new dependency

```bash
uv add <package>             # adds to [project.dependencies]
uv add --dev <package>       # adds to [tool.uv.dev-dependencies]
uv remove <package>          # removes a dependency
```

## Project Structure

```
backend/
├── main.py               FastAPI app entrypoint
├── pyproject.toml        uv / project config (replaces requirements.txt)
├── .python-version       pins Python 3.11 for uv
├── .env.example          environment variable template
├── Makefile              developer shortcuts
├── config/               settings (pydantic-settings)
├── models/               Pydantic data models + PriceGraph DAG
├── cache/                TTL cache (cachetools)
├── scrapers/             Playwright scrapers (Amazon + Flipkart)
├── agents/               LangGraph nodes + graph wiring
├── api/                  FastAPI routes
└── utils/                shared helpers
```
