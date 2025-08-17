#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn
exec uvicorn app:app --host 127.0.0.1 --port 8080
