@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Tab 5 (Coqui XTTS) is always installed when dependencies succeed.
set "USE_TTS=Y"

echo Smart Transcript — XTTS v2 edition.
echo.
echo Python: use **3.11 or 3.10** ^(Coqui TTS / Whisper are not tested on older Python here^).
echo.
echo Where should packages be installed?
echo   1^) New **venv** in this folder ^(recommended; needs `py -3.11` or `py -3.10` from python.org^)
echo   2^) **Conda** environment ^(`conda` must work on PATH^)
echo   3^) **`python` from PATH** ^(no new venv; first `python` on PATH must be 3.11 or 3.10^)
echo.
set /p RUNTIME_CHOICE=Choose 1, 2 or 3 [default 1]: 
if not defined RUNTIME_CHOICE set "RUNTIME_CHOICE=1"

if "%RUNTIME_CHOICE%"=="2" goto conda_mode
if "%RUNTIME_CHOICE%"=="3" goto path_python_mode
goto venv_mode

:path_python_mode
set "VENV_DIR="
echo.
echo [PATH] Detecting first `python` on PATH...
where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: No `python` on PATH. Install Python 3.11/3.10 or pick option 1 or 2.
  goto fail
)
set "PY_EXE="
for /f "delims=" %%A in ('where python') do (
  set "PY_EXE=%%A"
  goto path_have_exe
)
:path_have_exe
echo Using: "%PY_EXE%"
"%PY_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,10),(3,11)) else 1)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: PATH python must be 3.10 or 3.11. Run:  python --version
  goto fail
)
for /f "usebackq delims=" %%V in (`"%PY_EXE%" -c "import sys; print('%%d.%%d' %% (sys.version_info.major, sys.version_info.minor))"`) do set "RUNTIME_PY_VER=%%V"
echo OK: Python %RUNTIME_PY_VER%
set "START_MODE=PYTHON"
goto install_requirements

:venv_mode
echo.
echo [Venv] Looking for Python 3.11 / 3.10 via `py` launcher...
set "PY_ARG="
set "PY_VER="
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_ARG=-3.11" & set "PY_VER=3.11"
if defined PY_ARG goto py_ok
py -3.10 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_ARG=-3.10" & set "PY_VER=3.10"
if defined PY_ARG goto py_ok
echo ERROR: No Python 3.11 or 3.10 found for `py -3.11` / `py -3.10`.
echo Install from https://www.python.org/ ^(enable "py launcher"^), then re-run.
goto fail

:py_ok
echo Using: py %PY_ARG% ^(Python %PY_VER%^)
echo.
echo Existing venv folders in this directory:
if exist ".venv\Scripts\python.exe" echo   - .venv
if exist ".venv_py311\Scripts\python.exe" echo   - .venv_py311
if exist ".venv_py310\Scripts\python.exe" echo   - .venv_py310
echo.

set "USE_EXISTING="
set /p USE_EXISTING=Use an **existing** venv folder here? y/N: 
if /I "%USE_EXISTING%"=="y" goto use_existing_venv
goto create_new_venv

:use_existing_venv
set "VENV_DIR="
set /p VENV_DIR=Enter venv folder name or path ^(e.g. .venv_py310^): 
if not defined VENV_DIR echo ERROR: No path entered.& goto fail
if not exist "%VENV_DIR%\Scripts\python.exe" echo ERROR: Not a valid venv: %VENV_DIR%& goto fail
goto venv_ready

:create_new_venv
set "VENV_NAME_INPUT="
set /p VENV_NAME_INPUT=New venv folder name ^(Enter for .venv_py%PY_VER:.=%^): 
if not defined VENV_NAME_INPUT set "VENV_NAME_INPUT=.venv_py%PY_VER:.=%"
set "VENV_NAME_INPUT=%VENV_NAME_INPUT: =_%"
set "VENV_DIR=%VENV_NAME_INPUT%"
if exist "%VENV_DIR%\Scripts\python.exe" set "VENV_DIR=%VENV_DIR%_%RANDOM%"
echo Creating venv: %VENV_DIR%
py %PY_ARG% -m venv "%VENV_DIR%"
if errorlevel 1 echo ERROR: Could not create venv.& goto fail

:venv_ready
set "PY_EXE=%VENV_DIR%\Scripts\python.exe"
if not exist "%PY_EXE%" echo ERROR: Python executable not found in venv.& goto fail
set "START_MODE=PYTHON"
for /f "usebackq delims=" %%i in (`"%PY_EXE%" -c "import sys; print('%%d.%%d' %% (sys.version_info.major, sys.version_info.minor))"`) do set "RUNTIME_PY_VER=%%i"
echo Venv Python: %RUNTIME_PY_VER%
goto install_requirements

:conda_mode
echo.
echo [Conda] Locating conda...
set "CONDA_CMD="
if defined CONDA_EXE set "CONDA_CMD=%CONDA_EXE%"
if not defined CONDA_CMD (
  where conda >nul 2>&1
  if not errorlevel 1 set "CONDA_CMD=conda"
)
if not defined CONDA_CMD if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\MiniConda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\MiniConda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%ProgramData%\miniconda3\Scripts\conda.exe" set "CONDA_CMD=%ProgramData%\miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%ProgramData%\MiniConda3\Scripts\conda.exe" set "CONDA_CMD=%ProgramData%\MiniConda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "CONDA_CMD=%ProgramData%\anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD (
  echo ERROR: Conda not found. Install Miniconda/Anaconda or add conda to PATH.
  goto fail
)
echo Using: %CONDA_CMD%
echo Env will use **Python 3.11 or 3.10** only.
echo.
"%CONDA_CMD%" env list
echo.
set /p CONDA_ENV_NAME=Existing env name to use ^(or Enter to create new^): 
if defined CONDA_ENV_NAME goto conda_env_selected

