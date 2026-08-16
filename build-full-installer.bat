@echo off
setlocal
cd /d "%~dp0"

if not exist "third_party\LibreOffice\program\soffice.exe" (
    echo Missing LibreOffice runtime.
    echo Place it at third_party\LibreOffice\program\soffice.exe, then run this again.
    exit /b 1
)

call build-windows.bat --non-interactive
if errorlevel 1 exit /b 1

if exist "dist\OpenMerger\engine\LibreOffice" rmdir /s /q "dist\OpenMerger\engine\LibreOffice"
mkdir "dist\OpenMerger\engine"
xcopy /e /i /y "third_party\LibreOffice" "dist\OpenMerger\engine\LibreOffice" >nul
> "dist\OpenMerger\edition.json" echo {"edition":"full"}

set "ISCC=ISCC.exe"
where ISCC.exe >nul 2>nul
if errorlevel 1 set "ISCC=%~dp0tools\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup is required. Install it, then run this script again.
    exit /b 1
)

"%ISCC%" "installer\OpenMerger-Full.iss"
