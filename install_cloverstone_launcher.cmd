@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_cloverstone_launcher.ps1"
if errorlevel 1 (
  echo.
  echo Cloverstone could not be connected to Journey.
  pause
  exit /b 1
)
echo.
echo Done. Click the green Cloverstone badge to open Journey.
pause
