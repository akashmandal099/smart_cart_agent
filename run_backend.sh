#!/bin/bash
set -e  # stop on first error

# ── 1. Copy .env only if it doesn't already exist ─────────────────────────
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "✅ Created .env from .env.example"
  else
    echo "⚠️  No .env or .env.example found — continuing with defaults"
  fi
else
  echo "✅ .env already exists — skipping copy"
fi

# ── 2. Install / sync dependencies ────────────────────────────────────────
uv sync --group dev

# ── 3. Install Playwright browser ─────────────────────────────────────────
uv run playwright install chromium

# ── 4. Run the app ────────────────────────────────────────────────────────
uv run python -m main