set "CONDA_ENV_NAME=transcript_py311"
set /p CONDA_ENV_NAME=New env name [default transcript_py311]: 
if not defined CONDA_ENV_NAME set "CONDA_ENV_NAME=transcript_py311"
echo Creating %CONDA_ENV_NAME% with python=3.11...
"%CONDA_CMD%" create -y -n "%CONDA_ENV_NAME%" python=3.11
if errorlevel 1 (
  echo 3.11 failed, trying 3.10...
  "%CONDA_CMD%" create -y -n "%CONDA_ENV_NAME%" python=3.10
  if errorlevel 1 (
    echo ERROR: Could not create conda env with Python 3.11 or 3.10.
    goto fail
  )
)

:conda_env_selected
set "START_MODE=CONDA"
set "PY_EXE="
for /f "usebackq delims=" %%i in (`"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -c "import sys; print('%%d.%%d' %% (sys.version_info.major, sys.version_info.minor))"`) do set "RUNTIME_PY_VER=%%i"
echo Conda env Python: %RUNTIME_PY_VER%
"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,10),(3,11)) else 1)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Conda env must be Python 3.10 or 3.11 ^(found %RUNTIME_PY_VER%^).
  goto fail
)
echo [Conda] Upgrade pip...
"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install --upgrade pip
if errorlevel 1 echo ERROR: pip upgrade failed in conda env.& goto fail
goto conda_install_requirements

:install_requirements
echo.
echo [Install] Upgrade pip...
"%PY_EXE%" -m pip install --upgrade pip
if errorlevel 1 echo ERROR: pip upgrade failed.& goto fail

echo [Install] Base packages...
"%PY_EXE%" -m pip install customtkinter tkinterdnd2 openai-whisper torch deep-translator huggingface_hub
if errorlevel 1 echo ERROR: base requirements install failed.& goto fail

echo [Install] Coqui TTS ^(XTTS v2^)...
"%PY_EXE%" -m pip install TTS
if errorlevel 1 (
  echo WARNING: Coqui TTS install failed. Tab 5 may not work until you fix pip errors above.
) else (
  echo Re-pin transformers for XTTS...
  "%PY_EXE%" -m pip install "transformers==4.39.3"
  echo Quick test: Coqui TTS import...
  "%PY_EXE%" -c "from TTS.api import TTS; print('OK: Coqui TTS import')"
)
goto save_config

:conda_install_requirements
echo.
echo [Install] Base packages in conda env...
"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install customtkinter tkinterdnd2 openai-whisper torch deep-translator huggingface_hub
if errorlevel 1 echo ERROR: base requirements install failed in conda env.& goto fail

echo [Install] Coqui TTS ^(XTTS v2^)...
"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install TTS
if errorlevel 1 (
  echo WARNING: Coqui TTS install failed in conda env.
) else (
  echo Re-pin transformers for XTTS...
  "%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install "transformers==4.39.3"
  "%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -c "from TTS.api import TTS; print('OK: Coqui TTS import')"
)

:save_config
echo.
echo [Config] Writing .python_for_start_gui.txt and ui_settings.json...
if /I "%START_MODE%"=="CONDA" (
  > ".python_for_start_gui.txt" echo conda:%CONDA_ENV_NAME%
) else (
  > ".python_for_start_gui.txt" echo %PY_EXE%
)

if /I "%START_MODE%"=="CONDA" (
  py -3 -c "import json, os; p='ui_settings.json'; d=json.load(open(p,'r',encoding='utf-8')) if os.path.exists(p) else {}; d['tts_runtime_mode']='conda_env'; d['tts_conda_env']=r'%CONDA_ENV_NAME%'; d['tts_python_path']=''; d['tts_enabled']=True; d['tts_engine']='xtts_v2'; d.pop('openvoice_ckpt_dir', None); open(p,'w',encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))"
) else (
  "%PY_EXE%" -c "import json, os; p='ui_settings.json'; d=json.load(open(p,'r',encoding='utf-8')) if os.path.exists(p) else {}; d['tts_runtime_mode']='python_path'; d['tts_python_path']=r'%PY_EXE%'; d['tts_conda_env']=''; d['tts_enabled']=True; d['tts_engine']='xtts_v2'; d.pop('openvoice_ckpt_dir', None); open(p,'w',encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))"
)

echo.
echo Install finished.
if /I "%START_MODE%"=="CONDA" (
  echo Runtime: conda env **%CONDA_ENV_NAME%** ^(Python %RUNTIME_PY_VER%^)
) else if defined VENV_DIR (
  echo Runtime: venv **%VENV_DIR%**
  echo Python: %PY_EXE% ^(%RUNTIME_PY_VER%^)
) else (
  echo Runtime: PATH interpreter **%PY_EXE%** ^(Python %RUNTIME_PY_VER%^)
)
echo Start GUI: start_gui.bat
goto end

:fail
echo.
echo Install failed.

:end
echo.
pause
endlocal
