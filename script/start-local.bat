@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM  pdf2zh local launcher (no Docker required)
REM
REM  Creates a Python 3.12 virtualenv in .venv, installs the project into it,
REM  then starts the Gradio web UI at http://127.0.0.1:7860/
REM
REM  Double-click this file, or run it from a terminal.
REM  Requires only that `uv` is on PATH (https://docs.astral.sh/uv/).
REM ============================================================================

cd /d "%~dp0.."

set VENV_DIR=.venv
set PY_VERSION=3.12

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] `uv` was not found on PATH.
    echo         Install it from https://docs.astral.sh/uv/ and run this script again.
    pause
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/2] Creating Python %PY_VERSION% virtualenv in %VENV_DIR% ...
    uv venv --python %PY_VERSION% "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtualenv.
        pause
        exit /b 1
    )
    echo [2/2] Installing pdf2zh and its dependencies ^(this may take a few minutes^) ...
    uv pip install --python "%VENV_DIR%" -e .
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo [ok] Reusing existing virtualenv at %VENV_DIR%
)

echo.
echo Starting the web UI at http://127.0.0.1:7860/  ^(Ctrl+C to stop^)
echo.
"%VENV_DIR%\Scripts\python.exe" -m pdf2zh.pdf2zh -i

pause
