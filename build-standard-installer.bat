@echo off
setlocal
cd /d "%~dp0"

call build-windows.bat --non-interactive
if errorlevel 1 exit /b 1

if exist "dist\OpenMerger\engine" rmdir /s /q "dist\OpenMerger\engine"
> "dist\OpenMerger\edition.json" echo {"edition":"standard"}

set "ISCC=ISCC.exe"
where ISCC.exe >nul 2>nul
if errorlevel 1 set "ISCC=%~dp0tools\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup is required. Install it, then run this script again.
    exit /b 1
)

"%ISCC%" "installer\OpenMerger-Standard.iss"
