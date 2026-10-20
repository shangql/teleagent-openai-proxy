@echo off
REM ============================================================
REM  TeleAgent OpenAI-Compatible Proxy - Windows launcher
REM ============================================================
REM  Usage:
REM    start_proxy.cmd                 start on 127.0.0.1:8088
REM    start_proxy.cmd 0.0.0.0 8088    custom listen address / port
REM
REM  NOTE: this file is intentionally ASCII-only so that it runs
REM  correctly under any Windows console code page (GBK/UTF-8).
REM ============================================================
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROXY_SCRIPT=%SCRIPT_DIR%openai_proxy.py"

REM ---- arguments ----
set "HOST=127.0.0.1"
set "PORT=8088"
if not "%~1"=="" set "HOST=%~1"
if not "%~2"=="" set "PORT=%~2"

REM ---- locate python interpreter ----
REM  priority: bundled TeleAgent runtime > python.exe on PATH
set "PY="
set "TELEAGENT_PY=%USERPROFILE%\.local\share\TeleAgent\runtimes\python\python.exe"
if exist "%TELEAGENT_PY%" set "PY=%TELEAGENT_PY%"

if not defined PY (
    for %%I in (python.exe) do (
        if not defined PY if not "%%~$PATH:I"=="" set "PY=%%~$PATH:I"
    )
)

if not defined PY (
    echo [ERROR] Python interpreter not found.
    echo   Install Python 3.8+ and add it to PATH, or make sure the
    echo   TeleAgent runtime exists at: %TELEAGENT_PY%
    exit /b 1
)

echo [INFO] Python     : %PY%
echo [INFO] Proxy      : %PROXY_SCRIPT%
echo [INFO] Listen     : %HOST%:%PORT%
echo [INFO] API Base   : http://%HOST%:%PORT%/v1
echo [INFO] Console    : http://%HOST%:%PORT%/console
echo.

REM ---- preflight: is TeleAgent (super-agent on 4397) running? ----
netstat -ano | findstr ":4397" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [WARN] No listener on 127.0.0.1:4397.
    echo        Start the TeleAgent desktop app first, otherwise the
    echo        proxy cannot obtain the super-agent session key.
    echo.
)

REM ---- run ----
"%PY%" "%PROXY_SCRIPT%" --host %HOST% --port %PORT%
endlocal
