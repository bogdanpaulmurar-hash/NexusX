@echo off
cd /d "%~dp0"
echo Instalare dependinte NexusX...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
echo.
echo Gata. Porneste cu run_NexusX.bat
pause
