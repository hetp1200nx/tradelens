@echo off
title TradeLens online
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting up...
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
if not exist .env copy .env.example .env
echo Starting TradeLens and opening it to the internet. Keep this window open.
.venv\Scripts\python online.py
pause
