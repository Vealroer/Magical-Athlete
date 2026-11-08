@echo off
setlocal
cd /d "%~dp0"
set "GAME_PYTHON=.venv\Scripts\python.exe"
if not exist "%GAME_PYTHON%" (
    echo Set up the Python environment first. See README.md.
    pause
    exit /b 1
)
"%GAME_PYTHON%" -c "import ssl" >nul 2>nul
if not errorlevel 1 goto launch
rem Some portable Windows runtimes load OpenSSL only via their base executable.
for /f "usebackq tokens=1,* delims==" %%A in (".venv\pyvenv.cfg") do if "%%A"=="executable " set "GAME_BASE=%%B"
if not defined GAME_BASE exit /b 1
set "GAME_PYTHON=%GAME_BASE:~1%"
set "PYTHONPATH=%CD%\.venv\Lib\site-packages"
:launch
echo Open http://127.0.0.1:8000 on this PC, or use its LAN IP on another device.
"%GAME_PYTHON%" -m uvicorn server:app --host 0.0.0.0 --port 8000 --workers 1 --ws websockets-sansio
if errorlevel 1 pause
