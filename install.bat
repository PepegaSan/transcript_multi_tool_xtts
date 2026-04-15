@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Smart Transcript — XTTS v2 edition ^(Tab 5 uses Coqui XTTS only; no OpenVoice^).
echo.

echo [1/8] Use Text-to-Speech (Tab 5)?
set "USE_TTS=Y"
set /p USE_TTS=Use TTS features? Y/n: 
if not defined USE_TTS set "USE_TTS=Y"
if /I "%USE_TTS%"=="N" set "USE_TTS=N"
if /I not "%USE_TTS%"=="N" set "USE_TTS=Y"
if /I "%USE_TTS%"=="Y" (
  echo TTS selected: installer will install Coqui "TTS" ^(XTTS v2^).
) else (
  echo TTS disabled: Tab 5 will be disabled in app.
)
echo.

echo [2/8] Choose environment type
echo   1^) Python venv ^(recommended^)
echo   2^) Conda env
set /p ENV_MODE=Select 1 or 2 [default 1]: 
if not defined ENV_MODE set "ENV_MODE=1"

if "%ENV_MODE%"=="2" goto conda_mode
goto venv_mode

:venv_mode
echo [3/8] Find compatible Python...
set "PY_ARG="
set "PY_VER="
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_ARG=-3.11" & set "PY_VER=3.11"
if defined PY_ARG goto py_ok
py -3.10 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_ARG=-3.10" & set "PY_VER=3.10"
if defined PY_ARG goto py_ok
py -3.9 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY_ARG=-3.9" & set "PY_VER=3.9"
if defined PY_ARG goto py_ok
echo ERROR: No compatible Python found.
echo Please install Python 3.9, 3.10, or 3.11 ^(with launcher^).
goto fail

:py_ok
echo Using Python %PY_VER%
echo.
echo [4/8] Select venv...
if exist ".venv\Scripts\python.exe" echo  - found .venv
if exist ".venv_py311\Scripts\python.exe" echo  - found .venv_py311
if exist ".venv_py310\Scripts\python.exe" echo  - found .venv_py310
if exist ".venv_py39\Scripts\python.exe" echo  - found .venv_py39
echo.

set "USE_EXISTING="
set /p USE_EXISTING=Use existing venv path? y/N: 
if /I "%USE_EXISTING%"=="y" goto use_existing_venv
goto create_new_venv

:use_existing_venv
set "VENV_DIR="
set /p VENV_DIR=Enter existing venv folder path (example .venv): 
if not defined VENV_DIR echo ERROR: No path entered.& goto fail
if not exist "%VENV_DIR%\Scripts\python.exe" echo ERROR: Not a valid venv: %VENV_DIR%& goto fail
goto venv_ready

:create_new_venv
set "VENV_NAME_INPUT="
set /p VENV_NAME_INPUT=Optional new venv name (Enter for auto): 
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
"%PY_EXE%" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" > ".tmp_pyver.txt"
set "RUNTIME_PY_VER="
set /p RUNTIME_PY_VER=<".tmp_pyver.txt"
del ".tmp_pyver.txt" >nul 2>&1
goto install_requirements

:conda_mode
echo [3/8] Find conda...
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
  echo ERROR: Conda not found.
  echo Install Miniconda/Anaconda or add conda to PATH.
  goto fail
)
echo Using conda: %CONDA_CMD%
echo.
echo [4/8] Available conda envs:
"%CONDA_CMD%" env list
echo.
set /p CONDA_ENV_NAME=Enter existing env name to use (or press Enter to create new): 
if defined CONDA_ENV_NAME goto conda_env_selected

set "CONDA_ENV_NAME=transcript_py311"
set /p CONDA_ENV_NAME=New env name [default transcript_py311]: 
if not defined CONDA_ENV_NAME set "CONDA_ENV_NAME=transcript_py311"
echo Creating conda env %CONDA_ENV_NAME% with Python 3.11...
"%CONDA_CMD%" create -y -n "%CONDA_ENV_NAME%" python=3.11
if errorlevel 1 (
  echo Python 3.11 create failed. Trying Python 3.10...
  "%CONDA_CMD%" create -y -n "%CONDA_ENV_NAME%" python=3.10
  if errorlevel 1 (
    echo ERROR: Could not create conda env.
    goto fail
  )
)

