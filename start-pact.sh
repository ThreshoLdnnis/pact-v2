#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 scripts/bootstrap.py
exec .venv/bin/python -m uvicorn pact.app:create_app --factory --host 127.0.0.1 --port 8000
