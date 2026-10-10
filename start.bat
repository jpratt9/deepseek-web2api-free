@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title DeepSeek Chat API Proxy Server

:: ============================================================
::  0. Default config (override with the PORT / HOST env vars)
:: ============================================================
if "%PORT%"=="" set "PORT=8080"
if "%HOST%"=="" set "HOST=127.0.0.1"
set "REQ=requirements.txt"

echo ==================================================
echo    DeepSeek Chat API Proxy launcher
echo    HOST=%HOST%    PORT=%PORT%
echo ==================================================
echo.

if not exist ".env" (
    if not exist ".env.example" (
        echo [ERROR] No .env or .env.example found; cannot create a config file.
        pause
        exit /b 1
    )
    copy /Y ".env.example" ".env" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Could not copy .env.example to .env; check directory write permissions.
        pause
        exit /b 1
    )
    echo [CONFIG] No .env found; created it from .env.example.
) else (
    echo [CONFIG] .env detected; keeping the existing config.
)
echo.

:: ============================================================
::  1. Locate system Python (needs 3.10+)
:: ============================================================
set "PYTHON="
where python >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON where py >nul 2>&1 && set "PYTHON=py"
if not defined PYTHON goto :no_python
"%PYTHON%" --version >nul 2>&1 || goto :no_python
"%PYTHON%" -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 || goto :old_python
for /f "tokens=*" %%v in ('"%PYTHON%" --version 2^>^&1') do set "PYVER=%%v"
echo [1/6] System Python: !PYVER!
echo.

:: ============================================================
::  2. Find or create a virtualenv (prefers .venv, then venv / env)
:: ============================================================
set "VENV="
if exist ".venv\Scripts\python.exe" set "VENV=.venv"
if not defined VENV if exist "venv\Scripts\python.exe" set "VENV=venv"
if not defined VENV if exist "env\Scripts\python.exe" set "VENV=env"
if defined VENV (
    echo [2/6] Virtualenv detected: %VENV%
) else (
    echo [2/6] No virtualenv found; creating .venv ...
    "%PYTHON%" -m venv .venv
    if errorlevel 1 (
        echo        Failed to create .venv; trying venv ...
        "%PYTHON%" -m venv venv
        if errorlevel 1 goto :venv_failed
        set "VENV=venv"
    ) else (
        set "VENV=.venv"
    )
    echo        Virtualenv created: !VENV!
)
set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" goto :venv_failed
echo.

:: ============================================================
::  3. Verify dependencies (auto-install if missing)
:: ============================================================
set "CHK=%TEMP%\ds2api_pipchk_%RANDOM%.txt"
echo [3/6] Verifying dependencies in %VENV% ...
"%PY%" -m pip install --dry-run -r "%REQ%" > "%CHK%" 2>&1
set "DRY_RC=!errorlevel!"
findstr /i "would install" "%CHK%" >nul 2>&1
set "NEED=!errorlevel!"
del "%CHK%" >nul 2>&1
if !DRY_RC! equ 0 if !NEED! equ 1 (
    echo        All dependencies present; skipping install.
) else (
    echo        Dependencies missing or verification failed; installing ...
    if !DRY_RC! neq 0 echo        (pip verification failed -- may be offline or pip is too old; installing directly)
    "%PY%" -m pip install --upgrade pip >nul 2>&1
    "%PY%" -m pip install -r "%REQ%"
    if errorlevel 1 goto :deps_failed
    echo        Dependency install complete.
)
echo.

