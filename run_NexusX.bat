@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw -m nexusx %*
) else (
  python -m nexusx %*
)
