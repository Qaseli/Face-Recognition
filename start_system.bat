@echo off
echo ============================================
echo  Facial Recognition Attendance System
echo ============================================
echo.

cd /d "%~dp0"

REM Use the virtual environment's Python directly
if exist "venv\Scripts\python.exe" (
    echo Starting server with virtual environment...
    echo.
    echo Dashboard: http://localhost:5000
    echo Press Ctrl+C to stop.
    echo.
    venv\Scripts\python.exe server.py
    pause
) else (
    echo ERROR: Virtual environment not found!
    echo Please create it first: python -m venv venv
    echo Then install dependencies: venv\Scripts\pip install -r requirements.txt
    pause
)
