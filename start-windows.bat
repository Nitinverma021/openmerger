@echo off
setlocal
cd /d "%~dp0"

if not exist .venv-windows (
    py -3 -m venv .venv-windows
)

call .venv-windows\Scripts\activate.bat
pip install -r requirements.txt
python run.py

