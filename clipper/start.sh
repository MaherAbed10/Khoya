#!/usr/bin/env bash
# Mac / Linux: double-click or run ./start.sh
set -e
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -r requirements.txt
( sleep 2; (open http://localhost:5000 || xdg-open http://localhost:5000) >/dev/null 2>&1 ) &
python app.py