:conda_env_selected
set "START_MODE=CONDA"
set "PY_EXE="
set "RUNTIME_PY_VER="
"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" > ".tmp_conda_pyver.txt"
if errorlevel 1 echo ERROR: Could not read Python version from conda env.& goto fail
set /p RUNTIME_PY_VER=<".tmp_conda_pyver.txt"
del ".tmp_conda_pyver.txt" >nul 2>&1
echo Conda env Python: %RUNTIME_PY_VER%
echo [5/8] Upgrade pip in conda env...
"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install --upgrade pip
if errorlevel 1 echo ERROR: pip upgrade failed in conda env.& goto fail
goto conda_install_requirements

:install_requirements
echo [5/8] Upgrade pip...
"%PY_EXE%" -m pip install --upgrade pip
if errorlevel 1 echo ERROR: pip upgrade failed.& goto fail

echo [6/8] Install requirements...
"%PY_EXE%" -m pip install customtkinter tkinterdnd2 openai-whisper torch deep-translator huggingface_hub
if errorlevel 1 echo ERROR: base requirements install failed.& goto fail
if /I "%USE_TTS%"=="Y" (
  "%PY_EXE%" -m pip install TTS
  if errorlevel 1 (
    echo WARNING: Coqui TTS install failed.
    set /p CONT_KEEP_TAB5=Continue and keep Tab 5 enabled? Y/n: 
    if /I "%CONT_KEEP_TAB5%"=="N" set "USE_TTS=N"
  )
)
if /I "%USE_TTS%"=="Y" (
  echo Re-pin transformers for XTTS compatibility...
  "%PY_EXE%" -m pip install "transformers==4.39.3"
  echo Quick import test ^(Coqui TTS / XTTS^)...
  "%PY_EXE%" -c "from TTS.api import TTS; print('OK: Coqui TTS import')"
)
goto save_config

:conda_install_requirements
echo [6/8] Install requirements...
"%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install customtkinter tkinterdnd2 openai-whisper torch deep-translator huggingface_hub
if errorlevel 1 echo ERROR: base requirements install failed in conda env.& goto fail
if /I "%USE_TTS%"=="Y" (
  "%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install TTS
  if errorlevel 1 (
    echo WARNING: Coqui TTS install failed in conda env.
    set /p CONT_KEEP_TAB5=Continue and keep Tab 5 enabled? Y/n: 
    if /I "%CONT_KEEP_TAB5%"=="N" set "USE_TTS=N"
  )
)
if /I "%USE_TTS%"=="Y" (
  echo Re-pin transformers for XTTS compatibility...
  "%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -m pip install "transformers==4.39.3"
  echo Quick import test ^(Coqui TTS / XTTS^)...
  "%CONDA_CMD%" run -n "%CONDA_ENV_NAME%" python -c "from TTS.api import TTS; print('OK: Coqui TTS import')"
)

:save_config
echo [7/8] Save start config...
if /I "%START_MODE%"=="CONDA" (
  > ".python_for_start_gui.txt" echo conda:%CONDA_ENV_NAME%
) else (
  > ".python_for_start_gui.txt" echo %PY_EXE%
)

echo [8/8] Save app defaults...
if /I "%START_MODE%"=="CONDA" (
  py -3 -c "import json, os; p='ui_settings.json'; d=json.load(open(p,'r',encoding='utf-8')) if os.path.exists(p) else {}; d['tts_runtime_mode']='conda_env'; d['tts_conda_env']=r'%CONDA_ENV_NAME%'; d['tts_python_path']=''; d['tts_enabled']=('%USE_TTS%'=='Y'); d['tts_engine']='xtts_v2'; d.pop('openvoice_ckpt_dir', None); open(p,'w',encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))"
) else (
  "%PY_EXE%" -c "import json, os; p='ui_settings.json'; d=json.load(open(p,'r',encoding='utf-8')) if os.path.exists(p) else {}; d['tts_runtime_mode']='python_path'; d['tts_python_path']=r'%PY_EXE%'; d['tts_conda_env']=''; d['tts_enabled']=('%USE_TTS%'=='Y'); d['tts_engine']='xtts_v2'; d.pop('openvoice_ckpt_dir', None); open(p,'w',encoding='utf-8').write(json.dumps(d, ensure_ascii=False, indent=2))"
)

echo.
echo Install complete.
echo TTS enabled: %USE_TTS%
if /I "%START_MODE%"=="CONDA" (
  echo Conda env: %CONDA_ENV_NAME%
) else (
  echo Venv: %VENV_DIR%
  echo Python: %PY_EXE%
)
echo Start with: start_gui.bat
goto end

:fail
echo.
echo Install failed.

:end
echo.
pause
endlocal
