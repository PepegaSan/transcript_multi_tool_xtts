@echo off
setlocal EnableExtensions

rem ---------------------------------------------------------------------------
rem SmartTranscript XTTS v2 - Optional PyTorch CUDA install (English only)
rem
rem What it does:
rem   1) Checks that conda is available on PATH
rem   2) Best-effort check for NVIDIA tooling via nvidia-smi
rem   3) Installs torch + torchvision + torchaudio from PyTorch wheel index
rem
rem Notes:
rem   - Default CUDA tag is cu124 (override with TORCH_CUDA_TAG=cu121 etc.)
rem   - This does not guarantee GPU works on every machine/driver combo.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

set "ENV_NAME=xtts"
if not "%SMARTTRANSCRIPT_CONDA_ENV%"=="" set "ENV_NAME=%SMARTTRANSCRIPT_CONDA_ENV%"

set "CUDA_TAG=cu124"
if not "%TORCH_CUDA_TAG%"=="" set "CUDA_TAG=%TORCH_CUDA_TAG%"

set "TORCH_INDEX=https://download.pytorch.org/whl/%CUDA_TAG%"

echo.
echo === SmartTranscript XTTS v2 - PyTorch CUDA install (optional) ===
echo Conda environment = %ENV_NAME%
echo CUDA wheel tag    = %CUDA_TAG%
echo PyTorch index     = %TORCH_INDEX%
echo.

where conda >nul 2>&1
if errorlevel 1 (
  echo [ERROR] conda not found on PATH.
  echo Install Miniconda/Anaconda, then run from "Anaconda Prompt".
  echo https://docs.conda.io/en/latest/miniconda.html
  echo.
  pause
  exit /b 1
)

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo [WARNING] nvidia-smi not found. GPU acceleration may not work.
  set "CONTINUE="
  set /p CONTINUE="Continue anyway? (y/N): "
  if /I not "%CONTINUE%"=="y" (
    echo [INFO] Aborted by user.
    exit /b 1
  )
)

echo [INFO] Checking conda environment "%ENV_NAME%" ...
call conda run -n "%ENV_NAME%" python -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Conda environment "%ENV_NAME%" missing or broken.
  echo Run setup_conda_env.bat first.
  echo.
  pause
  exit /b 1
)

echo.
echo [INFO] Installing PyTorch CUDA wheels...
call conda run -n "%ENV_NAME%" python -m pip install --upgrade torch torchvision torchaudio --index-url "%TORCH_INDEX%"
if errorlevel 1 (
  echo [ERROR] PyTorch CUDA install failed.
  echo.
  pause
  exit /b 1
)

echo.
echo === DONE ===
echo Installed PyTorch CUDA wheels (tag=%CUDA_TAG%) into "%ENV_NAME%".
echo.
echo Quick check:
echo   conda run -n "%ENV_NAME%" python -c "import torch; print(torch.__version__); print('cuda_available=', torch.cuda.is_available())"
echo.
pause
endlocal