:: ============================================================
::  4. Build WebUI (v3.0.0 React account-pool admin panel)
:: ============================================================
set "WEBUI_DIR=webui-new"
set "WEBUI_DIST=%WEBUI_DIR%\dist"
set "NEED_BUILD=1"
if exist "%WEBUI_DIST%\index.html" if not defined WEBUI_REBUILD set "NEED_BUILD=0"
echo [4/6] Checking WebUI build artifacts ...
if "!NEED_BUILD!"=="0" (
    echo        WebUI already built; skipping build (to force a rebuild, run: set WEBUI_REBUILD=1).
) else (
    if defined WEBUI_REBUILD (
        echo        WEBUI_REBUILD detected; forcing a rebuild ...
    ) else (
        echo        No build artifacts found; starting build ...
    )
    where node >nul 2>&1
    if errorlevel 1 (
        echo        [WARN] node/npm not found; cannot build the WebUI.
        echo        Starting the backend API only; run %WEBUI_DIR%\scripts\build.bat later to build manually.
    ) else (
        pushd "%WEBUI_DIR%"
        call scripts\build.bat
        set "BUILD_RC=!errorlevel!"
        popd
        if !BUILD_RC! neq 0 (
            echo        [WARN] WebUI build failed; starting the backend API only.
            echo        Run %WEBUI_DIR%\scripts\build.bat later to retry.
        ) else (
            echo        WebUI build complete: %WEBUI_DIST%
        )
    )
)
echo.
:: ============================================================
::  5. Free the port (only kill this project's own processes, never others)
:: ============================================================
echo [5/6] Checking port %PORT% ...
set "BLOCKED="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    set "PID=%%a"
    set "CMDLINE="
    for /f "usebackq tokens=*" %%c in (`powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=%%a').CommandLine" 2^>nul`) do set "CMDLINE=%%c"
    if defined CMDLINE (
        echo        Port %PORT% held by PID !PID!, command line: !CMDLINE!
        echo !CMDLINE! | findstr /i "uvicorn server:app server.py ds2api" >nul
        if !errorlevel! equ 0 (
            echo        This project's process; terminating it ...
            taskkill /F /PID !PID! >nul 2>&1
            if !errorlevel! neq 0 taskkill /F /T /PID !PID! >nul 2>&1
            ping -n 2 127.0.0.1 >nul
        ) else (
            echo        Process unrelated to this project; refusing to terminate it.
            set "BLOCKED=1"
        )
    ) else (
        echo        Port %PORT% held by PID !PID!, but its command line can't be read; refusing to auto-terminate.
        set "BLOCKED=1"
    )
)
if defined BLOCKED (
    echo.
    echo   ============================================================
    echo   Port %PORT% is held by another process that isn't this service.
    echo   Free the port yourself, or start on a different port:
    echo       set PORT=9090 ^&^& start.bat
    echo   ============================================================
    echo.
    pause
    exit /b 1
)
echo.

:: ============================================================
::  6. Start the service
:: ============================================================
echo [6/6] Starting the service %HOST%:%PORT% ...
echo.
:: Bind address: 0.0.0.0 / :: is the listen address; browsers should use 127.0.0.1
set "ACCESS_HOST=%HOST%"
if "%ACCESS_HOST%"=="0.0.0.0" set "ACCESS_HOST=127.0.0.1"
echo.
echo   ============================================================
echo   Once started, the service is reachable at:
echo      WebUI admin panel:  http://%ACCESS_HOST%:%PORT%/webui/
echo      OpenAI API:      http://%ACCESS_HOST%:%PORT%/v1/chat/completions
echo      Health check:       http://%ACCESS_HOST%:%PORT%/health
"%PY%" -c "import os; from dotenv import load_dotenv; load_dotenv('.env'); print('  Admin password: ' + os.environ.get('DEEPSEEK_ADMIN_PASSWORD', 'admin'))"
echo   ============================================================
echo.
if not "%WEBUI_OPEN%"=="0" (
    echo   Opening the browser in 3 seconds (to skip, run: set WEBUI_OPEN=0)
    start "" powershell -NoProfile -Command "Start-Sleep -Seconds 3; Start-Process 'http://%ACCESS_HOST%:%PORT%/webui/'"
) else (
    echo   Skipped opening the browser (WEBUI_OPEN=0).
)
echo.
"%PY%" -m uvicorn server:app --host %HOST% --port %PORT%
if errorlevel 1 (
    echo.
    echo   The service exited abnormally; check the log above.
    pause
)
exit /b %errorlevel%

:: ---------- Error handling ----------
:no_python
echo.
echo [ERROR] Python 3.10+ not found (tried "python" and "py").
echo        Install it from https://www.python.org/downloads/ and add it to PATH.
pause
exit /b 1

:old_python
echo.
echo [ERROR] Python 3.10+ required, current version:
"%PYTHON%" --version
pause
exit /b 1

:venv_failed
echo.
echo [ERROR] Failed to create/use the virtualenv.
echo        Run manually: "%PYTHON%" -m venv .venv
pause
exit /b 1

:deps_failed
echo.
echo [ERROR] Dependency install failed; check the log above.
echo        Run manually: "%PY%" -m pip install -r "%REQ%"
pause
exit /b 1
