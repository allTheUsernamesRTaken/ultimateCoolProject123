@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 (
  echo.
  echo The dashboard did not start. Check the message above.
  pause
)
