#!/usr/bin/env bash
set -euo pipefail
cd /opt/darwinx || exit 1
source venv/bin/activate
python scripts/run_payouts.py
