@echo off
title Oil Godown Inventory
cd /d "%~dp0"

echo ============================================================
echo   Oil Godown Inventory
echo   Keep THIS window open while you use the app.
echo   To stop the app, just close this window.
echo ============================================================
echo.

REM --- Check that Python is installed ---
python --version >nul 2>nul
if errorlevel 1 (
    echo Python is not installed on this computer.
    echo.
    echo Please install it from:  https://www.python.org/downloads
    echo IMPORTANT: On the first install screen, tick the box
    echo            "Add python.exe to PATH", then run this file again.
    echo.
    pause
    exit /b
)

REM --- Skip Streamlit's first-run email prompt ---
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

REM --- Install required packages the first time only ---
python -c "import streamlit, pandas, sqlalchemy" 2>nul
if errorlevel 1 (
    echo First-time setup: installing required packages. This may take a minute...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    echo.
)

echo Starting the app. Your web browser will open in a moment...
echo.
python -m streamlit run app.py

pause
