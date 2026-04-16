# Smart Transcript & DaVinci Cutter — **XTTS v2 edition**

This repository is the **Coqui XTTS v2–only** variant: Tab 5 voice export uses **multilingual XTTS v2** (including **German**, **English**, and other supported languages). 

## Who this is for

You do **not** need to be a Python developer, but you should be comfortable on **Windows** with: running `.bat` files, reading error text from the console, and waiting for **large downloads** (Whisper/TTS/PyTorch dependencies are several gigabytes in total). If `install.bat` fails, copy the red error lines into a search or issue report.

## Install (Windows)

1. Install **Python 3.11 or 3.10** from [python.org](https://www.python.org/downloads/windows/) and enable the **“py launcher”** (recommended). Alternatively use **Miniconda/Anaconda** and pick conda mode in the installer.
2. Run **`install.bat`** and choose **venv (1)**, **conda (2)**, or **PATH python (3)** when prompted. The script writes **`.python_for_start_gui.txt`** (ignored by git) and creates or updates **`ui_settings.json`** (local-only; not committed—defaults work if the file is missing).
3. Start the app with **`start_gui.bat`**.
4. In **Tab 5**, set **Runtime** to the same Python/conda env where **Coqui `TTS`** is installed, then use **Check local TTS runtime**.

Manual `pip install -r requirements.txt` is supported for advanced setups; **`install.bat`** installs the same core packages explicitly (and pins **`transformers==4.39.3`** after `TTS` for XTTS stability).

## GPU / CUDA (optional but recommended)

- **Whisper (Tab 1)** and **XTTS (Tab 5)** are much faster on a **CUDA** GPU with a matching **PyTorch** build.
- Default **`pip install torch`** from PyPI is often **CPU-only** on Windows. If **Tab 1 → Device** shows **CUDA** but `torch.cuda.is_available()` is false in the runtime line under the Whisper options, install a **CUDA-enabled** torch build from the official matrix: [PyTorch — Get Started](https://pytorch.org/get-started/locally/) (pick Windows, Pip, your CUDA version).
- **No NVIDIA GPU:** leave **Device** on **auto** or **cpu**. The app is usable; large Whisper models will be slow.

## Other tools

- **FFmpeg** on `PATH` is required for **FFmpeg video export** and related checks in the app. Install from [ffmpeg.org](https://ffmpeg.org/download.html) or your package manager and confirm `ffmpeg -version` in a terminal.
- **DaVinci Resolve** integration expects Resolve installed and (when using the API path field) a valid **`DaVinciResolveScript.py`** location if it is not discoverable automatically.

## Tab 5 language

Choose the profile / export language (e.g. `de` for German). XTTS uses that language code for synthesis.

## License / upstream

Application logic is in `transcript.py`. Voice synthesis is provided by [Coqui TTS](https://github.com/coqui-ai/TTS) (XTTS v2). Respect Coqui’s license and model terms for distribution.
