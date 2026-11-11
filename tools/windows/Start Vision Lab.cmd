@echo off
setlocal
if "%~1"=="" (
    "%~dp0runtime\python.exe" -B -X utf8 -m journey_vision
    pause
) else (
    "%~dp0runtime\python.exe" -B -X utf8 -m journey_vision %*
)
exit /b %ERRORLEVEL%
