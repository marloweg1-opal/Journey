@echo off
setlocal

set "JOURNEY_HOME=%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%JOURNEY_HOME%ark.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%JOURNEY_HOME%ark.py" %*
  exit /b %ERRORLEVEL%
)

if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
  "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" "%JOURNEY_HOME%ark.py" %*
  exit /b %ERRORLEVEL%
)

echo Journey could not find Python 3.
echo Install Python 3 or make the py/python command available on PATH.
exit /b 1
