@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "PY_EXE="
set "CONDA_ENV="
set "CONDA_CMD="
if exist ".python_for_start_gui.txt" (
  set /p PY_EXE=<".python_for_start_gui.txt"
)
if defined PY_EXE (
  for /f "tokens=1,* delims=:" %%A in ("%PY_EXE%") do (
    if /I "%%A"=="conda" (
      set "CONDA_ENV=%%B"
    )
  )
)
if defined CONDA_ENV (
  set "CONDA_ENV=%CONDA_ENV: =%"
  if "%CONDA_ENV%"=="" set "CONDA_ENV="
)
if not defined PY_EXE (
  if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
  ) else (
    set "PY_EXE=python"
  )
)
if defined CONDA_ENV goto skip_python_path_check
if not exist "%PY_EXE%" (
  if /I "%PY_EXE%"=="python" (
    rem keep as-is
  ) else (
    echo Stored Python path not found: %PY_EXE%
    echo Falling back to system Python.
    set "PY_EXE=python"
  )
)
:skip_python_path_check

echo Starting Smart Transcript GUI (XTTS v2 edition)...
if defined CONDA_ENV (
  where conda >nul 2>&1
  if not errorlevel 1 set "CONDA_CMD=conda"
  if not defined CONDA_CMD if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\miniconda3\Scripts\conda.exe"
  if not defined CONDA_CMD if exist "%USERPROFILE%\MiniConda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\MiniConda3\Scripts\conda.exe"
  if not defined CONDA_CMD if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\anaconda3\Scripts\conda.exe"
  if not defined CONDA_CMD (
    echo Conda command not found in PATH.
    echo Please open Anaconda/Miniconda prompt, or run install.bat again.
    echo Configured env: !CONDA_ENV!
    echo.
    echo GUI exited with an error. Press any key to close.
    pause >nul
    exit /b 1
  )
  echo Using conda: !CONDA_CMD!
  echo Using env: !CONDA_ENV!
  "!CONDA_CMD!" run -n "!CONDA_ENV!" python "transcript.py"
) else (
  "%PY_EXE%" "transcript.py"
)

if errorlevel 1 (
  echo.
  if defined CONDA_ENV (
    "!CONDA_CMD!" run -n "!CONDA_ENV!" python -c "import customtkinter" >nul 2>&1
  ) else (
    "%PY_EXE%" -c "import customtkinter" >nul 2>&1
  )
  if errorlevel 1 (
    echo Hint: customtkinter is missing in this Python environment.
    echo Please run install.bat and use/create a project venv.
    if defined CONDA_ENV (
      echo Current Conda env: !CONDA_ENV!
    ) else (
      echo Current Python: %PY_EXE%
    )
    echo.
  )
  echo GUI exited with an error. Press any key to close.
  pause >nul
)

endlocal
