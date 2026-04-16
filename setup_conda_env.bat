@echo off
setlocal EnableExtensions

rem ---------------------------------------------------------------------------
rem SmartTranscript XTTS v2 - Conda environment helper (English only)
rem
rem What it does:
rem   1) Checks that "conda" is available on PATH
rem   2) Creates (or updates) a conda env with Python 3.11
rem   3) Installs Python dependencies from requirements.txt next to this script
rem
rem Notes:
rem   - This script does NOT download Miniconda automatically.
rem   - If conda is missing, install Miniconda/Anaconda first, then re-run.
rem   - GPU acceleration requires a separate PyTorch CUDA install step
rem     (not handled here to keep this script simple and reliable).
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

rem Default env name (unique). Override without editing:
rem   set SMARTTRANSCRIPT_CONDA_ENV=myenv
rem   setup_conda_env.bat
set "ENV_NAME=xtts"
if not "%SMARTTRANSCRIPT_CONDA_ENV%"=="" set "ENV_NAME=%SMARTTRANSCRIPT_CONDA_ENV%"
set "PY_VER=3.11"
set "REQ_FILE=%~dp0requirements.txt"

echo.
echo === SmartTranscript XTTS v2 - Conda environment setup ===
echo Environment name: %ENV_NAME%
echo Python version  : %PY_VER%
echo Requirements    : %REQ_FILE%
echo.

where conda >nul 2>&1
if errorlevel 1 (
  echo [ERROR] "conda" was not found on PATH.
  echo.
  echo Please install Miniconda or Anaconda for Windows, then open
  echo "Anaconda Prompt" or "Miniconda Prompt" and run this script again.
  echo.
  echo Official Miniconda downloads:
  echo   https://docs.conda.io/en/latest/miniconda.html
  echo.
  pause
  exit /b 1
)

if not exist "%REQ_FILE%" (
  echo [ERROR] requirements.txt not found next to this script:
  echo   %REQ_FILE%
  echo.
  pause
  exit /b 1
)

echo [INFO] Ensuring conda channels are configured (fixes NoChannelsConfiguredError)...
rem If the user has an empty/broken channel list, conda cannot install python.
call conda config --append channels defaults >nul 2>&1
call conda config --append channels conda-forge >nul 2>&1

echo [INFO] Creating conda environment (if it already exists, this may take a moment)...
call conda create -n "%ENV_NAME%" python=%PY_VER% -y
if errorlevel 1 (
  echo [ERROR] conda create failed.
  pause
  exit /b 1
)

echo.
echo [INFO] Upgrading pip inside the environment...
call conda run -n "%ENV_NAME%" python -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] pip upgrade failed.
  pause
  exit /b 1
)

echo.
echo [INFO] Installing dependencies from requirements.txt ...
call conda run -n "%ENV_NAME%" python -m pip install -r "%REQ_FILE%"
if errorlevel 1 (
  echo [ERROR] pip install -r requirements.txt failed.
  pause
  exit /b 1
)

echo.
echo === DONE ===
echo Conda environment "%ENV_NAME%" is ready.
echo.
echo Next steps in the app (Tab 5 - Voice Export):
echo   - Runtime: choose "conda_env"
echo   - Environment name: %ENV_NAME%
echo.
echo NOTE:
echo   This script installs the dependencies listed in requirements.txt.
echo   If you need GPU-accelerated PyTorch, install the matching CUDA build
echo   manually into this environment (see PyTorch "Get Started" page).
echo.
pause
endlocal
