@echo off
rem Windows: double-click this file
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
start "" http://localhost:5000
python app.py
pause
