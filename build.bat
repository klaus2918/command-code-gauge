@echo off
REM CCGauge build script: bundle a single-file Windows executable with PyInstaller.
REM Output: dist\CCGauge.exe  (data is stored next to the exe in .\data\)
setlocal

cd /d "%~dp0"

echo [1/3] Generating icon...
python scripts\build_icon.py || goto :error

echo [2/3] Running PyInstaller...
python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name CCGauge ^
  --icon assets\CCGauge.ico ^
  --add-data "app\web;app\web" ^
  --add-data "assets;assets" ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import pystray._win32 ^
  --collect-submodules webview ^
  entry.py || goto :error

echo [3/3] Done. Output: dist\CCGauge.exe
goto :eof

:error
echo Build failed with errorlevel %errorlevel%.
exit /b %errorlevel%
