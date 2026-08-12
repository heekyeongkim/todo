@echo off
rem HWPX generator launcher - double-click to run (Windows)
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install from https://python.org ^(check "Add to PATH"^).
  pause
  exit /b 1
)

if not exist ".deps_installed" (
  echo Installing packages ^(first run only^)...
  python -m pip install -r requirements.txt -q && echo ok > .deps_installed
)

if "%GEMINI_API_KEY%"=="" (
  if exist "gemini_api_key.txt" (
    set /p GEMINI_API_KEY=<gemini_api_key.txt
  ) else (
    echo.
    echo Gemini API key needed ^(free^): https://aistudio.google.com/apikey
    set /p GEMINI_API_KEY=Paste API key here:
    echo %GEMINI_API_KEY%> gemini_api_key.txt
  )
)

start "" http://127.0.0.1:8765
python server.py
pause
