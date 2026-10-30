#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up..."
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
.venv/bin/python run.py
