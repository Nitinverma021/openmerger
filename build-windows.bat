@echo off
setlocal
cd /d "%~dp0"

if not exist .venv-windows (
    py -3 -m venv .venv-windows
)

call .venv-windows\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-build.txt

pyinstaller --noconfirm --clean OpenMerger-Windows.spec

echo.
echo Build complete:
echo dist\OpenMerger\OpenMerger.exe
if /i not "%~1"=="--non-interactive" pause
