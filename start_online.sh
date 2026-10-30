#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up..."
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
echo "Starting TradeLens and opening it to the internet. Keep this terminal open."
.venv/bin/python online.py
