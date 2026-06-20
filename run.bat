@echo off
title OCR Form Validator - Launcher
cls

echo ==========================================
echo    OCR Form Validator Setup ^& Launcher
echo ==========================================
echo.

:: Pull latest changes from git
where git >nul 2>nul
if %errorlevel% equ 0 (
    echo [SYSTEM] Checking for updates from repository...
    git pull
) else (
    if exist "C:\Program Files\Git\cmd\git.exe" (
        echo [SYSTEM] Checking for updates from repository (using absolute Git path)...
        "C:\Program Files\Git\cmd\git.exe" pull
    ) else (
        echo [WARNING] Git not found in PATH or standard location. Skipping auto-update.
    )
)
echo.

:: Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [SYSTEM] Python is not installed or not in PATH.
    echo [SYSTEM] Attempting to install Python 3.11 automatically via winget...
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo [ERROR] winget installation failed.
        echo Opening Python download page...
        start https://www.python.org/downloads/
        echo.
        echo Please install Python manually. Make sure to check "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
    echo [SUCCESS] Python has been installed successfully!
    echo.
    echo CRITICAL: Please close this window and double-click run.bat again to continue the setup.
    pause
    exit /b 0
)

:: Check for Node.js
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [SYSTEM] Node.js is not installed or not in PATH.
    echo [SYSTEM] Attempting to install Node.js LTS automatically via winget...
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo [ERROR] winget installation failed.
        echo Opening Node.js download page...
        start https://nodejs.org/
        echo.
        echo Please install Node.js manually and run this script again.
        pause
        exit /b 1
    )
    echo [SUCCESS] Node.js has been installed successfully!
    echo.
    echo CRITICAL: Please close this window and double-click run.bat again to continue the setup.
    pause
    exit /b 0
)

:: Python and Node.js are present, continue setup
echo [SYSTEM] Python and Node.js detected. Proceeding with setup...
echo.

:: Setup backend
if not exist "backend\.venv" (
    echo [SYSTEM] Creating Python virtual environment in backend\.venv...
    python -m venv backend\.venv
)

echo [SYSTEM] Installing/updating backend Python dependencies...
call backend\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
call deactivate
echo [SUCCESS] Backend libraries are ready.
echo.

:: Setup frontend
if not exist "frontend\node_modules" (
    echo [SYSTEM] Installing frontend package dependencies (this may take a minute)...
    cd frontend
    call npm install
    cd ..
) else (
    echo [SYSTEM] Frontend dependencies already installed. Skipping.
)
echo.

:: Start services
echo [SYSTEM] Starting services...
echo.

:: Launch FastAPI Backend in a new minimized/normal window
echo [SYSTEM] Launching OCR Backend...
start "OCR Backend" cmd /c "cd backend && call .venv\Scripts\activate.bat && uvicorn main:app --reload --host 0.0.0.0 --port 8000"

:: Launch Vite Frontend in a new window
echo [SYSTEM] Launching Frontend Interface...
start "OCR Frontend" cmd /c "cd frontend && npm run dev"

echo.
echo [SYSTEM] Waiting for services to initialize...
timeout /t 5 >nul

echo [SYSTEM] Launching application in web browser...
start http://localhost:5173/

echo.
echo ==========================================
echo    App is running!
echo    - Frontend: http://localhost:5173
echo    - Backend API Docs: http://localhost:8000/docs
echo.
echo    Keep this launcher window open if you want, 
echo    or you can close it. To stop the application,
echo    close the backend and frontend command windows.
echo ==========================================
pause
