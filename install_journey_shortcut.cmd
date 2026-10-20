@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_journey_shortcut.ps1"
if errorlevel 1 (
  echo.
  echo Journey could not create the desktop shortcut.
  echo Review the message above, then press any key to close this window.
  pause >nul
  exit /b 1
)

echo.
echo You can close this window or press any key.
pause >nul
