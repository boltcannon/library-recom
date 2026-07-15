@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

if not defined PORT set "PORT=8501"

echo Starting StoryShelf locally...
echo.
echo App URL: http://localhost:%PORT%
echo Press Ctrl+C in this window to stop the app.
echo.

"%PYTHON_EXE%" -m streamlit run app.py --server.address=127.0.0.1 --server.port=%PORT%

if errorlevel 1 (
    echo.
    echo StoryShelf could not start.
    echo Make sure Python and dependencies are installed:
    echo   pip install -r requirements.txt
    echo.
    pause
)

endlocal
