@echo off
echo ============================================
echo  Fucking Fast Downloader - Setup
echo ============================================
echo.

echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: pip install failed. Make sure Python is installed and in PATH.
    pause
    exit /b 1
)

echo.
echo [2/3] Installing Playwright...
pip install playwright
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Playwright install failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Downloading Chromium browser for Playwright...
playwright install chromium
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Chromium download failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Setup complete! Run: python main.py
echo ============================================
pause
