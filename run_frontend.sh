#!/bin/bash
set -e

MODE=${1:-streamlit}

if [ "$MODE" = "streamlit" ]; then
  uv run streamlit run frontend/streamlit_app.py --server.port 8501
elif [ "$MODE" = "gradio" ]; then
  uv run python frontend/gradio_app.py
else
  echo "Usage: ./run_frontend.sh [streamlit|gradio]"
  exit 1
fi