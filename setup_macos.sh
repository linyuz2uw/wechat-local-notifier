#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Setup complete."
echo "Run:"
echo "  source .venv/bin/activate"
echo "  python wechat_local_notifier.py --debug-state"
