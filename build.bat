@echo off
REM CCGauge build script.
REM   [1/4] generate icon
REM   [2/4] PyInstaller single-file exe  -> dist\CCGauge.exe
REM   [3/4] Inno Setup installer         -> dist\CCGauge-v<ver>-setup.exe
REM   [4/4] summary
REM Version comes from app\__init__.py (single source) and is injected into iscc.
setlocal

cd /d "%~dp0"

REM --- interpreter probe: python first, fall back to the py launcher ---
set "PY=python"
where python >nul 2>&1 || set "PY=py -3"

echo ========================================
echo  CCGauge Build
echo ========================================

echo.
echo [1/4] Generating icon...
%PY% scripts\build_icon.py || goto :error

echo.
echo [2/4] Running PyInstaller...
%PY% -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name CCGauge ^
  --icon assets\CCGauge.ico ^
  --add-data "app\web;app\web" ^
  --add-data "assets;assets" ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import pystray._win32 ^
  --collect-submodules webview ^
  entry.py || goto :error

REM --- version: single source of truth = app\__init__.py ---
for /f "usebackq delims=" %%v in (`%PY% scripts\read_version.py`) do set "APPVER=%%v"
if not defined APPVER (
  echo [WARN] Cannot read version from app\__init__.py
  set "APPVER=0.0.0-dev"
)
echo     version = %APPVER%

echo.
echo [3/4] Building installer (Inno Setup)...
where iscc >nul 2>&1
if errorlevel 1 (
  echo [WARN] iscc.exe not found - skipping installer.
  echo [WARN] Install Inno Setup first:
  echo [WARN]   choco install innosetup -y
  echo [WARN]   or https://jrsoftware.org/isdl.php
  echo [WARN] then re-run build.bat, or compile manually:
  echo [WARN]   iscc /DMyAppVersion=%APPVER% CCGauge.iss
  goto :portable
)
iscc /DMyAppVersion=%APPVER% CCGauge.iss || goto :error

echo.
echo [4/4] Done.
echo.
echo ========================================
echo  Output:
echo    dist\CCGauge.exe                 (portable)
echo    dist\CCGauge-v%APPVER%-setup.exe (installer)
echo ========================================
goto :eof

:portable
echo.
echo [4/4] Done (portable only).
echo    dist\CCGauge.exe
goto :eof

:error
echo.
echo Build failed with errorlevel %errorlevel%.
exit /b %errorlevel%
